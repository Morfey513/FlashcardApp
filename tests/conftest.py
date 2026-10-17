import os
import sys
import traceback

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtCore import QEvent
from PyQt6.QtWidgets import QApplication


_unhandled_qt_exceptions = []


def _capture_unhandled_qt_exception(exc_type, exc, tb):
    _unhandled_qt_exceptions.append((exc_type, exc, tb))
    traceback.print_exception(exc_type, exc, tb)


if sys.excepthook is sys.__excepthook__:
    sys.excepthook = _capture_unhandled_qt_exception


@pytest.fixture(autouse=True)
def fail_on_unhandled_qt_exception():
    _unhandled_qt_exceptions.clear()
    yield
    if _unhandled_qt_exceptions:
        formatted = "\n".join(
            "".join(traceback.format_exception(exc_type, exc, tb)).rstrip()
            for exc_type, exc, tb in _unhandled_qt_exceptions
        )
        pytest.fail("Unhandled exception in Qt callback:\n" + formatted, pytrace=False)


@pytest.fixture(scope="session", autouse=True)
def qt_application():
    """Own exactly one QApplication for the lifetime of the pytest process."""
    app = QApplication.instance()
    assert app is None, "UI tests must not create QApplication before the shared fixture"
    app = QApplication([])
    try:
        yield app
    finally:
        for widget in list(app.topLevelWidgets()):
            widget.close()
            widget.deleteLater()
        app.processEvents()
        QEventLoop = app  # keep the strong application reference through teardown
        QEventLoop.sendPostedEvents(None, 0)
        app.processEvents()
        app.quit()


@pytest.fixture(autouse=True)
def qt_widget_cleanup(qt_application, fail_on_unhandled_qt_exception):
    """Release test-created top-level widgets before the next test starts.

    Qt keeps deferred-delete events queued until control returns to its event
    loop.  Leaving several test-created windows alive until session teardown
    can make native Qt6 teardown order depend on test collection order.
    """
    yield
    for widget in list(qt_application.topLevelWidgets()):
        widget.close()
        widget.deleteLater()
    qt_application.sendPostedEvents(None, 0)
    qt_application.processEvents()
