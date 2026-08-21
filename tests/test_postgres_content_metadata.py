from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from src.logic.passwords import PasswordHasher
from src.storage.postgres_content_metadata_repository import (
    PostgresContentMetadataRepository,
)
from src.storage.postgres_models import (
    Base,
    FlashcardDeckMetadataModel,
    QuizMetadataModel,
    UserModel,
)


def _repository(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'content.db'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    with sessions.begin() as session:
        session.add(UserModel(
            id="teacher-1", username="teacher", display_name="Teacher",
            password_hash=PasswordHasher.hash("password1"), role="teacher",
            status="active", ban_reason="",
        ))
    return PostgresContentMetadataRepository(sessions), sessions, engine


def test_imports_quiz_metadata_with_resolved_owner_and_settings(tmp_path):
    repository, _sessions, engine = _repository(tmp_path)
    source = {
        "id": "quiz-1",
        "name": "Database Quiz",
        "moderation": {
            "owner_id": "teacher-1", "status": "pending_review",
            "visibility": "class_only",
        },
        "test_settings": {
            "time_limit_minutes": 15, "passing_grade_percent": 75,
            "attempt_limit": 2, "due_at": "2026-09-01T14:30:00+00:00",
            "answer_review_policy": "after_due_date",
        },
        "questions": [{"id": "q1", "question": "Body stays in JSON"}],
    }

    assert repository.import_quiz(source, "data/quizzes/quiz-1/quiz.json")
    item = repository.get_by_id("quiz", "quiz-1")

    assert item["owner_id"] == "teacher-1"
    assert item["owner_resolved"] is True
    assert item["status"] == "pending_review"
    assert item["visibility"] == "class_only"
    assert item["test_settings"]["time_limit_minutes"] == 15
    assert item["test_settings"]["answer_review_policy"] == "after_due_date"
    assert "questions" not in item
    engine.dispose()


def test_legacy_owner_is_preserved_without_invalid_foreign_key(tmp_path):
    repository, _sessions, engine = _repository(tmp_path)
    source = {
        "id": "deck-1", "name": "Bundled Deck",
        "moderation": {
            "owner_id": "legacy", "status": "published", "visibility": "public"
        },
        "cards": [{"id": "c1", "front": "JSON", "back": "only"}],
    }

    assert repository.import_flashcard_deck(
        source, "data/flashcards/deck-1/deck.json"
    )
    item = repository.get_by_id("flashcard", "deck-1")

    assert item["owner_id"] is None
    assert item["source_owner_id"] == "legacy"
    assert item["owner_resolved"] is False
    engine.dispose()


def test_import_is_idempotent_and_updates_metadata_not_content_body(tmp_path):
    repository, sessions, engine = _repository(tmp_path)
    source = {
        "id": "quiz-1", "name": "Original",
        "moderation": {
            "owner_id": "teacher-1", "status": "draft", "visibility": "private"
        },
        "questions": [{"id": "q1"}],
    }
    assert repository.import_quiz(source, "data/quizzes/quiz-1/quiz.json")
    source["name"] = "Renamed"
    source["moderation"]["status"] = "published"
    source["moderation"]["visibility"] = "public"
    source["questions"].append({"id": "q2"})
    assert repository.import_quiz(source, "data/quizzes/quiz-1/quiz.json")

    items = repository.get_all("quiz")
    assert len(items) == 1
    assert items[0]["name"] == "Renamed"
    assert items[0]["status"] == "published"
    with sessions() as session:
        row = session.scalar(select(QuizMetadataModel))
        assert not hasattr(row, "questions")
    engine.dispose()


def test_owned_queries_and_invalid_metadata(tmp_path):
    repository, sessions, engine = _repository(tmp_path)
    quiz = {
        "id": "quiz-1", "name": "Owned Quiz",
        "moderation": {
            "owner_id": "teacher-1", "status": "published", "visibility": "public"
        },
    }
    deck = {
        "id": "deck-1", "name": "Owned Deck",
        "moderation": {
            "owner_id": "teacher-1", "status": "draft", "visibility": "private"
        },
    }
    assert repository.import_quiz(quiz, "quiz.json")
    assert repository.import_flashcard_deck(deck, "deck.json")
    assert {item["kind"] for item in repository.get_owned_by("teacher-1")} == {
        "quiz", "flashcard"
    }
    assert not repository.import_quiz(
        {"id": "bad", "name": "Bad", "moderation": {"status": "wrong"}},
        "bad.json",
    )
    with sessions() as session:
        assert session.scalar(select(FlashcardDeckMetadataModel).where(
            FlashcardDeckMetadataModel.id == "deck-1"
        )) is not None
    engine.dispose()
