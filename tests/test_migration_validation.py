"""Opt-in Alembic checks and isolated coverage for the JSON import CLIs."""

import importlib
import importlib.util
import os
from pathlib import Path

import pytest


REVISION_HEAD = "20260817_0006"


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

    database_url = os.environ["STUDY_BUDDY_TEST_DATABASE_URL"]
    monkeypatch.setenv("STUDY_BUDDY_DATABASE_URL", database_url)
    config = Config("alembic.ini")

    command.downgrade(config, "base")
    command.upgrade(config, "head")
    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            assert connection.execute(text("select version_num from alembic_version")).scalar_one() == REVISION_HEAD
            tables = set(inspect(connection).get_table_names())
            assert {"users", "quizzes", "quiz_questions"}.issubset(tables)
        command.downgrade(config, "base")
        command.upgrade(config, "head")
        with engine.connect() as connection:
            assert connection.execute(text("select version_num from alembic_version")).scalar_one() == REVISION_HEAD
    finally:
        engine.dispose()


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
