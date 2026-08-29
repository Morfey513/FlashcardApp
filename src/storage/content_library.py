"""Read-only local library and explicit downloaded-content cache."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import hashlib
import mimetypes
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from src.config import CACHE_DIR
from src.storage.flashcard_repository import FlashcardRepository
from src.storage.quiz_repository import QuizRepository


class ContentLibrary:
    """Merge bundled repository content with validated, downloaded cache entries."""

    MANIFEST = "manifest.json"
    BODY = "content.json"
    MEDIA_DIR = "media"

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
        entry = self._recover_entry(kind, str(content_id))
        manifest = self._read_valid_manifest(entry, kind)
        if manifest is None or not self.can_access(manifest, user_id):
            return None
        return {
            **manifest,
            "file": str(entry / self.BODY),
            "body": self._read_json(entry / self.BODY),
        }

    def has_package(self, kind, content_id):
        """Whether a valid package exists, regardless of current account access."""
        entry = self._recover_entry(kind, str(content_id))
        return self._read_valid_manifest(entry, kind) is not None

    def update_state(self, kind: str, content_id: str, remote_version, user_id="guest"):
        cached = self.get_downloaded(kind, content_id, user_id)
        if cached is None:
            return "not_downloaded"
        if remote_version is None or cached.get("content_version") is None:
            return "stale"
        remote_version, local_version = int(remote_version), int(cached["content_version"])
        if remote_version > local_version:
            return "update_available"
        if remote_version < local_version:
            return "stale"
        return "synchronized"

    def refresh_download(self, kind: str, content_id: str, metadata: dict, body: dict, user_id="guest", media=None):
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
            offline_access=cached.get("offline_access", "content_visibility"),
            quiz_projection=metadata.get("package_projection", cached.get("quiz_projection")),
            media=media,
        )
        self._update_diagnostics(kind, content_id, {
            "cache_state": "synchronized", "last_synchronized_at": self._now(),
            "last_checked_at": self._now(), "last_update_error": None,
        })
        return True

    def record_check(self, kind, content_id, state, *, error=None):
        """Persist non-authoritative refresh diagnostics without touching the body."""
        values = {"cache_state": state, "last_checked_at": self._now()}
        values["last_update_error"] = str(error) if error is not None else None
        if error is None:
            values["failed_server_version"] = None
        self._update_diagnostics(kind, content_id, values)

    def record_update_failure(self, kind, content_id, error, server_version=None):
        self._update_diagnostics(kind, content_id, {
            "cache_state": "update_failed",
            "last_checked_at": self._now(),
            "last_update_error": str(error),
            "failed_server_version": server_version,
        })

    def record_retry_available(self, kind, content_id):
        """Refresh check time while retaining the failure that the user may retry."""
        return self._update_diagnostics(kind, content_id, {
            "cache_state": "update_failed", "last_checked_at": self._now(),
        })

    def record_updating(self, kind, content_id):
        return self._update_diagnostics(kind, content_id, {
            "cache_state": "updating", "last_update_error": None,
        })

    def mark_revoked(self, kind, content_id, user_id, reason="revoked"):
        """Record explicit server revocation for one account, preserving the package."""
        entry = self._entry_dir(kind, str(content_id))
        manifest = self._read_valid_manifest(entry, kind)
        if manifest is None:
            return False
        revoked = dict(manifest.get("revoked_accounts") or {})
        revoked[str(user_id or "guest")] = str(reason)
        self._rewrite_manifest(kind, entry, {"revoked_accounts": revoked})
        return True

    def mark_globally_revoked(self, kind, content_id, reason="revoked"):
        """Record an authoritative content lifecycle removal for every account."""
        entry = self._entry_dir(kind, str(content_id))
        manifest = self._read_valid_manifest(entry, kind)
        if manifest is None:
            return False
        self._rewrite_manifest(kind, entry, {"global_revocation": str(reason)})
        return True

    def clear_global_revocation(self, kind, content_id):
        """Clear a lifecycle tombstone only after an authoritative successful lookup."""
        entry = self._entry_dir(kind, str(content_id))
        manifest = self._read_valid_manifest(entry, kind)
        if manifest is None:
            return False
        if manifest.get("global_revocation") is None:
            return True
        self._rewrite_manifest(kind, entry, {"global_revocation": None})
        return True

    def clear_revocation(self, kind, content_id, user_id):
        entry = self._entry_dir(kind, str(content_id))
        manifest = self._read_valid_manifest(entry, kind)
        if manifest is None:
            return False
        revoked = dict(manifest.get("revoked_accounts") or {})
        revoked.pop(str(user_id or "guest"), None)
        self._rewrite_manifest(kind, entry, {"revoked_accounts": revoked})
        return True

    def authorize_account(self, kind, content_id, user_id):
        """Persist an explicit successful restricted-access check for one account."""
        account_id = str(user_id or "guest")
        entry = self._entry_dir(kind, str(content_id))
        manifest = self._read_valid_manifest(entry, kind)
        if manifest is None or account_id == "guest":
            return False
        allowed = {str(value) for value in manifest.get("allowed_account_ids", [])}
        allowed.add(account_id)
        revoked = dict(manifest.get("revoked_accounts") or {})
        revoked.pop(account_id, None)
        self._rewrite_manifest(kind, entry, {
            "allowed_account_ids": sorted(allowed), "revoked_accounts": revoked,
        })
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
        # This is content lifecycle state, not account authorization.  It must
        # survive logout and prevent a public package from reappearing to a
        # guest after an authoritative banned/deleted/absent response.
        if manifest.get("global_revocation"):
            return False
        account_id = str(user_id or "guest")
        if account_id in {str(value) for value in (manifest.get("revoked_accounts") or {})}:
            return False
        allowed = {str(value) for value in manifest.get("allowed_account_ids", [])}
        owner_id = manifest.get("owner_id")
        if (
            manifest.get("visibility") == "public"
            and manifest.get("offline_access") != "downloader_only"
        ):
            return True
        return account_id != "guest" and (
            account_id in allowed or (owner_id is not None and account_id == str(owner_id))
        )

    def store_download(self, kind: str, content_id: str, body: dict, *,
                       name: str, visibility="public", owner_id=None,
                       allowed_account_ids=None, content_version=None,
                       remote_updated_at=None, offline_access="content_visibility",
                       quiz_projection=None, media=None) -> dict:
        """Atomically store a validated JSON body and its access manifest."""
        self._validate_kind(kind)
        if not isinstance(body, dict) or not str(content_id).strip() or not str(name).strip():
            raise ValueError("Downloaded content requires an id, name, and object body")
        if body.get("id") is not None and str(body["id"]) != str(content_id):
            raise ValueError("Downloaded content id does not match its cache key")
        if not self._valid_body(kind, body):
            raise ValueError("Downloaded content body is incomplete or unusable offline")
        if visibility not in {"public", "class_only", "private"}:
            raise ValueError(f"Unsupported visibility: {visibility!r}")
        if offline_access not in {"content_visibility", "downloader_only"}:
            raise ValueError(f"Unsupported offline access policy: {offline_access!r}")
        content_id = str(content_id)
        target = self._recover_entry(kind, content_id)
        target.parent.mkdir(parents=True, exist_ok=True)
        temp_dir = Path(tempfile.mkdtemp(prefix=f".{content_id}-", dir=target.parent))
        try:
            validated_media, media_state, media_bytes = self._prepare_media(media or [])
            self._validate_media_references(kind, body, validated_media)
            manifest = {
                "content_id": content_id,
                "kind": kind,
                "name": str(name),
                "source": "downloaded",
                "visibility": visibility,
                "owner_id": str(owner_id) if owner_id is not None else None,
                "allowed_account_ids": [str(value) for value in (allowed_account_ids or [])],
                "offline_access": offline_access,
                "quiz_projection": quiz_projection,
                "package_projection": quiz_projection or ("study" if kind == "flashcard" else None),
                "content_version": content_version,
                "remote_updated_at": remote_updated_at,
                "media": validated_media,
                "media_state": media_state,
                "downloaded_bytes": len(json.dumps(body, ensure_ascii=False).encode("utf-8")) + media_bytes,
                "cache_state": "available_offline" if content_version is None else "synchronized",
                "last_checked_at": self._now(),
                "last_synchronized_at": self._now() if content_version is not None else None,
                "last_update_error": None,
                "failed_server_version": None,
                "revoked_accounts": {},
                "global_revocation": None,
            }
            old_manifest = self._read_valid_manifest(target, kind)
            if old_manifest:
                for key in ("revoked_accounts", "global_revocation"):
                    manifest[key] = old_manifest.get(key, manifest[key])
            self._write_json(temp_dir / self.BODY, body)
            self._write_media(temp_dir, validated_media)
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
                try:
                    shutil.rmtree(backup)
                except OSError:
                    # The package is committed once staging becomes current.
                    # Windows may temporarily retain a handle to the backup;
                    # discovery will retry this cleanup later.
                    pass
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
            self._downloaded(kind)  # Recover an interrupted swap before removal.
            for entry in directory.iterdir():
                manifest = self._read_valid_manifest(entry, kind)
                if manifest and manifest.get("source") == "downloaded":
                    shutil.rmtree(entry)
                    removed += 1
        return removed

    def remove_download(self, kind: str, content_id: str) -> bool:
        """Remove one complete downloaded package (never bundled content)."""
        entry = self._recover_entry(kind, str(content_id))
        manifest = self._read_valid_manifest(entry, kind)
        if manifest is None or manifest.get("source") != "downloaded":
            return False
        shutil.rmtree(entry)
        return True

    def downloaded_size(self, kind=None) -> int:
        kinds = (kind,) if kind else ("quiz", "flashcard")
        total = 0
        for current_kind in kinds:
            for item in self._downloaded(current_kind):
                total += int(item["manifest"].get("downloaded_bytes") or 0)
        return total

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
        for candidate in list(directory.iterdir()):
            if candidate.name.startswith(".") and candidate.name.endswith(".previous"):
                self._recover_entry(kind, candidate.name[1:-len(".previous")])
        entries = []
        for entry in sorted(directory.iterdir(), key=lambda item: item.name):
            manifest = self._read_valid_manifest(entry, kind)
            if manifest is None:
                continue
            body = self._read_json(entry / self.BODY)
            entries.append({**manifest, "file": str(entry / self.BODY), "body": body, "manifest": manifest})
        return entries

    def _read_valid_manifest(self, entry, kind, expected_content_id=None):
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
            or str(manifest.get("content_id", "")) != str(
                expected_content_id if expected_content_id is not None else entry.name
            )
            or str(body.get("id", "")) != str(manifest.get("content_id", ""))
            or (
                manifest.get("content_version") is not None
                and body.get("content_version") != manifest.get("content_version")
            )
            or not str(manifest.get("name", "")).strip()
            or manifest.get("visibility") not in {"public", "class_only", "private"}
            or not isinstance(manifest.get("allowed_account_ids", []), list)
            or manifest.get("offline_access", "content_visibility") not in {
                "content_visibility", "downloader_only"
            }
            or not self._valid_body(kind, body)
        ):
            return None
        media_valid, media_partial = self._valid_media(entry, manifest.get("media", []))
        if not media_valid:
            return None
        if media_partial:
            manifest["media_state"] = "partially_available"
        return manifest

    def _valid_media(self, entry, descriptors):
        # Phase 5 manifests used a placeholder mapping; preserve them as legacy.
        if isinstance(descriptors, dict):
            return True, False
        if not isinstance(descriptors, list):
            return False, False
        media_root = (entry / self.MEDIA_DIR).resolve()
        partial = False
        for descriptor in descriptors:
            if not isinstance(descriptor, dict) or not str(descriptor.get("media_id", "")).strip():
                return False, False
            if descriptor.get("state") != "available":
                if descriptor.get("required", False):
                    return False, False
                continue
            relative = descriptor.get("local_relative_path")
            if not isinstance(relative, str):
                return False, False
            target = (entry / relative).resolve()
            valid = media_root in target.parents and target.is_file()
            if valid:
                try:
                    payload = target.read_bytes()
                    valid = (
                        len(payload) == int(descriptor.get("size_bytes", descriptor.get("size")))
                        and hashlib.sha256(payload).hexdigest().lower()
                        == str(descriptor.get("checksum_sha256", descriptor.get("checksum"))).lower()
                    )
                except (OSError, TypeError, ValueError):
                    valid = False
            if valid:
                continue
            if descriptor.get("required", False):
                return False, False
            # Do not expose a broken local path; the returned manifest drives
            # the read adapter and presents this as a placeholder instead.
            descriptor["state"] = "unavailable"
            partial = True
        return True, partial

    def _recover_entry(self, kind, content_id):
        """Restore the previous valid package after an interrupted directory swap."""
        target = self._entry_dir(kind, content_id)
        backup = target.with_name(f".{target.name}.previous")
        if self._read_valid_manifest(target, kind) is not None:
            if backup.exists():
                shutil.rmtree(backup, ignore_errors=True)
            return target
        if not backup.exists():
            return target
        if self._read_valid_manifest(backup, kind, content_id) is None:
            return target
        if target.exists():
            invalid = Path(tempfile.mkdtemp(
                prefix=f".{target.name}-invalid-", dir=target.parent
            ))
            invalid.rmdir()
            os.replace(target, invalid)
            try:
                os.replace(backup, target)
            except Exception:
                os.replace(invalid, target)
                raise
        else:
            os.replace(backup, target)
        return target

    def _update_diagnostics(self, kind, content_id, values):
        entry = self._recover_entry(kind, str(content_id))
        manifest = self._read_valid_manifest(entry, kind)
        if manifest is None:
            return False
        self._rewrite_manifest(kind, entry, values)
        return True

    def _rewrite_manifest(self, kind, entry, values):
        manifest = self._read_valid_manifest(entry, kind)
        if manifest is None:
            return
        manifest.update(values)
        temp = entry / ".manifest.tmp"
        self._write_json(temp, manifest)
        os.replace(temp, entry / self.MANIFEST)

    @staticmethod
    def _now():
        return datetime.now(timezone.utc).isoformat()

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

    def _prepare_media(self, media):
        """Validate supplied descriptor/bytes pairs without ever trusting a path."""
        descriptors, total, partial = [], 0, False
        for item in media:
            if not isinstance(item, dict):
                raise ValueError("Invalid media package entry")
            descriptor = dict(item.get("descriptor") or item)
            media_id = str(descriptor.get("media_id") or descriptor.get("id") or "").strip()
            if not media_id or any(char in media_id for char in "/\\"):
                raise ValueError("Invalid media id")
            if not str(descriptor.get("item_id", "")).strip() or not str(
                descriptor.get("attachment_role") or descriptor.get("role") or ""
            ).strip():
                raise ValueError("Media descriptor is missing item association")
            required = bool(descriptor.get("required", False))
            payload = item.get("bytes")
            if payload is None:
                # Optional failed media does not invalidate a useful text package.
                if required:
                    raise ValueError("Required media was not downloaded")
                partial = True
                descriptor["state"] = "unavailable"
                descriptor["media_id"] = media_id
                descriptors.append(descriptor)
                continue
            if not isinstance(payload, (bytes, bytearray)):
                raise ValueError("Media payload must be bytes")
            expected_size = descriptor.get("size_bytes", descriptor.get("size"))
            checksum = descriptor.get("checksum_sha256", descriptor.get("checksum"))
            mime_type = descriptor.get("mime_type")
            if expected_size is None or checksum is None or not mime_type:
                raise ValueError("Media descriptor is missing validation metadata")
            if len(payload) != int(expected_size):
                raise ValueError("Media size does not match descriptor")
            if hashlib.sha256(payload).hexdigest().lower() != str(checksum).lower():
                raise ValueError("Media checksum does not match descriptor")
            extension = mimetypes.guess_extension(str(mime_type).split(";", 1)[0]) or ""
            filename = f"{media_id}{extension}"
            descriptor.update({"media_id": media_id, "filename": filename, "state": "available"})
            descriptor["local_relative_path"] = f"{self.MEDIA_DIR}/{filename}"
            descriptor["_bytes"] = bytes(payload)
            descriptors.append(descriptor)
            total += len(payload)
        return descriptors, ("partially_available" if partial else "complete"), total

    def _write_media(self, directory, descriptors):
        available = [item for item in descriptors if item.get("state") == "available"]
        if not available:
            return
        media_dir = directory / self.MEDIA_DIR
        media_dir.mkdir()
        for descriptor in available:
            payload = descriptor.pop("_bytes", None)
            if payload is None:
                raise ValueError("Validated media payload was lost")
            target = (media_dir / descriptor["filename"]).resolve()
            if target.parent != media_dir.resolve():
                raise ValueError("Unsafe media cache path")
            target.write_bytes(payload)

    @staticmethod
    def _validate_media_references(kind, body, descriptors):
        if not descriptors:
            return
        rows = body.get("questions" if kind == "quiz" else "cards") or []
        known = {
            (str(item.get("media_id")), str(item.get("item_id")), str(item.get("attachment_role") or item.get("role")))
            for item in descriptors
        }
        for row in rows:
            if not isinstance(row, dict):
                continue
            item_id = str(row.get("id", ""))
            for reference in row.get("media") or []:
                if not isinstance(reference, dict):
                    raise ValueError("Media reference is malformed")
                key = (str(reference.get("media_id", "")), item_id, str(reference.get("role", "")))
                if key not in known:
                    raise ValueError("Media reference does not match package descriptor")

    @staticmethod
    def _valid_body(kind, body):
        if kind != "quiz":
            return isinstance(body.get("cards"), list)
        questions = body.get("questions")
        if not isinstance(questions, list):
            return False
        for question in questions:
            if not isinstance(question, dict):
                return False
            question_type = question.get("type", "short_answer")
            if not str(question.get("id", "")).strip() or not str(
                question.get("question", "")
            ).strip():
                return False
            if question_type == "matching":
                pairs = question.get("pairs")
                if not isinstance(pairs, list) or any(
                    not isinstance(pair, dict)
                    or pair.get("prompt") is None
                    or pair.get("answer") is None
                    for pair in pairs
                ):
                    return False
            elif question_type in {"multiple_choice", "ordering"}:
                if not isinstance(question.get("answer"), list):
                    return False
            elif question_type in {
                "short_answer", "single_choice", "true_false", "open", "text"
            }:
                if "answer" not in question or question.get("answer") is None:
                    return False
            else:
                return False
        return True


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
        # An explicit bundled repository path must continue to resolve through
        # that repository even when an offline package happens to share its ID.
        # Downloaded rows use content.json (or a direct content ID).
        if normalized.endswith(("/quiz.json", "/deck.json")):
            return None
        content_id = normalized.split("/")[-1]
        if content_id == ContentLibrary.BODY:
            content_id = normalized.split("/")[-2]
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
                "package_projection": (
                    item["manifest"].get("package_projection")
                    or item["manifest"].get("quiz_projection")
                ),
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
            return self._with_cached_media(cached, "questions")
        return self.base.load_quiz_questions(value)

    def load_deck_cards(self, value):
        cached = self._cached(value)
        if cached is not None and self.kind == "flashcard":
            return self._with_cached_media(cached, "cards")
        return self.base.load_deck_cards(value)

    def _with_cached_media(self, cached, field):
        """Overlay absolute cache paths onto a copy; content.json stays portable."""
        rows = deepcopy(cached["body"].get(field) or [])
        descriptors = cached.get("media") or {}
        if not isinstance(descriptors, list):
            return rows
        entry = Path(cached["file"]).parent
        media = {
            str(item.get("media_id")): item for item in descriptors
            if item.get("state") == "available" and item.get("local_relative_path")
        }
        for row in rows:
            if not isinstance(row, dict):
                continue
            for reference in row.get("media") or []:
                if not isinstance(reference, dict):
                    continue
                descriptor = media.get(str(reference.get("media_id")))
                if not descriptor:
                    continue
                local = str((entry / descriptor["local_relative_path"]).resolve())
                role = str(reference.get("role") or descriptor.get("attachment_role") or "")
                self._apply_media_path(row, role, local)
        return rows

    @staticmethod
    def _apply_media_path(row, role, local):
        normalized = role.lower()
        if "image" in normalized:
            row["image_path"] = local
            row["image"] = local
            return
        if "audio" not in normalized:
            return
        if normalized in {"audio", "audio_front", "front_audio"}:
            row["audio"] = local
            row["audio_front"] = local
        elif "back" in normalized:
            row["audio_back"] = local
        elif "hint" in normalized:
            row["audio_hint"] = local
        elif "description" in normalized:
            row["audio_description"] = local

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
