from pathlib import Path

from src.utils.paths import resolve_stored_path, to_stored_path


def test_project_path_round_trip():
    source = Path.cwd() / "data" / "images" / "example.png"
    stored = to_stored_path(source)
    assert stored == "data/images/example.png"
    assert resolve_stored_path(stored) == source


def test_empty_stored_path_is_none():
    assert resolve_stored_path("") is None
