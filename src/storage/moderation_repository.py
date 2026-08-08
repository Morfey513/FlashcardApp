"""Content lifecycle metadata and append-only per-item moderation history."""

import json
from datetime import datetime, timezone

from src.storage.flashcard_repository import FlashcardRepository
from src.storage.quiz_repository import QuizRepository


class ModerationRepository:
    STATUSES = {"draft", "pending_review", "published", "rejected", "banned"}

    def __init__(self, flashcards=None, quizzes=None):
        self.flashcards = flashcards or FlashcardRepository()
        self.quizzes = quizzes or QuizRepository()

    def get_all_content(self):
        items = []
        for kind, repo, entries, resolver in (
            ("flashcard", self.flashcards, self.flashcards.get_all_decks(), self.flashcards.resolve_path),
            ("quiz", self.quizzes, self.quizzes.get_all_quizzes(), self.quizzes._resolve_path),
        ):
            for entry in entries:
                file = resolver(entry["file"])
                data = json.loads(file.read_text(encoding="utf-8"))
                metadata, changed = self._metadata(data)
                if changed:
                    file.write_text(json.dumps(data, indent=4), encoding="utf-8")
                items.append({"kind": kind, "name": entry["name"], "file": entry["file"], "path": file, **metadata})
        return items

    def update_status(self, item, status, actor_id, note=""):
        if status not in self.STATUSES:
            return False
        data = json.loads(item["path"].read_text(encoding="utf-8"))
        metadata, _ = self._metadata(data)
        metadata.update({"status": status, "reviewed_by": str(actor_id), "reviewed_at": self._now(), "review_note": note})
        data["moderation"] = metadata
        item["path"].write_text(json.dumps(data, indent=4), encoding="utf-8")
        history = item["path"].parent / "moderation_history.json"
        entries = json.loads(history.read_text(encoding="utf-8")) if history.exists() else []
        entries.append({"timestamp": metadata["reviewed_at"], "action": status, "actor_id": str(actor_id), "note": note})
        history.write_text(json.dumps(entries, indent=4), encoding="utf-8")
        return True

    def set_content_status(self, relative_path, kind, status, actor_id, note=""):
        """Set a lifecycle status from an editor without exposing file paths to UI."""
        item = next(
            (
                entry for entry in self.get_all_content()
                if entry["kind"] == kind and entry["file"] == relative_path
            ),
            None,
        )
        return bool(item and self.update_status(item, status, actor_id, note))

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
            if item["visibility"] == "public" or str(user_id) in {
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
            if item["visibility"] == "public" or str(user_id) in {
                str(value) for value in item["allowed_user_ids"]
            }:
                visible.append(item)
        return visible

    @staticmethod
    def get_preview(item, limit=None):
        """Return reviewable quiz questions/cards and their total count.

        The dialog is responsible for presenting each content type.  Keeping
        the original records here lets a moderator inspect choices, answers,
        and attached media instead of only seeing a list of titles.
        """
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
        defaults = {"owner_id": "legacy", "status": "published", "visibility": "public", "allowed_user_ids": [], "reviewed_by": None, "reviewed_at": None, "review_note": ""}
        for key, value in defaults.items():
            if key not in metadata:
                metadata[key] = value
                changed = True
        return metadata, changed

    @staticmethod
    def _now():
        return datetime.now(timezone.utc).isoformat()
