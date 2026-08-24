"""Opt-in Alembic checks and isolated coverage for the JSON import CLIs."""

import importlib
import importlib.util
import os
from pathlib import Path

import pytest
from sqlalchemy.engine import make_url


REVISION_HEAD = "20260823_0007"
TEST_DATABASE_NAME = "study_buddy_test"


def _validate_test_database_url(database_url: str) -> str:
    """Accept only the explicitly provisioned disposable PostgreSQL target."""
    try:
        parsed = make_url(database_url)
    except Exception as exc:
        raise ValueError("STUDY_BUDDY_TEST_DATABASE_URL is not a valid database URL") from exc
    if parsed.get_backend_name() != "postgresql":
        raise ValueError("STUDY_BUDDY_TEST_DATABASE_URL must use PostgreSQL")
    if parsed.get_driver_name() not in {"psycopg", "psycopg2"}:
        raise ValueError("STUDY_BUDDY_TEST_DATABASE_URL must use psycopg or psycopg2")
    if parsed.database != TEST_DATABASE_NAME:
        raise ValueError(
            f"STUDY_BUDDY_TEST_DATABASE_URL must target the dedicated {TEST_DATABASE_NAME} database"
        )
    return database_url


@pytest.mark.skipif(
    not os.getenv("STUDY_BUDDY_TEST_DATABASE_URL"),
    reason="set STUDY_BUDDY_TEST_DATABASE_URL to an isolated disposable PostgreSQL database",
)
def test_alembic_upgrade_downgrade_and_reupgrade(monkeypatch):
    """Exercise the real revision chain, never the application's configured DB."""
    alembic = pytest.importorskip("alembic")
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, inspect, text
    from sqlalchemy.exc import IntegrityError

    database_url = _validate_test_database_url(os.environ["STUDY_BUDDY_TEST_DATABASE_URL"])
    monkeypatch.setenv("STUDY_BUDDY_DATABASE_URL", database_url)
    config = Config("alembic.ini")

    command.downgrade(config, "base")
    command.upgrade(config, "head")
    engine = create_engine(database_url)
    try:
        with engine.begin() as connection:
            assert connection.execute(text("select version_num from alembic_version")).scalar_one() == REVISION_HEAD
            inspector = inspect(connection)
            tables = set(inspector.get_table_names())
            assert {"users", "quizzes", "quiz_questions", "quiz_attempts", "quiz_attempt_questions"}.issubset(tables)

            attempt_columns = {column["name"]: column for column in inspector.get_columns("quiz_attempts")}
            assert attempt_columns["assessment_snapshot"]["nullable"] is True
            assert str(attempt_columns["assessment_snapshot"]["type"]).upper() == "JSONB"

            question_columns = {column["name"] for column in inspector.get_columns("quiz_attempt_questions")}
            assert question_columns == {"attempt_id", "position", "question_id", "presentation_json", "grading_key_json"}
            assert inspector.get_pk_constraint("quiz_attempt_questions")["constrained_columns"] == ["attempt_id", "position"]
            unique_constraints = {
                tuple(constraint["column_names"])
                for constraint in inspector.get_unique_constraints("quiz_attempt_questions")
            }
            assert ("attempt_id", "question_id") in unique_constraints
            foreign_keys = inspector.get_foreign_keys("quiz_attempt_questions")
            assert len(foreign_keys) == 1
            assert foreign_keys[0]["constrained_columns"] == ["attempt_id"]
            assert foreign_keys[0]["referred_table"] == "quiz_attempts"
            assert (foreign_keys[0].get("options") or {}).get("ondelete") == "CASCADE"

            index = next(index for index in inspector.get_indexes("quiz_attempts") if index["name"] == "uq_quiz_attempts_active_assessment")
            assert index["unique"] is True
            assert index["column_names"] == ["user_id", "quiz_id"]
            index_definition = connection.execute(
                text("SELECT indexdef FROM pg_indexes WHERE schemaname = current_schema() AND indexname = 'uq_quiz_attempts_active_assessment'")
            ).scalar_one()
            normalized_index_definition = " ".join(index_definition.lower().split())
            assert "assessment_snapshot is not null" in normalized_index_definition
            assert "in_progress" in normalized_index_definition
            assert "abandoned" in normalized_index_definition

            connection.execute(text("INSERT INTO users (id, username, password_hash, display_name, role, status) VALUES ('migration-u', 'migration-u', 'x', 'Migration User', 'student', 'active')"))
            connection.execute(text("INSERT INTO quizzes (id, source_owner_id, name, lifecycle, visibility, source_path) VALUES ('migration-q', 'migration-u', 'Migration Quiz', 'published', 'private', 'migration-validation')"))
            connection.execute(text("INSERT INTO quiz_attempts (id, user_id, quiz_id, status, started_at) VALUES ('legacy-a', 'migration-u', 'migration-q', 'submitted', now())"))
            assert connection.execute(text("SELECT assessment_snapshot FROM quiz_attempts WHERE id = 'legacy-a'")).scalar_one() is None
            connection.execute(text("INSERT INTO quiz_attempts (id, user_id, quiz_id, status, started_at, assessment_snapshot) VALUES ('completed-a', 'migration-u', 'migration-q', 'submitted', now(), '{\"version\": 1}'::jsonb)"))
            connection.execute(text("INSERT INTO quiz_attempts (id, user_id, quiz_id, status, started_at, assessment_snapshot) VALUES ('active-a', 'migration-u', 'migration-q', 'in_progress', now(), '{\"version\": 1}'::jsonb)"))
            savepoint = connection.begin_nested()
            try:
                with pytest.raises(IntegrityError):
                    connection.execute(text("INSERT INTO quiz_attempts (id, user_id, quiz_id, status, started_at, assessment_snapshot) VALUES ('active-b', 'migration-u', 'migration-q', 'abandoned', now(), '{\"version\": 1}'::jsonb)"))
            finally:
                # PostgreSQL marks the transaction failed after the expected
                # constraint error; explicitly roll back the savepoint before
                # releasing it so the outer transaction remains usable.
                savepoint.rollback()
        command.downgrade(config, "base")
        command.upgrade(config, "head")
        with engine.connect() as connection:
            assert connection.execute(text("select version_num from alembic_version")).scalar_one() == REVISION_HEAD
            assert "assessment_snapshot" in {column["name"] for column in inspect(connection).get_columns("quiz_attempts")}
            assert "quiz_attempt_questions" in inspect(connection).get_table_names()
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    "database_url",
    [
        "postgresql+psycopg://user:secret@localhost:5432/study_buddy_test",
        "postgresql+psycopg2://user:secret@localhost:5432/study_buddy_test",
    ],
)
def test_validation_accepts_dedicated_postgresql_urls(database_url):
    assert _validate_test_database_url(database_url) == database_url


@pytest.mark.parametrize(
    "database_url, message",
    [
        ("sqlite:///study_buddy_test.db", "PostgreSQL"),
        ("postgresql+psycopg://user:secret@localhost:5432/study_buddy", "study_buddy_test"),
        ("not-a-url", "valid database URL"),
    ],
)
def test_validation_rejects_unsafe_database_urls(database_url, message):
    with pytest.raises(ValueError, match=message):
        _validate_test_database_url(database_url)


class _IdempotentRepository:
    records = set()
    calls = {}

    def __init__(self):
        pass

    def __getattr__(self, name):
        def operation(*args, **kwargs):
            key = (name, repr(args), repr(sorted(kwargs.items())))
            self.records.add(key)
            self.calls[name] = self.calls.get(name, 0) + 1
            return True

        return operation


def _run_import_clis(monkeypatch, tmp_path):
    data = tmp_path / "data"
    quizzes = data / "quizzes" / "quiz-1"
    decks = data / "flashcard_decks" / "deck-1"
    quizzes.mkdir(parents=True)
    decks.mkdir(parents=True)
    (data / "users.json").write_text('{"users": [{"id": "u-1", "login": "one"}]}', encoding="utf-8")
    (quizzes / "quiz.json").write_text('{"id": "quiz-1", "name": "Quiz", "questions": [], "moderation": {"visibility": "class_only", "invite": "ABC123", "enrollments": ["u-1"]}}', encoding="utf-8")
    (decks / "deck.json").write_text('{"id": "deck-1", "name": "Deck", "cards": [], "moderation": {"visibility": "class_only", "invite": "ABC123", "enrollments": ["u-1"]}}', encoding="utf-8")
    for root in (quizzes, decks):
        progress = root / "progress"
        progress.mkdir()
        (progress / "u-1.json").write_text("{}", encoding="utf-8")
    attempts = quizzes / "attempts"
    attempts.mkdir()
    (attempts / "u-1.json").write_text('{"user_id": "u-1", "score": 1}', encoding="utf-8")
    (quizzes / "edit_history.json").write_text("[]", encoding="utf-8")
    (quizzes / "moderation_history.json").write_text("[]", encoding="utf-8")
    (decks / "edit_history.json").write_text("[]", encoding="utf-8")
    (decks / "moderation_history.json").write_text("[]", encoding="utf-8")

    specs = [
        ("tools.migrate_users_to_postgres", "USERS_FILE", data / "users.json", "PostgresUserRepository"),
        ("tools.migrate_content_metadata_to_postgres", "QUIZ_DIR", data / "quizzes", "PostgresContentMetadataRepository"),
        ("tools.migrate_content_metadata_to_postgres", "FLASHCARD_DIR", data / "flashcard_decks", None),
        ("tools.migrate_classes_to_postgres", "QUIZ_DIR", data / "quizzes", "PostgresClassRepository"),
        ("tools.migrate_classes_to_postgres", "FLASHCARD_DIR", data / "flashcard_decks", None),
        ("tools.migrate_learning_state_to_postgres", "QUIZ_DIR", data / "quizzes", "PostgresLearningRepository"),
        ("tools.migrate_learning_state_to_postgres", "FLASHCARD_DIR", data / "flashcard_decks", None),
        ("tools.migrate_content_bodies_to_postgres", "QUIZ_DIR", data / "quizzes", "PostgresContentBodyRepository"),
        ("tools.migrate_content_bodies_to_postgres", "FLASHCARD_DIR", data / "flashcard_decks", None),
        ("tools.migrate_content_history_to_postgres", "QUIZ_DIR", data / "quizzes", "PostgresContentHistoryRepository"),
        ("tools.migrate_content_history_to_postgres", "FLASHCARD_DIR", data / "flashcard_decks", None),
    ]
    modules = {}
    for module_name, attr, value, repository_name in specs:
        if module_name not in modules:
            path = Path(module_name.replace(".", "/") + ".py")
            spec = importlib.util.spec_from_file_location(module_name, path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            modules[module_name] = module
        module = modules[module_name]
        monkeypatch.setattr(module, attr, value)
        if repository_name:
            monkeypatch.setattr(module, repository_name, _IdempotentRepository)
    return [modules[name] for name in (
        "tools.migrate_users_to_postgres",
        "tools.migrate_content_metadata_to_postgres",
        "tools.migrate_classes_to_postgres",
        "tools.migrate_learning_state_to_postgres",
        "tools.migrate_content_bodies_to_postgres",
        "tools.migrate_content_history_to_postgres",
    )]


def test_all_json_import_clis_are_ordered_and_idempotent(monkeypatch, tmp_path):
    """Run each documented phase twice against isolated fake repositories."""
    pytest.importorskip("sqlalchemy")
    _IdempotentRepository.records.clear()
    _IdempotentRepository.calls.clear()
    modules = _run_import_clis(monkeypatch, tmp_path)
    for module in modules:
        assert module.main() == 0
    first_count = len(_IdempotentRepository.records)
    first_calls = dict(_IdempotentRepository.calls)
    for module in modules:
        assert module.main() == 0
    assert len(_IdempotentRepository.records) == first_count
    assert _IdempotentRepository.calls == {name: count * 2 for name, count in first_calls.items()}
    assert "import_content_access" in first_calls
