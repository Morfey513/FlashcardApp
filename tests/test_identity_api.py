import os
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker


# Importing the ASGI entry point creates its production repository. This safe
# URL prevents collection from depending on a developer's local PostgreSQL URL;
# each test below injects its own isolated repositories.
os.environ.setdefault("STUDY_BUDDY_DATABASE_URL", "sqlite+pysqlite:///:memory:")

from src.api.main import create_app
from src.controllers.flashcard_editor_controller import FlashcardEditorController
from src.controllers.quiz_controller import QuizController
from src.controllers.quiz_editor_controller import QuizEditorController
from src.storage.http_user_repository import HttpUserRepository
from src.storage.http_content_metadata_repository import HttpContentMetadataRepository
from src.storage.http_content_body_repository import HttpContentBodyRepository
from src.storage.http_content_history_repository import HttpContentHistoryRepository
from src.storage.http_class_repository import HttpClassRepository
from src.storage.http_learning_repository import HttpLearningRepository
from src.storage.http_domain_repositories import HttpFlashcardRepository, HttpQuizRepository


def test_http_quiz_assessment_adapter_contracts():
    calls = []

    class User:
        def _request(self, method, path, payload=None, authenticated=False):
            calls.append((method, path, payload, authenticated))
            return 200, {"id": "attempt-1", "quiz_id": "quiz-1", "questions": [], "saved": True}

    repo = HttpQuizRepository(User())
    assert repo.start_assessment("quiz-1")["id"] == "attempt-1"
    assert repo.get_assessment("quiz-1", "attempt-1")["id"] == "attempt-1"
    assert repo.checkpoint_assessment("quiz-1", "attempt-1", 2, "answer")["saved"] is True
    assert repo.submit_assessment("quiz-1", "attempt-1")["id"] == "attempt-1"
    assert [call[:2] for call in calls] == [
        ("POST", "/api/v1/quizzes/quiz-1/assessments"),
        ("GET", "/api/v1/quizzes/quiz-1/assessments/attempt-1"),
        ("PUT", "/api/v1/quizzes/quiz-1/assessments/attempt-1/responses/2"),
        ("POST", "/api/v1/quizzes/quiz-1/assessments/attempt-1/submit"),
    ]
    assert all(call[3] for call in calls)
    assert calls[2][2] == {"user_answer": "answer"}


def test_http_quiz_checkpoint_adapter_reaches_fastapi_with_user_answer(identity_api):
    """Exercise the real adapter/request path, including FastAPI validation."""
    client, _users, _sessions = identity_api
    registration = _register(client, "checkpoint.adapter")

    class ContentStub:
        def get_for_actor(self, _user_id, _role, _scope, kind):
            assert kind == "quiz"
            return [{"id": "quiz-1"}]

    class LearningStub:
        def get_assessment(self, user_id, attempt_id):
            assert user_id == registration["user"]["id"]
            return {"id": attempt_id, "quiz_id": "quiz-1", "status": "in_progress"}

        def checkpoint_assessment(self, user_id, attempt_id, position, answer):
            assert user_id == registration["user"]["id"]
            assert (attempt_id, position, answer) == ("attempt-1", 2, "answer")
            return {"saved": True, "user_answer": answer}

    client.app.state.content_repository = ContentStub()
    client.app.state.learning_repository = LearningStub()

    def requester(method, path, payload, headers):
        response = client.request(method, path, json=payload, headers=headers)
        return response.status_code, response.json() if response.content else None

    user_repository = HttpUserRepository(
        base_url="http://testserver", requester=requester
    )
    user_repository._token = registration["access_token"]
    user_repository._current_user = registration["user"]
    quiz_repository = HttpQuizRepository(user_repository)

    result = quiz_repository.checkpoint_assessment(
        "quiz-1", "attempt-1", 2, "answer"
    )

    assert result == {"saved": True, "user_answer": "answer"}
from src.storage.repository_factory import create_flashcard_repository, create_quiz_repository
from src.storage.postgres_class_repository import PostgresClassRepository
from src.storage.postgres_content_metadata_repository import PostgresContentMetadataRepository
from src.storage.postgres_models import Base, UserSessionModel
from src.storage.postgres_session_repository import PostgresSessionRepository
from src.storage.postgres_user_repository import PostgresUserRepository


@pytest.fixture
def identity_api(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'identity_api.db'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    users = PostgresUserRepository(sessions)
    tokens = PostgresSessionRepository(sessions, lifetime=timedelta(hours=2))
    app = create_app(users, tokens)
    with TestClient(app) as client:
        yield client, users, sessions
    engine.dispose()


def _register(client, login="api.student"):
    response = client.post(
        "/api/v1/auth/register",
        json={"name": "API Student", "login": login, "password": "password1"},
    )
    assert response.status_code == 201
    return response.json()


def _adapter_for(client):
    def requester(method, path, payload, headers):
        response = client.request(method, path, json=payload, headers=headers)
        return response.status_code, response.json() if response.content else None

    return HttpUserRepository(base_url="http://testserver", requester=requester)


def test_assessment_checkpoint_rejects_cross_quiz_without_mutation(identity_api):
    client, _users, _sessions = identity_api
    registration = _register(client, "checkpoint.owner")

    class LearningStub:
        checkpoint_called = False

        def get_assessment(self, user_id, attempt_id):
            return {"id": attempt_id, "quiz_id": "quiz-a", "status": "in_progress"}

        def checkpoint_assessment(self, *args):
            self.checkpoint_called = True
            return {"saved": True}

    learning = LearningStub()
    client.app.state.learning_repository = learning
    response = client.put(
        "/api/v1/quizzes/quiz-b/assessments/attempt-1/responses/0",
        json={"user_answer": "answer"},
        headers={"Authorization": f"Bearer {registration['access_token']}"},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Assessment was not found"
    assert learning.checkpoint_called is False


def test_assessment_start_requires_authentication(identity_api):
    client, _users, _sessions = identity_api
    response = client.post("/api/v1/quizzes/quiz-a/assessments")
    assert response.status_code == 401
    assert response.json()["detail"] == "Authentication required"


def test_health_and_protected_profile(identity_api):
    client, _users, _sessions = identity_api

    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/ready").json() == {"status": "ready"}
    response = client.get("/api/v1/users/me")
    assert response.status_code == 401
    assert response.json()["detail"] == "Authentication required"

    adapter = _adapter_for(client)
    assert adapter.is_online() is True


def test_registration_profile_updates_and_logout(identity_api):
    client, _users, sessions = identity_api
    registration = _register(client)
    token = registration["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    assert registration["token_type"] == "bearer"
    assert registration["expires_in"] == 7200
    assert registration["user"]["login"] == "api.student"
    assert client.post(
        "/api/v1/auth/register",
        json={"name": "Duplicate", "login": "API.STUDENT", "password": "password1"},
    ).status_code == 409

    with sessions() as session:
        stored_hash = session.scalar(select(UserSessionModel.session_token_hash))
    assert stored_hash
    assert stored_hash != token

    response = client.put(
        "/api/v1/users/me/preferences",
        headers=headers,
        json={
            "preferences": {
                "theme": "light",
                "language": "fr",
                "window_sizes": {"launcher": [800, 700]},
            }
        },
    )
    assert response.status_code == 200
    assert response.json()["preferences"]["language"] == "fr"

    response = client.patch(
        "/api/v1/users/me/display-name",
        headers=headers,
        json={"name": "Updated Student"},
    )
    assert response.status_code == 200
    assert response.json()["name"] == "Updated Student"

    assert client.post("/api/v1/auth/logout", headers=headers).status_code == 204
    assert client.get("/api/v1/users/me", headers=headers).status_code == 401


def test_authenticated_users_can_resolve_roster_safe_public_profiles(identity_api):
    client, _users, _sessions = identity_api
    first = _register(client, "roster.one")
    second = _register(client, "roster.two")
    headers = {"Authorization": f"Bearer {first['access_token']}"}

    response = client.post(
        "/api/v1/users/profiles",
        headers=headers,
        json={"user_ids": [second["user"]["id"], second["user"]["id"], "missing"]},
    )
    assert response.status_code == 200
    assert response.json() == [{
        "id": second["user"]["id"],
        "login": "roster.two",
        "name": "API Student",
    }]

    assert client.post(
        "/api/v1/users/profiles", json={"user_ids": [second["user"]["id"]]},
    ).status_code == 401


def test_login_password_change_and_invalid_credentials(identity_api):
    client, _users, _sessions = identity_api
    _register(client, "password.student")

    bad_login = client.post(
        "/api/v1/auth/login",
        json={"login": "password.student", "password": "incorrect"},
    )
    assert bad_login.status_code == 401
    assert bad_login.json()["detail"] == "Invalid login or password"

    login = client.post(
        "/api/v1/auth/login",
        json={"login": "password.student", "password": "password1"},
    )
    assert login.status_code == 200
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    change = client.post(
        "/api/v1/users/me/change-password",
        headers=headers,
        json={"current_password": "password1", "new_password": "newpassword"},
    )
    assert change.status_code == 204
    assert client.post(
        "/api/v1/auth/login",
        json={"login": "password.student", "password": "newpassword"},
    ).status_code == 200


def test_banned_user_cannot_login_or_reuse_existing_session(identity_api):
    client, users, _sessions = identity_api
    registration = _register(client, "blocked.student")
    headers = {"Authorization": f"Bearer {registration['access_token']}"}
    user_id = registration["user"]["id"]

    assert users.update_status(user_id, "banned", "API policy violation")
    assert client.get("/api/v1/users/me", headers=headers).status_code == 401

    response = client.post(
        "/api/v1/auth/login",
        json={"login": "blocked.student", "password": "password1"},
    )
    assert response.status_code == 403
    assert "API policy violation" in response.json()["detail"]


def test_http_repository_matches_desktop_account_contract(identity_api):
    client, _users, _sessions = identity_api
    repository = _adapter_for(client)

    created, message, user = repository.register(
        "Desktop Student", "desktop.student", "password1"
    )
    assert created and message == "Account created"
    assert repository.get_user_by_id(user["id"])["login"] == "desktop.student"
    assert repository.save_preferences(
        user["id"], {"theme": "light", "language": "fr"}
    )
    assert repository.update_display_name(user["id"], "Remote Student")
    assert repository.change_password(user["id"], "password1", "newpassword") == (
        True,
        "Password changed",
    )
    assert repository.logout()
    assert repository.get_user_by_id(user["id"]) is None
    assert repository.authenticate("desktop.student", "newpassword")["name"] == (
        "Remote Student"
    )


def test_http_repository_resolves_roster_display_profiles_without_admin_access(identity_api):
    client, _users, _sessions = identity_api
    first = _adapter_for(client)
    second = _adapter_for(client)
    _ok, _message, current = first.register("Roster Teacher", "roster.teacher", "password1")
    _ok, _message, other = second.register("Roster Learner", "roster.learner", "password1")

    assert first.get_all_users() == []
    assert first.get_public_users_by_ids([other["id"]]) == [{
        "id": other["id"], "login": "roster.learner", "name": "Roster Learner"
    }]
    assert first.get_user_by_id(other["id"])["name"] == "Roster Learner"
    assert first.get_user_by_id(current["id"])["name"] == "Roster Teacher"


def test_http_quiz_repository_resolves_attempt_through_class_endpoint(identity_api):
    client, users, _sessions = identity_api
    teacher_http = _adapter_for(client)
    _ok, _message, teacher = teacher_http.register(
        "Resolution Teacher", "resolution.teacher", "password1"
    )
    assert users.update_role(teacher["id"], "teacher")
    authenticated = teacher_http.authenticate("resolution.teacher", "password1")
    assert authenticated["role"] == "teacher"
    quizzes = HttpQuizRepository(teacher_http)
    assert quizzes.create_quiz(
        "Resolution Quiz",
        [{"id": "q1", "type": "short_answer", "question": "Q", "answer": "A"}],
    )
    quiz = next(row for row in quizzes.get_all_quizzes() if row["name"] == "Resolution Quiz")
    attempt = quizzes.save_test_attempt(quiz["file"], {
        "id": "attempt-1", "status": "in_progress", "total": 1,
        "answers": [], "user_id": teacher["id"],
    })
    assert attempt
    result = quizzes.resolve_test_attempt(quiz["file"], "attempt-1", "refund", teacher["id"])
    assert result["status"] == "refunded"
    assert result["resolution"] == "refund"


def test_repository_factory_uses_json_before_api_authentication(monkeypatch):
    monkeypatch.setenv("STUDY_BUDDY_STORAGE", "api")
    user = HttpUserRepository()
    assert create_quiz_repository(user).__class__.__name__ == "QuizRepository"
    assert create_flashcard_repository(user).__class__.__name__ == "FlashcardRepository"


def test_repository_factory_uses_http_after_api_authentication(monkeypatch):
    monkeypatch.setenv("STUDY_BUDDY_STORAGE", "api")
    user = HttpUserRepository()
    user._token = "test-token"
    assert create_quiz_repository(user).__class__ is HttpQuizRepository
    assert create_flashcard_repository(user).__class__ is HttpFlashcardRepository


def test_http_repository_admin_operations_are_enforced_by_server(identity_api):
    client, users, _sessions = identity_api
    student_repository = _adapter_for(client)
    created, _message, student = student_repository.register(
        "Managed Student", "managed.desktop", "password1"
    )
    assert created
    assert student_repository.get_all_users() == []  # HTTP 403, not a UI-only rule.

    _created, _message, admin = users.register(
        "API Administrator", "api.admin", "password1"
    )
    assert users.update_role(admin["id"], "admin")
    admin_repository = _adapter_for(client)
    assert admin_repository.authenticate("api.admin", "password1")["role"] == "admin"
    assert len(admin_repository.get_all_users()) == 2
    assert admin_repository.update_role(student["id"], "teacher")
    assert admin_repository.set_account_status(
        "student", student["id"], "banned", "Remote policy violation",
        actor_id="forged-client-id",
    )

    # The server derives the real actor from the token and blocks self-mutation.
    assert not admin_repository.update_role(admin["id"], "student")
    assert not admin_repository.update_status(admin["id"], "banned", "self")

    assert student_repository.authenticate("managed.desktop", "password1") is None
    assert "Remote policy violation" in student_repository.get_ban_message(
        "managed.desktop"
    )


def test_content_metadata_api_and_http_adapter_enforce_ownership(identity_api):
    client, users, sessions = identity_api
    teacher_http = _adapter_for(client)
    _created, _message, teacher = teacher_http.register(
        "Content Teacher", "content.teacher", "password1"
    )
    assert users.update_role(teacher["id"], "teacher")
    assert teacher_http.authenticate("content.teacher", "password1")["role"] == "teacher"
    content_http = HttpContentMetadataRepository(teacher_http)
    payload = {
        "id": "quiz-api-1",
        "name": "Server Quiz",
        "status": "pending_review",
        "visibility": "class_only",
        "source_path": "data/quizzes/quiz-api-1/quiz.json",
        "test_settings": {"time_limit_minutes": 20, "attempt_limit": 2},
    }

    saved = content_http.save("quiz", payload)
    assert saved["owner_id"] == teacher["id"]
    assert saved["status"] == "pending_review"
    assert saved["content_version"] == 1
    assert content_http.get_all("quiz", "owned")[0]["id"] == "quiz-api-1"
    assert content_http.get_by_id("quiz", "quiz-api-1")["name"] == "Server Quiz"
    assert content_http.get_by_id("quiz", "quiz-api-1")["content_version"] == 1

    other_http = _adapter_for(client)
    other_http.register("Other Teacher", "other.teacher", "password1")
    other = other_http._current_user
    assert users.update_role(other["id"], "teacher")
    assert other_http.authenticate("other.teacher", "password1")["role"] == "teacher"
    other_content = HttpContentMetadataRepository(other_http)
    payload["name"] = "Stolen Name"
    assert other_content.save("quiz", payload) is None
    assert other_content.get_by_id("quiz", "quiz-api-1") is None

    _created, _message, admin = users.register("Admin", "content.admin", "password1")
    assert users.update_role(admin["id"], "admin")
    admin_http = _adapter_for(client)
    assert admin_http.authenticate("content.admin", "password1")["role"] == "admin"
    payload.update({"name": "Admin correction", "status": "published"})
    corrected = HttpContentMetadataRepository(admin_http).save("quiz", payload)
    assert corrected["name"] == "Admin correction"
    assert corrected["owner_id"] == teacher["id"]
    assert corrected["source_owner_id"] == teacher["id"]


def test_content_metadata_api_filters_public_and_admin_scope(identity_api):
    client, users, sessions = identity_api
    _created, _message, teacher = users.register(
        "Owner", "metadata.owner", "password1"
    )
    assert users.update_role(teacher["id"], "teacher")
    metadata = PostgresContentMetadataRepository(sessions)
    assert metadata.import_quiz({
        "id": "public-quiz", "name": "Public",
        "moderation": {"owner_id": teacher["id"], "status": "published", "visibility": "public"},
    }, "public.json")
    assert metadata.import_flashcard_deck({
        "id": "private-deck", "name": "Private",
        "moderation": {"owner_id": teacher["id"], "status": "draft", "visibility": "private"},
    }, "private.json")

    student_http = _adapter_for(client)
    student_http.register("Viewer", "metadata.viewer", "password1")
    student_content = HttpContentMetadataRepository(student_http)
    assert [item["id"] for item in student_content.get_all()] == ["public-quiz"]
    assert student_content.get_all(scope="all") == []

    _created, _message, admin = users.register("Admin", "metadata.admin", "password1")
    assert users.update_role(admin["id"], "admin")
    admin_http = _adapter_for(client)
    assert admin_http.authenticate("metadata.admin", "password1")["role"] == "admin"
    assert {item["id"] for item in HttpContentMetadataRepository(admin_http).get_all(scope="all")} == {
        "public-quiz", "private-deck"
    }


def test_class_api_join_rotate_roster_and_remove(identity_api):
    client, users, sessions = identity_api
    teacher_http = _adapter_for(client)
    _ok, _message, teacher = teacher_http.register(
        "Class Teacher", "class.teacher", "password1"
    )
    assert users.update_role(teacher["id"], "teacher")
    assert teacher_http.authenticate("class.teacher", "password1")["role"] == "teacher"
    content = PostgresContentMetadataRepository(sessions)
    classes = PostgresClassRepository(sessions)
    source = {
        "id": "class-quiz", "name": "Class Quiz",
        "moderation": {
            "owner_id": teacher["id"], "status": "published",
            "visibility": "class_only", "enrollments": {},
        },
    }
    assert content.import_quiz(source, "class-quiz.json")
    assert classes.import_content_access(source, "quiz")
    teacher_classes = HttpClassRepository(teacher_http)
    success, code = teacher_classes.generate_or_rotate_code(
        "class-quiz", "quiz", teacher["id"]
    )
    assert success and code

    student_http = _adapter_for(client)
    _ok, _message, student = student_http.register(
        "Class Student", "class.student", "password1"
    )
    student_classes = HttpClassRepository(student_http)
    assert student_classes.enroll_with_code(code, student["id"])[0]
    assert HttpContentMetadataRepository(student_http).get_by_id(
        "quiz", "class-quiz"
    )["name"] == "Class Quiz"
    roster = teacher_classes.get_owned_classes(teacher["id"])
    assert roster[0]["roster"][0]["user_id"] == student["id"]
    assert teacher_classes.remove_enrollment(
        "class-quiz", "quiz", teacher["id"], student["id"]
    )[0]
    assert HttpContentMetadataRepository(student_http).get_by_id(
        "quiz", "class-quiz"
    ) is None


def test_authenticated_learning_progress_and_attempt_api(identity_api):
    client, _users, sessions = identity_api
    registration = _register(client, "learning.student")
    user_id = registration["user"]["id"]
    headers = {"Authorization": f"Bearer {registration['access_token']}"}
    content = PostgresContentMetadataRepository(sessions)
    assert content.import_quiz({
        "id": "learning-quiz", "name": "Learning Quiz",
        "moderation": {
            "owner_id": user_id, "status": "published", "visibility": "public",
        },
    }, "learning-quiz.json")

    response = client.put(
        "/api/v1/progress/quiz/learning-quiz", headers=headers,
        json={"progress": {
            "question-1": {"correct": 2, "wrong": 1, "mastered": True}
        }},
    )
    assert response.status_code == 200
    assert client.get(
        "/api/v1/progress/quiz/learning-quiz", headers=headers
    ).json()["progress"]["question-1"]["correct"] == 2

    response = client.put(
        "/api/v1/quizzes/learning-quiz/attempts/attempt-api-1", headers=headers,
        json={
            "id": "attempt-api-1", "quiz_id": "learning-quiz",
            "started_at": "2026-08-17T12:00:00+00:00",
            "submitted_at": "2026-08-17T12:01:00+00:00",
            "status": "submitted", "score": 1, "total": 1,
            "percentage": 100.0, "passed": True,
            "answers": [{
                "question_id": "question-1", "question": "2 + 2?",
                "type": "short_answer", "user_answer": "4", "correct_answer": "4",
            }],
        },
    )
    assert response.status_code == 200
    attempts = client.get(
        "/api/v1/quizzes/learning-quiz/attempts", headers=headers
    ).json()
    assert attempts[0]["id"] == "attempt-api-1"
    assert attempts[0]["answers"][0]["correct_answer"] == "4"

    user_http = _adapter_for(client)
    assert user_http.authenticate("learning.student", "password1")
    adapter = HttpLearningRepository(user_http)
    assert adapter.get_progress("quiz", "learning-quiz")["question-1"]["correct"] == 2
    assert adapter.get_quiz_attempts("learning-quiz")[0]["score"] == 1


def test_batched_progress_api_is_authorized_current_and_bounded(identity_api):
    client, users, sessions = identity_api
    teacher = _register(client, "progress.teacher")
    assert users.update_role(teacher["user"]["id"], "teacher")
    student = _register(client, "progress.student")
    student_id = student["user"]["id"]
    teacher_id = teacher["user"]["id"]
    headers = {"Authorization": f"Bearer {student['access_token']}"}
    metadata = PostgresContentMetadataRepository(sessions)
    classes = PostgresClassRepository(sessions)
    bodies = client.app.state.content_body_repository
    learning = client.app.state.learning_repository

    public_deck = {
        "id": "summary-public-deck", "name": "Public Deck",
        "moderation": {"owner_id": teacher_id, "status": "published",
                       "visibility": "public"},
    }
    class_quiz = {
        "id": "summary-class-quiz", "name": "Class Quiz",
        "moderation": {
            "owner_id": teacher_id, "status": "published", "visibility": "class_only",
            "invite": {"code": "SUMM-ARY1"},
            "enrollments": {student_id: {}},
        },
    }
    private_quiz = {
        "id": "summary-private-quiz", "name": "Private Quiz",
        "moderation": {"owner_id": teacher_id, "status": "published",
                       "visibility": "private"},
    }
    assert metadata.import_flashcard_deck(public_deck, "summary-public-deck.json")
    assert metadata.import_quiz(class_quiz, "summary-class-quiz.json")
    assert metadata.import_quiz(private_quiz, "summary-private-quiz.json")
    assert classes.import_content_access(class_quiz, "quiz")
    assert bodies.import_flashcard_deck({
        "id": public_deck["id"], "cards": [
            {"id": "card-1", "front": "Prompt", "back": "Answer"},
        ],
    })
    for quiz_id in (class_quiz["id"], private_quiz["id"]):
        assert bodies.import_quiz({
            "id": quiz_id, "questions": [{
                "id": "question-1", "type": "short_answer",
                "question": "Question", "answer": "Answer",
            }],
        })
    assert learning.import_flashcard_progress(public_deck["id"], student_id, {
        "card-1": {"correct": 5, "wrong": 2, "mastered": True},
    })
    assert learning.import_quiz_progress(class_quiz["id"], student_id, {
        "question-1": {"correct": 1, "wrong": 3, "mastered": False},
    })

    statements = []
    engine = sessions.kw["bind"]
    listener = lambda *_args: statements.append(1)
    event.listen(engine, "before_cursor_execute", listener)
    response = client.get(
        "/api/v1/progress/summary?include_items=true", headers=headers,
    )
    event.remove(engine, "before_cursor_execute", listener)

    assert response.status_code == 200
    # Three existing authentication/profile statements plus one set-based projection.
    assert len(statements) == 4
    by_id = {row["id"]: row for row in response.json()["collections"]}
    assert set(by_id) == {public_deck["id"], class_quiz["id"]}
    assert by_id[public_deck["id"]]["items"][0] == {
        "id": "card-1", "text": "Prompt", "mastered": True,
        "correct": 5, "wrong": 2,
    }
    assert by_id[class_quiz["id"]]["summary"]["percent"] == 0

    assert classes.remove_member(
        "quiz", class_quiz["id"], teacher_id, "teacher", student_id,
    )[0]
    assert {row["id"] for row in client.get(
        "/api/v1/progress/summary", headers=headers,
    ).json()["collections"]} == {public_deck["id"]}

    public_deck["moderation"]["status"] = "draft"
    assert metadata.import_flashcard_deck(public_deck, "summary-public-deck.json")
    assert client.get("/api/v1/progress/summary", headers=headers).json()["collections"] == []
    assert metadata.delete_for_actor(
        "flashcard", public_deck["id"], teacher_id, "teacher",
    )
    assert client.get("/api/v1/progress/summary", headers=headers).json()["collections"] == []


@pytest.mark.parametrize(
    ("kind", "content_id", "item_id", "text"),
    [("quiz", "quiz-1", "q1", "Question text"),
     ("flashcard", "deck-1", "c1", "Card front")],
)
def test_progress_endpoint_can_return_lightweight_display_items(
    identity_api, kind, content_id, item_id, text,
):
    client, _users, _sessions = identity_api
    registration = _register(client, f"progress.items.{kind}")
    headers = {"Authorization": f"Bearer {registration['access_token']}"}

    class ContentStub:
        def get_for_actor(self, *_args):
            return [{"id": content_id}]

    class LearningStub:
        def get_quiz_progress(self, *_args):
            return {item_id: {"mastered": True, "correct": 4, "wrong": 1}}

        get_flashcard_progress = get_quiz_progress

    class BodyStub:
        calls = []

        def get_quiz(self, value, *, include_answers=True):
            self.calls.append(("quiz", value))
            assert value == content_id
            assert include_answers is False
            return {"questions": [{"id": item_id, "question": text}]}

        def get_flashcard_deck(self, value):
            self.calls.append(("flashcard", value))
            assert value == content_id
            return {"cards": [{"id": item_id, "front": text}]}

    client.app.state.content_repository = ContentStub()
    client.app.state.learning_repository = LearningStub()
    bodies = BodyStub()
    client.app.state.content_body_repository = bodies

    plain = client.get(
        f"/api/v1/progress/{kind}/{content_id}", headers=headers,
    )
    assert plain.json() == {
        "progress": {item_id: {"mastered": True, "correct": 4, "wrong": 1}},
    }
    assert bodies.calls == []

    response = client.get(
        f"/api/v1/progress/{kind}/{content_id}?include_items=true", headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["items"] == [{
        "id": item_id, "text": text, "mastered": True, "correct": 4, "wrong": 1,
    }]
    assert response.json()["summary"] == {
        "mastered": 1, "total": 1, "percent": 100, "has_progress": True,
    }
    assert bodies.calls == [(kind, content_id)]


@pytest.mark.parametrize(
    ("kind", "content_id", "item_id", "text", "method_name"),
    [("quiz", "quiz-1", "q1", "Question text", "get_quiz_progress_items"),
     ("flashcard", "deck-1", "c1", "Card front", "get_flashcard_progress_items")],
)
def test_progress_endpoint_prefers_item_projection_over_full_body(
    identity_api, kind, content_id, item_id, text, method_name,
):
    client, _users, _sessions = identity_api
    registration = _register(client, f"progress.projection.{kind}")
    headers = {"Authorization": f"Bearer {registration['access_token']}"}

    class ContentStub:
        def get_for_actor(self, *_args):
            return [{"id": content_id}]

    class LearningStub:
        def get_quiz_progress(self, *_args):
            return {item_id: {"mastered": True, "correct": 2, "wrong": 0}}

        get_flashcard_progress = get_quiz_progress

    class BodyStub:
        def get_quiz(self, *_args, **_kwargs):
            raise AssertionError("full quiz body must not be loaded")

        def get_flashcard_deck(self, *_args):
            raise AssertionError("full deck body must not be loaded")

        def get_quiz_progress_items(self, value):
            assert method_name == "get_quiz_progress_items"
            assert value == content_id
            return [{"id": item_id, "text": text}]

        def get_flashcard_progress_items(self, value):
            assert method_name == "get_flashcard_progress_items"
            assert value == content_id
            return [{"id": item_id, "text": text}]

    client.app.state.content_repository = ContentStub()
    client.app.state.learning_repository = LearningStub()
    client.app.state.content_body_repository = BodyStub()

    response = client.get(
        f"/api/v1/progress/{kind}/{content_id}?include_items=true", headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["items"] == [{
        "id": item_id, "text": text, "mastered": True, "correct": 2, "wrong": 0,
    }]


def test_quiz_attempt_put_enforces_owner_and_quiz(identity_api):
    client, users, sessions = identity_api
    owner = _register(client, "attempt.owner")
    other = _register(client, "attempt.other")
    outsider = _register(client, "attempt.outsider")
    metadata = PostgresContentMetadataRepository(sessions)
    for quiz_id, visibility in (("attempt-quiz", "public"), ("other-quiz", "public"),
                                ("private-quiz", "private")):
        assert metadata.import_quiz({
            "id": quiz_id, "name": quiz_id,
            "moderation": {
                "owner_id": owner["user"]["id"], "status": "published",
                "visibility": visibility,
            },
        }, f"{quiz_id}.json")

    def attempt_payload(quiz_id, status="submitted"):
        return {
            "id": "owned-attempt", "quiz_id": quiz_id,
            "started_at": "2026-08-17T12:00:00+00:00",
            "status": status, "score": 1, "total": 1, "percentage": 100.0,
            "passed": True,
            "answers": [{"question_id": "q1", "question": "2 + 2?",
                         "type": "short_answer", "user_answer": "4",
                         "correct_answer": "4"}],
        }

    owner_headers = {"Authorization": f"Bearer {owner['access_token']}"}
    other_headers = {"Authorization": f"Bearer {other['access_token']}"}
    outsider_headers = {"Authorization": f"Bearer {outsider['access_token']}"}
    created = client.put(
        "/api/v1/quizzes/attempt-quiz/attempts/owned-attempt",
        headers=owner_headers, json=attempt_payload("attempt-quiz"),
    )
    assert created.status_code == 200

    denied = client.put(
        "/api/v1/quizzes/attempt-quiz/attempts/owned-attempt",
        headers=other_headers,
        json=attempt_payload("attempt-quiz", "refunded"),
    )
    assert denied.status_code == 403
    original = client.get(
        "/api/v1/quizzes/attempt-quiz/attempts", headers=owner_headers,
    ).json()[0]
    assert original["user_id"] == owner["user"]["id"]
    assert original["status"] == "submitted"
    assert original["answers"][0]["user_answer"] == "4"

    cross_quiz = client.put(
        "/api/v1/quizzes/other-quiz/attempts/owned-attempt",
        headers=owner_headers, json=attempt_payload("other-quiz"),
    )
    assert cross_quiz.status_code == 400
    assert client.get(
        "/api/v1/quizzes/attempt-quiz/attempts", headers=owner_headers,
    ).json()[0]["quiz_id"] == "attempt-quiz"

    no_access = client.put(
        "/api/v1/quizzes/private-quiz/attempts/owned-attempt",
        headers=outsider_headers, json=attempt_payload("private-quiz"),
    )
    assert no_access.status_code in {403, 404}
    assert client.get(
        "/api/v1/quizzes/attempt-quiz/attempts", headers=owner_headers,
    ).json()[0]["quiz_id"] == "attempt-quiz"


def test_content_body_api_owner_write_and_authenticated_read(identity_api):
    client, users, sessions = identity_api
    teacher_http = _adapter_for(client)
    _ok, _message, teacher = teacher_http.register(
        "Body Teacher", "body.teacher", "password1"
    )
    assert users.update_role(teacher["id"], "teacher")
    assert teacher_http.authenticate("body.teacher", "password1")
    metadata = PostgresContentMetadataRepository(sessions)
    assert metadata.import_quiz({
        "id": "body-quiz", "name": "Body Quiz",
        "moderation": {
            "owner_id": teacher["id"], "status": "published", "visibility": "public",
        },
    }, "body-quiz.json")
    bodies = HttpContentBodyRepository(teacher_http)
    saved = bodies.save_quiz({
        "id": "body-quiz", "name": "Body Quiz", "questions": [{
            "id": "question-1", "question": "2 + 2?", "type": "short_answer",
            "answer": "4", "image_path": "",
        }],
    })
    assert saved["questions"][0]["answer"] == "4"
    assert saved["content_version"] == 2
    history = HttpContentHistoryRepository(teacher_http).get_history(
        "quiz", "body-quiz"
    )
    assert history["edits"][0]["changed_by"] == teacher["id"]

    student_http = _adapter_for(client)
    student_http.register("Body Student", "body.student", "password1")
    student_bodies = HttpContentBodyRepository(student_http)
    student_body = student_bodies.get_quiz("body-quiz")
    assert student_body["questions"][0]["question"] == "2 + 2?"
    assert student_body["content_version"] == 2
    assert student_bodies.save_quiz({
        "id": "body-quiz", "name": "Changed", "questions": []
    }) is None


def test_quiz_editor_can_resubmit_published_content_through_real_api(identity_api):
    client, users, sessions = identity_api
    teacher = _register(client, "editor.published.teacher")
    teacher_id = teacher["user"]["id"]
    assert users.update_role(teacher_id, "teacher")
    metadata = PostgresContentMetadataRepository(sessions)
    bodies = client.app.state.content_body_repository
    source = {
        "id": "editor-published-quiz", "name": "Published Quiz",
        "moderation": {
            "owner_id": teacher_id, "status": "published", "visibility": "public",
        },
    }
    assert metadata.import_quiz(source, "editor-published-quiz.json")
    assert bodies.import_quiz({
        "id": source["id"], "questions": [{
            "id": "question-1", "type": "short_answer",
            "question": "Original", "answer": "Answer",
        }],
    })

    http_user = _adapter_for(client)
    assert http_user.authenticate("editor.published.teacher", "password1")
    controller = QuizEditorController(
        teacher_id, "teacher", user_repository=http_user,
    )
    assert controller.get_quiz_entries()
    assert controller.load_quiz("Published Quiz")
    changed = [{
        "id": "question-1", "type": "short_answer",
        "question": "Changed", "answer": "Updated",
    }]

    assert controller.save_quiz(
        changed, {"question-1"}, "public",
        {"attempt_limit": 3, "passing_grade_percent": 70},
    )
    current = metadata.get_by_id("quiz", source["id"])
    assert current["status"] == "pending_review"
    assert current["visibility"] == "public"
    assert current["test_settings"]["attempt_limit"] == 3
    assert bodies.get_quiz(source["id"])["questions"][0]["question"] == "Changed"


def test_quiz_body_api_preserves_authorization_redaction_and_all_types(identity_api):
    client, users, sessions = identity_api
    teacher = _register(client, "quiz.body.teacher")
    student = _register(client, "quiz.body.student")
    outsider = _register(client, "quiz.body.outsider")
    admin = _register(client, "quiz.body.admin")
    assert users.update_role(teacher["user"]["id"], "teacher")
    assert users.update_role(admin["user"]["id"], "admin")
    metadata = PostgresContentMetadataRepository(sessions)
    classes = PostgresClassRepository(sessions)
    bodies = client.app.state.content_body_repository

    public_source = {
        "id": "all-types-public", "name": "All Types Public",
        "moderation": {
            "owner_id": teacher["user"]["id"], "status": "published",
            "visibility": "public",
        },
    }
    class_source = {
        "id": "all-types-class", "name": "All Types Class",
        "moderation": {
            "owner_id": teacher["user"]["id"], "status": "published",
            "visibility": "class_only", "invite": {"code": "QUIZ-BODY2"},
            "enrollments": {student["user"]["id"]: {}},
        },
    }
    assert metadata.import_quiz(public_source, "all-types-public.json")
    assert metadata.import_quiz(class_source, "all-types-class.json")
    assert classes.import_content_access(class_source, "quiz")
    questions = [
        {"id": "single", "question": "Single", "type": "single_choice",
         "choices": ["A", "B"], "answer": "B"},
        {"id": "multiple", "question": "Multiple", "type": "multiple_choice",
         "choices": ["A", "B", "C"], "answer": ["A", "C"]},
        {"id": "boolean", "question": "Boolean", "type": "true_false",
         "answer": True},
        {"id": "short", "question": "Short", "type": "short_answer",
         "answer": ["one", "two"]},
        {"id": "matching", "question": "Matching", "type": "matching",
         "pairs": [{"prompt": "P", "answer": "A"}]},
        {"id": "ordering", "question": "Ordering", "type": "ordering",
         "answer": ["first", "second"]},
    ]
    for quiz_id in (public_source["id"], class_source["id"]):
        assert bodies.import_quiz({"id": quiz_id, "questions": questions})

    def headers(registration):
        return {"Authorization": f"Bearer {registration['access_token']}"}

    owner_body = client.get(
        f"/api/v1/content/bodies/quiz/{public_source['id']}",
        headers=headers(teacher),
    ).json()
    admin_body = client.get(
        f"/api/v1/content/bodies/quiz/{class_source['id']}",
        headers=headers(admin),
    ).json()
    student_public = client.get(
        f"/api/v1/content/bodies/quiz/{public_source['id']}",
        headers=headers(student),
    ).json()
    student_class = client.get(
        f"/api/v1/content/bodies/quiz/{class_source['id']}",
        headers=headers(student),
    ).json()

    assert [row["id"] for row in owner_body["questions"]] == [
        row["id"] for row in questions
    ]
    assert owner_body["questions"][0]["choices"] == ["A", "B"]
    assert owner_body["questions"][3]["answer"] == ["one", "two"]
    assert owner_body["questions"][4]["pairs"] == [{"prompt": "P", "answer": "A"}]
    assert owner_body["questions"][5]["answer"] == ["first", "second"]
    assert admin_body["questions"] == owner_body["questions"]
    for redacted in (student_public, student_class):
        assert all("answer" not in row for row in redacted["questions"])
        assert redacted["questions"][0]["choices"] == ["A", "B"]
        assert redacted["questions"][4]["pairs"] == [
            {"prompt": "P", "answer": None},
        ]

    assert client.get(
        f"/api/v1/content/bodies/quiz/{class_source['id']}",
        headers=headers(outsider),
    ).status_code in {403, 404}
    assert classes.remove_member(
        "quiz", class_source["id"], teacher["user"]["id"], "teacher",
        student["user"]["id"],
    )[0]
    assert client.get(
        f"/api/v1/content/bodies/quiz/{class_source['id']}",
        headers=headers(student),
    ).status_code in {403, 404}

    public_source["moderation"]["status"] = "draft"
    assert metadata.import_quiz(public_source, "all-types-public.json")
    assert client.get(
        f"/api/v1/content/bodies/quiz/{public_source['id']}",
        headers=headers(student),
    ).status_code in {403, 404}
    assert bodies.import_quiz({
        "id": public_source["id"], "questions": [
            {"id": "changed", "question": "Changed", "type": "short_answer",
             "answer": "new"},
        ],
    })
    assert client.get(
        f"/api/v1/content/bodies/quiz/{public_source['id']}",
        headers=headers(teacher),
    ).json()["questions"][0]["id"] == "changed"


def test_flashcard_body_api_preserves_visibility_roles_and_immediate_consistency(identity_api):
    client, users, sessions = identity_api
    teacher = _register(client, "deck.body.teacher")
    student = _register(client, "deck.body.student")
    outsider = _register(client, "deck.body.outsider")
    admin = _register(client, "deck.body.admin")
    assert users.update_role(teacher["user"]["id"], "teacher")
    assert users.update_role(admin["user"]["id"], "admin")
    metadata = PostgresContentMetadataRepository(sessions)
    classes = PostgresClassRepository(sessions)
    bodies = client.app.state.content_body_repository

    public_source = {
        "id": "deck-body-public", "name": "Deck Body Public",
        "moderation": {
            "owner_id": teacher["user"]["id"], "status": "published",
            "visibility": "public",
        },
    }
    class_source = {
        "id": "deck-body-class", "name": "Deck Body Class",
        "moderation": {
            "owner_id": teacher["user"]["id"], "status": "published",
            "visibility": "class_only", "invite": {"code": "DECK-BODY2"},
            "enrollments": {student["user"]["id"]: {}},
        },
    }
    assert metadata.import_flashcard_deck(public_source, "deck-body-public.json")
    assert metadata.import_flashcard_deck(class_source, "deck-body-class.json")
    assert classes.import_content_access(class_source, "flashcard")
    cards = [{
        "id": "card-2", "front": "Second", "back": "Answer 2",
        "hint": "Hint 2", "description": "Description 2",
        "image": "second.png", "audio": {"front": "second-front.mp3"},
    }, {
        "id": "card-1", "front": "First", "back": "Answer 1",
        "hint": "Hint 1", "description": "Description 1",
        "audio": {"back": "first-back.mp3"},
    }]
    for deck_id in (public_source["id"], class_source["id"]):
        assert bodies.import_flashcard_deck({"id": deck_id, "cards": cards})

    def headers(registration):
        return {"Authorization": f"Bearer {registration['access_token']}"}

    def get(deck_id, registration):
        return client.get(
            f"/api/v1/content/bodies/flashcard/{deck_id}",
            headers=headers(registration),
        )

    owner_body = get(public_source["id"], teacher).json()
    admin_body = get(class_source["id"], admin).json()
    student_public = get(public_source["id"], student).json()
    student_class = get(class_source["id"], student).json()
    assert [row["id"] for row in owner_body["cards"]] == ["card-2", "card-1"]
    assert owner_body["cards"][0]["back"] == "Answer 2"
    assert owner_body["cards"][0]["hint"] == "Hint 2"
    assert owner_body["cards"][0]["description"] == "Description 2"
    assert owner_body["cards"][0]["image"]
    assert owner_body["cards"][0]["audio"]["front"]
    # Flashcard backs are study content, so the existing representation is the
    # same for authorized students, owners, and administrators.
    assert student_public["cards"] == owner_body["cards"]
    assert student_class["cards"] == admin_body["cards"]
    assert get(class_source["id"], outsider).status_code in {403, 404}

    assert classes.remove_member(
        "flashcard", class_source["id"], teacher["user"]["id"], "teacher",
        student["user"]["id"],
    )[0]
    assert get(class_source["id"], student).status_code in {403, 404}

    public_source["moderation"]["status"] = "draft"
    assert metadata.import_flashcard_deck(public_source, "deck-body-public.json")
    assert get(public_source["id"], student).status_code in {403, 404}
    assert get(public_source["id"], teacher).status_code == 200

    public_source["moderation"]["status"] = "published"
    public_source["name"] = "Renamed Deck"
    assert metadata.import_flashcard_deck(public_source, "deck-body-public.json")
    assert bodies.import_flashcard_deck({
        "id": public_source["id"], "cards": [{
            "id": "changed", "front": "Changed front", "back": "Changed back",
        }],
    })
    changed = get(public_source["id"], student)
    assert changed.status_code == 200
    assert changed.json()["name"] == "Renamed Deck"
    assert changed.json()["cards"] == [{
        "id": "changed", "front": "Changed front", "back": "Changed back",
        "hint": "", "description": "", "image": "", "audio": {},
    }]

    assert metadata.delete_for_actor(
        "flashcard", public_source["id"], teacher["user"]["id"], "teacher",
    )
    assert get(public_source["id"], teacher).status_code in {403, 404}


def test_content_delete_distinguishes_owner_forbidden_and_missing(identity_api):
    client, users, sessions = identity_api
    owner = _register(client, "delete.owner")
    other = _register(client, "delete.other")
    assert users.update_role(owner["user"]["id"], "teacher")
    assert users.update_role(other["user"]["id"], "teacher")
    metadata = PostgresContentMetadataRepository(sessions)
    assert metadata.import_quiz({
        "id": "delete-quiz", "name": "Delete Quiz",
        "moderation": {"owner_id": owner["user"]["id"], "status": "draft",
                       "visibility": "private"},
    }, "delete-quiz.json")
    owner_headers = {"Authorization": f"Bearer {owner['access_token']}"}
    other_headers = {"Authorization": f"Bearer {other['access_token']}"}

    assert client.delete(
        "/api/v1/content/metadata/quiz/delete-quiz", headers=other_headers,
    ).status_code == 403
    assert client.delete(
        "/api/v1/content/metadata/quiz/missing", headers=owner_headers,
    ).status_code == 404
    assert client.delete(
        "/api/v1/content/metadata/quiz/delete-quiz", headers=owner_headers,
    ).status_code == 200


def test_desktop_domain_repositories_complete_remote_content_workflow(identity_api, monkeypatch):
    """The PyQt-facing contracts operate entirely through HTTP/PostgreSQL."""
    client, users, _sessions = identity_api
    teacher_http = _adapter_for(client)
    _ok, _message, teacher = teacher_http.register(
        "Remote Teacher", "remote.teacher", "password1"
    )
    assert users.update_role(teacher["id"], "teacher")
    assert teacher_http.authenticate("remote.teacher", "password1")["role"] == "teacher"

    quizzes = HttpQuizRepository(teacher_http)
    assert quizzes.create_quiz("Remote Quiz")
    quiz = next(row for row in quizzes.get_all_quizzes() if row["name"] == "Remote Quiz")
    question = {
        "id": "remote-question", "type": "short_answer",
        "question": "2 + 2?", "answer": "4",
    }
    assert quizzes.save_quiz_content(
        quiz["file"], [question], {"attempt_limit": 2, "passing_grade_percent": 75}
    )
    item = next(row for row in quizzes.get_content_items() if row["file"] == quiz["file"])
    assert quizzes.update_moderation(
        item, "pending_review", "class_only", "Ready for class review"
    )

    _ok, _message, admin = users.register(
        "Remote Admin", "remote.admin", "password1"
    )
    assert users.update_role(admin["id"], "admin")
    admin_http = _adapter_for(client)
    assert admin_http.authenticate("remote.admin", "password1")
    admin_metadata = HttpContentMetadataRepository(admin_http)
    metadata = admin_metadata.get_by_id("quiz", quiz["file"])
    metadata.update({"status": "published", "review_note": "Approved"})
    for key in ("kind", "owner_id", "source_owner_id", "owner_resolved", "created_at", "updated_at", "content_version"):
        metadata.pop(key, None)
    assert admin_metadata.save("quiz", metadata)["status"] == "published"

    classes = HttpClassRepository(teacher_http)
    rotated, code = classes.generate_or_rotate_code(quiz["file"], "quiz", teacher["id"])
    assert rotated and code
    assert classes.get_invitation(quiz["file"], "quiz")["code"] == code

    student_http = _adapter_for(client)
    _ok, _message, student = student_http.register(
        "Remote Student", "remote.student", "password1"
    )
    assert HttpClassRepository(student_http).enroll_with_code(code, student["id"])[0]
    student_quizzes = HttpQuizRepository(student_http)
    assert "answer" not in student_quizzes.load_quiz_questions(quiz["file"])[0]
    monkeypatch.setenv("STUDY_BUDDY_STORAGE", "api")
    assert "Remote Quiz" in QuizController(
        student["id"], role="student", user_repository=student_http
    ).get_available_quizzes()
    assert student_quizzes.save_quiz_progress(
        quiz["file"], {"remote-question": {"correct": 1, "wrong": 0, "mastered": True}}
    )
    attempt = student_quizzes.save_test_attempt(quiz["file"], {
        "id": "remote-attempt", "status": "submitted", "score": 1, "total": 1,
        "percentage": 100.0, "passed": True, "quiz_name": "desktop-only",
        "user_id": student["id"], "answers": [{
            "question_id": "remote-question", "is_correct": True,
        }],
    })
    assert attempt and student_quizzes.get_latest_test_attempt(
        quiz["file"], student["id"]
    )["id"] == "remote-attempt"

    owned = classes.get_owned_classes(teacher["id"], "quiz")
    roster = owned[0]["roster"]
    assert roster[0]["user_id"] == student["id"]
    assert roster[0]["best_grade"] == 100.0
    history = HttpContentHistoryRepository(teacher_http).get_history("quiz", quiz["file"])
    assert history["edits"][-1]["changed_by"] == teacher["id"]
    assert history["moderation"][-1]["note"] == "Approved"

    decks = HttpFlashcardRepository(teacher_http)
    assert decks.create_deck("Remote Deck", [{
        "id": "remote-card", "front": "Front", "back": "Back",
    }])
    deck = next(row for row in decks.get_all_decks() if row["name"] == "Remote Deck")
    assert decks.load_deck_cards(deck["file"])[0]["back"] == "Back"
    assert "Remote Quiz" in QuizEditorController(
        teacher["id"], "teacher", user_repository=teacher_http
    ).get_quiz_names()
    assert "Remote Deck" in FlashcardEditorController(
        teacher["id"], "teacher", user_repository=teacher_http
    ).get_deck_names()
    assert decks.delete_deck_permanently("Remote Deck")
