import sys
from types import SimpleNamespace

from src import main as app_main


def test_exception_hook_logs_traceback_and_shows_nonfatal_message(monkeypatch, qt_application):
    logged = []
    shown = []

    def record_error(message, *, exc_info):
        logged.append((message, exc_info))

    monkeypatch.setattr(app_main.logger, "error", record_error)
    monkeypatch.setattr(
        app_main,
        "QMessageBox",
        SimpleNamespace(warning=lambda *args: shown.append(args)),
    )
    monkeypatch.setattr(sys, "excepthook", sys.__excepthook__)
    app_main.install_exception_hook()
    assert sys.excepthook is app_main.handle_unhandled_exception

    try:
        raise ValueError("callback failed")
    except ValueError:
        exc_type, exc, tb = sys.exc_info()

    sys.excepthook(exc_type, exc, tb)

    assert logged == [("Unhandled exception in Qt callback", (exc_type, exc, tb))]
    assert len(shown) == 1
    assert shown[0][1:] == (
        "Unexpected error",
        "An unexpected error occurred. Details were saved to the application log.",
    )
    assert app_main._showing_unhandled_error is False
