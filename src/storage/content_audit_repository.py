"""Append-only JSON audit history for authored quiz and flashcard changes."""

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

from src.config import CONTENT_EDIT_HISTORY_FILENAME

logger = logging.getLogger(__name__)


class ContentAuditRepository:
    """Stores actor-attributed edits beside a content item's JSON file.

    Content ownership and edit attribution are deliberately independent: an
    administrator may edit a teacher's content without becoming its owner.
    """

    @staticmethod
    def append(
        content_file,
        *,
        changed_by,
        role,
        change_summary,
        action="updated",
        changed_fields=None,
    ):
        if changed_by is None or not str(change_summary).strip():
            return False
        history_file = Path(content_file).parent / CONTENT_EDIT_HISTORY_FILENAME
        entries = ContentAuditRepository._read_for_append(history_file)
        if entries is None:
            # An audit trail must fail closed: never replace malformed history
            # with a fresh list and silently discard earlier attribution.
            return False
        entries.append({
            "id": str(uuid.uuid4()),
            "changed_by": str(changed_by),
            "role": str(role or "unknown"),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": str(action),
            "change_summary": str(change_summary).strip(),
            "changed_fields": list(changed_fields or []),
        })
        temporary = history_file.with_suffix(history_file.suffix + ".tmp")
        temporary.write_text(json.dumps(entries, indent=4), encoding="utf-8")
        temporary.replace(history_file)
        return True

    @staticmethod
    def get_history(content_file):
        return ContentAuditRepository._read_file(
            Path(content_file).parent / CONTENT_EDIT_HISTORY_FILENAME
        )

    @staticmethod
    def _read_file(history_file):
        if not history_file.exists():
            return []
        try:
            entries = json.loads(history_file.read_text(encoding="utf-8"))
            return entries if isinstance(entries, list) else []
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            logger.error("Failed to read content edit history %s: %s", history_file, exc)
            return []

    @staticmethod
    def _read_for_append(history_file):
        if not history_file.exists():
            return []
        try:
            entries = json.loads(history_file.read_text(encoding="utf-8"))
            if not isinstance(entries, list):
                raise TypeError("audit history root must be a list")
            return entries
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            logger.error("Refusing to overwrite invalid audit history %s: %s", history_file, exc)
            return None


def summarize_collection_change(kind, old_items, new_items, *, settings_changed=False):
    """Return a concise audit summary and the fields that materially changed."""
    old_items = old_items or []
    new_items = new_items or []
    fields = []
    details = []
    if old_items != new_items:
        field = "questions" if kind == "quiz" else "cards"
        fields.append(field)
        if len(old_items) != len(new_items):
            details.append(f"{field} {len(old_items)} → {len(new_items)}")
        else:
            details.append(f"edited {field}")
    if settings_changed:
        fields.append("test_settings")
        details.append("assessment settings changed")
    if not details:
        return "", []
    label = "quiz" if kind == "quiz" else "flashcard deck"
    return f"Updated {label}: {'; '.join(details)}.", fields
