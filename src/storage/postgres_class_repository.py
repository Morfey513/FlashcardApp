"""PostgreSQL classes, invitation codes, and enrollment memberships."""

import re
import secrets
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from src.storage.database import create_session_factory
from src.storage.postgres_models import (
    ClassFlashcardDeckModel,
    ClassInvitationModel,
    ClassMemberModel,
    ClassModel,
    ClassQuizModel,
    FlashcardDeckMetadataModel,
    QuizMetadataModel,
    UserModel,
)


class PostgresClassRepository:
    ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    NAMESPACE = uuid.UUID("a7926ea6-5a87-41f5-9f92-c2bceaad14bc")

    def __init__(self, session_factory=None):
        self.session_factory = session_factory or create_session_factory()

    @staticmethod
    def normalize_code(code):
        return re.sub(r"[^A-Z2-9]", "", str(code).upper())

    @classmethod
    def class_id_for(cls, kind, content_id):
        return str(uuid.uuid5(cls.NAMESPACE, f"{kind}:{content_id}"))

    def import_content_access(self, source: dict, kind: str) -> bool:
        content_id = str(source.get("id", ""))
        metadata = source.get("moderation") or {}
        owner_id = str(metadata.get("owner_id") or "")
        try:
            model, link_model, link_field, normalized_kind = self._models(kind)
            with self.session_factory.begin() as session:
                content = session.get(model, content_id)
                if content is None or content.owner_id is None or content.owner_id != owner_id:
                    return False
                class_id = self.class_id_for(normalized_kind, content_id)
                classroom = session.get(ClassModel, class_id)
                if classroom is None:
                    classroom = ClassModel(
                        id=class_id, owner_id=owner_id, name=content.name, status="active"
                    )
                    session.add(classroom)
                else:
                    classroom.owner_id = owner_id
                    classroom.name = content.name
                link_key = {"class_id": class_id, link_field: content_id}
                if session.get(link_model, tuple(link_key.values())) is None:
                    session.add(link_model(**link_key))
                self._import_invitation(session, classroom, metadata.get("invite") or {})
                self._import_members(session, class_id, metadata.get("enrollments") or {})
                return True
        except (SQLAlchemyError, ValueError, TypeError):
            return False

    def get_owned_classes(self, owner_id: str, kind=None):
        try:
            with self.session_factory() as session:
                classes = session.scalars(
                    select(ClassModel)
                    .where(ClassModel.owner_id == str(owner_id), ClassModel.status == "active")
                    .order_by(ClassModel.name)
                ).all()
                rows = []
                for classroom in classes:
                    content = self._content_for_class(session, classroom.id)
                    if content is None or (kind and content["kind"] != kind):
                        continue
                    invitation = session.scalar(select(ClassInvitationModel).where(
                        ClassInvitationModel.class_id == classroom.id,
                        ClassInvitationModel.status == "active",
                    ))
                    members = session.scalars(select(ClassMemberModel).where(
                        ClassMemberModel.class_id == classroom.id,
                        ClassMemberModel.status == "active",
                    )).all()
                    rows.append({
                        "id": classroom.id,
                        "name": classroom.name,
                        "owner_id": classroom.owner_id,
                        **content,
                        "invite_code": invitation.display_code if invitation else "",
                        "roster": [{
                            "user_id": member.user_id,
                            "enrolled_at": member.joined_at.isoformat(),
                        } for member in members],
                    })
                return rows
        except SQLAlchemyError:
            return []

    def get_invitation(self, kind, content_id, actor_id, actor_role):
        """Return one authorized content invitation without expanding all classes."""
        try:
            with self.session_factory() as session:
                classroom = self._class_for_content(session, kind, content_id)
                if classroom is None or (
                    actor_role != "admin" and classroom.owner_id != str(actor_id)
                ):
                    return None
                invitation = session.scalar(select(ClassInvitationModel).where(
                    ClassInvitationModel.class_id == classroom.id,
                    ClassInvitationModel.status == "active",
                ))
                return invitation.display_code if invitation else ""
        except (SQLAlchemyError, ValueError):
            return None

    def join_with_code(self, code, user_id):
        normalized = self.normalize_code(code)
        if not normalized:
            return False, "Enter an invitation code."
        try:
            with self.session_factory.begin() as session:
                invitation = session.scalar(select(ClassInvitationModel).where(
                    ClassInvitationModel.normalized_code == normalized,
                    ClassInvitationModel.status == "active",
                ))
                if invitation is None:
                    return False, "That invitation code was not found."
                if session.get(UserModel, str(user_id)) is None:
                    return False, "A valid account is required."
                content = self._content_for_class(session, invitation.class_id)
                if (
                    content is None or content["status"] != "published"
                    or content["visibility"] != "class_only"
                ):
                    return False, "This invitation is not currently available."
                key = (invitation.class_id, str(user_id))
                member = session.get(ClassMemberModel, key)
                already = member is not None and member.status == "active"
                if member is None:
                    member = ClassMemberModel(
                        class_id=invitation.class_id, user_id=str(user_id), status="active"
                    )
                    session.add(member)
                else:
                    member.status = "active"
                    member.removed_at = None
                    member.joined_at = datetime.now(timezone.utc)
                state = "already enrolled in" if already else "enrolled in"
                return True, f"You are {state} {content['name']}."
        except SQLAlchemyError:
            return False, "Enrollment could not be saved."

    def rotate_code(self, kind, content_id, actor_id, actor_role):
        try:
            with self.session_factory.begin() as session:
                classroom = self._class_for_content(session, kind, content_id)
                if classroom is None:
                    model, link_model, link_field, normalized_kind = self._models(kind)
                    content = session.get(model, str(content_id))
                    if content is None or content.owner_id is None or (
                        actor_role != "admin" and content.owner_id != str(actor_id)
                    ):
                        return False, "Only the content owner can manage its invitation code."
                    class_id = self.class_id_for(normalized_kind, str(content_id))
                    classroom = ClassModel(
                        id=class_id, owner_id=content.owner_id,
                        name=content.name, status="active",
                    )
                    session.add(classroom)
                    session.add(link_model(**{
                        "class_id": class_id, link_field: str(content_id),
                    }))
                elif (
                    actor_role != "admin" and classroom.owner_id != str(actor_id)
                ):
                    return False, "Only the content owner can manage its invitation code."
                active = session.scalars(select(ClassInvitationModel).where(
                    ClassInvitationModel.class_id == classroom.id,
                    ClassInvitationModel.status == "active",
                )).all()
                now = datetime.now(timezone.utc)
                for invitation in active:
                    invitation.status = "revoked"
                    invitation.revoked_at = now
                code = self._new_code(session, classroom.name)
                session.add(ClassInvitationModel(
                    id=str(uuid.uuid4()), class_id=classroom.id,
                    created_by=str(actor_id), display_code=code,
                    normalized_code=self.normalize_code(code), status="active",
                ))
                return True, code
        except (SQLAlchemyError, ValueError):
            return False, "Invitation code could not be rotated."

    def remove_member(self, kind, content_id, actor_id, actor_role, user_id):
        try:
            with self.session_factory.begin() as session:
                classroom = self._class_for_content(session, kind, content_id)
                if classroom is None or (
                    actor_role != "admin" and classroom.owner_id != str(actor_id)
                ):
                    return False, "Only the content owner can remove enrolled students."
                member = session.get(ClassMemberModel, (classroom.id, str(user_id)))
                if member is None or member.status != "active":
                    return False, "That student is not enrolled in this item."
                member.status = "removed"
                member.removed_at = datetime.now(timezone.utc)
                return True, "Student access removed."
        except SQLAlchemyError:
            return False, "Student access could not be removed."

    def active_content_ids_for_user(self, user_id):
        try:
            with self.session_factory() as session:
                class_ids = session.scalars(select(ClassMemberModel.class_id).where(
                    ClassMemberModel.user_id == str(user_id),
                    ClassMemberModel.status == "active",
                )).all()
                if not class_ids:
                    return {"quiz": set(), "flashcard": set()}
                quizzes = set(session.scalars(select(ClassQuizModel.quiz_id).where(
                    ClassQuizModel.class_id.in_(class_ids)
                )).all())
                decks = set(session.scalars(select(ClassFlashcardDeckModel.deck_id).where(
                    ClassFlashcardDeckModel.class_id.in_(class_ids)
                )).all())
                return {"quiz": quizzes, "flashcard": decks}
        except SQLAlchemyError:
            return {"quiz": set(), "flashcard": set()}

    def _import_invitation(self, session, classroom, invitation):
        code = str(invitation.get("code") or "").strip()
        if not code:
            return
        normalized = self.normalize_code(code)
        active = session.scalar(select(ClassInvitationModel).where(
            ClassInvitationModel.class_id == classroom.id,
            ClassInvitationModel.status == "active",
        ))
        if active and active.normalized_code == normalized:
            return
        if active:
            active.status = "revoked"
            active.revoked_at = datetime.now(timezone.utc)
        existing = session.scalar(select(ClassInvitationModel).where(
            ClassInvitationModel.normalized_code == normalized
        ))
        if existing:
            existing.class_id = classroom.id
            existing.status = "active"
            existing.revoked_at = None
            return
        session.add(ClassInvitationModel(
            id=str(uuid.uuid4()), class_id=classroom.id,
            created_by=classroom.owner_id, display_code=code,
            normalized_code=normalized, status="active",
            created_at=self._parse_datetime(invitation.get("created_at")) or datetime.now(timezone.utc),
        ))

    def _import_members(self, session, class_id, enrollments):
        source_ids = {str(value) for value in enrollments}
        existing = session.scalars(select(ClassMemberModel).where(
            ClassMemberModel.class_id == class_id
        )).all()
        for member in existing:
            if member.user_id not in source_ids and member.status == "active":
                member.status = "removed"
                member.removed_at = datetime.now(timezone.utc)
        for user_id, value in enrollments.items():
            user_id = str(user_id)
            if session.get(UserModel, user_id) is None:
                continue
            member = session.get(ClassMemberModel, (class_id, user_id))
            joined = self._parse_datetime(
                value.get("enrolled_at") if isinstance(value, dict) else None
            ) or datetime.now(timezone.utc)
            if member is None:
                session.add(ClassMemberModel(
                    class_id=class_id, user_id=user_id, status="active", joined_at=joined
                ))
            else:
                member.status = "active"
                member.joined_at = joined
                member.removed_at = None

    def _new_code(self, session, name):
        prefix = "".join(c for c in name.upper() if c in self.ALPHABET)[:4] or "CLASS"
        while True:
            code = f"{prefix}-{''.join(secrets.choice(self.ALPHABET) for _ in range(4))}"
            if session.scalar(select(ClassInvitationModel.id).where(
                ClassInvitationModel.normalized_code == self.normalize_code(code)
            )) is None:
                return code

    def _class_for_content(self, session, kind, content_id):
        _model, link_model, link_field, normalized = self._models(kind)
        link = session.scalar(select(link_model).where(
            getattr(link_model, link_field) == str(content_id)
        ))
        return session.get(ClassModel, link.class_id) if link else None

    def _content_for_class(self, session, class_id):
        quiz_link = session.scalar(select(ClassQuizModel).where(
            ClassQuizModel.class_id == class_id
        ))
        if quiz_link:
            item = session.get(QuizMetadataModel, quiz_link.quiz_id)
            return self._content_dict(item, "quiz") if item else None
        deck_link = session.scalar(select(ClassFlashcardDeckModel).where(
            ClassFlashcardDeckModel.class_id == class_id
        ))
        if deck_link:
            item = session.get(FlashcardDeckMetadataModel, deck_link.deck_id)
            return self._content_dict(item, "flashcard") if item else None
        return None

    @staticmethod
    def _content_dict(item, kind):
        return {
            "content_id": item.id, "kind": kind, "name": item.name,
            "status": item.lifecycle, "visibility": item.visibility,
            "source_path": item.source_path,
        }

    @staticmethod
    def _models(kind):
        normalized = str(kind).casefold()
        if normalized == "quiz":
            return QuizMetadataModel, ClassQuizModel, "quiz_id", "quiz"
        if normalized in {"flashcard", "deck", "flashcard_deck"}:
            return (
                FlashcardDeckMetadataModel, ClassFlashcardDeckModel,
                "deck_id", "flashcard",
            )
        raise ValueError(f"Unsupported content kind: {kind!r}")

    @staticmethod
    def _parse_datetime(value):
        if not value:
            return None
        if isinstance(value, datetime):
            return value
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
