"""Focused security and lifecycle coverage for server-authoritative assessments."""

import os
import threading
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, delete, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from sqlalchemy import event

from src.logic.assessment_grading import grade_question
from src.storage.postgres_learning_repository import PostgresLearningRepository
from src.storage.postgres_models import (
    Base,
    QuizAttemptAnswerModel,
    QuizAttemptModel,
    QuizAttemptQuestionModel,
    QuizMetadataModel,
    ClassModel,
    ClassQuizModel,
    ClassMemberModel,
    UserModel,
)


@event.listens_for(QuizAttemptAnswerModel, "before_insert")
def _sqlite_schema_compatibility(_mapper, _connection, target):
    # The production migration permits NULL correct_answer; the declarative
    # annotation predates that migration and makes SQLite create it NOT NULL.
    if target.correct_answer is None:
        target.correct_answer = {}


@pytest.fixture
def learning_repo(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'assessment.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    yield PostgresLearningRepository(factory), factory
    engine.dispose()


def _questions():
    return [
        {"id": "q1", "question": "Two plus two?", "type": "short_answer", "answer": ["4"]},
        {"id": "q2", "question": "Pick", "type": "single_choice", "choices": ["a", "b"], "answer": "b"},
    ]


def test_assessment_start_resume_and_snapshot_is_immutable(learning_repo):
    repo, factory = learning_repo
    settings = {"attempt_limit": 1, "answer_review_policy": "never", "passing_grade_percent": 50}
    first = repo.start_assessment("student-a", {"id": "quiz-a"}, settings, _questions())
    resumed = repo.start_assessment("student-a", {"id": "quiz-a"}, settings, [{**_questions()[0], "question": "changed", "answer": ["9"]}])
    assert first["id"] == resumed["id"]
    first_positions = {question["id"]: question["position"] for question in first["questions"]}
    resumed_positions = {question["id"]: question["position"] for question in resumed["questions"]}
    assert resumed_positions == first_positions
    resumed_by_id = {question["id"]: question for question in resumed["questions"]}
    assert resumed_by_id["q1"]["question"] == "Two plus two?"
    with factory() as session:
        attempt = session.get(QuizAttemptModel, first["id"])
        assert attempt.assessment_snapshot["answer_review_policy"] == "never"


def test_ordering_snapshot_freezes_complete_presentation(learning_repo):
    repo, factory = learning_repo
    ordering = {
        "id": "order-q", "question": "Arrange", "type": "ordering",
        # The content repository stores the canonical order under answer.
        "answer": ["first", "second", "third"],
    }
    assessment = repo.start_assessment("student-a", {"id": "quiz-order"}, {}, [ordering])
    assert set(assessment["questions"][0]["items"]) == {"first", "second", "third"}
    ordering["answer"] = ["changed"]
    resumed = repo.get_assessment("student-a", assessment["id"])
    assert set(resumed["questions"][0]["items"]) == {"first", "second", "third"}


def test_terminal_get_applies_answer_review_policy(learning_repo):
    repo, factory = learning_repo
    immediate = repo.start_assessment("student-a", {"id": "quiz-now"},
                                      {"answer_review_policy": "immediate"}, _questions())
    repo.submit_assessment("student-a", immediate["id"], {"0": "4"})
    assert repo.get_assessment("student-a", immediate["id"])["answers"]

    delayed = repo.start_assessment("student-a", {"id": "quiz-later"}, {
        "answer_review_policy": "after_due_date",
        "due_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
    }, _questions())
    repo.submit_assessment("student-a", delayed["id"], {"0": "4"})
    assert repo.get_assessment("student-a", delayed["id"])["answers"] == []
    with factory.begin() as session:
        attempt = session.get(QuizAttemptModel, delayed["id"])
        snapshot = dict(attempt.assessment_snapshot)
        snapshot["due_at"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        attempt.assessment_snapshot = snapshot
    assert repo.get_assessment("student-a", delayed["id"])["answers"]

    hidden = repo.start_assessment("student-a", {"id": "quiz-hidden"},
                                   {"answer_review_policy": "never"}, _questions())
    repo.submit_assessment("student-a", hidden["id"], {"0": "4"})
    result = repo.get_assessment("student-a", hidden["id"])
    assert result["answers"] == []
    assert "grading_key_json" not in result


def test_checkpoint_uses_frozen_position_and_rejects_unknown_without_mutation(learning_repo):
    repo, factory = learning_repo
    assessment = repo.start_assessment("student-a", {"id": "quiz-a"}, {}, _questions())
    q1_position = next(q["position"] for q in assessment["questions"] if q["id"] == "q1")
    assert repo.checkpoint_assessment("student-a", assessment["id"], q1_position, "4")["saved"]
    assert repo.checkpoint_assessment("student-a", assessment["id"], 99, "bad") is None
    with factory() as session:
        answers = session.scalars(select(QuizAttemptAnswerModel).where(QuizAttemptAnswerModel.attempt_id == assessment["id"])).all()
        assert len(answers) == 1 and answers[0].question_id == "q1" and answers[0].user_answer == "4"


def test_submit_ignores_client_score_and_uses_frozen_keys(learning_repo):
    repo, factory = learning_repo
    assessment = repo.start_assessment("student-a", {"id": "quiz-a"}, {"passing_grade_percent": 100}, _questions())
    positions = {q["id"]: q["position"] for q in assessment["questions"]}
    result = repo.submit_assessment("student-a", assessment["id"], {str(positions["q1"]): "4", str(positions["q2"]): "a", "client_score": 999})
    assert result["status"] == "submitted"
    assert result["score"] == 1 and result["passed"] is False
    assert result["answers"]
    assert repo.submit_assessment("student-a", assessment["id"], {"0": "4"}) is None
    with factory() as session:
        assert session.get(QuizAttemptModel, assessment["id"]).status == "submitted"


def test_deadline_finalizes_timed_out_and_review_policies_redact(learning_repo):
    repo, factory = learning_repo
    assessment = repo.start_assessment("student-a", {"id": "quiz-a"}, {"answer_review_policy": "never", "time_limit_minutes": 1}, _questions())
    with factory.begin() as session:
        attempt = session.get(QuizAttemptModel, assessment["id"])
        snapshot = dict(attempt.assessment_snapshot)
        snapshot["deadline_at"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        attempt.assessment_snapshot = snapshot
    result = repo.submit_assessment("student-a", assessment["id"], {"0": "4"})
    assert result["status"] == "timed_out" and result["answers"] == []


def test_immediate_review_returns_results_but_after_due_date_stays_redacted(learning_repo):
    repo, factory = learning_repo
    immediate = repo.start_assessment("student-a", {"id": "quiz-immediate"}, {"answer_review_policy": "immediate"}, _questions())
    immediate_result = repo.submit_assessment("student-a", immediate["id"], {"0": "4"})
    assert immediate_result["answers"]

    delayed = repo.start_assessment("student-a", {"id": "quiz-delayed"}, {
        "answer_review_policy": "after_due_date",
        "due_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
    }, _questions())
    delayed_result = repo.submit_assessment("student-a", delayed["id"], {"0": "4"})
    assert delayed_result["answers"] == []


def test_expired_checkpoint_grades_persisted_answers_and_blocks_later_mutation(learning_repo):
    repo, factory = learning_repo
    assessment = repo.start_assessment("student-a", {"id": "quiz-timeout"}, {
        "answer_review_policy": "immediate", "passing_grade_percent": 50,
        "time_limit_minutes": 1,
    }, _questions())
    q1_position = next(q["position"] for q in assessment["questions"] if q["id"] == "q1")
    q2_position = next(q["position"] for q in assessment["questions"] if q["id"] == "q2")
    assert repo.checkpoint_assessment("student-a", assessment["id"], q1_position, "4")["saved"]
    with factory.begin() as session:
        attempt = session.get(QuizAttemptModel, assessment["id"])
        snapshot = dict(attempt.assessment_snapshot)
        snapshot["deadline_at"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        attempt.assessment_snapshot = snapshot

    timed_out = repo.checkpoint_assessment("student-a", assessment["id"], q2_position, "b")
    assert timed_out["status"] == "timed_out"
    assert timed_out["score"] == 1
    assert timed_out["percentage"] == 50.0
    assert timed_out["passed"] is True

    assert repo.checkpoint_assessment("student-a", assessment["id"], q1_position, "wrong") is None
    assert repo.submit_assessment("student-a", assessment["id"], {
        str(q1_position): "wrong", str(q2_position): "b"
    }) is None
    with factory() as session:
        attempt = session.get(QuizAttemptModel, assessment["id"])
        answers = session.scalars(select(QuizAttemptAnswerModel).where(
            QuizAttemptAnswerModel.attempt_id == assessment["id"]
        )).all()
        assert attempt.status == "timed_out"
        assert attempt.score == 1 and attempt.percentage == 50.0 and attempt.passed is True
        assert {answer.position: answer.user_answer for answer in answers} == {
            q1_position: "4", q2_position: None
        }


def test_assessment_response_cannot_cross_user_boundary(learning_repo):
    repo, _factory = learning_repo
    assessment = repo.start_assessment("student-a", {"id": "quiz-a"}, {}, _questions())
    assert repo.get_assessment("student-b", assessment["id"]) is None
    assert repo.checkpoint_assessment("student-b", assessment["id"], 0, "forged") is None
    assert repo.submit_assessment("student-b", assessment["id"], {"0": "forged"}) is None


def test_teacher_resolution_preserves_frozen_snapshot(learning_repo):
    repo, factory = learning_repo
    now = datetime.now(timezone.utc)
    with factory.begin() as session:
        session.add_all([
            UserModel(id="student-a", username="student-a", email="student-a@example.test", password_hash="x", display_name="Student", role="student"),
            UserModel(id="teacher-a", username="teacher-a", email="teacher-a@example.test", password_hash="x", display_name="Teacher", role="teacher"),
            QuizMetadataModel(id="quiz-a", owner_id="teacher-a", source_owner_id="teacher-a", name="Quiz", lifecycle="published", visibility="class_only", source_path="quiz-a.json"),
            QuizAttemptModel(id="attempt-a", user_id="student-a", quiz_id="quiz-a", mode="assessment", status="in_progress", started_at=now, total=1, assessment_snapshot={"version": 1, "answer_review_policy": "never"}),
        ])
    resolved = repo.resolve_attempt("quiz-a", "attempt-a", "mark_zero", "teacher-a")
    assert resolved["status"] == "marked_zero"
    with factory() as session:
        stored = session.get(QuizAttemptModel, "attempt-a")
        assert stored.resolved_by == "teacher-a"
        assert stored.assessment_snapshot == {"version": 1, "answer_review_policy": "never"}


def test_all_supported_question_types_have_distinct_grading_contracts():
    cases = [
        ("true_false", True, True),
        ("single_choice", "b", "b"),
        ("multiple_choice", ["a", "c"], ["c", "a"]),
        ("short_answer", ["Paris", "paris"], "PARIS"),
        ("matching", {"one": "1"}, {"one": "1"}),
        ("ordering", ["a", "b"], ["a", "b"]),
    ]
    assert all(grade_question(kind, answer, response) for kind, answer, response in cases)


def test_legacy_null_snapshot_is_not_treated_as_assessment(learning_repo):
    _repo, factory = learning_repo
    with factory.begin() as session:
        session.add(QuizAttemptModel(id="legacy", user_id="student-a", quiz_id="quiz-a", mode="test", status="submitted", started_at=datetime.now(timezone.utc), total=1))
    assert _repo.get_assessment("student-a", "legacy") is None


@pytest.mark.skipif(
    not os.environ.get("STUDY_BUDDY_TEST_DATABASE_URL"),
    reason="STUDY_BUDDY_TEST_DATABASE_URL is not configured",
)
def test_concurrent_assessment_start_requires_dedicated_postgres():
    """Two independent PostgreSQL sessions must converge on one assessment."""
    database_url = os.environ["STUDY_BUDDY_TEST_DATABASE_URL"]
    parsed = make_url(database_url)
    assert parsed.get_backend_name() == "postgresql"
    assert parsed.database == "study_buddy_test", "refuse to touch the application database"

    engine = create_engine(database_url, pool_pre_ping=True)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    suffix = uuid.uuid4().hex
    # Keep every identifier used in bounded username/email columns below the
    # schema's 50-character limit while retaining per-run uniqueness.
    student_id, teacher_id = f"s-{suffix}", f"t-{suffix}"
    quiz_id, class_id = f"q-{suffix}", f"c-{suffix}"
    questions = [{"id": f"qst-{suffix}", "question": "Two plus two?", "type": "short_answer", "answer": ["4"]}]
    worker_engines = []
    try:
        with factory.begin() as session:
            session.add_all([
                UserModel(id=student_id, username=student_id, email=f"{student_id}@e.test", password_hash="x", display_name="Student", role="student", status="active"),
                UserModel(id=teacher_id, username=teacher_id, email=f"{teacher_id}@e.test", password_hash="x", display_name="Teacher", role="teacher", status="active"),
            ])
            session.flush()
            session.add(ClassModel(id=class_id, owner_id=teacher_id, name="Concurrency class", status="active"))
            # Establish the referenced ORM rows before inserting dependent
            # membership/quiz-link rows.  This keeps the fixture reliable on
            # PostgreSQL's enforced foreign keys.
            session.flush()
            session.add(
                ClassMemberModel(class_id=class_id, user_id=student_id, status="active")
            )
            session.add(
                QuizMetadataModel(id=quiz_id, owner_id=teacher_id, source_owner_id=teacher_id, name="Concurrency quiz", lifecycle="published", visibility="class_only", source_path=f"{quiz_id}.json")
            )
            session.flush()
            session.add(
                ClassQuizModel(class_id=class_id, quiz_id=quiz_id)
            )

        barrier = threading.Barrier(2)
        results, errors = [], []

        def start():
            try:
                barrier.wait(timeout=10)
                worker_engine = create_engine(database_url, pool_pre_ping=True)
                worker_engines.append(worker_engine)
                repo = PostgresLearningRepository(sessionmaker(bind=worker_engine, expire_on_commit=False))
                results.append(repo.start_assessment(student_id, {"id": quiz_id}, {}, questions))
            except Exception as exc:  # expose harness failures rather than silently skipping
                errors.append(exc)

        threads = [threading.Thread(target=start) for _ in range(2)]
        for thread in threads: thread.start()
        for thread in threads: thread.join(timeout=30)
        assert all(not thread.is_alive() for thread in threads)
        assert not errors, errors
        assert len(results) == 2 and all(result for result in results)
        assert results[0]["id"] == results[1]["id"]

        with factory() as session:
            attempts = session.scalars(select(QuizAttemptModel).where(QuizAttemptModel.user_id == student_id, QuizAttemptModel.quiz_id == quiz_id, QuizAttemptModel.assessment_snapshot.is_not(None), QuizAttemptModel.status == "in_progress")).all()
            assert len(attempts) == 1
            frozen = session.scalars(select(QuizAttemptQuestionModel).where(QuizAttemptQuestionModel.attempt_id == attempts[0].id)).all()
            assert len(frozen) == len(questions)
    finally:
        for worker_engine in worker_engines:
            worker_engine.dispose()
        with factory.begin() as session:
            session.execute(delete(QuizAttemptModel).where(QuizAttemptModel.user_id == student_id, QuizAttemptModel.quiz_id == quiz_id))
            session.execute(delete(ClassQuizModel).where(ClassQuizModel.class_id == class_id))
            session.execute(delete(ClassMemberModel).where(ClassMemberModel.class_id == class_id))
            session.execute(delete(ClassModel).where(ClassModel.id == class_id))
            session.execute(delete(QuizMetadataModel).where(QuizMetadataModel.id == quiz_id))
            session.execute(delete(UserModel).where(UserModel.id.in_([student_id, teacher_id])))
        engine.dispose()


def _pg_race_setup(database_url, *, deadline=None):
    """Create an isolated PostgreSQL assessment and return cleanup context."""
    engine = create_engine(database_url, pool_pre_ping=True)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    suffix = uuid.uuid4().hex[:16]
    student, teacher = f"rs-{suffix}", f"rt-{suffix}"
    quiz, klass = f"rq-{suffix}", f"rc-{suffix}"
    questions = [{"id": f"qq-{suffix}", "question": "2+2?", "type": "short_answer", "answer": ["4"]}]
    settings = {"time_limit_minutes": 1}
    if deadline is not None:
        settings["time_limit_minutes"] = None
    with factory.begin() as session:
        session.add_all([
            UserModel(id=student, username=student, email=f"{student}@e.test", password_hash="x", display_name="S", role="student", status="active"),
            UserModel(id=teacher, username=teacher, email=f"{teacher}@e.test", password_hash="x", display_name="T", role="teacher", status="active"),
        ])
        session.flush()
        session.add(ClassModel(id=klass, owner_id=teacher, name="Race", status="active"))
        session.flush()
        session.add(ClassMemberModel(class_id=klass, user_id=student, status="active"))
        session.add(QuizMetadataModel(id=quiz, owner_id=teacher, source_owner_id=teacher, name="Race quiz", lifecycle="published", visibility="class_only", source_path=f"{quiz}.json"))
        session.flush()
        session.add(ClassQuizModel(class_id=klass, quiz_id=quiz))
    repo = PostgresLearningRepository(factory)
    assessment = repo.start_assessment(student, {"id": quiz}, settings, questions)
    if deadline is not None:
        with factory.begin() as session:
            attempt = session.get(QuizAttemptModel, assessment["id"])
            snap = dict(attempt.assessment_snapshot)
            snap["deadline_at"] = deadline.isoformat()
            attempt.assessment_snapshot = snap
    return engine, factory, repo, student, teacher, quiz, klass, assessment["id"]


def _pg_race_cleanup(engine, factory, student, teacher, quiz, klass, attempt_id):
    with factory.begin() as session:
        session.execute(delete(QuizAttemptModel).where(QuizAttemptModel.id == attempt_id))
        session.execute(delete(ClassQuizModel).where(ClassQuizModel.class_id == klass))
        session.execute(delete(ClassMemberModel).where(ClassMemberModel.class_id == klass))
        session.execute(delete(ClassModel).where(ClassModel.id == klass))
        session.execute(delete(QuizMetadataModel).where(QuizMetadataModel.id == quiz))
        session.execute(delete(UserModel).where(UserModel.id.in_([student, teacher])))
    engine.dispose()


_PG_RACE_SKIP = pytest.mark.skipif(not os.environ.get("STUDY_BUDDY_TEST_DATABASE_URL"), reason="STUDY_BUDDY_TEST_DATABASE_URL is not configured")


@_PG_RACE_SKIP
def test_pg_concurrent_checkpoint_and_submit():
    url = os.environ["STUDY_BUDDY_TEST_DATABASE_URL"]
    assert make_url(url).database == "study_buddy_test"
    engine, factory, repo, student, teacher, quiz, klass, aid = _pg_race_setup(url)
    barrier, results = threading.Barrier(2), []
    def worker(submit):
        barrier.wait(); results.append(repo.submit_assessment(student, aid, {"0": "4"}) if submit else repo.checkpoint_assessment(student, aid, 0, "4"))
    threads = [threading.Thread(target=worker, args=(False,)), threading.Thread(target=worker, args=(True,))]
    try:
        [t.start() for t in threads]; [t.join(30) for t in threads]
        assert all(not t.is_alive() for t in threads)
        with factory() as session: assert session.get(QuizAttemptModel, aid).status == "submitted"
    finally: _pg_race_cleanup(engine, factory, student, teacher, quiz, klass, aid)


@_PG_RACE_SKIP
def test_pg_concurrent_checkpoints_same_position():
    url = os.environ["STUDY_BUDDY_TEST_DATABASE_URL"]; assert make_url(url).database == "study_buddy_test"
    engine, factory, repo, student, teacher, quiz, klass, aid = _pg_race_setup(url)
    barrier, errors = threading.Barrier(2), []
    def worker(value):
        try: barrier.wait(); repo.checkpoint_assessment(student, aid, 0, value)
        except Exception as exc: errors.append(exc)
    threads = [threading.Thread(target=worker, args=("4",)), threading.Thread(target=worker, args=("5",))]
    try:
        [t.start() for t in threads]; [t.join(30) for t in threads]
        assert not errors
        with factory() as session: assert session.scalar(select(QuizAttemptAnswerModel).where(QuizAttemptAnswerModel.attempt_id == aid, QuizAttemptAnswerModel.position == 0)) is not None
    finally: _pg_race_cleanup(engine, factory, student, teacher, quiz, klass, aid)


@_PG_RACE_SKIP
def test_pg_expiry_races_submit_and_checkpoint():
    url = os.environ["STUDY_BUDDY_TEST_DATABASE_URL"]; assert make_url(url).database == "study_buddy_test"
    engine, factory, repo, student, teacher, quiz, klass, aid = _pg_race_setup(url, deadline=datetime.now(timezone.utc) - timedelta(seconds=1))
    barrier = threading.Barrier(2)
    def worker(submit):
        barrier.wait(); return repo.submit_assessment(student, aid, {"0": "4"}) if submit else repo.checkpoint_assessment(student, aid, 0, "4")
    threads = [threading.Thread(target=worker, args=(False,)), threading.Thread(target=worker, args=(True,))]
    try:
        [t.start() for t in threads]; [t.join(30) for t in threads]
        with factory() as session: assert session.get(QuizAttemptModel, aid).status == "timed_out"
    finally: _pg_race_cleanup(engine, factory, student, teacher, quiz, klass, aid)


@_PG_RACE_SKIP
def test_pg_teacher_resolution_races_learner_submit():
    url = os.environ["STUDY_BUDDY_TEST_DATABASE_URL"]; assert make_url(url).database == "study_buddy_test"
    engine, factory, repo, student, teacher, quiz, klass, aid = _pg_race_setup(url)
    barrier = threading.Barrier(2)
    def worker(resolve):
        barrier.wait(); return repo.resolve_attempt(quiz, aid, "submit_current", teacher) if resolve else repo.submit_assessment(student, aid, {"0": "4"})
    threads = [threading.Thread(target=worker, args=(True,)), threading.Thread(target=worker, args=(False,))]
    try:
        [t.start() for t in threads]; [t.join(30) for t in threads]
        with factory() as session: assert session.get(QuizAttemptModel, aid).status == "submitted"
    finally: _pg_race_cleanup(engine, factory, student, teacher, quiz, klass, aid)
