import copy
import json
import hashlib

import pytest

from src.controllers.quiz_controller import QuizController
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


def downloaded_quiz_body(content_id="downloaded-quiz", name="Downloaded Quiz"):
    return {
        "id": content_id,
        "name": name,
        "content_version": 1,
        "questions": [
            {
                "id": "matching-1",
                "question": "Match country to capital:",
                "type": "matching",
                "pairs": [
                    {"prompt": "Spain", "answer": "Madrid"},
                    {"prompt": "Norway", "answer": "Oslo"},
                ],
                "has_image": True,
                "image_path": "https://cdn.example/questions/capitals.png",
            },
            {
                "id": "choice-1",
                "question": "Which country has Madrid as its capital?",
                "type": "single_choice",
                "choices": ["Spain", "Norway"],
                "answer": "Spain",
            },
        ],
    }


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


def test_media_package_is_validated_and_overlaid_without_mutating_content(tmp_path):
    repo = library(tmp_path)
    payload = b"not-a-real-png"
    descriptor = {
        "media_id": "image-1", "item_id": "matching-1", "attachment_role": "image",
        "content_id": "media-quiz", "content_version": 1, "mime_type": "image/png",
        "size_bytes": len(payload), "checksum_sha256": hashlib.sha256(payload).hexdigest(),
    }
    body = downloaded_quiz_body("media-quiz")
    body["questions"][0]["media"] = [{"media_id": "image-1", "role": "image"}]
    repo.store_download("quiz", "media-quiz", body, name="Media", content_version=1,
                        media=[{"descriptor": descriptor, "bytes": payload}])

    rows = repo.repository_for("quiz").load_quiz_questions("media-quiz")
    assert rows[0]["image_path"].endswith("image-1.png")
    assert repo.get_downloaded("quiz", "media-quiz")["body"]["questions"][0]["image_path"].startswith("https://")
    assert repo.get_downloaded("quiz", "media-quiz")["media_state"] == "complete"


def test_optional_missing_media_commits_partial_package_but_bad_checksum_does_not(tmp_path):
    repo = library(tmp_path)
    body = downloaded_quiz_body("optional-media")
    body["questions"][0]["media"] = [{"media_id": "missing", "role": "image"}]
    descriptor = {
        "media_id": "missing", "item_id": "matching-1", "attachment_role": "image",
        "content_id": "optional-media", "content_version": 1, "mime_type": "image/png",
        "size_bytes": 1, "checksum_sha256": "0" * 64,
    }
    repo.store_download("quiz", "optional-media", body, name="Optional", content_version=1,
                        media=[{"descriptor": descriptor, "bytes": None}])
    assert repo.get_downloaded("quiz", "optional-media")["media_state"] == "partially_available"
    with pytest.raises(ValueError, match="checksum"):
        repo.store_download("quiz", "bad-media", {**body, "id": "bad-media"}, name="Bad", content_version=1,
                            media=[{"descriptor": {**descriptor, "content_id": "bad-media"}, "bytes": b"x"}])
    assert repo.get_downloaded("quiz", "bad-media") is None


def test_downloaded_catalog_row_carries_package_projection(tmp_path):
    repo = library(tmp_path)
    body = downloaded_quiz_body("practice-catalog")
    repo.store_download("quiz", "practice-catalog", body, name="Practice",
                        content_version=1, quiz_projection="practice_only")

    rows = repo.repository_for("quiz").get_all_quizzes()
    row = next(item for item in rows if item["id"] == "practice-catalog")
    assert row["source"] == "downloaded"
    assert row["package_projection"] == "practice_only"


@pytest.mark.parametrize("damage", ["remove", "corrupt"])
def test_post_commit_optional_media_loss_keeps_text_package_visible(tmp_path, damage):
    repo = library(tmp_path)
    payload = b"valid optional image"
    body = downloaded_quiz_body("optional-after-commit")
    body["questions"][0]["media"] = [{"media_id": "optional-image", "role": "image"}]
    descriptor = {
        "media_id": "optional-image", "item_id": "matching-1", "attachment_role": "image",
        "content_id": "optional-after-commit", "content_version": 1, "mime_type": "image/png",
        "size_bytes": len(payload), "checksum_sha256": hashlib.sha256(payload).hexdigest(),
    }
    repo.store_download("quiz", "optional-after-commit", body, name="Optional", content_version=1,
                        media=[{"descriptor": descriptor, "bytes": payload}])
    path = tmp_path / "cache" / "library" / "quizzes" / "optional-after-commit" / "media" / "optional-image.png"
    if damage == "remove":
        path.unlink()
    else:
        path.write_bytes(b"corrupt")

    cached = repo.get_downloaded("quiz", "optional-after-commit")
    assert cached is not None and cached["media_state"] == "partially_available"
    rows = repo.repository_for("quiz").load_quiz_questions("optional-after-commit")
    assert rows[0]["image_path"].startswith("https://")


def test_post_commit_required_media_loss_hides_package(tmp_path):
    repo = library(tmp_path)
    payload = b"required image"
    body = downloaded_quiz_body("required-after-commit")
    body["questions"][0]["media"] = [{"media_id": "required-image", "role": "image"}]
    descriptor = {
        "media_id": "required-image", "item_id": "matching-1", "attachment_role": "image",
        "content_id": "required-after-commit", "content_version": 1, "mime_type": "image/png",
        "size_bytes": len(payload), "checksum_sha256": hashlib.sha256(payload).hexdigest(), "required": True,
    }
    repo.store_download("quiz", "required-after-commit", body, name="Required", content_version=1,
                        media=[{"descriptor": descriptor, "bytes": payload}])
    path = tmp_path / "cache" / "library" / "quizzes" / "required-after-commit" / "media" / "required-image.png"
    path.unlink()
    assert repo.get_downloaded("quiz", "required-after-commit") is None
    assert repo.list_downloaded("quiz") == []


def test_matching_manifest_body_id_and_version_is_valid(tmp_path):
    repo = library(tmp_path)
    body = {
        "id": "coherent", "name": "Coherent", "content_version": 3,
        "questions": [],
    }
    repo.store_download(
        "quiz", "coherent", body, name="Coherent", content_version=3,
    )

    assert repo.get_downloaded("quiz", "coherent")["body"] == body


def test_mismatched_body_id_is_hidden_from_discovery(tmp_path):
    repo = library(tmp_path)
    body = {"id": "expected", "name": "Quiz", "questions": []}
    repo.store_download("quiz", "expected", body, name="Quiz")
    entry = tmp_path / "cache" / "library" / "quizzes" / "expected"
    (entry / "content.json").write_text(
        json.dumps({**body, "id": "different"}), encoding="utf-8"
    )

    assert repo.get_downloaded("quiz", "expected") is None
    assert repo.list_downloaded("quiz") == []


def test_mismatched_body_version_is_hidden_from_discovery(tmp_path):
    repo = library(tmp_path)
    body = {
        "id": "versioned", "name": "Quiz", "content_version": 4,
        "questions": [],
    }
    repo.store_download(
        "quiz", "versioned", body, name="Quiz", content_version=4,
    )
    entry = tmp_path / "cache" / "library" / "quizzes" / "versioned"
    (entry / "content.json").write_text(
        json.dumps({**body, "content_version": 5}), encoding="utf-8"
    )

    assert repo.get_downloaded("quiz", "versioned") is None
    assert repo.list_downloaded("quiz") == []


def test_legacy_package_without_manifest_revision_remains_valid(tmp_path):
    repo = library(tmp_path)
    body = {"id": "legacy", "name": "Legacy", "questions": []}
    manifest = repo.store_download("quiz", "legacy", body, name="Legacy")

    assert manifest["content_version"] is None
    assert repo.get_downloaded("quiz", "legacy")["body"] == body


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


def test_interrupted_directory_swap_recovers_previous_valid_package(tmp_path):
    repo = library(tmp_path)
    repo.store_download(
        "quiz", "stable", {
            "id": "stable", "name": "Old", "content_version": 1,
            "questions": [],
        },
        name="Old", content_version=1,
    )
    target = tmp_path / "cache" / "library" / "quizzes" / "stable"
    backup = target.with_name(".stable.previous")
    target.replace(backup)
    abandoned_staging = target.with_name(".stable-interrupted")
    abandoned_staging.mkdir()
    (abandoned_staging / "content.json").write_text("{}", encoding="utf-8")

    reopened = library(tmp_path)
    recovered = reopened.get_downloaded("quiz", "stable")

    assert recovered["name"] == "Old"
    assert recovered["content_version"] == 1
    assert target.exists()
    assert not backup.exists()
    assert reopened.list("quiz")[0]["name"] == "Old"


def test_interrupted_swap_recovers_backup_over_invalid_target(tmp_path):
    repo = library(tmp_path)
    repo.store_download(
        "flashcard", "stable",
        {"id": "stable", "name": "Old", "content_version": 1, "cards": []},
        name="Old", content_version=1,
    )
    target = tmp_path / "cache" / "library" / "flashcards" / "stable"
    backup = target.with_name(".stable.previous")
    target.replace(backup)
    target.mkdir()
    (target / "manifest.json").write_text("{}", encoding="utf-8")

    recovered = library(tmp_path).get_downloaded("flashcard", "stable")

    assert recovered["body"]["name"] == "Old"
    assert target.exists()
    assert not backup.exists()


def test_refresh_compares_versions_and_preserves_old_package_on_failure(tmp_path, monkeypatch):
    repo = library(tmp_path)
    repo.store_download("quiz", "v1", {
        "id": "v1", "name": "Old", "content_version": 1, "questions": [],
    },
                        name="Old", content_version=1)
    assert repo.update_state("quiz", "v1", 1) == "synchronized"
    assert repo.update_state("quiz", "v1", 2) == "update_available"
    assert repo.refresh_download("quiz", "v1", {"name": "New", "content_version": 2},
                                {"id": "v1", "name": "New", "content_version": 2, "questions": []})
    assert repo.get_downloaded("quiz", "v1")["body"]["name"] == "New"


def test_refresh_rejects_body_revision_mismatch_and_can_retry(tmp_path, monkeypatch):
    repo = library(tmp_path)
    repo.store_download("quiz", "v1", {
        "id": "v1", "name": "Old", "content_version": 1, "questions": [],
    },
                        name="Old", content_version=1)
    with pytest.raises(ValueError, match="revisions do not match"):
        repo.refresh_download("quiz", "v1", {"name": "New", "content_version": 2},
                              {"id": "v1", "name": "New", "content_version": 1, "questions": []})
    assert repo.get_downloaded("quiz", "v1")["body"]["name"] == "Old"
    assert repo.refresh_download("quiz", "v1", {"name": "New", "content_version": 2},
                                {"id": "v1", "name": "New", "content_version": 2, "questions": []})
    assert repo.get_downloaded("quiz", "v1")["body"]["name"] == "New"
    original = repo._write_json
    monkeypatch.setattr(repo, "_write_json", lambda path, value: (_ for _ in ()).throw(OSError("fail")) if path.name == repo.MANIFEST else original(path, value))
    with pytest.raises(OSError):
        repo.refresh_download("quiz", "v1", {"name": "Broken", "content_version": 3},
                              {"id": "v1", "name": "Broken", "content_version": 3, "questions": []})
    assert repo.get_downloaded("quiz", "v1")["body"]["name"] == "New"


def test_remote_media_is_not_resolved_as_local_path():
    assert resolve_stored_path("https://cdn.example/media.png") is None
    assert ContentLibrary.resolve_media("https://cdn.example/media.png") is None


def test_library_rejects_unusable_redacted_quiz_before_discovery(tmp_path):
    repo = library(tmp_path)
    redacted = {
        "id": "cached",
        "name": "Cached",
        "questions": [{
            "id": "q1",
            "question": "Match",
            "type": "matching",
            "pairs": [{"prompt": "Spain", "answer": None}],
        }],
    }
    with pytest.raises(ValueError, match="unusable offline"):
        repo.store_download("quiz", "cached", redacted, name="Cached")

    assert repo.list_downloaded("quiz") == []
    assert repo.repository_for("quiz", "guest", repo.quiz_repository).get_all_quizzes() == []


def test_downloaded_quiz_round_trip_reopen_delete_and_redownload_is_stable(tmp_path):
    repo = library(tmp_path)
    body = downloaded_quiz_body()
    metadata = {
        "name": body["name"],
        "content_version": 2,
        "updated_at": "2026-08-26T12:00:00+00:00",
        "visibility": "public",
    }
    entry = tmp_path / "cache" / "library" / "quizzes" / body["id"]

    repo.store_download(
        "quiz", body["id"], body,
        name=body["name"], content_version=body["content_version"],
        remote_updated_at="2026-08-25T12:00:00+00:00",
    )
    first_body_bytes = (entry / "content.json").read_bytes()
    first_manifest = json.loads((entry / "manifest.json").read_text(encoding="utf-8"))
    assert json.loads(first_body_bytes) == body
    assert first_manifest["content_id"] == body["id"]
    assert first_manifest["content_version"] == 1
    assert first_manifest["remote_updated_at"] == "2026-08-25T12:00:00+00:00"

    first_adapter = repo.repository_for("quiz", "guest", repo.quiz_repository)
    first_row = next(row for row in first_adapter.get_all_quizzes() if row["id"] == body["id"])
    assert first_row["source"] == "downloaded"
    assert first_row["file"] == str(entry / "content.json")
    assert first_adapter.load_quiz_questions(first_row["file"]) == body["questions"]
    first_controller = QuizController("guest", first_adapter, role="guest")
    assert first_controller.load_quiz_by_name(body["name"], mode="practice") is not None
    assert (entry / "content.json").read_bytes() == first_body_bytes

    reopened = library(tmp_path)
    reopened_adapter = reopened.repository_for("quiz", "guest", reopened.quiz_repository)
    reopened_controller = QuizController("guest", reopened_adapter, role="guest")
    assert reopened_controller.load_quiz_by_name(body["name"], mode="practice") is not None
    assert json.loads((entry / "content.json").read_text(encoding="utf-8")) == body

    reopened.store_download(
        "quiz", body["id"], copy.deepcopy(body),
        name=body["name"], content_version=body["content_version"],
        remote_updated_at="2026-08-25T12:00:00+00:00",
    )
    assert (entry / "content.json").read_bytes() == first_body_bytes

    updated = copy.deepcopy(body)
    updated["content_version"] = 2
    updated["questions"][0]["pairs"][0]["answer"] = "Madrid, Spain"
    assert reopened.refresh_download("quiz", body["id"], metadata, updated)
    assert json.loads((entry / "content.json").read_text(encoding="utf-8")) == updated

    assert reopened.clear_downloaded_data() == 1
    assert not entry.exists()
    assert reopened.get_downloaded("quiz", body["id"]) is None

    reopened.store_download(
        "quiz", body["id"], body,
        name=body["name"], content_version=body["content_version"],
    )
    after_redownload = library(tmp_path)
    after_redownload_controller = QuizController(
        "guest",
        after_redownload.repository_for("quiz", "guest", after_redownload.quiz_repository),
        role="guest",
    )
    assert after_redownload_controller.load_quiz_by_name(body["name"], mode="practice") is not None
    assert json.loads((entry / "content.json").read_text(encoding="utf-8")) == body


def test_multiple_downloads_and_account_boundaries_survive_repository_restart(tmp_path):
    repo = library(tmp_path)
    public = downloaded_quiz_body("public-quiz", "Public Quiz")
    private = downloaded_quiz_body("private-quiz", "Private Quiz")
    repo.store_download("quiz", public["id"], public, name=public["name"])
    repo.store_download(
        "quiz", private["id"], private, name=private["name"],
        visibility="private", owner_id="account-1",
    )

    restarted = library(tmp_path)
    assert {row["content_id"] for row in restarted.list_downloaded("quiz")} == {
        "public-quiz", "private-quiz",
    }
    assert {row["id"] for row in restarted.repository_for(
        "quiz", "guest", restarted.quiz_repository,
    ).get_all_quizzes()} == {"public-quiz"}
    assert {row["id"] for row in restarted.repository_for(
        "quiz", "account-2", restarted.quiz_repository,
    ).get_all_quizzes()} == {"public-quiz"}
    assert {row["id"] for row in restarted.repository_for(
        "quiz", "account-1", restarted.quiz_repository,
    ).get_all_quizzes()} == {"public-quiz", "private-quiz"}

    relogged = library(tmp_path)
    assert relogged.get_downloaded("quiz", "private-quiz", "account-1")["body"] == private


def test_redacted_download_cannot_be_marked_synchronized(tmp_path):
    repo = library(tmp_path)
    body = downloaded_quiz_body("redacted-quiz", "Redacted Quiz")
    body["questions"][0]["pairs"] = [
        {"prompt": "Spain", "answer": None},
        {"prompt": "Norway", "answer": None},
    ]
    with pytest.raises(ValueError, match="unusable offline"):
        repo.store_download(
            "quiz", body["id"], body, name=body["name"], content_version=1
        )

    assert repo.get_downloaded("quiz", body["id"]) is None


def test_bundled_deck_body_wins_over_same_id_download(tmp_path):
    repo = library(tmp_path)
    cards = [{"id": "c1", "front": "Capital of Spain?", "back": "Madrid"}]
    assert repo.flashcard_repository.create_deck("Bundled Deck", cards)
    bundled = repo.flashcard_repository.get_all_decks()[0]
    repo.store_download(
        "flashcard", bundled["id"],
        {
            "id": bundled["id"],
            "name": "Bundled Deck",
            "cards": [{"id": "c1", "front": "Capital of Spain?", "back": None}],
        },
        name="Bundled Deck",
    )

    adapter = repo.repository_for("flashcard", "guest", repo.flashcard_repository)
    assert adapter.load_deck_cards(bundled["file"])[0]["back"] == "Madrid"


@pytest.mark.parametrize(
    ("quiz_name", "question_count", "matching_position"),
    [("General Quiz (Copy)", 6, 4), ("General Quiz", 100, 40)],
)
def test_bundled_quiz_body_wins_over_same_id_valid_download(
    tmp_path, quiz_name, question_count, matching_position,
):
    repo = library(tmp_path)
    questions = [
        {
            "id": f"q-{position}",
            "question": f"Question {position}",
            "type": "short_answer",
            "answer": "answer",
        }
        for position in range(question_count)
    ]
    questions[matching_position] = {
        "id": "e92d4a97",
        "question": "Match country to capital:",
        "type": "matching",
        "pairs": [
            {"prompt": "Spain", "answer": "Madrid"},
            {"prompt": "Norway", "answer": "Oslo"},
        ],
    }
    assert repo.quiz_repository.create_quiz(quiz_name, questions)
    bundled = repo.quiz_repository.get_all_quizzes()[0]

    downloaded = copy.deepcopy(questions)
    downloaded[matching_position]["pairs"] = [
        {"prompt": "Spain", "answer": "Barcelona"},
        {"prompt": "Norway", "answer": "Bergen"},
    ]
    repo.store_download(
        "quiz", bundled["id"],
        {"id": bundled["id"], "name": quiz_name, "questions": downloaded},
        name=quiz_name,
    )

    adapter = repo.repository_for("quiz", "guest", repo.quiz_repository)
    loaded = adapter.load_quiz_questions(bundled["file"])
    assert loaded[matching_position]["pairs"] == questions[matching_position]["pairs"]

    controller = QuizController("guest", adapter, role="guest")
    assert controller.load_quiz_by_name(quiz_name, mode="practice") is not None


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
