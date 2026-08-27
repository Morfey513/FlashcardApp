from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from src.logic.passwords import PasswordHasher
from src.storage.postgres_learning_repository import PostgresLearningRepository
from src.storage.postgres_models import (
    Base, ClassFlashcardDeckModel, ClassMemberModel, ClassModel, ClassQuizModel,
    FlashcardDeckMetadataModel, FlashcardModel, FlashcardProgressModel,
    QuizAttemptAnswerModel, QuizAttemptModel, QuizMetadataModel,
    QuizQuestionModel, QuizQuestionProgressModel, UserModel,
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


def test_progress_summary_is_set_based_and_enforces_current_availability(tmp_path):
    repository, sessions, engine = _repository(tmp_path)
    with sessions.begin() as session:
        session.add(UserModel(
            id="teacher-1", username="teacher", display_name="Teacher",
            password_hash=PasswordHasher.hash("password1"), role="teacher",
            status="active", ban_reason="",
        ))
        session.add_all([
            FlashcardDeckMetadataModel(
                id="public-deck", owner_id="teacher-1", source_owner_id="teacher-1",
                name="Public Deck", lifecycle="published", visibility="public",
                source_path="public-deck.json",
            ),
            FlashcardDeckMetadataModel(
                id="private-deck", owner_id="teacher-1", source_owner_id="teacher-1",
                name="Private Deck", lifecycle="published", visibility="private",
                source_path="private-deck.json",
            ),
            FlashcardDeckMetadataModel(
                id="owned-draft", owner_id="student-1", source_owner_id="student-1",
                name="Owned Draft", lifecycle="draft", visibility="private",
                source_path="owned-draft.json",
            ),
            QuizMetadataModel(
                id="class-quiz", owner_id="teacher-1", source_owner_id="teacher-1",
                name="Class Quiz", lifecycle="published", visibility="class_only",
                source_path="class-quiz.json",
            ),
            QuizMetadataModel(
                id="unpublished-quiz", owner_id="teacher-1", source_owner_id="teacher-1",
                name="Unpublished Quiz", lifecycle="draft", visibility="public",
                source_path="unpublished-quiz.json",
            ),
        ])
        session.add_all([
            FlashcardModel(deck_id="public-deck", card_id="c-public",
                           front_text="Public prompt", back_text="A", position=0),
            FlashcardModel(deck_id="private-deck", card_id="c-private",
                           front_text="Private prompt", back_text="A", position=0),
            FlashcardModel(deck_id="owned-draft", card_id="c-owned",
                           front_text="Owned prompt", back_text="A", position=0),
            QuizQuestionModel(quiz_id="class-quiz", question_id="q-class",
                              question_text="Class question", question_type="short_answer",
                              position=0, correct_answer="A"),
            QuizQuestionModel(quiz_id="unpublished-quiz", question_id="q-draft",
                              question_text="Draft question", question_type="short_answer",
                              position=0, correct_answer="A"),
        ])
        session.add_all([
            FlashcardProgressModel(user_id="student-1", deck_id="public-deck",
                                   card_id="c-public", correct_count=3, wrong_count=2,
                                   mastered=True),
            QuizQuestionProgressModel(user_id="student-1", quiz_id="class-quiz",
                                      question_id="q-class", correct_count=4, wrong_count=1,
                                      mastered=False),
        ])
        session.add(ClassModel(
            id="class-1", owner_id="teacher-1", name="Class", status="active",
        ))
        session.add(ClassQuizModel(class_id="class-1", quiz_id="class-quiz"))
        session.add(ClassMemberModel(
            class_id="class-1", user_id="student-1", status="active",
        ))

    statements = []
    event.listen(engine, "before_cursor_execute", lambda *_args: statements.append(1))
    result = repository.get_progress_summary("student-1", "student")

    assert len(statements) == 1
    by_id = {row["id"]: row for row in result["collections"]}
    assert set(by_id) == {
        "deck-1", "quiz-1", "public-deck", "owned-draft", "class-quiz",
    }
    assert by_id["public-deck"]["items"] == [{
        "id": "c-public", "text": "Public prompt", "mastered": True,
        "correct": 3, "wrong": 2,
    }]
    assert by_id["class-quiz"]["items"][0]["correct"] == 4
    assert by_id["owned-draft"]["summary"] == {
        "mastered": 0, "total": 1, "percent": 0, "has_progress": False,
    }

    with sessions.begin() as session:
        session.get(ClassMemberModel, ("class-1", "student-1")).status = "removed"
        session.get(FlashcardDeckMetadataModel, "public-deck").lifecycle = "draft"
        session.delete(session.get(FlashcardDeckMetadataModel, "owned-draft"))
    changed = repository.get_progress_summary("student-1", "student")
    assert {row["id"] for row in changed["collections"]} == {"deck-1", "quiz-1"}
    engine.dispose()


def test_progress_summary_reflects_kind_and_all_progress_clears(tmp_path):
    repository, sessions, engine = _repository(tmp_path)
    with sessions.begin() as session:
        session.add(FlashcardModel(
            deck_id="deck-1", card_id="card-1", front_text="Card", back_text="Answer",
            position=0,
        ))
        session.add(QuizQuestionModel(
            quiz_id="quiz-1", question_id="question-1", question_text="Question",
            question_type="short_answer", position=0, correct_answer="Answer",
        ))
    assert repository.import_flashcard_progress("deck-1", "student-1", {
        "card-1": {"correct": 2, "wrong": 1, "mastered": True},
    })
    assert repository.import_quiz_progress("quiz-1", "student-1", {
        "question-1": {"correct": 1, "wrong": 3, "mastered": False},
    })
    assert repository.clear_user_progress("flashcard", "student-1") == 1
    summary = repository.get_progress_summary("student-1", "student")
    by_id = {row["id"]: row for row in summary["collections"]}
    assert by_id["deck-1"]["items"][0]["correct"] == 0
    assert by_id["quiz-1"]["items"][0]["wrong"] == 3
    assert repository.clear_user_progress("quiz", "student-1") == 1
    assert repository.get_progress_summary("student-1", "student")["summary"] == {
        "flashcards": {"mastered": 0, "total": 1},
        "quizzes": {"mastered": 0, "total": 1},
    }
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
