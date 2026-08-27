"""Read-only local library and explicit downloaded-content cache."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path
from urllib.parse import urlparse

from src.config import CACHE_DIR
from src.storage.flashcard_repository import FlashcardRepository
from src.storage.quiz_repository import QuizRepository


class ContentLibrary:
    """Merge bundled repository content with validated, downloaded cache entries."""

    MANIFEST = "manifest.json"
    BODY = "content.json"

    def __init__(self, *, quiz_repository=None, flashcard_repository=None, cache_root=None):
        self.quiz_repository = quiz_repository or QuizRepository()
        self.flashcard_repository = flashcard_repository or FlashcardRepository()
        self.cache_root = Path(cache_root or CACHE_DIR) / "library"

    def list(self, kind: str, user_id="guest") -> list[dict]:
        """Return bundled entries plus downloaded entries accessible to user_id."""
        bundled = self._bundled(kind)
        downloaded = [
            item for item in self._downloaded(kind)
            if self.can_access(item["manifest"], user_id)
        ]
        return bundled + downloaded

    def get_downloaded(self, kind: str, content_id: str, user_id="guest"):
        """Return one accessible downloaded entry, without consulting a server."""
        self._validate_kind(kind)
        entry = self._entry_dir(kind, str(content_id))
        manifest = self._read_valid_manifest(entry, kind)
        if manifest is None or not self.can_access(manifest, user_id):
            return None
        return {
            **manifest,
            "file": str(entry / self.BODY),
            "body": self._read_json(entry / self.BODY),
        }

    def update_state(self, kind: str, content_id: str, remote_version, user_id="guest"):
        cached = self.get_downloaded(kind, content_id, user_id)
        if cached is None:
            return "not_downloaded"
        if remote_version is None or cached.get("content_version") is None:
            return "stale"
        return "update_available" if int(remote_version) > int(cached["content_version"]) else "synchronized"

    def refresh_download(self, kind: str, content_id: str, metadata: dict, body: dict, user_id="guest"):
        cached = self.get_downloaded(kind, content_id, user_id)
        if cached is None:
            return False
        if metadata.get("content_version") != body.get("content_version"):
            raise ValueError("Content metadata and body revisions do not match")
        self.store_download(
            kind, content_id, body, name=metadata["name"],
            visibility=metadata.get("visibility", cached.get("visibility", "public")),
            owner_id=metadata.get("owner_id", cached.get("owner_id")),
            allowed_account_ids=metadata.get("allowed_account_ids", cached.get("allowed_account_ids", [])),
            content_version=metadata.get("content_version"),
            remote_updated_at=metadata.get("updated_at"),
        )
        return True

    def list_downloaded(self, kind: str) -> list[dict]:
        """Return valid cached entries, including entries locked for this session."""
        return [
            {**item, "manifest": item["manifest"]}
            for item in self._downloaded(kind)
        ]

    def repository_for(self, kind: str, user_id="guest", base_repository=None):
        """Return a read-through adapter while preserving the base repository contract."""
        self._validate_kind(kind)
        base = base_repository or (
            self.quiz_repository if kind == "quiz" else self.flashcard_repository
        )
        return _LibraryRepository(self, kind, base, user_id)

    def can_access(self, manifest: dict, user_id="guest") -> bool:
        if manifest.get("source") != "downloaded":
            return manifest.get("source") == "bundled"
        if manifest.get("visibility") == "public":
            return True
        account_id = str(user_id or "guest")
        allowed = {str(value) for value in manifest.get("allowed_account_ids", [])}
        owner_id = manifest.get("owner_id")
        return account_id != "guest" and (
            account_id in allowed or (owner_id is not None and account_id == str(owner_id))
        )

    def store_download(self, kind: str, content_id: str, body: dict, *,
                       name: str, visibility="public", owner_id=None,
                       allowed_account_ids=None, content_version=None,
                       remote_updated_at=None) -> dict:
        """Atomically store a validated JSON body and its access manifest."""
        self._validate_kind(kind)
        if not isinstance(body, dict) or not str(content_id).strip() or not str(name).strip():
            raise ValueError("Downloaded content requires an id, name, and object body")
        if body.get("id") is not None and str(body["id"]) != str(content_id):
            raise ValueError("Downloaded content id does not match its cache key")
        if visibility not in {"public", "class_only", "private"}:
            raise ValueError(f"Unsupported visibility: {visibility!r}")
        content_id = str(content_id)
        target = self._entry_dir(kind, content_id)
        target.parent.mkdir(parents=True, exist_ok=True)
        temp_dir = Path(tempfile.mkdtemp(prefix=f".{content_id}-", dir=target.parent))
        try:
            manifest = {
                "content_id": content_id,
                "kind": kind,
                "name": str(name),
                "source": "downloaded",
                "visibility": visibility,
                "owner_id": str(owner_id) if owner_id is not None else None,
                "allowed_account_ids": [str(value) for value in (allowed_account_ids or [])],
                "content_version": content_version,
                "remote_updated_at": remote_updated_at,
                "media": self._media_metadata(body),
            }
            self._write_json(temp_dir / self.BODY, body)
            self._write_json(temp_dir / self.MANIFEST, manifest)
            if target.exists():
                backup = target.with_name(f".{target.name}.previous")
                if backup.exists():
                    shutil.rmtree(backup)
                os.replace(target, backup)
                try:
                    os.replace(temp_dir, target)
                except Exception:
                    os.replace(backup, target)
                    raise
                shutil.rmtree(backup)
            else:
                os.replace(temp_dir, target)
            return manifest.copy()
        finally:
            if temp_dir.exists():
                shutil.rmtree(temp_dir, ignore_errors=True)

    def clear_downloaded_data(self) -> int:
        """Delete only downloaded cache entries; bundled JSON is never under cache_root."""
        removed = 0
        for kind in ("quiz", "flashcard"):
            directory = self.cache_root / self._kind_folder(kind)
            if not directory.exists():
                continue
            for entry in directory.iterdir():
                manifest = self._read_valid_manifest(entry, kind)
                if manifest and manifest.get("source") == "downloaded":
                    shutil.rmtree(entry)
                    removed += 1
        return removed

    @staticmethod
    def resolve_media(value):
        """Return local media paths only; remote media is deliberately unavailable."""
        if not value or urlparse(str(value)).scheme in {"http", "https"}:
            return None
        path = Path(value)
        return path if path.is_absolute() else None

    def _bundled(self, kind):
        self._validate_kind(kind)
        source = self.quiz_repository if kind == "quiz" else self.flashcard_repository
        rows = source.get_all_quizzes() if kind == "quiz" else source.get_all_decks()
        return [{**dict(row), "kind": kind, "source": "bundled"} for row in rows]

    def _downloaded(self, kind):
        directory = self.cache_root / self._kind_folder(kind)
        if not directory.exists():
            return []
        entries = []
        for entry in sorted(directory.iterdir(), key=lambda item: item.name):
            manifest = self._read_valid_manifest(entry, kind)
            if manifest is None:
                continue
            body = self._read_json(entry / self.BODY)
            entries.append({**manifest, "file": str(entry / self.BODY), "body": body, "manifest": manifest})
        return entries

    def _read_valid_manifest(self, entry, kind):
        if not entry.is_dir():
            return None
        try:
            manifest = self._read_json(entry / self.MANIFEST)
            body = self._read_json(entry / self.BODY)
        except (OSError, json.JSONDecodeError, TypeError):
            return None
        if (
            not isinstance(manifest, dict) or not isinstance(body, dict)
            or manifest.get("source") != "downloaded"
            or manifest.get("kind") != kind
            or str(manifest.get("content_id", "")) != entry.name
            or not str(manifest.get("name", "")).strip()
            or manifest.get("visibility") not in {"public", "class_only", "private"}
            or not isinstance(manifest.get("allowed_account_ids", []), list)
        ):
            return None
        return manifest

    def _entry_dir(self, kind, content_id):
        safe_id = "".join(char if char.isalnum() or char in "_-" else "_" for char in content_id)
        if not safe_id:
            raise ValueError("Content id cannot be empty")
        return self.cache_root / self._kind_folder(kind) / safe_id

    @staticmethod
    def _kind_folder(kind):
        return "quizzes" if kind == "quiz" else "flashcards"

    @staticmethod
    def _validate_kind(kind):
        if kind not in {"quiz", "flashcard"}:
            raise ValueError(f"Unsupported content kind: {kind!r}")

    @staticmethod
    def _read_json(path):
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _write_json(path, value):
        path.write_text(json.dumps(value, indent=2), encoding="utf-8")

    @staticmethod
    def _media_metadata(body):
        return {"local": [], "remote": []}


class _LibraryRepository:
    """Read-through adapter for cached bodies; all writes delegate to the base."""

    def __init__(self, library, kind, base, user_id):
        self.library = library
        self.kind = kind
        self.base = base
        self.user_id = str(user_id or "guest")
        self.supports_offline_download = bool(getattr(base, "supports_offline_download", False))

    def __getattr__(self, name):
        return getattr(self.base, name)

    def _cached(self, value):
        normalized = str(value or "").replace("\\", "/").rstrip("/")
        content_id = normalized.split("/")[-1]
        if content_id == ContentLibrary.BODY:
            content_id = normalized.split("/")[-2]
        for suffix in ("quiz.json", "deck.json"):
            if content_id == suffix:
                content_id = str(value).replace("\\", "/").rstrip("/").split("/")[-2]
        return self.library.get_downloaded(self.kind, content_id, self.user_id)

    def _cached_rows(self):
        rows = []
        for item in self.library.list_downloaded(self.kind):
            if not self.library.can_access(item["manifest"], self.user_id):
                continue
            rows.append({
                "id": item["content_id"], "name": item["name"],
                "file": item["file"], "source": "downloaded",
                "content_version": item["manifest"].get("content_version"),
            })
        return rows

    def get_all_quizzes(self):
        if self.kind != "quiz":
            return self.base.get_all_quizzes()
        rows = list(self.base.get_all_quizzes())
        known = {str(row.get("id") or row.get("file")) for row in rows}
        return rows + [row for row in self._cached_rows() if row["id"] not in known]

    def get_all_decks(self):
        if self.kind != "flashcard":
            return self.base.get_all_decks()
        rows = list(self.base.get_all_decks())
        known = {str(row.get("id") or row.get("file")) for row in rows}
        return rows + [row for row in self._cached_rows() if row["id"] not in known]

    def load_quiz_questions(self, value):
        cached = self._cached(value)
        if cached is not None and self.kind == "quiz":
            return list(cached["body"].get("questions") or [])
        return self.base.load_quiz_questions(value)

    def load_deck_cards(self, value):
        cached = self._cached(value)
        if cached is not None and self.kind == "flashcard":
            return list(cached["body"].get("cards") or [])
        return self.base.load_deck_cards(value)

    def get_content_items(self):
        """Preserve base moderation metadata and append accessible cache metadata."""
        from src.storage.moderation_repository import ModerationRepository

        base_moderation = ModerationRepository(
            quizzes=self.base if self.kind == "quiz" else self.library.quiz_repository,
            flashcards=self.base if self.kind == "flashcard" else self.library.flashcard_repository,
        )
        items = [item for item in base_moderation.get_all_content() if item["kind"] == self.kind]
        for item in self.library.list_downloaded(self.kind):
            manifest = item["manifest"]
            if not self.library.can_access(manifest, self.user_id):
                continue
            items.append({
                "kind": self.kind, "name": manifest["name"], "file": item["file"],
                "path": item["file"], "owner_id": manifest.get("owner_id"),
                "status": "published", "visibility": manifest["visibility"],
                "allowed_user_ids": manifest.get("allowed_account_ids", []),
                "server_authorized": True, "source": "downloaded",
                "test_settings": item["body"].get("test_settings", {}),
            })
        return items
