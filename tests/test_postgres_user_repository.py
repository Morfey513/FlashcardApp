import os
import uuid

import pytest
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import sessionmaker

from src.storage.database import create_session_factory, get_database_url
from src.storage.postgres_models import Base, UserModel
from src.storage.postgres_user_repository import PostgresUserRepository
from src.storage.repository_factory import create_user_repository
from src.storage.user_repository import JsonUserRepository


@pytest.fixture
def postgres_repository(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'users.db'}")
    Base.metadata.create_all(engine)
    repository = PostgresUserRepository(
        sessionmaker(bind=engine, expire_on_commit=False)
    )
    yield repository
    engine.dispose()


def test_postgres_repository_matches_registration_auth_and_preferences(
    postgres_repository,
):
    repository = postgres_repository

    created, message, user = repository.register(
        "Database Student", "database.student", "password1"
    )

    assert created is True
    assert message == "Account created"
    assert user["role"] == "student"
    assert user["preferences"] == {"theme": "dark", "language": "en"}
    assert "password" not in user
    assert repository.authenticate("DATABASE.STUDENT", "password1")["id"] == user["id"]
    assert repository.authenticate("database.student", "wrong") is None

    preferences = {
        "theme": "light",
        "language": "fr",
        "launcher_size": [820, 740],
        "window_sizes": {"quiz_editor": [880, 640]},
        "future_setting": True,
    }
    assert repository.save_preferences(user["id"], preferences)
    saved = next(item for item in repository.get_all_users() if item["id"] == user["id"])
    assert saved["preferences"] == preferences


def test_postgres_repository_matches_profile_role_password_and_ban_behavior(
    postgres_repository,
):
    repository = postgres_repository
    _created, _message, user = repository.register(
        "Old Name", "managed.user", "password1"
    )

    assert repository.update_display_name(user["id"], "New Name")
    assert repository.update_role(user["id"], "teacher")
    assert not repository.update_role(user["id"], "owner")
    assert repository.change_password(user["id"], "wrong", "newpassword") == (
        False,
        "Current password is incorrect",
    )
    assert repository.change_password(user["id"], "password1", "newpassword")[0]
    assert repository.authenticate("managed.user", "newpassword")["name"] == "New Name"

    assert not repository.set_account_status(
        "teacher", user["id"], "banned", "Not authorized"
    )
    assert repository.set_account_status(
        "admin", user["id"], "banned", "Policy violation"
    )
    assert repository.authenticate("managed.user", "newpassword") is None
    assert repository.get_ban_message("managed.user") == (
        "Account suspended. Reason: Policy violation"
    )
    assert repository.set_account_status("admin", user["id"], "active")
    assert repository.authenticate("managed.user", "newpassword")["status"] == "active"


def test_json_import_preserves_legacy_id_hash_and_preferences(postgres_repository):
    repository = postgres_repository
    source = {
        "id": "1",
        "login": "legacy.admin",
        "name": "Legacy Admin",
        "role": "admin",
        "status": "active",
        "password": (
            "pbkdf2_sha256$210000$1c53269189d57135786300bd74209b98$"
            "de49130da22faefb90f6467745d6ab19e1792de205b42c5e84ebacaade7f4833"
        ),
        "preferences": {"theme": "light", "language": "en"},
    }

    assert repository.import_json_user(source)
    assert repository.import_json_user(source)  # idempotent upsert
    users = repository.get_all_users()
    assert len(users) == 1
    assert users[0]["id"] == "1"
    assert repository.authenticate("legacy.admin", "admin123")["role"] == "admin"


def test_repository_factory_defaults_to_json(monkeypatch):
    monkeypatch.delenv("STUDY_BUDDY_STORAGE", raising=False)
    repository = create_user_repository()
    assert isinstance(repository, JsonUserRepository)
    assert repository.is_online() is False


def test_repository_factory_rejects_unknown_backend(monkeypatch):
    monkeypatch.setenv("STUDY_BUDDY_STORAGE", "spreadsheet")
    with pytest.raises(ValueError, match="Unsupported STUDY_BUDDY_STORAGE"):
        create_user_repository()


def test_database_url_is_required_and_read_from_environment(monkeypatch):
    monkeypatch.delenv("STUDY_BUDDY_DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="STUDY_BUDDY_DATABASE_URL is required"):
        get_database_url()

    monkeypatch.setenv("STUDY_BUDDY_DATABASE_URL", " sqlite+pysqlite:///:memory: ")
    assert get_database_url() == "sqlite+pysqlite:///:memory:"


def test_repository_factory_can_select_sql_backend_without_connecting(monkeypatch):
    monkeypatch.setenv("STUDY_BUDDY_STORAGE", "postgresql")
    monkeypatch.setenv("STUDY_BUDDY_DATABASE_URL", "sqlite+pysqlite:///:memory:")
    create_session_factory.cache_clear()
    try:
        repository = create_user_repository()
        assert isinstance(repository, PostgresUserRepository)
        assert repository.get_all_users() == []
        assert repository.is_online() is True
    finally:
        session_factory = create_session_factory()
        session_factory.kw["bind"].dispose()
        create_session_factory.cache_clear()


def test_repository_factory_can_select_http_backend(monkeypatch):
    from src.storage.http_user_repository import HttpUserRepository

    monkeypatch.setenv("STUDY_BUDDY_STORAGE", "api")
    monkeypatch.setenv("STUDY_BUDDY_API_URL", "http://127.0.0.1:9876")
    repository = create_user_repository()
    assert isinstance(repository, HttpUserRepository)
    assert repository.base_url == "http://127.0.0.1:9876"


@pytest.mark.skipif(
    not os.getenv("STUDY_BUDDY_TEST_DATABASE_URL"),
    reason="STUDY_BUDDY_TEST_DATABASE_URL is not configured",
)
def test_live_postgres_registration_round_trip():
    """Optional smoke test against the explicitly configured local test DB."""
    database_url = os.environ["STUDY_BUDDY_TEST_DATABASE_URL"]
    engine = create_engine(database_url)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    repository = PostgresUserRepository(sessions)
    login = f"integration.{uuid.uuid4().hex}"

    created, _message, user = repository.register("Integration User", login, "password1")
    try:
        assert created
        assert repository.authenticate(login, "password1")["id"] == user["id"]
    finally:
        if user:
            with sessions.begin() as session:
                session.execute(delete(UserModel).where(UserModel.id == user["id"]))
        engine.dispose()
