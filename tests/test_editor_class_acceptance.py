"""Real HTTP acceptance chain for the online editor and class access."""

import os
import secrets

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from src.api.main import create_app
from src.storage.postgres_user_repository import PostgresUserRepository
from tools import bootstrap_server


@pytest.fixture(scope="module")
def disposable_editor_api():
    template = os.getenv("STUDY_BUDDY_TEST_DATABASE_URL")
    if not template:
        pytest.skip("disposable PostgreSQL credentials are not configured")
    bootstrap_server.validate_database_url(template)
    source = make_url(template)
    name = "study_buddy_bootstrap_" + secrets.token_hex(6)
    target = source.set(
        username=name, password=secrets.token_urlsafe(24), database=name,
    ).render_as_string(hide_password=False)
    admin = source.set(database="postgres").render_as_string(hide_password=False)
    admin_engine = create_engine(admin, isolation_level="AUTOCOMMIT", pool_pre_ping=True)
    target_engine = None
    name_available = False
    try:
        with admin_engine.connect() as connection:
            privileges = connection.execute(text(
                "SELECT rolcreatedb, rolcreaterole, rolsuper FROM pg_roles "
                "WHERE rolname = current_user"
            )).one()
            if not (privileges.rolsuper or (privileges.rolcreatedb and privileges.rolcreaterole)):
                pytest.skip("configured disposable user cannot create scratch roles/databases")
            assert connection.execute(text(
                "SELECT 1 FROM pg_database WHERE datname = :name"
            ), {"name": name}).scalar_one_or_none() is None
            assert connection.execute(text(
                "SELECT 1 FROM pg_roles WHERE rolname = :name"
            ), {"name": name}).scalar_one_or_none() is None
            name_available = True
        # The bootstrap helper intentionally permits only its configured disposable name.
        original_name = bootstrap_server.TEST_DATABASE_NAME
        bootstrap_server.TEST_DATABASE_NAME = name
        try:
            bootstrap_server.provision_disposable_database(admin, target)
        finally:
            bootstrap_server.TEST_DATABASE_NAME = original_name
        bootstrap_server.upgrade_schema(target)
        target_engine = create_engine(target, pool_pre_ping=True)
        users = PostgresUserRepository(sessionmaker(bind=target_engine, expire_on_commit=False))
        with TestClient(create_app(user_repository=users)) as client:
            yield client, users
    finally:
        if target_engine is not None:
            target_engine.dispose()
        try:
            if name_available:
                with admin_engine.connect() as connection:
                    owner = connection.execute(text(
                        "SELECT r.rolname FROM pg_database d JOIN pg_roles r ON r.oid = d.datdba "
                        "WHERE d.datname = :name"
                    ), {"name": name}).scalar_one_or_none()
                    if owner == name:
                        connection.execute(text(
                            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                            "WHERE datname = :name AND pid <> pg_backend_pid()"
                        ), {"name": name})
                        connection.exec_driver_sql(f'DROP DATABASE "{name}"')
                        connection.exec_driver_sql(f'DROP ROLE "{name}"')
                    elif owner is not None:
                        raise RuntimeError("refusing to clean a scratch database owned by another role")
                    elif connection.execute(text(
                        "SELECT 1 FROM pg_roles WHERE rolname = :name"
                    ), {"name": name}).scalar_one_or_none() is not None:
                        # Provisioning may have created the role before CREATE DATABASE failed.
                        connection.exec_driver_sql(f'DROP ROLE "{name}"')
        finally:
            admin_engine.dispose()


def _register(client, login):
    response = client.post("/api/v1/auth/register", json={
        "name": login, "login": login, "password": "acceptance-password-1",
    })
    assert response.status_code == 201, response.text
    return response.json()


def _headers(account):
    return {"Authorization": f"Bearer {account['access_token']}"}


@pytest.mark.parametrize("kind,items_key,first,edited", [
    ("quiz", "questions",
     {"id": "question-1", "question": "Original question", "type": "true_false", "answer": True},
     {"id": "question-1", "question": "Edited question", "type": "true_false", "answer": False}),
    ("flashcard", "cards",
     {"id": "card-1", "front": "Original front", "back": "Original back"},
     {"id": "card-1", "front": "Edited front", "back": "Edited back"}),
])
def test_online_editor_class_workflow(disposable_editor_api, kind, items_key, first, edited):
    client, users = disposable_editor_api
    suffix = secrets.token_hex(4)
    admin = _register(client, f"editor.admin.{suffix}")
    teacher = _register(client, f"editor.teacher.{suffix}")
    other_teacher = _register(client, f"editor.other.{suffix}")
    student = _register(client, f"editor.student.{suffix}")
    outsider = _register(client, f"editor.outsider.{suffix}")
    # A new database has no admin. Bootstrap that role once; subsequent role
    # changes use the real admin HTTP endpoint.
    admin_user = users.authenticate(f"editor.admin.{suffix}", "acceptance-password-1")
    assert users.update_role(admin_user["id"], "admin")
    for account, login in ((teacher, f"editor.teacher.{suffix}"),
                           (other_teacher, f"editor.other.{suffix}")):
        user = users.authenticate(login, "acceptance-password-1")
        changed = client.patch(
            f"/api/v1/admin/users/{user['id']}/role", json={"role": "teacher"},
            headers=_headers(admin),
        )
        assert changed.status_code == 200, changed.text

    content_id = f"acceptance-{kind}-{suffix}"
    metadata_url = f"/api/v1/content/metadata/{kind}/{content_id}"
    body_url = f"/api/v1/content/bodies/{kind}/{content_id}"
    metadata = {
        "id": content_id, "name": "Original title", "status": "draft",
        "visibility": "private", "source_path": f"{content_id}.json",
    }
    body = {"id": content_id, "name": metadata["name"], items_key: [first]}
    assert client.put(metadata_url, json=metadata, headers=_headers(student)).status_code == 403
    created = client.put(metadata_url, json=metadata, headers=_headers(teacher))
    assert created.status_code == 200, created.text
    assert created.json()["status"] == "draft"
    assert client.put(metadata_url, json=metadata, headers=_headers(other_teacher)).status_code == 403
    assert client.put(body_url, json=body, headers=_headers(student)).status_code == 403
    assert client.put(body_url, json=body, headers=_headers(other_teacher)).status_code == 403
    saved = client.put(body_url, json=body, headers=_headers(teacher))
    assert saved.status_code == 200, saved.text
    first_version = client.get(metadata_url, headers=_headers(teacher)).json()["content_version"]

    metadata["name"] = "Edited title"
    changed = client.put(metadata_url, json=metadata, headers=_headers(teacher))
    assert changed.status_code == 200, changed.text
    assert changed.json()["name"] == "Edited title"
    body["name"] = "Edited title"
    body[items_key] = [edited]
    changed_body = client.put(body_url, json=body, headers=_headers(teacher))
    assert changed_body.status_code == 200, changed_body.text
    assert changed_body.json()[items_key][0]["id"] == edited["id"]
    persisted = client.get(body_url, headers=_headers(teacher))
    assert persisted.status_code == 200
    assert persisted.json()[items_key][0]["question" if kind == "quiz" else "front"] == (
        edited["question"] if kind == "quiz" else edited["front"]
    )
    edited_version = client.get(metadata_url, headers=_headers(teacher)).json()["content_version"]
    assert edited_version > first_version

    metadata.update(status="pending_review", visibility="class_only")
    assert client.put(metadata_url, json=metadata, headers=_headers(other_teacher)).status_code == 403
    assert client.put(metadata_url, json=metadata, headers=_headers(student)).status_code == 403
    submitted = client.put(metadata_url, json=metadata, headers=_headers(teacher))
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["status"] == "pending_review"
    metadata["status"] = "published"
    assert client.put(metadata_url, json=metadata, headers=_headers(teacher)).status_code == 403
    assert client.put(metadata_url, json=metadata, headers=_headers(other_teacher)).status_code == 403
    approved = client.put(metadata_url, json=metadata, headers=_headers(admin))
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "published"
    assert approved.json()["visibility"] == "class_only"

    invitation_url = f"/api/v1/classes/{kind}/{content_id}/invitation"
    rotated = client.post(invitation_url + "/rotate", headers=_headers(teacher))
    assert rotated.status_code == 200, rotated.text
    code = rotated.json()["code"]
    assert client.get(invitation_url, headers=_headers(teacher)).json()["code"] == code
    classes = client.get("/api/v1/classes/owned", headers=_headers(teacher))
    assert classes.status_code == 200
    assert any(item["content_id"] == content_id for item in classes.json())
    for account in (student, outsider):
        assert client.get(metadata_url, headers=_headers(account)).status_code == 404
        assert client.get(body_url, headers=_headers(account)).status_code == 404
    joined = client.post("/api/v1/classes/join", json={"code": code}, headers=_headers(student))
    assert joined.status_code == 200, joined.text
    assert client.get(metadata_url, headers=_headers(student)).status_code == 200
    assert client.get(body_url, headers=_headers(student)).status_code == 200
    assert client.get(metadata_url, headers=_headers(outsider)).status_code == 404
    assert client.get(body_url, headers=_headers(outsider)).status_code == 404

    student_user = users.authenticate(f"editor.student.{suffix}", "acceptance-password-1")
    removed = client.delete(
        f"/api/v1/classes/{kind}/{content_id}/members/{student_user['id']}",
        headers=_headers(teacher),
    )
    assert removed.status_code == 200, removed.text
    assert client.get(metadata_url, headers=_headers(student)).status_code == 404
    assert client.get(body_url, headers=_headers(student)).status_code == 404
    new_code = client.post(invitation_url + "/rotate", headers=_headers(teacher))
    assert new_code.status_code == 200 and new_code.json()["code"] != code
    assert client.post(
        "/api/v1/classes/join", json={"code": code}, headers=_headers(outsider),
    ).status_code == 400
