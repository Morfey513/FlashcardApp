"""Content lifecycle metadata and append-only per-item moderation history."""

import json
from datetime import datetime, timezone

from src.storage.flashcard_repository import FlashcardRepository
from src.storage.quiz_repository import QuizRepository
from src.logic.access_control import (
    CONTENT_STATUSES,
    VISIBILITIES,
    default_visibility_for_status,
    is_content_status,
    is_visibility,
    can_moderate_content,
    can_edit_content,
)


class ModerationRepository:
    STATUSES = set(CONTENT_STATUSES)
    VISIBILITIES = set(VISIBILITIES)

    def __init__(self, flashcards=None, quizzes=None):
        self.flashcards = flashcards or FlashcardRepository()
        self.quizzes = quizzes or QuizRepository()

    def get_all_content(self):
        items = []
        for kind, repo, entries, resolver in (
            ("flashcard", self.flashcards, self.flashcards.get_all_decks(), self.flashcards.resolve_path),
            ("quiz", self.quizzes, self.quizzes.get_all_quizzes(), self.quizzes._resolve_path),
        ):
            remote_loader = getattr(repo, "get_content_items", None)
            if callable(remote_loader):
                items.extend(remote_loader())
                continue
            for entry in entries:
                file = resolver(entry["file"])
                data = json.loads(file.read_text(encoding="utf-8"))
                metadata, changed = self._metadata(data)
                if changed:
                    file.write_text(json.dumps(data, indent=4), encoding="utf-8")
                item = {"kind": kind, "name": entry["name"], "file": entry["file"], "path": file, **metadata}
                if kind == "quiz":
                    from src.logic.test_settings import normalize_test_settings
                    item["test_settings"] = normalize_test_settings(data.get("test_settings"))
                items.append(item)
        return items

    def update_status(
        self, item, status, actor_id, note="", visibility=None, *, actor_role=None
    ):
        owns_content = str(item.get("owner_id")) == str(actor_id)
        may_submit_own_work = (
            can_edit_content(actor_role, owns_content)
            and actor_role == "teacher"
            and status in {"draft", "pending_review"}
        )
        if not can_moderate_content(actor_role) and not may_submit_own_work:
            return False
        if not is_content_status(status):
            return False
        if visibility is not None and not is_visibility(visibility):
            return False
        repository = self.quizzes if item["kind"] == "quiz" else self.flashcards
        remote_update = getattr(repository, "update_moderation", None)
        if callable(remote_update):
            return bool(remote_update(item, status, visibility, note))
        data = json.loads(item["path"].read_text(encoding="utf-8"))
        metadata, _ = self._metadata(data)
        if visibility is not None:
            metadata["visibility"] = visibility
        metadata.update({"status": status, "reviewed_by": str(actor_id), "reviewed_at": self._now(), "review_note": note})
        data["moderation"] = metadata
        item["path"].write_text(json.dumps(data, indent=4), encoding="utf-8")
        history = item["path"].parent / "moderation_history.json"
        entries = json.loads(history.read_text(encoding="utf-8")) if history.exists() else []
        entries.append({"timestamp": metadata["reviewed_at"], "action": status, "actor_id": str(actor_id), "note": note})
        history.write_text(json.dumps(entries, indent=4), encoding="utf-8")
        return True

    def set_content_status(
        self, relative_path, kind, status, actor_id, note="", visibility=None,
        *, actor_role=None,
    ):
        """Set a lifecycle status from an editor without exposing file paths to UI."""
        item = next(
            (
                entry for entry in self.get_all_content()
                if entry["kind"] == kind and entry["file"] == relative_path
            ),
            None,
        )
        return bool(item and self.update_status(
            item, status, actor_id, note, visibility, actor_role=actor_role
        ))

    def get_content_for_user(self, user_id, role):
        """Return only content that may be opened in a study session.

        Moderation data remains visible in the admin dashboard, but drafts,
        rejected submissions, and banned content never leak into a learner's
        deck or quiz picker.  Owners may preview their own non-banned work.
        """
        visible = []
        for item in self.get_all_content():
            if role == "admin":
                visible.append(item)
                continue
            if item["status"] == "banned":
                continue
            if str(item["owner_id"]) == str(user_id):
                visible.append(item)
                continue
            if item["status"] != "published":
                continue
            if item.get("server_authorized") or item["visibility"] == "public" or str(user_id) in {
                str(value) for value in item["allowed_user_ids"]
            }:
                visible.append(item)
        return visible

    def get_content_for_selector(self, user_id, role):
        """Return content for a learner's picker, including the owner's locked work.

        Draft, rejected, and banned items are private to their creator in the
        picker.  Moderators review other authors' content in the moderation
        window instead of seeing it in their personal study list.  A banned
        item is never studyable, but its owner can see its moderation state
        and reason in order to understand the action.
        """
        visible = []
        for item in self.get_all_content():
            if str(item["owner_id"]) == str(user_id):
                visible.append(item)
                continue
            if item["status"] != "published":
                continue
            if item.get("server_authorized") or item["visibility"] == "public" or str(user_id) in {
                str(value) for value in item["allowed_user_ids"]
            }:
                visible.append(item)
        return visible

    def get_preview(self, item, limit=None):
        """Return reviewable quiz questions/cards and their total count.

        The dialog is responsible for presenting each content type.  Keeping
        the original records here lets a moderator inspect choices, answers,
        and attached media instead of only seeing a list of titles.
        """
        repository = self.quizzes if item["kind"] == "quiz" else self.flashcards
        remote_preview = getattr(repository, "get_preview", None)
        if callable(remote_preview):
            return remote_preview(item, limit)
        try:
            data = json.loads(item["path"].read_text(encoding="utf-8"))
            entries = data.get("questions", []) if item["kind"] == "quiz" else data.get("cards", [])
            return entries if limit is None else entries[:limit], len(entries)
        except (OSError, json.JSONDecodeError, TypeError):
            return [], 0

    @staticmethod
    def _metadata(data):
        metadata = data.setdefault("moderation", {})
        changed = False
        defaults = {
            "owner_id": "legacy",
            "status": "published",
            "allowed_user_ids": [],
            "reviewed_by": None,
            "reviewed_at": None,
            "review_note": "",
        }
        for key, value in defaults.items():
            if key not in metadata:
                metadata[key] = value
                changed = True
        if "visibility" not in metadata:
            metadata["visibility"] = default_visibility_for_status(metadata["status"])
            changed = True
        return metadata, changed

    @staticmethod
    def _now():
        return datetime.now(timezone.utc).isoformat()
