import json

from src.logic.app_settings import AppSettings


def test_guest_launcher_size_is_saved_independently(tmp_path):
    settings = AppSettings()
    settings.settings_file = tmp_path / "settings.json"
    settings.settings = {"theme": "dark", "language": "en"}

    settings.set_launcher_size(710, 690)

    assert settings.get_launcher_size() == [710, 690]
    saved = json.loads(settings.settings_file.read_text(encoding="utf-8"))
    assert saved == {
        "theme": "dark",
        "language": "en",
        "launcher_size": [710, 690],
    }


def test_guest_subwindow_sizes_are_saved_independently(tmp_path):
    settings = AppSettings()
    settings.settings_file = tmp_path / "settings.json"
    settings.settings = {"theme": "dark", "language": "en"}

    settings.set_window_size("quiz_editor", 840, 640)
    settings.set_window_size("flashcard_editor", 880, 680)

    assert settings.get_window_size("quiz_editor") == [840, 640]
    assert settings.get_window_size("flashcard_editor") == [880, 680]
    assert settings.get_launcher_size() is None
