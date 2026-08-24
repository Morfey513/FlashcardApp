import os
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
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
    assert content_http.get_all("quiz", "owned")[0]["id"] == "quiz-api-1"
    assert content_http.get_by_id("quiz", "quiz-api-1")["name"] == "Server Quiz"

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
    history = HttpContentHistoryRepository(teacher_http).get_history(
        "quiz", "body-quiz"
    )
    assert history["edits"][0]["changed_by"] == teacher["id"]

    student_http = _adapter_for(client)
    student_http.register("Body Student", "body.student", "password1")
    student_bodies = HttpContentBodyRepository(student_http)
    assert student_bodies.get_quiz("body-quiz")["questions"][0]["question"] == "2 + 2?"
    assert student_bodies.save_quiz({
        "id": "body-quiz", "name": "Changed", "questions": []
    }) is None


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
    for key in ("kind", "owner_id", "source_owner_id", "owner_resolved", "created_at", "updated_at"):
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
