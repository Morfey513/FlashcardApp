from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.schema import CreateIndex
from sqlalchemy.orm import Session

from src.storage.postgres_models import (
    Base,
    QuizAttemptModel,
    QuizAttemptQuestionModel,
    QuizMetadataModel,
    UserModel,
)


@pytest.fixture
def session():
    engine = create_engine("sqlite+pysqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection, _connection_record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    try:
        with Session(engine) as db:
            db.add(
                UserModel(
                    id="user-1",
                    username="student",
                    email="student@example.test",
                    password_hash="hash",
                    display_name="Student",
                    role="student",
                )
            )
            db.commit()
            db.add(
                QuizMetadataModel(
                    id="quiz-1",
                    owner_id="user-1",
                    source_owner_id="user-1",
                    name="Quiz",
                    lifecycle="published",
                    visibility="class_only",
                    source_path="quiz.json",
                )
            )
            db.commit()
            yield db
    finally:
        engine.dispose()


def make_attempt(snapshot=None):
    return QuizAttemptModel(
        id="attempt-1",
        user_id="user-1",
        quiz_id="quiz-1",
        status="in_progress",
        started_at=datetime.now(timezone.utc),
        assessment_snapshot=snapshot,
    )


def make_question(position=1, question_id="question-1"):
    return QuizAttemptQuestionModel(
        attempt_id="attempt-1",
        position=position,
        question_id=question_id,
        presentation_json={"prompt": "2+2?", "choices": ["4", "5"]},
        grading_key_json={"correct": "4"},
    )


def test_legacy_attempt_has_no_snapshot_or_children(session):
    session.add(make_attempt())
    session.commit()

    attempt = session.get(QuizAttemptModel, "attempt-1")
    assert attempt.assessment_snapshot is None
    assert session.query(QuizAttemptQuestionModel).count() == 0


def test_snapshot_questions_persist_json_payloads(session):
    session.add(make_attempt({"version": 1, "question_count": 1}))
    session.add(make_question())
    session.commit()

    question = session.get(
        QuizAttemptQuestionModel, ("attempt-1", 1)
    )
    assert question.presentation_json["choices"] == ["4", "5"]
    assert question.grading_key_json == {"correct": "4"}


def test_duplicate_position_is_rejected(session):
    session.add(make_attempt({"version": 1}))
    session.add(make_question())
    session.commit()
    session.add(make_question(question_id="question-2"))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_duplicate_question_id_is_rejected(session):
    session.add(make_attempt({"version": 1}))
    session.add(make_question())
    session.commit()
    session.add(make_question(position=2))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_deleting_attempt_cascades_snapshot_questions(session):
    session.add(make_attempt({"version": 1}))
    session.add(make_question())
    session.commit()
    session.delete(session.get(QuizAttemptModel, "attempt-1"))
    session.commit()

    assert session.get(QuizAttemptQuestionModel, ("attempt-1", 1)) is None


def test_active_assessment_index_is_postgresql_partial_unique():
    index = next(
        index
        for index in QuizAttemptModel.__table__.indexes
        if index.name == "uq_quiz_attempts_active_assessment"
    )
    assert index.unique is True
    compiled = str(CreateIndex(index).compile(dialect=postgresql.dialect()))
    assert "UNIQUE" in compiled
    assert "WHERE assessment_snapshot IS NOT NULL" in compiled
    assert "status IN ('in_progress', 'abandoned')" in compiled
