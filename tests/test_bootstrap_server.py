"""Focused coverage for the disposable server bootstrap tool."""

import os
import secrets

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url

from tools import bootstrap_server


class _Result:
    def __init__(self, *, row=None, scalar=None):
        self._row = row
        self._scalar = scalar

    def first(self):
        return self._row

    def scalar_one(self):
        return self._scalar

    def scalar_one_or_none(self):
        return self._scalar


class _ProvisionConnection:
    def __init__(self, role_row, owner):
        self.role_row = role_row
        self.owner = owner
        self.statements = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def exec_driver_sql(self, statement, parameters=None):
        self.statements.append((statement, parameters))
        if "FROM pg_roles" in statement:
            return _Result(row=self.role_row)
        if "SELECT format" in statement:
            return _Result(scalar='CREATE ROLE "study_buddy_test" LOGIN PASSWORD \'redacted\'')
        if "FROM pg_database" in statement:
            return _Result(scalar=self.owner)
        return _Result()


class _ProvisionEngine:
    def __init__(self, connection):
        self.connection = connection
        self.disposed = False

    def connect(self):
        return self.connection

    def dispose(self):
        self.disposed = True


def _provision_urls():
    return (
        "postgresql://admin:admin-secret@127.0.0.1:5432/postgres",
        "postgresql://study_buddy_test:app-secret@127.0.0.1:5432/study_buddy_test",
    )


def test_bootstrap_runs_in_order_and_is_idempotent(monkeypatch):
    calls = []
    monkeypatch.setattr(bootstrap_server, "validate_database_url", lambda value: "safe-url")
    monkeypatch.setattr(bootstrap_server, "validate_admin_database_url", lambda value: "safe-admin-url")
    monkeypatch.setattr(bootstrap_server, "validate_same_postgresql_server", lambda admin, target: None)
    monkeypatch.setattr(bootstrap_server, "verify_database_reachable", lambda value: calls.append(("reachable", value)))
    monkeypatch.setattr(bootstrap_server, "provision_disposable_database", lambda admin, target: calls.append(("provision", admin, target)))
    monkeypatch.setattr(bootstrap_server, "upgrade_schema", lambda value: calls.append(("migrate", value)))
    monkeypatch.setattr(bootstrap_server, "seed_bundled_demo_content", lambda value: calls.append(("seed", value)))
    monkeypatch.setattr(bootstrap_server, "start_and_verify_api", lambda *args: calls.append(("api", args[0])))

    bootstrap_server.bootstrap("postgresql://user:secret@localhost/study_buddy_test", "postgresql://admin:secret@localhost/postgres")
    bootstrap_server.bootstrap("postgresql://user:secret@localhost/study_buddy_test", "postgresql://admin:secret@localhost/postgres")

    assert calls == [
        ("reachable", "safe-admin-url"), ("provision", "safe-admin-url", "safe-url"),
        ("reachable", "safe-url"), ("migrate", "safe-url"), ("seed", "safe-url"), ("api", "safe-url"),
    ] * 2


def test_unreachable_database_is_actionable_and_never_exposes_secret():
    with pytest.raises(RuntimeError, match="PostgreSQL is unreachable") as error:
        bootstrap_server.verify_database_reachable("postgresql+psycopg://user:secret@127.0.0.1:1/study_buddy_test")
    assert "secret" not in bootstrap_server.public_error(error.value)


def test_main_reports_unreachable_database_without_a_traceback_or_secret(monkeypatch, capsys):
    monkeypatch.setenv("STUDY_BUDDY_TEST_DATABASE_URL", "postgresql://user:secret@127.0.0.1:1/study_buddy_test")
    monkeypatch.setenv("STUDY_BUDDY_BOOTSTRAP_ADMIN_URL", "postgresql://admin:secret@127.0.0.1:1/postgres")
    monkeypatch.setattr(bootstrap_server, "verify_database_reachable", lambda _url: (_ for _ in ()).throw(
        RuntimeError("PostgreSQL is unreachable; password=secret")
    ))

    assert bootstrap_server.main([]) == 1
    output = capsys.readouterr().err
    assert "PostgreSQL is unreachable" in output
    assert "secret" not in output
    assert "Traceback" not in output


@pytest.mark.parametrize("url", ["sqlite:///study_buddy_test.db", "postgresql://u:p@localhost/study_buddy"])
def test_bootstrap_refuses_non_disposable_database(url):
    with pytest.raises(ValueError, match="study_buddy_test|PostgreSQL"):
        bootstrap_server.validate_database_url(url)


def test_public_error_redacts_url_password():
    assert "secret" not in bootstrap_server.public_error(RuntimeError("postgresql://user:secret@localhost/study_buddy_test refused"))


def test_api_start_refuses_an_unowned_healthy_service(monkeypatch):
    monkeypatch.setattr(bootstrap_server, "endpoint_status", lambda *_args: 200)
    monkeypatch.setattr(bootstrap_server, "_owned_api_is_running", lambda _url, _base: False)

    with pytest.raises(RuntimeError, match="not started by this bootstrap"):
        bootstrap_server.start_and_verify_api("safe-url", bootstrap_server.DEFAULT_BASE_URL, 1)


def test_api_start_refuses_a_different_origin():
    with pytest.raises(ValueError, match="bootstrap API origin"):
        bootstrap_server.start_and_verify_api("safe-url", "http://localhost:9000", 1)


def test_bootstrap_refuses_administrator_on_a_different_postgresql_server():
    with pytest.raises(ValueError, match="same PostgreSQL host and port"):
        bootstrap_server.validate_same_postgresql_server(
            "postgresql://admin:secret@127.0.0.1:5432/postgres",
            "postgresql://app:secret@127.0.0.2:5432/study_buddy_test",
        )


def test_provision_creates_missing_role_and_database(monkeypatch):
    connection = _ProvisionConnection(role_row=None, owner=None)
    engine = _ProvisionEngine(connection)
    monkeypatch.setattr(bootstrap_server, "create_engine", lambda *_args, **_kwargs: engine)
    monkeypatch.setattr(bootstrap_server, "_password_verifier", lambda *_args: "SCRAM-SHA-256$verifier")

    bootstrap_server.provision_disposable_database(*_provision_urls())

    statements = [statement for statement, _parameters in connection.statements]
    assert any(statement.startswith("CREATE ROLE") for statement in statements)
    assert any(statement.startswith("CREATE DATABASE study_buddy_test OWNER") for statement in statements)
    assert "app-secret" not in repr(connection.statements)
    assert "SCRAM-SHA-256$verifier" in repr(connection.statements)
    assert engine.disposed


def test_provision_matching_role_and_owner_is_a_noop(monkeypatch):
    connection = _ProvisionConnection(role_row=type("Role", (), {"rolcanlogin": True})(), owner="study_buddy_test")
    monkeypatch.setattr(bootstrap_server, "create_engine", lambda *_args, **_kwargs: _ProvisionEngine(connection))

    bootstrap_server.provision_disposable_database(*_provision_urls())

    assert not any(statement.startswith("CREATE ") for statement, _parameters in connection.statements)


def test_provision_refuses_different_existing_database_owner_without_ddl(monkeypatch):
    connection = _ProvisionConnection(role_row=type("Role", (), {"rolcanlogin": True})(), owner="other_role")
    monkeypatch.setattr(bootstrap_server, "create_engine", lambda *_args, **_kwargs: _ProvisionEngine(connection))

    with pytest.raises(RuntimeError, match="owned by a different role"):
        bootstrap_server.provision_disposable_database(*_provision_urls())

    assert not any(statement.startswith("CREATE ") for statement, _parameters in connection.statements)


@pytest.mark.skipif(
    not os.getenv("STUDY_BUDDY_TEST_DATABASE_URL"),
    reason="disposable PostgreSQL credentials are not configured",
)
def test_live_fresh_disposable_role_and_database_provision(monkeypatch):
    """Exercise real creation and rerun, then remove only this unique scratch DB."""
    source = make_url(bootstrap_server.validate_database_url(
        os.environ["STUDY_BUDDY_TEST_DATABASE_URL"]
    ))
    admin_url = source.set(database="postgres").render_as_string(hide_password=False)
    name = "study_buddy_bootstrap_" + secrets.token_hex(5)
    target_url = source.set(
        username=name, password=secrets.token_urlsafe(24), database=name
    ).render_as_string(hide_password=False)
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        with admin_engine.connect() as connection:
            privileges = connection.execute(text(
                "SELECT rolcreatedb, rolcreaterole, rolsuper "
                "FROM pg_roles WHERE rolname = current_user"
            )).one()
            if not (privileges.rolsuper or (privileges.rolcreatedb and privileges.rolcreaterole)):
                pytest.skip("configured disposable user cannot create scratch roles/databases")
            assert connection.execute(text(
                "SELECT count(*) FROM pg_database WHERE datname = :name"
            ), {"name": name}).scalar_one() == 0
            assert connection.execute(text(
                "SELECT count(*) FROM pg_roles WHERE rolname = :name"
            ), {"name": name}).scalar_one() == 0
        monkeypatch.setattr(bootstrap_server, "TEST_DATABASE_NAME", name)
        bootstrap_server.provision_disposable_database(admin_url, target_url)
        target_engine = create_engine(target_url)
        try:
            with target_engine.connect() as connection:
                assert connection.exec_driver_sql("SELECT 1").scalar_one() == 1
        finally:
            target_engine.dispose()
        bootstrap_server.provision_disposable_database(admin_url, target_url)
    finally:
        with admin_engine.connect() as connection:
            owner = connection.execute(text(
                "SELECT r.rolname FROM pg_database d JOIN pg_roles r ON r.oid = d.datdba "
                "WHERE d.datname = :name"
            ), {"name": name}).scalar_one_or_none()
            if owner == name:
                connection.exec_driver_sql(f'DROP DATABASE "{name}"')
            if connection.execute(text(
                "SELECT count(*) FROM pg_roles WHERE rolname = :name"
            ), {"name": name}).scalar_one():
                connection.exec_driver_sql(f'DROP ROLE "{name}"')
        admin_engine.dispose()


@pytest.mark.skipif(
    not os.getenv("STUDY_BUDDY_TEST_DATABASE_URL"),
    reason="bootstrap target URL is not configured",
)
def test_live_bootstrap_rerun_keeps_one_copy_of_each_bundled_demo(monkeypatch):
    """Exercise the actual disposable service path twice without deleting data."""
    from src.storage.postgres_models import (
        FlashcardDeckMetadataModel, FlashcardMediaModel, FlashcardModel, MediaModel,
        QuizMetadataModel, QuizQuestionModel,
    )

    url = bootstrap_server.validate_database_url(os.environ["STUDY_BUDDY_TEST_DATABASE_URL"])
    admin_url = make_url(url).set(
        username="bootstrap", password="placeholder", database="postgres"
    ).render_as_string(hide_password=False)
    original_reachability = bootstrap_server.verify_database_reachable
    monkeypatch.setattr(bootstrap_server, "provision_disposable_database", lambda _admin, _target: None)
    monkeypatch.setattr(
        bootstrap_server,
        "verify_database_reachable",
        lambda value: None if value == admin_url else original_reachability(value),
    )
    bootstrap_server.bootstrap(url, admin_url, port=8001, timeout_seconds=20)
    engine = create_engine(url)
    try:
        with engine.connect() as connection:
            before = {
                "versions": (
                    connection.scalar(select(QuizMetadataModel.content_version).where(
                        QuizMetadataModel.id == "da5430fa-b771-4262-9383-90e4e3abc3f0"
                    )),
                    connection.scalar(select(FlashcardDeckMetadataModel.content_version).where(
                        FlashcardDeckMetadataModel.id == "8f348fc7-0545-413c-96c6-52b0800b4ef0"
                    )),
                ),
                "media": tuple(connection.execute(select(
                    FlashcardMediaModel.deck_id, FlashcardMediaModel.card_id,
                    FlashcardMediaModel.role, MediaModel.id, MediaModel.storage_key,
                    MediaModel.checksum_sha256,
                ).join(MediaModel, MediaModel.id == FlashcardMediaModel.media_id).where(
                    FlashcardMediaModel.deck_id == "8f348fc7-0545-413c-96c6-52b0800b4ef0"
                ).order_by(FlashcardMediaModel.card_id, FlashcardMediaModel.role)).all()),
            }
    finally:
        engine.dispose()
    bootstrap_server.bootstrap(url, admin_url, port=8001, timeout_seconds=20)

    engine = create_engine(url)
    try:
        with engine.connect() as connection:
            assert connection.scalar(select(func.count()).select_from(QuizMetadataModel).where(
                QuizMetadataModel.id == "da5430fa-b771-4262-9383-90e4e3abc3f0"
            )) == 1
            assert connection.scalar(select(func.count()).select_from(FlashcardDeckMetadataModel).where(
                FlashcardDeckMetadataModel.id == "8f348fc7-0545-413c-96c6-52b0800b4ef0"
            )) == 1
            assert connection.scalar(select(func.count()).select_from(QuizQuestionModel).where(
                QuizQuestionModel.quiz_id == "da5430fa-b771-4262-9383-90e4e3abc3f0"
            )) == 6
            assert connection.scalar(select(func.count()).select_from(FlashcardModel).where(
                FlashcardModel.deck_id == "8f348fc7-0545-413c-96c6-52b0800b4ef0"
            )) == 2
            after = {
                "versions": (
                    connection.scalar(select(QuizMetadataModel.content_version).where(
                        QuizMetadataModel.id == "da5430fa-b771-4262-9383-90e4e3abc3f0"
                    )),
                    connection.scalar(select(FlashcardDeckMetadataModel.content_version).where(
                        FlashcardDeckMetadataModel.id == "8f348fc7-0545-413c-96c6-52b0800b4ef0"
                    )),
                ),
                "media": tuple(connection.execute(select(
                    FlashcardMediaModel.deck_id, FlashcardMediaModel.card_id,
                    FlashcardMediaModel.role, MediaModel.id, MediaModel.storage_key,
                    MediaModel.checksum_sha256,
                ).join(MediaModel, MediaModel.id == FlashcardMediaModel.media_id).where(
                    FlashcardMediaModel.deck_id == "8f348fc7-0545-413c-96c6-52b0800b4ef0"
                ).order_by(FlashcardMediaModel.card_id, FlashcardMediaModel.role)).all()),
            }
            assert after == before
    finally:
        engine.dispose()
