import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QPushButton

from src.ui import main_window as main_window_module
from src.ui.flashcard_viewer import DeckListRow
from src.ui.quiz_view import QuizListRow
from src.ui.settings_panel import SettingsPanel


def test_quiz_keep_offline_action_emits_from_selector_row():
    app = QApplication.instance() or QApplication([])
    row = QuizListRow(
        {"name": "Remote", "total": 1, "mastered": 0, "can_download": True},
        "0 / 1",
    )
    calls = []
    row.keep_offline.connect(lambda: calls.append(True))
    button = row.findChild(QPushButton, "content_offline_btn")
    button.click()
    assert calls == [True]
    row.close()
    app.processEvents()


def test_downloaded_and_locked_states_are_visible():
    app = QApplication.instance() or QApplication([])
    downloaded = QuizListRow(
        {"name": "Cached", "total": 1, "mastered": 0, "downloaded": True, "can_download": True},
        "0 / 1",
    )
    locked = DeckListRow(
        {"name": "Restricted", "total": 0, "mastered": 0, "locked": True},
        "0 / 0",
    )
    assert any(button.text() == "Downloaded" for button in downloaded.findChildren(QPushButton))
    assert any(button.text() == "Locked" for button in locked.findChildren(QPushButton))
    downloaded.close()
    locked.close()
    app.processEvents()


def test_keep_offline_requires_explicit_remote_capability():
    app = QApplication.instance() or QApplication([])
    local = QuizListRow(
        {"name": "Bundled", "total": 1, "mastered": 0, "can_download": False},
        "0 / 1",
    )
    remote = QuizListRow(
        {"name": "Remote", "total": 1, "mastered": 0, "can_download": True},
        "0 / 1",
    )
    assert not local.findChildren(QPushButton, "content_offline_btn")
    assert remote.findChild(QPushButton, "content_offline_btn") is not None
    local.close()
    remote.close()
    app.processEvents()


def test_settings_exposes_separate_clear_downloaded_data_action():
    app = QApplication.instance() or QApplication([])
    panel = SettingsPanel()
    calls = []
    panel.clear_downloaded_data_requested.connect(lambda: calls.append(True))
    panel.clear_downloaded_data_btn.click()
    assert calls == [True]
    panel.close()
    app.processEvents()


def test_main_window_clear_downloaded_data_uses_library_only(monkeypatch):
    calls = []

    class Library:
        def clear_downloaded_data(self):
            calls.append("clear")
            return 2

    monkeypatch.setattr(main_window_module.QMessageBox, "question", lambda *args, **kwargs: main_window_module.QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(
        "src.storage.repository_factory.create_content_library",
        lambda: Library(),
    )
    assert main_window_module.MainLauncher.clear_downloaded_data(object()) == 2
    assert calls == ["clear"]
