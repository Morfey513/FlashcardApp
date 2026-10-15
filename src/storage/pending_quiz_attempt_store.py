"""Durable, explicit-retry records for Test Mode results owed to the API."""

import hashlib
import json
import os
import secrets
from pathlib import Path

from src.config import CACHE_DIR


class PendingQuizAttemptStore:
    def __init__(self, root=None):
        self.root = Path(root) if root is not None else CACHE_DIR / "pending_test_attempts"

    def _path(self, user_id, quiz_id, attempt_id):
        key = json.dumps([str(user_id), str(quiz_id), str(attempt_id)], separators=(",", ":"))
        return self.root / f"{hashlib.sha256(key.encode('utf-8')).hexdigest()}.json"

    def save(self, quiz_path, attempt, operation):
        """Atomically replace the one pending record for this attempt."""
        record = {
            "user_id": str(attempt["user_id"]),
            "quiz_id": str(attempt["quiz_id"]),
            "quiz_path": str(quiz_path),
            "attempt_id": str(attempt["id"]),
            "operation": operation,
            "attempt": dict(attempt),
        }
        target = self._path(record["user_id"], record["quiz_id"], record["attempt_id"])
        self.root.mkdir(parents=True, exist_ok=True)
        temporary = self.root / f".{target.stem}.{secrets.token_hex(8)}.tmp"
        try:
            with temporary.open("w", encoding="utf-8") as stream:
                json.dump(record, stream, indent=4)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
        return record

    def list_for_user(self, user_id):
        if not self.root.exists():
            return []
        records = []
        for path in self.root.glob("*.json"):
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError, TypeError):
                continue
            if isinstance(record, dict) and record.get("user_id") == str(user_id):
                records.append(record)
        return sorted(records, key=lambda row: str(row.get("attempt", {}).get("submitted_at") or ""))

    def delete(self, user_id, quiz_id, attempt_id):
        self._path(user_id, quiz_id, attempt_id).unlink(missing_ok=True)
