"""Bounded Phase 7 closure scenarios.

These tests are deliberately gated on the disposable PostgreSQL environment.
They must never silently fall back to SQLite or the development database.  The
live implementations are kept here as explicit test entry points so a runner
can enable them once STUDY_BUDDY_TEST_DATABASE_URL is provisioned.
"""

import os
import threading
import time
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, event, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.engine import make_url

from src.api.main import create_app
from src.logic.passwords import PasswordHasher
from src.runtime_config import load_runtime_environment
from src.storage.postgres_models import (
    Base, UserModel, QuizMetadataModel, ClassModel, ClassQuizModel,
    ClassMemberModel, QuizAttemptModel, QuizAttemptQuestionModel,
)
from src.storage.postgres_content_metadata_repository import PostgresContentMetadataRepository
from src.storage.postgres_class_repository import PostgresClassRepository
from src.storage.postgres_content_body_repository import PostgresContentBodyRepository
from src.storage.postgres_content_history_repository import PostgresContentHistoryRepository
from src.storage.postgres_learning_repository import PostgresLearningRepository
from src.storage.postgres_session_repository import PostgresSessionRepository
from src.storage.postgres_user_repository import PostgresUserRepository


# Match the live runner's preflight: local, uncommitted runtime settings may
# provide the disposable database URL and must be loaded before gating tests.
load_runtime_environment()


def _require_test_database():
    value = os.getenv("STUDY_BUDDY_TEST_DATABASE_URL", "").strip()
    if not value:
        pytest.skip(
            "NOT EXECUTED: STUDY_BUDDY_TEST_DATABASE_URL is not configured; "
            "the required dedicated PostgreSQL fixture is unavailable"
        )
    parsed = make_url(value)
    if parsed.get_backend_name() != "postgresql" or parsed.database != "study_buddy_test":
        pytest.fail(
            "refusing Phase 7 closure tests: STUDY_BUDDY_TEST_DATABASE_URL "
            "must target PostgreSQL database study_buddy_test"
        )
    return value


def _fixture():
    url = _require_test_database()
    engine = create_engine(url, pool_pre_ping=True)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    tag = uuid.uuid4().hex[:12]
    owner, student, quiz, klass = [f"p7-{tag}-{x}" for x in ("o", "s", "q", "c")]
    with factory.begin() as s:
        s.add_all([
            UserModel(id=owner, username=owner, email=f"{owner}@e.test", password_hash="x", display_name="Owner", role="teacher"),
            UserModel(id=student, username=student, email=f"{student}@e.test", password_hash="x", display_name="Student", role="student"),
        ])
        s.flush()
        s.add_all([
            QuizMetadataModel(id=quiz, owner_id=owner, source_owner_id=owner, name="Phase7 draft", lifecycle="published", visibility="class_only", source_path=f"{quiz}.json"),
            ClassModel(id=klass, owner_id=owner, name="Phase7 class", status="active"),
        ])
        s.flush()
        s.add(ClassQuizModel(class_id=klass, quiz_id=quiz))
    return engine, factory, owner, student, quiz, klass


def _cleanup(engine, factory, owner, student, quiz, klass):
    with factory.begin() as s:
        s.execute(delete(ClassMemberModel).where(ClassMemberModel.class_id == klass))
        s.execute(delete(ClassQuizModel).where(ClassQuizModel.class_id == klass))
        s.execute(delete(ClassModel).where(ClassModel.id == klass))
        s.execute(delete(QuizMetadataModel).where(QuizMetadataModel.id == quiz))
        s.execute(delete(UserModel).where(UserModel.id.in_([owner, student])))
    engine.dispose()


def test_attempt_limit_completed_boundary_http_race():
    """Ten authenticated devices must not cross the final assessment boundary."""
    url = _require_test_database()
    engine = create_engine(url, pool_pre_ping=True, pool_size=15, max_overflow=0)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    tag = uuid.uuid4().hex[:12]
    owner, student, quiz, klass = [f"p7-http-{tag}-{value}" for value in ("owner", "student", "quiz", "class")]
    password = "phase7-attempt-password"
    question = {
        "id": f"p7-http-{tag}-question", "type": "short_answer",
        "question": "Two plus two?", "answer": ["4"],
    }
    settings = {"attempt_limit": 2, "passing_grade_percent": 50}
    try:
        with factory.begin() as session:
            session.add_all([
                UserModel(
                    id=owner, username=owner, email=f"{owner}@e.test",
                    password_hash=PasswordHasher.hash(password), display_name="Owner",
                    role="teacher", status="active",
                ),
                UserModel(
                    id=student, username=student, email=f"{student}@e.test",
                    password_hash=PasswordHasher.hash(password), display_name="Student",
                    role="student", status="active",
                ),
            ])
            session.flush()
            session.add_all([
                QuizMetadataModel(
                    id=quiz, owner_id=owner, source_owner_id=owner,
                    name="Phase 7 HTTP attempt limit", lifecycle="published",
                    visibility="class_only", source_path=f"{quiz}.json",
                    attempt_limit=2, passing_grade_percent=50,
                ),
                ClassModel(id=klass, owner_id=owner, name="Phase 7 HTTP class", status="active"),
            ])
            session.flush()
            session.add_all([
                ClassQuizModel(class_id=klass, quiz_id=quiz),
                ClassMemberModel(class_id=klass, user_id=student, status="active"),
            ])

        bodies = PostgresContentBodyRepository(factory)
        assert bodies.import_quiz({"id": quiz, "name": "Phase 7 HTTP attempt limit", "questions": [question]})
        learning = PostgresLearningRepository(factory)
        # Consume one of two permitted attempts.  The concurrent HTTP group
        # therefore races at the completed-attempt boundary with one slot left.
        previous = learning.start_assessment(student, {"id": quiz}, settings, [question])
        assert previous is not None
        assert learning.submit_assessment(student, previous["id"], {"0": "4"})

        users = PostgresUserRepository(factory)
        sessions = PostgresSessionRepository(factory)
        app = create_app(
            users, sessions,
            PostgresContentMetadataRepository(factory),
            PostgresClassRepository(factory),
            learning, bodies, PostgresContentHistoryRepository(factory),
        )
        with TestClient(app) as client:
            tokens = []
            for _ in range(10):
                response = client.post(
                    "/api/v1/auth/login", json={"login": student, "password": password},
                )
                assert response.status_code == 200
                tokens.append(response.json()["access_token"])

        def start_group():
            barrier = threading.Barrier(len(tokens))
            responses, errors, lock = [], [], threading.Lock()

            def start(token):
                try:
                    with TestClient(app, raise_server_exceptions=False) as client:
                        barrier.wait(timeout=15)
                        response = client.post(
                            f"/api/v1/quizzes/{quiz}/assessments",
                            headers={"Authorization": f"Bearer {token}"},
                        )
                    with lock:
                        responses.append(response)
                except Exception as exc:
                    with lock:
                        errors.append(exc)

            threads = [threading.Thread(target=start, args=(token,)) for token in tokens]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=30)
            assert all(not thread.is_alive() for thread in threads)
            assert not errors, errors
            return responses

        first_group = start_group()
        assert len(first_group) == 10
        assert {response.status_code for response in first_group} == {200}
        attempt_ids = {response.json()["id"] for response in first_group}
        assert len(attempt_ids) == 1
        attempt_id = attempt_ids.pop()

        with factory() as session:
            active = session.scalars(select(QuizAttemptModel).where(
                QuizAttemptModel.user_id == student,
                QuizAttemptModel.quiz_id == quiz,
                QuizAttemptModel.assessment_snapshot.is_not(None),
                QuizAttemptModel.status == "in_progress",
            )).all()
            assert [attempt.id for attempt in active] == [attempt_id]
            frozen = session.scalars(select(QuizAttemptQuestionModel).where(
                QuizAttemptQuestionModel.attempt_id == attempt_id,
            )).all()
            assert len(frozen) == 1

        with TestClient(app) as client:
            response = client.post(
                f"/api/v1/quizzes/{quiz}/assessments/{attempt_id}/submit",
                json={"responses": {"0": "4"}},
                headers={"Authorization": f"Bearer {tokens[0]}"},
            )
            assert response.status_code == 200
            assert response.json()["status"] == "submitted"

        second_group = start_group()
        assert len(second_group) == 10
        assert {response.status_code for response in second_group} == {409}
        with factory() as session:
            attempts = session.scalars(select(QuizAttemptModel).where(
                QuizAttemptModel.user_id == student,
                QuizAttemptModel.quiz_id == quiz,
                QuizAttemptModel.assessment_snapshot.is_not(None),
            )).all()
            assert len(attempts) == 2
            assert {attempt.status for attempt in attempts} == {"submitted"}
            assert all(attempt.counts_toward_limit for attempt in attempts)
            frozen = session.scalars(select(QuizAttemptQuestionModel).join(
                QuizAttemptModel,
                QuizAttemptQuestionModel.attempt_id == QuizAttemptModel.id,
            ).where(
                QuizAttemptModel.user_id == student,
                QuizAttemptModel.quiz_id == quiz,
            )).all()
            assert len(frozen) == 2
    finally:
        with factory.begin() as session:
            session.execute(delete(QuizAttemptModel).where(
                QuizAttemptModel.user_id == student, QuizAttemptModel.quiz_id == quiz,
            ))
            session.execute(delete(ClassMemberModel).where(ClassMemberModel.class_id == klass))
            session.execute(delete(ClassQuizModel).where(ClassQuizModel.class_id == klass))
            session.execute(delete(ClassModel).where(ClassModel.id == klass))
            session.execute(delete(QuizMetadataModel).where(QuizMetadataModel.id == quiz))
            session.execute(delete(UserModel).where(UserModel.id.in_([owner, student])))
        engine.dispose()


def test_content_metadata_metadata_and_body_races():
    engine, factory, owner, student, quiz, klass = _fixture()
    try:
        barrier = threading.Barrier(2); errors = []
        def worker(name):
            try:
                barrier.wait(timeout=10)
                PostgresContentMetadataRepository(sessionmaker(bind=create_engine(os.environ["STUDY_BUDDY_TEST_DATABASE_URL"]))).save_for_actor("quiz", {"id": quiz, "name": name, "status": "draft", "visibility": "private"}, owner, "teacher")
            except Exception as exc: errors.append(exc)
        ts = [threading.Thread(target=worker, args=(f"phase7-{i}",)) for i in range(2)]
        [t.start() for t in ts]; [t.join(30) for t in ts]
        assert not errors
        with factory() as s:
            row = s.get(QuizMetadataModel, quiz)
            # Import establishes version 1; each serialized effective update
            # advances exactly once.
            assert row.content_version == 3
            assert row.name.startswith("phase7-")
    finally: _cleanup(engine, factory, owner, student, quiz, klass)


def test_content_metadata_body_race_preserves_common_revision():
    engine, factory, owner, student, quiz, klass = _fixture()
    try:
        barrier = threading.Barrier(2); errors = []
        body = {"id": quiz, "name": "Phase7 body", "questions": [{"id": "q1", "question": "x", "type": "short_answer", "answer": ["y"]}]}
        def metadata():
            try:
                barrier.wait(timeout=10)
                PostgresContentMetadataRepository(sessionmaker(bind=create_engine(os.environ["STUDY_BUDDY_TEST_DATABASE_URL"]))).save_for_actor("quiz", {"id": quiz, "name": "Phase7 metadata", "status": "draft", "visibility": "private"}, owner, "teacher")
            except Exception as exc: errors.append(exc)
        def content():
            try:
                barrier.wait(timeout=10)
                PostgresContentBodyRepository(sessionmaker(bind=create_engine(os.environ["STUDY_BUDDY_TEST_DATABASE_URL"]))).import_quiz(body)
            except Exception as exc: errors.append(exc)
        ts = [threading.Thread(target=metadata), threading.Thread(target=content)]
        [t.start() for t in ts]; [t.join(30) for t in ts]
        assert not errors
        with factory() as s:
            row = s.get(QuizMetadataModel, quiz)
            assert row.content_version >= 2
            assert row.name.startswith("Phase7")
    finally: _cleanup(engine, factory, owner, student, quiz, klass)


@pytest.mark.parametrize("operation", ["rotate_rotate", "join_join", "join_reactivate_remove"])
def test_invitation_membership_races(operation):
    engine, factory, owner, student, quiz, klass = _fixture()
    try:
        repo = PostgresClassRepository(factory)
        if operation == "rotate_rotate":
            barrier = threading.Barrier(2); results = []
            def rotate():
                barrier.wait(); results.append(repo.rotate_code("quiz", quiz, owner, "teacher"))
            ts = [threading.Thread(target=rotate) for _ in range(2)]
        elif operation == "join_join":
            repo.rotate_code("quiz", quiz, owner, "teacher")
            code = repo.get_invitation("quiz", quiz, owner, "teacher")
            barrier = threading.Barrier(2); results = []
            def join():
                barrier.wait(); results.append(repo.join_with_code(code, student))
            ts = [threading.Thread(target=join) for _ in range(2)]
        else:
            repo.rotate_code("quiz", quiz, owner, "teacher")
            code = repo.get_invitation("quiz", quiz, owner, "teacher"); repo.join_with_code(code, student)
            barrier = threading.Barrier(2); results = []
            def conflict():
                barrier.wait(); results.append(repo.join_with_code(code, student) if len(results) == 0 else repo.remove_member("quiz", quiz, owner, "teacher", student))
            ts = [threading.Thread(target=conflict) for _ in range(2)]
        [t.start() for t in ts]; [t.join(30) for t in ts]
        assert all(not t.is_alive() for t in ts)
        with factory() as s:
            if operation == "rotate_rotate": assert s.scalar(select(__import__('src.storage.postgres_models', fromlist=['ClassInvitationModel']).ClassInvitationModel.id).where(__import__('src.storage.postgres_models', fromlist=['ClassInvitationModel']).ClassInvitationModel.class_id == klass, __import__('src.storage.postgres_models', fromlist=['ClassInvitationModel']).ClassInvitationModel.status == "active"))
            else: assert s.get(ClassMemberModel, (klass, student)).status in {"active", "removed"}
    finally: _cleanup(engine, factory, owner, student, quiz, klass)


def test_postgresql_outage_recovery_is_bounded_and_injected():
    """A one-shot driver failure returns promptly and the same API recovers."""
    engine, factory, owner, student, quiz, klass = _fixture()
    sessions = PostgresSessionRepository(factory)
    token, _expires_in = sessions.create(student)
    app = create_app(
        PostgresUserRepository(factory), sessions,
        PostgresContentMetadataRepository(factory),
        PostgresClassRepository(factory),
        PostgresLearningRepository(factory),
        PostgresContentBodyRepository(factory),
        PostgresContentHistoryRepository(factory),
    )
    injected = {"count": 0}

    def fail_once(*_args, **_kwargs):
        if injected["count"] == 0:
            injected["count"] = 1
            raise OperationalError(
                "SELECT", {}, RuntimeError("injected Phase 7 outage")
            )

    event.listen(engine, "before_cursor_execute", fail_once)
    try:
        headers = {"Authorization": f"Bearer {token}"}
        with TestClient(app, raise_server_exceptions=False) as client:
            started = time.perf_counter()
            unavailable = client.get("/api/v1/content/metadata", headers=headers)
            elapsed = time.perf_counter() - started

            assert unavailable.status_code == 503
            assert unavailable.json() == {
                "detail": "Persistence service is temporarily unavailable"
            }
            assert elapsed < 5
            assert injected["count"] == 1

            recovered = client.get("/api/v1/content/metadata", headers=headers)
            assert recovered.status_code == 200
    finally:
        event.remove(engine, "before_cursor_execute", fail_once)
        _cleanup(engine, factory, owner, student, quiz, klass)
