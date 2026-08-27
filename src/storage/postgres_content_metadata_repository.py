"""PostgreSQL catalog for quiz/deck metadata during hybrid JSON migration."""

import logging
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.exc import SQLAlchemyError

from src.logic.access_control import is_content_status, is_visibility
from src.logic.test_settings import normalize_test_settings
from src.storage.database import create_session_factory
from src.storage.postgres_models import (
    FlashcardDeckMetadataModel,
    QuizMetadataModel,
    UserModel,
)

logger = logging.getLogger(__name__)


class PostgresContentMetadataRepository:
    """Owns relational content identity; questions/cards still live in JSON."""

    def __init__(self, session_factory=None):
        self.session_factory = session_factory or create_session_factory()

    def import_quiz(self, source: dict, source_path: str) -> bool:
        return self._upsert(QuizMetadataModel, source, source_path, "quiz")

    def import_flashcard_deck(self, source: dict, source_path: str) -> bool:
        return self._upsert(
            FlashcardDeckMetadataModel, source, source_path, "flashcard"
        )

    def get_all(self, kind=None) -> list[dict]:
        models = self._models_for(kind)
        try:
            with self.session_factory() as session:
                rows = []
                for model, label in models:
                    items = session.scalars(
                        select(model).order_by(model.name, model.id)
                    ).all()
                    rows.extend(self._public(item, label) for item in items)
                return rows
        except SQLAlchemyError as exc:
            logger.error("Could not load PostgreSQL content metadata: %s", exc)
            return []

    def get_by_id(self, kind: str, content_id: str):
        model, label = self._model_for(kind)
        try:
            with self.session_factory() as session:
                item = session.get(model, str(content_id))
                return self._public(item, label) if item is not None else None
        except SQLAlchemyError as exc:
            logger.error("Could not load PostgreSQL %s '%s': %s", kind, content_id, exc)
            return None

    def get_owned_by(self, owner_id: str, kind=None) -> list[dict]:
        return [
            item for item in self.get_all(kind)
            if item["owner_id"] == str(owner_id)
        ]

    def get_for_actor(self, actor_id: str, actor_role: str, scope="available", kind=None):
        items = self.get_all(kind)
        actor_id = str(actor_id)
        if scope == "all":
            return items if actor_role == "admin" else []
        if scope == "owned":
            return [item for item in items if item["owner_id"] == actor_id]
        if scope != "available":
            return []
        from src.storage.postgres_class_repository import PostgresClassRepository
        enrolled = PostgresClassRepository(
            self.session_factory
        ).active_content_ids_for_user(actor_id)
        return [
            item for item in items
            if item["owner_id"] == actor_id
            or (
                item["status"] == "published"
                and (
                    item["visibility"] == "public"
                    or item["id"] in enrolled[item["kind"]]
                )
            )
        ]

    def save_for_actor(self, kind: str, payload: dict, actor_id: str, actor_role: str):
        if actor_role not in {"teacher", "admin"}:
            return False
        existing = self.get_by_id(kind, payload.get("id", ""))
        if existing and actor_role != "admin" and existing["owner_id"] != str(actor_id):
            return False
        status = str(payload.get("status", ""))
        if actor_role != "admin" and status not in {"draft", "pending_review"}:
            return False
        owner_id = (
            existing["source_owner_id"] if existing else str(actor_id)
        )
        source = {
            "id": payload.get("id"),
            "name": payload.get("name"),
            "moderation": {
                "owner_id": owner_id,
                "status": status,
                "visibility": payload.get("visibility"),
            },
            "test_settings": payload.get("test_settings"),
        }
        if kind == "quiz":
            return self.import_quiz(source, payload.get("source_path", ""))
        if kind in {"flashcard", "deck", "flashcard_deck"}:
            return self.import_flashcard_deck(source, payload.get("source_path", ""))
        return False

    def delete_for_actor(self, kind: str, content_id: str, actor_id: str, actor_role: str) -> bool:
        """Delete one owned item; database cascades remove its dependent state."""
        model, _label = self._model_for(kind)
        existing = self.get_by_id(kind, content_id)
        if existing is None:
            return False
        if actor_role != "admin" and (
            actor_role != "teacher" or existing["owner_id"] != str(actor_id)
        ):
            return False
        try:
            with self.session_factory.begin() as session:
                result = session.execute(
                    delete(model).where(model.id == str(content_id))
                )
                return bool(result.rowcount)
        except SQLAlchemyError as exc:
            logger.error("Could not delete %s '%s': %s", kind, content_id, exc)
            return False

    def _upsert(self, model, source, source_path, kind):
        content_id = str(source.get("id", "")).strip()
        name = str(source.get("name", "")).strip()
        moderation = source.get("moderation") or {}
        source_owner_id = str(moderation.get("owner_id") or "legacy")
        lifecycle = str(moderation.get("status") or "published")
        visibility = str(moderation.get("visibility") or "public")
        if not content_id or not name or not is_content_status(lifecycle) or not is_visibility(visibility):
            return False
        try:
            with self.session_factory.begin() as session:
                resolved_owner_id = (
                    source_owner_id
                    if session.get(UserModel, source_owner_id) is not None
                    else None
                )
                item = session.get(model, content_id)
                previous = None if item is None else {
                    "name": item.name, "owner_id": item.owner_id,
                    "source_owner_id": item.source_owner_id,
                    "lifecycle": item.lifecycle, "visibility": item.visibility,
                    "source_path": item.source_path,
                    "test_settings": {
                        "time_limit_minutes": item.time_limit_minutes,
                        "passing_grade_percent": item.passing_grade_percent,
                        "attempt_limit": item.attempt_limit,
                        "due_at": item.due_at,
                        "answer_review_policy": item.answer_review_policy,
                    } if kind == "quiz" else None,
                }
                if item is None:
                    item = model(id=content_id)
                    session.add(item)
                item.owner_id = resolved_owner_id
                item.source_owner_id = source_owner_id
                item.name = name
                item.lifecycle = lifecycle
                item.visibility = visibility
                item.source_path = str(source_path)
                if kind == "quiz":
                    settings = normalize_test_settings(source.get("test_settings"))
                    item.time_limit_minutes = settings["time_limit_minutes"]
                    item.passing_grade_percent = settings["passing_grade_percent"]
                    item.attempt_limit = settings["attempt_limit"]
                    item.due_at = self._parse_datetime(settings["due_at"])
                    item.answer_review_policy = settings["answer_review_policy"]
                if previous is not None and any((
                    previous["name"] != item.name,
                    previous["owner_id"] != item.owner_id,
                    previous["source_owner_id"] != item.source_owner_id,
                    previous["lifecycle"] != item.lifecycle,
                    previous["visibility"] != item.visibility,
                    previous["source_path"] != item.source_path,
                    kind == "quiz" and previous["test_settings"] != {
                        "time_limit_minutes": item.time_limit_minutes,
                        "passing_grade_percent": item.passing_grade_percent,
                        "attempt_limit": item.attempt_limit,
                        "due_at": item.due_at,
                        "answer_review_policy": item.answer_review_policy,
                    },
                )):
                    item.content_version += 1
                return True
        except (SQLAlchemyError, ValueError, TypeError) as exc:
            logger.error("Could not import %s metadata '%s': %s", kind, content_id, exc)
            return False

    @staticmethod
    def _parse_datetime(value):
        if not value:
            return None
        if isinstance(value, datetime):
            return value
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))

    @staticmethod
    def _public(item, kind):
        result = {
            "id": item.id,
            "kind": kind,
            "name": item.name,
            "owner_id": item.owner_id,
            "source_owner_id": item.source_owner_id,
            "owner_resolved": item.owner_id is not None,
            "status": item.lifecycle,
            "visibility": item.visibility,
            "source_path": item.source_path,
            "created_at": item.created_at.isoformat() if item.created_at else None,
            "updated_at": item.updated_at.isoformat() if item.updated_at else None,
            "content_version": item.content_version,
        }
        if kind == "quiz":
            result["test_settings"] = {
                "time_limit_minutes": item.time_limit_minutes,
                "passing_grade_percent": item.passing_grade_percent,
                "attempt_limit": item.attempt_limit,
                "due_at": item.due_at.isoformat() if item.due_at else None,
                "answer_review_policy": item.answer_review_policy,
            }
        return result

    @staticmethod
    def _model_for(kind):
        normalized = str(kind).casefold()
        if normalized == "quiz":
            return QuizMetadataModel, "quiz"
        if normalized in {"flashcard", "deck", "flashcard_deck"}:
            return FlashcardDeckMetadataModel, "flashcard"
        raise ValueError(f"Unsupported content kind: {kind!r}")

    @classmethod
    def _models_for(cls, kind):
        if kind is not None:
            return [cls._model_for(kind)]
        return [
            (QuizMetadataModel, "quiz"),
            (FlashcardDeckMetadataModel, "flashcard"),
        ]
