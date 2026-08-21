"""Attributed relational audit and moderation history for authored content."""

import logging
from datetime import datetime, timezone
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from src.storage.database import create_session_factory
from src.storage.postgres_models import (
    FlashcardDeckMetadataModel, FlashcardEditHistoryModel,
    FlashcardModerationHistoryModel, QuizEditHistoryModel,
    QuizMetadataModel, QuizModerationHistoryModel, UserModel,
)

logger = logging.getLogger(__name__)


class PostgresContentHistoryRepository:
    def __init__(self, session_factory=None):
        self.session_factory = session_factory or create_session_factory()

    def import_edit_history(self, kind, content_id, entries):
        if not isinstance(entries, list):
            return False
        model, content_model, field = self._edit_models(kind)
        try:
            with self.session_factory.begin() as session:
                if session.get(content_model, str(content_id)) is None:
                    return False
                for position, entry in enumerate(entries):
                    self._upsert_edit(session, model, field, str(content_id), entry, position)
                return True
        except (SQLAlchemyError, ValueError, TypeError) as exc:
            logger.error("Could not import %s edit history '%s': %s", kind, content_id, exc)
            return False

    def import_moderation_history(self, kind, content_id, entries):
        if not isinstance(entries, list):
            return False
        model, content_model, field = self._moderation_models(kind)
        try:
            with self.session_factory.begin() as session:
                if session.get(content_model, str(content_id)) is None:
                    return False
                for position, entry in enumerate(entries):
                    self._upsert_moderation(
                        session, model, field, str(content_id), entry, position
                    )
                return True
        except (SQLAlchemyError, ValueError, TypeError) as exc:
            logger.error("Could not import %s moderation history '%s': %s", kind, content_id, exc)
            return False

    def append_edit(self, kind, content_id, actor_id, actor_role, summary,
                    action="updated", changed_fields=None):
        entry = {
            "id": str(uuid5(NAMESPACE_URL, f"study-buddy-edit:{kind}:{content_id}:{datetime.now(timezone.utc).isoformat()}")),
            "changed_by": str(actor_id), "role": str(actor_role),
            "timestamp": datetime.now(timezone.utc).isoformat(), "action": action,
            "change_summary": str(summary), "changed_fields": list(changed_fields or []),
        }
        return self.import_edit_history(kind, content_id, [entry])

    def append_moderation(self, kind, content_id, actor_id, action, note=""):
        entry = {
            "id": str(uuid5(NAMESPACE_URL, f"study-buddy-moderation:{kind}:{content_id}:{datetime.now(timezone.utc).isoformat()}")),
            "actor_id": str(actor_id), "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": str(action), "note": str(note),
        }
        return self.import_moderation_history(kind, content_id, [entry])

    def get_history(self, kind, content_id):
        edit_model, _content, edit_field = self._edit_models(kind)
        mod_model, _content, mod_field = self._moderation_models(kind)
        try:
            with self.session_factory() as session:
                edits = session.scalars(select(edit_model).where(
                    getattr(edit_model, edit_field) == str(content_id)
                ).order_by(edit_model.changed_at)).all()
                moderation = session.scalars(select(mod_model).where(
                    getattr(mod_model, mod_field) == str(content_id)
                ).order_by(mod_model.created_at)).all()
                return {
                    "edits": [{
                        "id": row.id, "changed_by": row.source_actor_id,
                        "actor_resolved": row.changed_by is not None,
                        "role": row.actor_role, "timestamp": row.changed_at.isoformat(),
                        "action": row.action, "change_summary": row.change_summary,
                        "changed_fields": row.changed_fields,
                    } for row in edits],
                    "moderation": [{
                        "id": row.id, "actor_id": row.source_actor_id,
                        "actor_resolved": row.moderator_id is not None,
                        "timestamp": row.created_at.isoformat(), "action": row.action,
                        "note": row.note,
                    } for row in moderation],
                }
        except (SQLAlchemyError, ValueError) as exc:
            logger.error("Could not load %s history '%s': %s", kind, content_id, exc)
            return {"edits": [], "moderation": []}

    @classmethod
    def _upsert_edit(cls, session, model, field, content_id, entry, position):
        actor = str(entry.get("changed_by") or entry.get("actor_id") or "legacy")
        timestamp = cls._datetime(entry.get("timestamp"))
        row_id = str(entry.get("id") or uuid5(
            NAMESPACE_URL,
            f"study-buddy-import-edit:{model.__tablename__}:{content_id}:{timestamp.isoformat()}:{position}",
        ))
        resolved_actor = actor if session.get(UserModel, actor) is not None else None
        row = session.get(model, row_id)
        if row is None:
            row = model(
                id=row_id, changed_by=resolved_actor,
                source_actor_id=actor,
                actor_role=str(entry.get("role") or "unknown"),
                action=str(entry.get("action") or "updated"),
                change_summary=str(entry.get("change_summary") or "Content updated."),
                changed_fields=list(entry.get("changed_fields") or []),
                changed_at=timestamp, **{field: content_id},
            )
            session.add(row)
        row.changed_by = resolved_actor
        row.source_actor_id = actor
        row.actor_role = str(entry.get("role") or "unknown")
        row.action = str(entry.get("action") or "updated")
        row.change_summary = str(entry.get("change_summary") or "Content updated.")
        row.changed_fields = list(entry.get("changed_fields") or [])
        row.changed_at = timestamp

    @classmethod
    def _upsert_moderation(cls, session, model, field, content_id, entry, position):
        actor = str(entry.get("actor_id") or entry.get("changed_by") or "legacy")
        timestamp = cls._datetime(entry.get("timestamp"))
        row_id = str(entry.get("id") or uuid5(
            NAMESPACE_URL,
            f"study-buddy-import-moderation:{model.__tablename__}:{content_id}:{timestamp.isoformat()}:{position}",
        ))
        resolved_actor = actor if session.get(UserModel, actor) is not None else None
        row = session.get(model, row_id)
        if row is None:
            row = model(
                id=row_id, moderator_id=resolved_actor,
                source_actor_id=actor,
                action=str(entry.get("action") or "updated"),
                note=str(entry.get("note") or ""),
                created_at=timestamp, **{field: content_id},
            )
            session.add(row)
        row.moderator_id = resolved_actor
        row.source_actor_id = actor
        row.action = str(entry.get("action") or "updated")
        row.note = str(entry.get("note") or "")
        row.created_at = timestamp

    @staticmethod
    def _datetime(value):
        if isinstance(value, datetime):
            return value
        if value:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return datetime.now(timezone.utc)

    @staticmethod
    def _edit_models(kind):
        if str(kind).casefold() == "quiz":
            return QuizEditHistoryModel, QuizMetadataModel, "quiz_id"
        if str(kind).casefold() in {"flashcard", "deck", "flashcard_deck"}:
            return FlashcardEditHistoryModel, FlashcardDeckMetadataModel, "deck_id"
        raise ValueError(f"Unsupported content kind: {kind!r}")

    @staticmethod
    def _moderation_models(kind):
        if str(kind).casefold() == "quiz":
            return QuizModerationHistoryModel, QuizMetadataModel, "quiz_id"
        if str(kind).casefold() in {"flashcard", "deck", "flashcard_deck"}:
            return FlashcardModerationHistoryModel, FlashcardDeckMetadataModel, "deck_id"
        raise ValueError(f"Unsupported content kind: {kind!r}")
