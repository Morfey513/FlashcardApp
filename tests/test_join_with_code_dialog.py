import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QPushButton

from src.ui import join_with_code_dialog as join_ui


class ControllerStub:
    def __init__(self, result):
        self.result = result
        self.codes = []

    def join_with_code(self, code):
        self.codes.append(code)
        return self.result


def test_join_button_is_available_to_guests_and_invokes_callback():
    app = QApplication.instance() or QApplication([])
    button = QPushButton()
    calls = []

    join_ui.configure_join_with_code_button(button, "guest", lambda: calls.append(True))
    button.click()

    assert button.isEnabled() is True
    assert calls == [True]
    assert "Sign-in is required" in button.toolTip()
    assert app is not None


def test_join_flow_refreshes_and_confirms_only_after_success(monkeypatch):
    app = QApplication.instance() or QApplication([])
    controller = ControllerStub((True, "Enrolled"))
    refreshed = []
    notices = []
    monkeypatch.setattr(join_ui.JoinWithCodeDialog, "get_code", lambda _parent: "MATH-8X2K")
    monkeypatch.setattr(
        join_ui.QMessageBox,
        "information",
        lambda _parent, title, message: notices.append((title, message)),
    )

    join_ui.run_join_with_code_flow(None, controller, lambda: refreshed.append(True))

    assert controller.codes == ["MATH-8X2K"]
    assert refreshed == [True]
    assert notices == [("Enrollment complete", "Enrolled")]
    assert app is not None


def test_join_flow_reports_failure_without_refreshing(monkeypatch):
    app = QApplication.instance() or QApplication([])
    controller = ControllerStub((False, "Invalid or revoked code"))
    refreshed = []
    warnings = []
    monkeypatch.setattr(join_ui.JoinWithCodeDialog, "get_code", lambda _parent: "BAD-CODE")
    monkeypatch.setattr(
        join_ui.QMessageBox,
        "warning",
        lambda _parent, title, message: warnings.append((title, message)),
    )

    join_ui.run_join_with_code_flow(None, controller, lambda: refreshed.append(True))

    assert controller.codes == ["BAD-CODE"]
    assert refreshed == []
    assert warnings == [("Unable to enroll", "Invalid or revoked code")]
    assert app is not None
