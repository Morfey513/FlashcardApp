"""Managed server-side media storage with containment and type validation."""

import hashlib
import mimetypes
import os
from pathlib import Path
from uuid import uuid4

from src.config import MANAGED_MEDIA_DIR


class InvalidMedia(ValueError):
    pass


def managed_media_root() -> Path:
    return Path(os.getenv("STUDY_BUDDY_MEDIA_ROOT", str(MANAGED_MEDIA_DIR))).resolve()


def detected_mime(data: bytes) -> str | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        return "audio/wav"
    if data.startswith(b"OggS"):
        return "audio/ogg"
    if data.startswith(b"ID3") or (len(data) >= 2 and data[0] == 0xFF and data[1] & 0xE0 == 0xE0):
        return "audio/mpeg"
    if len(data) >= 12 and data[4:8] == b"ftyp":
        return "audio/mp4"
    return None


def validate_media(data: bytes, filename: str, *, expected_mime: str | None = None) -> str:
    if not data:
        raise InvalidMedia("Media file is empty")
    actual = detected_mime(data)
    declared = mimetypes.guess_type(filename)[0]
    if actual is None or not actual.startswith(("image/", "audio/")):
        raise InvalidMedia("Unsupported or invalid media content")
    if declared and declared.startswith(("image/", "audio/")) and declared != actual:
        # Common aliases are semantically equivalent.
        aliases = {"audio/mp3": "audio/mpeg", "audio/x-wav": "audio/wav"}
        if aliases.get(declared, declared) != aliases.get(actual, actual):
            raise InvalidMedia("Media content does not match its filename")
    if expected_mime and aliases_mime(expected_mime) != aliases_mime(actual):
        raise InvalidMedia("Stored media MIME type does not match its bytes")
    return actual


def aliases_mime(value: str) -> str:
    return {"audio/mp3": "audio/mpeg", "audio/x-wav": "audio/wav"}.get(value, value)


def store_media(
    data: bytes, filename: str, *, media_id: str | None = None,
    root: Path | None = None,
) -> dict:
    supplied = Path(filename)
    safe_name = supplied.name
    if (
        not safe_name or safe_name in {".", ".."} or supplied.is_absolute()
        or len(supplied.parts) != 1 or safe_name != str(filename)
    ):
        raise InvalidMedia("Invalid media filename")
    mime_type = validate_media(data, safe_name)
    identifier = str(media_id or uuid4())
    suffix = Path(safe_name).suffix.casefold()
    root = (root or managed_media_root()).resolve()
    root.mkdir(parents=True, exist_ok=True)
    target = (root / f"{identifier}{suffix}").resolve()
    if not target.is_relative_to(root):
        raise InvalidMedia("Invalid managed-media destination")
    temporary = target.with_suffix(target.suffix + f".{uuid4().hex}.tmp")
    temporary.write_bytes(data)
    os.replace(temporary, target)
    return {
        "media_id": identifier,
        "storage_key": target.name,
        "original_filename": safe_name,
        "mime_type": mime_type,
        "size_bytes": len(data),
        "checksum_sha256": hashlib.sha256(data).hexdigest(),
    }


def resolve_managed_media(storage_key: str, *, root: Path | None = None) -> Path:
    key = Path(str(storage_key))
    if key.is_absolute() or len(key.parts) != 1 or key.name in {".", ".."}:
        raise InvalidMedia("Media is outside the managed storage root")
    root = (root or managed_media_root()).resolve()
    path = (root / key).resolve()
    if not path.is_relative_to(root):
        raise InvalidMedia("Media is outside the managed storage root")
    return path


def read_validated_media(
    storage_key: str, mime_type: str, size_bytes: int, *, root: Path | None = None,
) -> bytes:
    path = resolve_managed_media(storage_key, root=root)
    data = path.read_bytes()
    if len(data) != int(size_bytes):
        raise InvalidMedia("Stored media size does not match its descriptor")
    validate_media(data, path.name, expected_mime=mime_type)
    return data
