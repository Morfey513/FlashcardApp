from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from src.logic.passwords import PasswordHasher
from src.storage.postgres_learning_repository import PostgresLearningRepository
from src.storage.postgres_models import (
    Base, FlashcardDeckMetadataModel, QuizAttemptAnswerModel,
    QuizAttemptModel, QuizMetadataModel, UserModel,
)


def _repository(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'learning.db'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    with sessions.begin() as session:
        session.add(UserModel(
            id="student-1", username="student", display_name="Student",
            password_hash=PasswordHasher.hash("password1"), role="student",
            status="active", ban_reason="",
        ))
        common = {
            "owner_id": None, "source_owner_id": "legacy", "lifecycle": "published",
            "visibility": "public",
        }
        session.add(QuizMetadataModel(
            id="quiz-1", name="Quiz", source_path="quiz.json", **common
        ))
        session.add(FlashcardDeckMetadataModel(
            id="deck-1", name="Deck", source_path="deck.json", **common
        ))
    return PostgresLearningRepository(sessions), sessions, engine


def test_progress_import_is_idempotent_and_guest_stays_local(tmp_path):
    repository, _sessions, engine = _repository(tmp_path)
    assert repository.import_flashcard_progress("deck-1", "student-1", {
        "card-1": {"correct": 2, "wrong": 1, "mastered": True},
    })
    assert repository.import_flashcard_progress("deck-1", "student-1", {
        "card-2": {"correct": 1, "wrong": 0, "mastered": False},
    })
    assert repository.get_flashcard_progress("deck-1", "student-1") == {
        "card-2": {"correct": 1, "wrong": 0, "mastered": False}
    }
    assert not repository.import_flashcard_progress("deck-1", "guest", {})
    assert repository.get_flashcard_progress("deck-1", "guest") == {}
    engine.dispose()


def test_quiz_progress_round_trip(tmp_path):
    repository, _sessions, engine = _repository(tmp_path)
    progress = {"question-1": {"correct": 5, "wrong": 2, "mastered": True}}
    assert repository.import_quiz_progress("quiz-1", "student-1", progress)
    assert repository.get_quiz_progress("quiz-1", "student-1") == progress
    engine.dispose()


def test_attempt_import_preserves_answers_and_resolution(tmp_path):
    repository, sessions, engine = _repository(tmp_path)
    source = {
        "id": "attempt-1", "quiz_id": "quiz-1", "user_id": "student-1",
        "mode": "test", "status": "submitted",
        "started_at": "2026-08-14T12:00:00+00:00",
        "submitted_at": "2026-08-14T12:01:00+00:00",
        "score": 1, "total": 1, "percentage": 100.0, "passed": True,
        "attempt_number": 1,
        "answers": [{
            "question_id": "question-1", "question": "2 + 2?",
            "type": "short_answer", "user_answer": "4", "correct_answer": "4",
            "is_correct": True, "response_seconds": 4.5,
        }],
    }
    assert repository.import_quiz_attempt(source)
    assert repository.import_quiz_attempt(source)
    attempts = repository.get_quiz_attempts("quiz-1", "student-1")
    assert len(attempts) == 1
    assert attempts[0]["answers"][0]["user_answer"] == "4"
    assert repository.assessment_summary("quiz-1", "student-1") == {
        "attempts_used": 1, "best_percentage": 100.0,
        "average_percentage": 100.0, "latest_status": "submitted",
    }
    with sessions() as session:
        assert len(session.scalars(select(QuizAttemptModel)).all()) == 1
        assert len(session.scalars(select(QuizAttemptAnswerModel)).all()) == 1
    engine.dispose()


def test_attempt_rejects_guest_or_unknown_relations(tmp_path):
    repository, _sessions, engine = _repository(tmp_path)
    base = {
        "id": "attempt-1", "quiz_id": "quiz-1", "user_id": "guest",
        "started_at": "2026-08-14T12:00:00+00:00", "answers": [],
    }
    assert not repository.import_quiz_attempt(base)
    assert not repository.import_quiz_attempt({**base, "user_id": "missing"})
    assert not repository.import_quiz_attempt({
        **base, "user_id": "student-1", "quiz_id": "missing"
    })
    engine.dispose()
