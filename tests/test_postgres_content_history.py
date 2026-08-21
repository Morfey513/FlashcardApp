from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from src.logic.passwords import PasswordHasher
from src.storage.postgres_content_history_repository import PostgresContentHistoryRepository
from src.storage.postgres_models import (
    Base, QuizEditHistoryModel, QuizMetadataModel,
    QuizModerationHistoryModel, UserModel,
)


def _repository(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'history.db'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    with sessions.begin() as session:
        session.add(UserModel(
            id="admin-1", username="admin", display_name="Admin",
            password_hash=PasswordHasher.hash("password1"), role="admin",
            status="active", ban_reason="",
        ))
        session.flush()
        session.add(QuizMetadataModel(
            id="quiz-1", owner_id="admin-1", source_owner_id="admin-1",
            name="Quiz", lifecycle="published", visibility="public",
            source_path="quiz.json",
        ))
    return PostgresContentHistoryRepository(sessions), sessions, engine


def test_history_import_is_idempotent_and_preserves_actor(tmp_path):
    repository, sessions, engine = _repository(tmp_path)
    edits = [{
        "id": "edit-1", "changed_by": "admin-1", "role": "admin",
        "timestamp": "2026-08-17T12:00:00+00:00", "action": "updated",
        "change_summary": "Updated questions.", "changed_fields": ["questions"],
    }]
    moderation = [{
        "timestamp": "2026-08-17T12:01:00+00:00", "actor_id": "admin-1",
        "action": "published", "note": "Approved",
    }]
    assert repository.import_edit_history("quiz", "quiz-1", edits)
    assert repository.import_edit_history("quiz", "quiz-1", edits)
    assert repository.import_moderation_history("quiz", "quiz-1", moderation)
    assert repository.import_moderation_history("quiz", "quiz-1", moderation)
    history = repository.get_history("quiz", "quiz-1")
    assert history["edits"][0]["changed_by"] == "admin-1"
    assert history["edits"][0]["changed_fields"] == ["questions"]
    assert history["moderation"][0]["note"] == "Approved"
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(QuizEditHistoryModel)) == 1
        assert session.scalar(select(func.count()).select_from(QuizModerationHistoryModel)) == 1
    engine.dispose()


def test_append_records_actual_actor_and_unknown_legacy_actor(tmp_path):
    repository, _sessions, engine = _repository(tmp_path)
    assert repository.append_edit(
        "quiz", "quiz-1", "admin-1", "admin", "Changed answer.",
        changed_fields=["questions"],
    )
    assert repository.import_moderation_history("quiz", "quiz-1", [{
        "timestamp": "2026-08-17T12:00:00+00:00", "actor_id": "legacy",
        "action": "published", "note": "",
    }])
    history = repository.get_history("quiz", "quiz-1")
    assert history["edits"][0]["actor_resolved"] is True
    assert history["moderation"][0]["actor_id"] == "legacy"
    assert history["moderation"][0]["actor_resolved"] is False
    engine.dispose()
