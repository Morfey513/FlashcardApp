from types import SimpleNamespace

from PyQt6.QtWidgets import QApplication

from src.ui.flashcard_viewer import FlashcardViewer


class _Recorder:
    def __init__(self, events):
        self.events = events
        self.stop_calls = 0

    def stop(self):
        self.stop_calls += 1
        self.events.append("stop")


class _Stack:
    def __init__(self, events):
        self.events = events

    def setCurrentWidget(self, _widget):
        self.events.append("panel")


def _viewer_harness(events):
    viewer = SimpleNamespace(
        recorded_audio=_Recorder(events),
        stack=_Stack(events),
        deck_selection_panel=object(),
        controller=SimpleNamespace(end_session=lambda: events.append("end_session")),
        refresh_deck_list=lambda: events.append("refresh"),
    )
    viewer._stop_active_playback = lambda: FlashcardViewer._stop_active_playback(viewer)
    return viewer


def test_return_to_deck_selection_stops_playback_before_panel_and_session_transition():
    events = []
    viewer = _viewer_harness(events)

    FlashcardViewer.return_to_deck_selection(viewer)

    assert events == ["stop", "panel", "refresh", "end_session"]


def test_playback_cleanup_is_idempotent_for_repeated_valid_exit_paths():
    events = []
    viewer = _viewer_harness(events)

    FlashcardViewer._stop_active_playback(viewer)
    FlashcardViewer._stop_active_playback(viewer)

    assert viewer.recorded_audio.stop_calls == 2


def test_window_close_stops_playback_before_viewer_close_completes(monkeypatch):
    monkeypatch.setattr(FlashcardViewer, "refresh_deck_list", lambda _self: None)
    controller = SimpleNamespace(user_id="guest", repo=None)
    viewer = FlashcardViewer(controller)
    events = []
    viewer.recorded_audio = _Recorder(events)

    assert viewer.close() is True
    assert events == ["stop"]

    viewer.deleteLater()
    QApplication.instance().processEvents()
