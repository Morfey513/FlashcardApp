"""Local invite-code generation and per-item enrolment management."""

import json
import re
import secrets
from datetime import datetime, timezone

from src.logic.access_control import default_visibility_for_status
from src.storage.moderation_repository import ModerationRepository


class InvitationRepository:
    """Manage codes shared by class-only quizzes and flashcard decks."""

    ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

    def __init__(self, moderation=None):
        self.moderation = moderation or ModerationRepository()

    @staticmethod
    def normalize_code(code):
        return re.sub(r"[^A-Z2-9]", "", str(code).upper())

    def get_invitation(self, relative_path, kind):
        item = self._find_item(relative_path, kind)
        if not item:
            return {}
        data = self._read_data(item)
        return dict(data.get("moderation", {}).get("invite", {}))

    def generate_or_rotate_code(self, relative_path, kind, owner_id):
        """Create a readable unique code; existing enrolments remain valid."""
        item = self._find_item(relative_path, kind)
        if not item or str(item.get("owner_id")) != str(owner_id):
            return False, "Only the content owner can manage its invitation code."
        data = self._read_data(item)
        metadata = self._metadata(data)
        code = self._new_unique_code(item["name"])
        metadata["invite"] = {
            "code": code,
            "created_at": self._now(),
            "rotated_at": self._now() if metadata.get("invite", {}).get("code") else None,
        }
        data["moderation"] = metadata
        self._write_data(item, data)
        return True, code

    def enroll_with_code(self, code, user_id):
        """Enrol a local account in a published class-only item."""
        normalized = self.normalize_code(code)
        if not normalized:
            return False, "Enter an invitation code."
        for item in self.moderation.get_all_content():
            data = self._read_data(item)
            metadata = self._metadata(data)
            invitation = metadata.get("invite", {})
            if self.normalize_code(invitation.get("code", "")) != normalized:
                continue
            if metadata.get("status") != "published" or metadata.get("visibility") != "class_only":
                return False, "This invitation is not currently available."
            enrollment_key = str(user_id)
            enrollments = metadata.setdefault("enrollments", {})
            already_enrolled = enrollment_key in enrollments
            enrollments.setdefault(enrollment_key, {"enrolled_at": self._now()})
            allowed = {str(value) for value in metadata.setdefault("allowed_user_ids", [])}
            allowed.add(enrollment_key)
            metadata["allowed_user_ids"] = sorted(allowed)
            data["moderation"] = metadata
            self._write_data(item, data)
            state = "already enrolled in" if already_enrolled else "enrolled in"
            return True, f"You are {state} {item['name']}."
        return False, "That invitation code was not found."

    def _new_unique_code(self, title):
        prefix = "".join(character for character in title.upper() if character in self.ALPHABET)[:4]
        prefix = prefix or "CLASS"
        existing = {
            self.normalize_code(self._read_data(item).get("moderation", {}).get("invite", {}).get("code", ""))
            for item in self.moderation.get_all_content()
        }
        while True:
            code = f"{prefix}-{''.join(secrets.choice(self.ALPHABET) for _ in range(4))}"
            if self.normalize_code(code) not in existing:
                return code

    def _find_item(self, relative_path, kind):
        return next(
            (
                item for item in self.moderation.get_all_content()
                if item["kind"] == kind and item["file"] == relative_path
            ),
            None,
        )

    @staticmethod
    def _read_data(item):
        return json.loads(item["path"].read_text(encoding="utf-8"))

    @staticmethod
    def _write_data(item, data):
        item["path"].write_text(json.dumps(data, indent=4), encoding="utf-8")

    @staticmethod
    def _now():
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _metadata(data):
        metadata = data.setdefault("moderation", {})
        metadata.setdefault("status", "draft")
        metadata.setdefault("visibility", default_visibility_for_status(metadata["status"]))
        metadata.setdefault("allowed_user_ids", [])
        metadata.setdefault("enrollments", {})
        return metadata
