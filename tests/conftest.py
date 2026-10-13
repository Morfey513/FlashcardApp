import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtCore import QEvent
from PyQt6.QtWidgets import QApplication


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
