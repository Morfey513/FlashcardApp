"""Shared helpers for paths stored in project JSON data."""

from pathlib import Path
from urllib.parse import urlparse

from src.config import BASE_DIR


def to_stored_path(path_value: str | Path) -> str:
    """Return a project-relative path when possible, otherwise an absolute one."""
    path = Path(path_value)
    if not path.is_absolute():
        return path.as_posix()

    try:
        return path.relative_to(BASE_DIR).as_posix()
    except ValueError:
        return str(path)


def resolve_stored_path(path_value: str | Path | None) -> Path | None:
    """Resolve a path from JSON to an absolute path, preserving empty values."""
    if not path_value:
        return None

    value = str(path_value)
    if urlparse(value).scheme in {"http", "https"}:
        return None
    path = Path(value)
    return path if path.is_absolute() else BASE_DIR / path
