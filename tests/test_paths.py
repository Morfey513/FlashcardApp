from pathlib import Path

from src.utils.paths import resolve_stored_path, to_stored_path


def test_project_path_round_trip():
    source = Path.cwd() / "data" / "images" / "example.png"
    stored = to_stored_path(source)
    assert stored == "data/images/example.png"
    assert resolve_stored_path(stored) == source


def test_empty_stored_path_is_none():
    assert resolve_stored_path("") is None


def test_paths_preserve_relative_and_external_absolute_values():
    relative = Path("custom") / "asset.mp3"
    external = (Path.cwd().parent / "external-example.mp3").resolve()

    assert to_stored_path(relative) == "custom/asset.mp3"
    assert to_stored_path(external) == str(external)
    assert resolve_stored_path(external) == external
    assert resolve_stored_path(None) is None
