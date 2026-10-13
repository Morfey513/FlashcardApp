"""Security-page API contracts, including session metadata isolation."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from sqlalchemy import event, select

from src.storage.postgres_models import UserSessionModel
from src.storage.http_user_repository import HttpUserRepository
from src.api.main import create_app
from src.storage.postgres_session_repository import PostgresSessionRepository
from src.storage.postgres_user_repository import PostgresUserRepository
from src.storage.postgres_models import Base


@pytest.fixture
def identity_api(tmp_path, monkeypatch):
    monkeypatch.setenv("STUDY_BUDDY_MEDIA_ROOT", str(tmp_path / "managed-media"))
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'security_sessions.db'}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    users = PostgresUserRepository(session_factory)
    tokens = PostgresSessionRepository(session_factory, lifetime=timedelta(hours=2))
    app = create_app(users, tokens)
    with TestClient(app) as client:
        yield client, users, session_factory
    engine.dispose()


def _headers(registration):
    return {"Authorization": f"Bearer {registration['access_token']}"}


def _register(client, login):
    response = client.post("/api/v1/auth/register", json={
        "name": login, "login": login, "password": "password1",
    })
    assert response.status_code == 201
    return response.json()


def test_login_without_optional_metadata_remains_compatible(identity_api):
    client, _users, sessions = identity_api
    account = _register(client, "legacy.session")
    response = client.post("/api/v1/auth/login", json={
        "login": "legacy.session", "password": "password1",
    })
    assert response.status_code == 200
    with sessions() as session:
        stored = session.scalar(select(UserSessionModel).where(
            UserSessionModel.session_token_hash.is_not(None)
        ).order_by(UserSessionModel.created_at.desc()))
        assert stored.client_label is None
        assert stored.device_fingerprint is None
        assert stored.ip_address in {"testclient", "127.0.0.1", None}
    assert account["user"]["id"]


def test_invalid_login_fingerprint_is_not_reflected_in_validation_response(identity_api):
    client, _users, _sessions = identity_api
    rejected = "raw-device-value-must-never-appear"
    response = client.post("/api/v1/auth/login", json={
        "login": "any", "password": "password1", "device_fingerprint": rejected,
    })
    assert response.status_code == 422
    assert rejected not in response.text
    assert "input" not in response.json()["detail"][0]

    account = _register(client, "valid.after.validation")
    assert client.get("/api/v1/users/me", headers=_headers(account)).status_code == 200


def test_own_sessions_hide_fingerprint_and_enforce_owner(identity_api):
    client, users, _sessions = identity_api
    first = _register(client, "owner.sessions")
    second_login = client.post("/api/v1/auth/login", json={
        "login": "owner.sessions", "password": "password1",
        "client_label": "Windows 11", "device_fingerprint": "a" * 64,
    }).json()
    other = _register(client, "other.sessions")

    listed = client.get("/api/v1/auth/sessions", headers=_headers(first))
    assert listed.status_code == 200
    body = listed.json()
    assert len(body["sessions"]) == 2
    assert body["last_successful_login_at"] is not None
    assert all("device_fingerprint" not in row for row in body["sessions"])
    target_id = next(row["id"] for row in body["sessions"] if not row["is_current"])

    # An administrator would use the narrow admin endpoint, never this one.
    assert client.delete(
        f"/api/v1/auth/sessions/{target_id}", headers=_headers(other)
    ).status_code == 404
    admin = _register(client, "owner.endpoint.admin")
    assert users.update_role(admin["user"]["id"], "admin")
    admin_token = client.post("/api/v1/auth/login", json={
        "login": "owner.endpoint.admin", "password": "password1",
    }).json()
    assert client.delete(
        f"/api/v1/auth/sessions/{target_id}", headers=_headers(admin_token)
    ).status_code == 404
    assert client.delete(
        f"/api/v1/auth/sessions/{target_id}", headers=_headers(first)
    ).status_code == 204
    assert client.get("/api/v1/users/me", headers=_headers(second_login)).status_code == 401


def test_last_successful_login_includes_revoked_other_session(identity_api):
    client, _users, _sessions = identity_api
    first = _register(client, "historic.session")
    other = client.post("/api/v1/auth/login", json={
        "login": "historic.session", "password": "password1",
    }).json()
    assert client.post("/api/v1/auth/logout", headers=_headers(other)).status_code == 204
    listed = client.get("/api/v1/auth/sessions", headers=_headers(first)).json()
    assert len(listed["sessions"]) == 1
    assert listed["last_successful_login_at"] is not None


def test_sign_out_others_preserves_current_session(identity_api):
    client, _users, _sessions = identity_api
    first = _register(client, "signout.others")
    other_token = client.post("/api/v1/auth/login", json={
        "login": "signout.others", "password": "password1",
    }).json()
    response = client.post("/api/v1/auth/sessions/sign-out-others", headers=_headers(first))
    assert response.status_code == 200
    assert client.get("/api/v1/users/me", headers=_headers(first)).status_code == 200
    assert client.get("/api/v1/users/me", headers=_headers(other_token)).status_code == 401


def test_admin_session_endpoint_is_gated_and_fingerprint_is_admin_only(identity_api):
    client, users, _sessions = identity_api
    target = _register(client, "target.sessions")
    login = client.post("/api/v1/auth/login", json={
        "login": "target.sessions", "password": "password1",
        "client_label": "Windows 11", "device_fingerprint": "b" * 64,
    })
    assert login.status_code == 200
    regular = _register(client, "regular.sessions")
    denied = client.get(
        f"/api/v1/admin/users/{target['user']['id']}/sessions", headers=_headers(regular)
    )
    assert denied.status_code == 403
    admin = _register(client, "admin.sessions")
    assert users.update_role(admin["user"]["id"], "admin")
    admin_login = client.post("/api/v1/auth/login", json={
        "login": "admin.sessions", "password": "password1",
    }).json()
    response = client.get(
        f"/api/v1/admin/users/{target['user']['id']}/sessions", headers=_headers(admin_login)
    )
    assert response.status_code == 200
    assert any(row["device_fingerprint"] == "b" * 64 for row in response.json())


def test_activity_updates_are_throttled(identity_api):
    client, _users, sessions = identity_api
    account = _register(client, "throttled.session")
    token = account["access_token"]
    with sessions.begin() as session:
        stored = session.scalar(select(UserSessionModel).where(
            UserSessionModel.session_token_hash.is_not(None)
        ))
        stored.last_activity_at = datetime.now(timezone.utc) - timedelta(minutes=10)

    updates = []
    engine = sessions.kw["bind"]

    def record_updates(_conn, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().upper().startswith("UPDATE USER_SESSIONS"):
            updates.append(statement)

    event.listen(engine, "before_cursor_execute", record_updates)
    try:
        headers = {"Authorization": f"Bearer {token}"}
        assert client.get("/api/v1/users/me", headers=headers).status_code == 200
        assert client.get("/api/v1/users/me", headers=headers).status_code == 200
    finally:
        event.remove(engine, "before_cursor_execute", record_updates)
    assert len(updates) == 1


def test_http_adapter_only_sends_hashed_device_metadata():
    calls = []

    def requester(method, path, payload, headers):
        calls.append((method, path, payload, headers))
        return 401, {"detail": "Invalid login or password"}

    repository = HttpUserRepository(requester=requester)
    assert repository.authenticate("student", "password1") is None
    payload = calls[0][2]
    assert len(payload["device_fingerprint"]) == 64
    assert payload["device_fingerprint"].isalnum()
    assert "node" not in payload and "mac" not in payload
