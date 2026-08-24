import json

import pytest

from src.storage.content_library import ContentLibrary
from src.storage.flashcard_repository import FlashcardRepository
from src.storage.quiz_repository import QuizRepository
from src.utils.paths import resolve_stored_path


def library(tmp_path):
    return ContentLibrary(
        quiz_repository=QuizRepository(tmp_path / "data" / "quizzes", tmp_path / "data" / "quizzes.json"),
        flashcard_repository=FlashcardRepository(tmp_path / "data" / "flashcards", tmp_path / "data" / "flashcard_decks.json"),
        cache_root=tmp_path / "cache",
    )


def test_bundled_content_is_available_to_guests_and_accounts(tmp_path):
    repo = library(tmp_path)
    repo.quiz_repository.create_quiz("Bundled", [])

    assert repo.list("quiz", "guest")[0]["source"] == "bundled"
    assert repo.list("quiz", "account-1")[0]["source"] == "bundled"


def test_public_download_survives_logout_and_remains_public(tmp_path):
    repo = library(tmp_path)
    body = {"id": "public-1", "name": "Public", "questions": []}
    repo.store_download("quiz", "public-1", body, name="Public")

    assert len(repo.list("quiz", "account-1")) == 1
    assert len(repo.list("quiz", "guest")) == 1
    assert (tmp_path / "cache" / "library" / "quizzes" / "public-1").exists()


def test_restricted_download_obeys_account_boundaries_and_logout(tmp_path):
    repo = library(tmp_path)
    repo.store_download(
        "flashcard", "private-1", {"id": "private-1", "name": "Private", "cards": []},
        name="Private", visibility="private", owner_id="account-1",
    )

    assert len(repo.list("flashcard", "account-1")) == 1
    assert repo.list("flashcard", "guest") == []
    assert repo.list("flashcard", "account-2") == []
    assert len(repo.list("flashcard", "account-1")) == 1


def test_clear_downloaded_data_preserves_bundled_and_json_data(tmp_path):
    repo = library(tmp_path)
    repo.quiz_repository.create_quiz("Bundled", [])
    repo.store_download("quiz", "downloaded-1", {"id": "downloaded-1", "name": "D", "questions": []}, name="D")

    assert repo.clear_downloaded_data() == 1
    assert len(repo.quiz_repository.get_all_quizzes()) == 1
    assert repo.list("quiz", "guest")[0]["source"] == "bundled"
    assert not (tmp_path / "cache" / "library" / "quizzes" / "downloaded-1").exists()


def test_invalid_or_incomplete_cache_entries_are_hidden(tmp_path):
    repo = library(tmp_path)
    entry = tmp_path / "cache" / "library" / "quizzes" / "broken"
    entry.mkdir(parents=True)
    (entry / "manifest.json").write_text(json.dumps({"source": "downloaded"}), encoding="utf-8")

    assert repo.list("quiz") == []


def test_failed_replacement_keeps_previous_valid_entry(tmp_path, monkeypatch):
    repo = library(tmp_path)
    repo.store_download("quiz", "stable", {"id": "stable", "name": "Old", "questions": []}, name="Old")
    original = repo._write_json

    def fail(path, value):
        if path.name == repo.MANIFEST and path.parent.name != "stable":
            raise OSError("simulated write failure")
        return original(path, value)

    monkeypatch.setattr(repo, "_write_json", fail)
    with pytest.raises(OSError):
        repo.store_download("quiz", "stable", {"id": "stable", "name": "New", "questions": []}, name="New")
    assert repo.list("quiz")[0]["name"] == "Old"


def test_remote_media_is_not_resolved_as_local_path():
    assert resolve_stored_path("https://cdn.example/media.png") is None
    assert ContentLibrary.resolve_media("https://cdn.example/media.png") is None


def test_library_repository_reads_public_cached_quiz_after_logout(tmp_path):
    repo = library(tmp_path)
    repo.store_download("quiz", "cached", {"id": "cached", "name": "Cached", "questions": [{"id": "q1"}]}, name="Cached")
    adapter = repo.repository_for("quiz", "guest", repo.quiz_repository)

    rows = adapter.get_all_quizzes()
    cached = next(row for row in rows if row["id"] == "cached")
    assert adapter.load_quiz_questions(cached["file"]) == [{"id": "q1"}]


def test_library_repository_keeps_restricted_cache_locked_until_authorized(tmp_path):
    repo = library(tmp_path)
    repo.store_download(
        "flashcard", "restricted", {"id": "restricted", "name": "Restricted", "cards": [{"id": "c1"}]},
        name="Restricted", visibility="private", owner_id="account-1",
    )
    guest = repo.repository_for("flashcard", "guest", repo.flashcard_repository)
    authorized = repo.repository_for("flashcard", "account-1", repo.flashcard_repository)

    assert all(row["id"] != "restricted" for row in guest.get_all_decks())
    assert any(row["id"] == "restricted" for row in authorized.get_all_decks())
    assert authorized.load_deck_cards("restricted") == [{"id": "c1"}]
