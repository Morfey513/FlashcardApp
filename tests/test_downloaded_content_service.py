import pytest

from src.storage.content_library import ContentLibrary
from src.storage.downloaded_content_service import DownloadedContentService
from src.storage.flashcard_repository import FlashcardRepository
from src.storage.quiz_repository import QuizRepository
from src.logic.quiz_logic import Quiz
from src.storage import content_library as content_library_module


class MetadataStub:
    def __init__(self, value=None, code=200):
        self.value = value
        self.code = code

    def get_by_id_result(self, _kind, _content_id):
        return self.code, self.value


class BodyStub:
    def __init__(self, quiz=None, flashcard=None, code=200, on_fetch=None):
        self.quiz = quiz
        self.flashcard = flashcard
        self.code = code
        self.on_fetch = on_fetch

    def get_quiz_result(self, _content_id):
        if self.on_fetch:
            self.on_fetch()
        return self.code, self.quiz

    def get_flashcard_deck_result(self, _content_id):
        if self.on_fetch:
            self.on_fetch()
        return self.code, self.flashcard

    def get_practice_package_result(self, kind, _content_id):
        if self.on_fetch:
            self.on_fetch()
        return self.code, self.quiz if kind == "quiz" else self.flashcard


def make_library(tmp_path):
    return ContentLibrary(
        quiz_repository=QuizRepository(
            tmp_path / "data" / "quizzes", tmp_path / "data" / "quizzes.json"
        ),
        flashcard_repository=FlashcardRepository(
            tmp_path / "data" / "flashcards",
            tmp_path / "data" / "flashcard_decks.json",
        ),
        cache_root=tmp_path / "cache",
    )


def quiz_metadata(version=1, visibility="public"):
    return {
        "id": "quiz-1", "kind": "quiz", "name": "Quiz",
        "content_version": version, "updated_at": "2026-08-28T12:00:00+00:00",
        "visibility": visibility, "owner_id": "teacher-1",
    }


def test_cached_state_is_presentation_safe_and_respects_access(tmp_path):
    library = make_library(tmp_path)
    library.store_download(
        "flashcard", "private-deck", {"id": "private-deck", "name": "Private", "content_version": 2, "cards": []},
        name="Private", visibility="private", owner_id="owner", content_version=2,
        quiz_projection="study",
    )
    service = DownloadedContentService(library, MetadataStub(), BodyStub())

    owner = service.get_cached_state("flashcard", "private-deck", "owner")
    locked = service.get_cached_state("flashcard", "private-deck", "other")
    assert owner["state"] == "synchronized"
    assert owner["package_projection"] == "study"
    assert owner["downloaded_bytes"] > 0
    assert "file" not in owner and "body" not in owner
    assert locked["state"] == "locked"
    assert locked["accessible"] is False


def test_media_manifest_wrapper_is_normalized_and_checked_before_download():
    attachment = {"media_id": "m1", "item_id": "q1", "attachment_role": "image"}
    code, attachments = DownloadedContentService._normalize_media_manifest(
        200,
        {"content_id": "quiz-1", "content_kind": "quiz", "content_version": 3,
         "attachments": [attachment]},
        "quiz", "quiz-1", 3,
    )
    assert code == 200 and attachments == [attachment]
    with pytest.raises(ValueError, match="revision"):
        DownloadedContentService._normalize_media_manifest(
            200,
            {"content_id": "quiz-1", "content_kind": "quiz", "content_version": 2,
             "attachments": []},
            "quiz", "quiz-1", 3,
        )


def test_advertised_public_practice_package_is_guest_readable_after_logout(tmp_path):
    library = make_library(tmp_path)
    metadata = {**quiz_metadata(), "package_projection": "practice_only"}
    body = {**quiz_body(), "package_type": "offline_practice"}
    service = DownloadedContentService(library, MetadataStub(metadata), BodyStub(quiz=body))

    assert service.update("quiz", "quiz-1", "student-1")["state"] == "synchronized"
    cached = library.get_downloaded("quiz", "quiz-1", "guest")
    assert cached is not None
    assert cached["package_projection"] == "practice_only"
    assert service.get_cached_state("quiz", "quiz-1", "guest")["package_projection"] == "practice_only"


@pytest.mark.parametrize("marker", [None, "assessment"])
def test_advertised_practice_requires_dedicated_package_marker(tmp_path, marker):
    library = make_library(tmp_path)
    metadata = {**quiz_metadata(), "package_projection": "practice_only"}
    body = quiz_body()
    if marker is not None:
        body["package_type"] = marker
    service = DownloadedContentService(library, MetadataStub(metadata), BodyStub(quiz=body))

    assert service.update("quiz", "quiz-1", "student-1")["state"] == "failed"
    assert library.get_downloaded("quiz", "quiz-1", "student-1") is None


def quiz_body(version=1, question="Old"):
    return {
        "id": "quiz-1", "name": "Quiz", "content_version": version,
        "questions": [{
            "id": "q1", "question": question, "type": "short_answer", "answer": "A",
        }],
    }


def all_types_quiz_body(version=1):
    return {
        "id": "quiz-1", "name": "Quiz", "content_version": version,
        "questions": [
            {"id": "short", "question": "Short", "type": "short_answer", "answer": ["one"]},
            {"id": "single", "question": "Single", "type": "single_choice", "choices": ["A", "B"], "answer": "A"},
            {"id": "multiple", "question": "Multiple", "type": "multiple_choice", "choices": ["A", "B"], "answer": ["A"]},
            {"id": "boolean", "question": "Boolean", "type": "true_false", "answer": True},
            {"id": "matching", "question": "Matching", "type": "matching", "pairs": [{"prompt": "P", "answer": "A"}]},
            {"id": "ordering", "question": "Ordering", "type": "ordering", "answer": ["first", "second"]},
        ],
    }


def test_initial_restricted_download_binds_authorized_account(tmp_path):
    library = make_library(tmp_path)
    service = DownloadedContentService(
        library, MetadataStub(quiz_metadata(1, "class_only")), BodyStub(quiz=quiz_body(1))
    )

    assert service.update("quiz", "quiz-1", "student-1")["state"] == "synchronized"
    assert library.get_downloaded("quiz", "quiz-1", "student-1") is not None
    assert library.get_downloaded("quiz", "quiz-1", "student-2") is None
    assert library.get_downloaded("quiz", "quiz-1", "guest") is None


def test_initial_revision_mismatch_is_rejected_without_partial_package(tmp_path):
    library = make_library(tmp_path)
    service = DownloadedContentService(
        library, MetadataStub(quiz_metadata(2)), BodyStub(quiz=quiz_body(1))
    )

    result = service.update("quiz", "quiz-1", "student-1")
    assert result["state"] == "failed"
    assert "revisions do not match" in result["error"]
    assert not library.has_package("quiz", "quiz-1")


def test_check_uses_versions_not_timestamps_and_handles_missing_or_lower(tmp_path):
    library = make_library(tmp_path)
    library.store_download(
        "quiz", "quiz-1", quiz_body(2), name="Quiz", content_version=2,
        remote_updated_at="2020-01-01T00:00:00+00:00",
    )
    service = DownloadedContentService(
        library, MetadataStub(quiz_metadata(2)), BodyStub(quiz=quiz_body(2))
    )

    assert service.check("quiz", "quiz-1", "student-1")["state"] == "synchronized"
    service.metadata.value = quiz_metadata(3)
    assert service.check("quiz", "quiz-1", "student-1")["state"] == "update_available"
    service.metadata.value = quiz_metadata(1)
    assert service.check("quiz", "quiz-1", "student-1")["state"] == "stale"
    service.metadata.value = quiz_metadata(None)
    assert service.check("quiz", "quiz-1", "student-1")["state"] == "stale"


def test_explicit_revocation_is_per_account_and_successful_check_unlocks(tmp_path):
    library = make_library(tmp_path)
    library.store_download(
        "quiz", "quiz-1", quiz_body(1), name="Quiz", visibility="class_only",
        allowed_account_ids=["student-1", "student-2"], content_version=1,
    )
    metadata = MetadataStub({"detail": "not found"}, code=404)
    service = DownloadedContentService(library, metadata, BodyStub(quiz=quiz_body(1)))

    assert service.check("quiz", "quiz-1", "student-1")["state"] == "locked"
    assert library.get_downloaded("quiz", "quiz-1", "student-1") is None
    assert library.get_downloaded("quiz", "quiz-1", "student-2") is not None

    metadata.code, metadata.value = 200, quiz_metadata(1, "class_only")
    assert service.check("quiz", "quiz-1", "student-1")["state"] == "synchronized"
    assert library.get_downloaded("quiz", "quiz-1", "student-1") is not None


def test_network_outage_never_infers_revocation(tmp_path):
    library = make_library(tmp_path)
    library.store_download(
        "quiz", "quiz-1", quiz_body(1), name="Quiz", content_version=1
    )
    service = DownloadedContentService(
        library, MetadataStub({"detail": "unavailable"}, code=503), BodyStub(quiz=quiz_body(1))
    )

    assert service.check("quiz", "quiz-1", "student-1")["state"] == "stale"
    cached = library.get_downloaded("quiz", "quiz-1", "student-1")
    assert cached is not None
    assert cached["cache_state"] == "stale"
    assert "503" in cached["last_update_error"]


def test_public_cache_remains_available_after_expired_session(tmp_path):
    library = make_library(tmp_path)
    library.store_download(
        "flashcard", "deck-1",
        {"id": "deck-1", "name": "Deck", "content_version": 1, "cards": []},
        name="Deck", content_version=1,
    )
    service = DownloadedContentService(
        library, MetadataStub({"detail": "expired"}, code=401), BodyStub()
    )

    assert service.check("flashcard", "deck-1", "guest")["state"] == "stale"
    assert library.get_downloaded("flashcard", "deck-1", "guest") is not None
    assert library.get_downloaded("flashcard", "deck-1", "guest")["revoked_accounts"] == {}


def test_restricted_cache_uses_manifest_on_logout_and_401(tmp_path):
    library = make_library(tmp_path)
    library.store_download(
        "flashcard", "deck-1",
        {"id": "deck-1", "name": "Deck", "content_version": 1, "cards": []},
        name="Deck", visibility="class_only",
        allowed_account_ids=["student-1"], content_version=1,
    )
    service = DownloadedContentService(
        library, MetadataStub({"detail": "expired"}, code=401), BodyStub()
    )

    assert service.check("flashcard", "deck-1", "guest")["state"] == "locked"
    assert service.check("flashcard", "deck-1", "student-2")["state"] == "locked"
    assert service.check("flashcard", "deck-1", "student-1")["state"] == "stale"
    manifest = library.list_downloaded("flashcard")[0]["manifest"]
    assert manifest["revoked_accounts"] == {}


def test_learner_quiz_download_is_explicitly_unavailable(tmp_path):
    library = make_library(tmp_path)
    metadata = quiz_metadata(1)
    metadata["offline_download_allowed"] = False
    service = DownloadedContentService(
        library, MetadataStub(metadata),
        BodyStub(quiz=quiz_body(1), on_fetch=lambda: pytest.fail("body must not be fetched")),
    )

    assert service.check("quiz", "quiz-1", "student-1")["state"] == "download_unavailable"
    assert service.update("quiz", "quiz-1", "student-1")["state"] == "download_unavailable"
    assert not library.has_package("quiz", "quiz-1")


def test_editor_all_types_quiz_download_reconstructs_and_is_account_bound(tmp_path):
    library = make_library(tmp_path)
    metadata = quiz_metadata(1)
    metadata["offline_download_allowed"] = True
    service = DownloadedContentService(
        library, MetadataStub(metadata), BodyStub(quiz=all_types_quiz_body(1))
    )

    assert service.update("quiz", "quiz-1", "teacher-1")["state"] == "synchronized"
    cached = library.get_downloaded("quiz", "quiz-1", "teacher-1")
    assert len(Quiz(cached["body"]["questions"]).cards) == 6
    assert library.get_downloaded("quiz", "quiz-1", "guest") is None
    assert library.get_downloaded("quiz", "quiz-1", "student-1") is None


def test_post_commit_backup_cleanup_failure_keeps_success_state(tmp_path, monkeypatch):
    library = make_library(tmp_path)
    library.store_download(
        "quiz", "quiz-1", quiz_body(1), name="Quiz", content_version=1
    )
    target = tmp_path / "cache" / "library" / "quizzes" / "quiz-1"
    backup = target.with_name(".quiz-1.previous")
    real_rmtree = content_library_module.shutil.rmtree

    def fail_backup_cleanup(path, *args, **kwargs):
        if path == backup:
            if kwargs.get("ignore_errors"):
                return None
            raise OSError("simulated open handle")
        return real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(content_library_module.shutil, "rmtree", fail_backup_cleanup)
    service = DownloadedContentService(
        library, MetadataStub(quiz_metadata(2)), BodyStub(quiz=quiz_body(2, "New"))
    )

    assert service.update("quiz", "quiz-1", "teacher-1")["state"] == "synchronized"
    assert library.get_downloaded("quiz", "quiz-1", "teacher-1")["body"]["questions"][0]["question"] == "New"
    assert backup.exists()

    monkeypatch.setattr(content_library_module.shutil, "rmtree", real_rmtree)
    assert library.get_downloaded("quiz", "quiz-1", "teacher-1")["cache_state"] == "synchronized"
    assert not backup.exists()


def test_explicit_banned_lifecycle_locks_owner_cache(tmp_path):
    library = make_library(tmp_path)
    library.store_download(
        "quiz", "quiz-1", quiz_body(1), name="Quiz", visibility="private",
        owner_id="teacher-1", content_version=1,
    )
    banned = {**quiz_metadata(2, "private"), "status": "banned"}
    service = DownloadedContentService(
        library, MetadataStub(banned), BodyStub(quiz=quiz_body(2))
    )

    assert service.check("quiz", "quiz-1", "teacher-1")["state"] == "locked"
    assert library.get_downloaded("quiz", "quiz-1", "teacher-1") is None


def test_authoritative_public_absence_creates_global_tombstone_across_logout(tmp_path):
    library = make_library(tmp_path)
    library.store_download(
        "flashcard", "deck-1",
        {"id": "deck-1", "name": "Deck", "content_version": 1, "cards": []},
        name="Deck", content_version=1,
    )
    service = DownloadedContentService(
        library, MetadataStub({"detail": "not found"}, code=404), BodyStub()
    )

    assert service.check("flashcard", "deck-1", "student-1")["state"] == "locked"
    assert library.get_downloaded("flashcard", "deck-1", "guest") is None
    assert library.get_downloaded("flashcard", "deck-1", "another-account") is None
    assert library.list_downloaded("flashcard")[0]["manifest"]["global_revocation"] == "not_found"


def test_authoritative_success_clears_global_tombstone(tmp_path):
    library = make_library(tmp_path)
    body = {"id": "deck-1", "name": "Deck", "content_version": 1, "cards": []}
    library.store_download("flashcard", "deck-1", body, name="Deck", content_version=1)
    library.mark_globally_revoked("flashcard", "deck-1", "deleted")
    metadata = {
        "id": "deck-1", "kind": "flashcard", "name": "Deck", "content_version": 1,
        "visibility": "public", "owner_id": "teacher-1",
    }
    service = DownloadedContentService(library, MetadataStub(metadata), BodyStub(flashcard=body))

    assert service.check("flashcard", "deck-1", "guest")["state"] == "synchronized"
    assert library.get_downloaded("flashcard", "deck-1", "guest") is not None
    assert library.list_downloaded("flashcard")[0]["manifest"]["global_revocation"] is None


def test_failed_update_preserves_old_package_and_records_retry_state(tmp_path):
    library = make_library(tmp_path)
    library.store_download(
        "quiz", "quiz-1", quiz_body(1), name="Quiz", content_version=1
    )
    path = tmp_path / "cache" / "library" / "quizzes" / "quiz-1" / "content.json"
    old_bytes = path.read_bytes()
    states = []

    def observe_updating():
        states.append(library.get_downloaded("quiz", "quiz-1")["cache_state"])

    service = DownloadedContentService(
        library, MetadataStub(quiz_metadata(2)),
        BodyStub(quiz={"malformed": True}, on_fetch=observe_updating),
    )
    result = service.update("quiz", "quiz-1", "student-1")

    assert states == ["updating"]
    assert result["state"] == "update_failed"
    assert path.read_bytes() == old_bytes
    cached = library.get_downloaded("quiz", "quiz-1")
    assert cached["cache_state"] == "update_failed"
    assert cached["failed_server_version"] == 2
    assert cached["body"]["questions"][0]["question"] == "Old"


def test_successful_retry_replaces_package_and_clears_failure(tmp_path):
    library = make_library(tmp_path)
    library.store_download(
        "quiz", "quiz-1", quiz_body(1), name="Quiz", content_version=1
    )
    service = DownloadedContentService(
        library, MetadataStub(quiz_metadata(2)), BodyStub(quiz={"malformed": True})
    )
    assert service.update("quiz", "quiz-1", "student-1")["state"] == "update_failed"
    assert service.check("quiz", "quiz-1", "student-1")["state"] == "update_failed"
    failed = library.get_downloaded("quiz", "quiz-1")
    assert failed["last_update_error"]
    assert failed["failed_server_version"] == 2

    service.bodies.quiz = quiz_body(2, "New")
    assert service.update("quiz", "quiz-1", "student-1")["state"] == "synchronized"
    cached = library.get_downloaded("quiz", "quiz-1")
    assert cached["content_version"] == 2
    assert cached["body"]["questions"][0]["question"] == "New"
    assert cached["last_update_error"] is None
    assert cached["failed_server_version"] is None


def test_flashcard_download_uses_flashcard_body_contract(tmp_path):
    library = make_library(tmp_path)
    metadata = {
        "id": "deck-1", "kind": "flashcard", "name": "Deck",
        "content_version": 4, "updated_at": None, "visibility": "public",
        "owner_id": "teacher-1",
    }
    body = {
        "id": "deck-1", "name": "Deck", "content_version": 4,
        "cards": [{"id": "c1", "front": "F", "back": "B"}],
    }
    service = DownloadedContentService(
        library, MetadataStub(metadata), BodyStub(flashcard=body)
    )

    assert service.update("flashcard", "deck-1", "student-1")["state"] == "synchronized"
    assert library.get_downloaded("flashcard", "deck-1")["body"] == body
