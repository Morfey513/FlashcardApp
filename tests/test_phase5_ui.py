import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QLabel, QPushButton

from src.ui import main_window as main_window_module
from src.ui.flashcard_viewer import DeckListRow
from src.ui.quiz_view import QuizListRow
from src.ui.quiz_view import QuizViewer
from src.ui.flashcard_viewer import FlashcardViewer
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
        {"name": "Cached", "total": 1, "mastered": 0, "downloaded": True,
         "can_download": True, "offline_state": "synchronized"},
        "0 / 1",
    )
    locked = DeckListRow(
        {"name": "Restricted", "total": 0, "mastered": 0, "locked": True,
         "offline_state": "locked"},
        "0 / 0",
    )
    downloaded_button = downloaded.findChild(QPushButton, "content_offline_btn")
    locked_button = locked.findChild(QPushButton, "content_offline_btn")
    assert downloaded_button.text() == "✓"
    assert downloaded_button.toolTip() == "Synchronized"
    assert locked_button.text() == "📥"
    assert locked_button.toolTip() == "Locked"
    assert downloaded_button.size() == locked_button.size()
    downloaded.close()
    locked.close()
    app.processEvents()


@pytest.mark.parametrize("row_type", [QuizListRow, DeckListRow])
def test_partially_available_media_state_is_visible(row_type):
    app = QApplication.instance() or QApplication([])
    row = row_type(
        {"name": "Media item", "total": 1, "mastered": 0,
         "downloaded": True, "can_download": False,
         "offline_state": "synchronized", "media_state": "partially_available"},
        "0 / 1",
    )
    assert any(label.text() == "Media unavailable" for label in row.findChildren(QLabel))
    row.close()
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


@pytest.mark.parametrize(
    ("row_type", "state", "label", "enabled"),
    [
        (QuizListRow, "update_available", "Update now", True),
        (QuizListRow, "updating", "Updating...", False),
        (QuizListRow, "update_failed", "Update failed — Retry", True),
        (DeckListRow, "stale", "Offline / stale", True),
        (DeckListRow, "locked", "Locked", False),
        (DeckListRow, "available_offline", "Available offline", False),
        (QuizListRow, "download_unavailable", "Offline unavailable", False),
    ],
)
def test_download_lifecycle_states_are_distinct_and_actionable(
    row_type, state, label, enabled,
):
    app = QApplication.instance() or QApplication([])
    row = row_type({
        "name": "Offline item", "total": 1, "mastered": 0,
        "downloaded": state != "locked", "locked": state == "locked",
        "can_download": state != "locked", "offline_state": state,
    }, "0 / 1")
    button = row.findChild(QPushButton, "content_offline_btn")

    assert button.toolTip() == label
    assert button.text() in {"📥", "✓"}
    assert button.isEnabled() is enabled
    row.close()
    app.processEvents()


@pytest.mark.parametrize(
    ("viewer_type", "method_name", "refresh_name", "kind"),
    [
        (QuizViewer, "keep_quiz_offline", "refresh_quiz_list", "quiz"),
        (FlashcardViewer, "keep_deck_offline", "refresh_deck_list", "flashcard"),
    ],
)
def test_update_action_delegates_to_controller_and_refreshes(
    viewer_type, method_name, refresh_name, kind,
):
    calls = []

    class Controller:
        downloaded_content = object()

        def update_downloaded_content(self, content_id):
            calls.append((kind, content_id))
            return {"state": "synchronized"}

    class ViewerStub:
        controller = Controller()

    viewer = ViewerStub()
    setattr(viewer, refresh_name, lambda: calls.append("refresh"))
    result = getattr(viewer_type, method_name)(viewer, {"id": "content-1"})

    assert result is True
    assert calls == [(kind, "content-1"), "refresh"]


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
