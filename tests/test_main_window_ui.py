import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from src.ui import main_window as main_window_module


class MainControllerStub:
    def __init__(self):
        self.role = "guest"
        self.name = "Guest"

    def get_theme(self):
        return "light"

    def set_theme(self, _theme):
        pass

    def continue_as_guest(self):
        self.role = "guest"
        self.name = "Guest"

    def get_current_role(self):
        return self.role

    def get_current_user_name(self):
        return self.name

    def can_access_editor(self):
        return self.role in {"teacher", "admin"}

    def get_launcher_size(self):
        return 700, 620

    def set_launcher_size(self, _width, _height):
        pass

    def is_online(self):
        return False

    def get_storage_backend(self):
        return "json"


@pytest.mark.parametrize(
    ("role", "editors", "role_action", "action_kind", "student_actions"),
    [
        ("guest", False, False, None, False),
        ("student", False, False, None, True),
        ("teacher", True, True, "classes", False),
        ("admin", True, True, "moderation", False),
    ],
)
def test_launcher_exposes_only_actions_allowed_for_role(
    role, editors, role_action, action_kind, student_actions, monkeypatch
):
    app = QApplication.instance() or QApplication([])
    controller = MainControllerStub()
    monkeypatch.setattr(main_window_module, "MainController", lambda: controller)
    window = main_window_module.MainLauncher(Path("missing.qss"), Path("missing.qss"))

    controller.role = role
    controller.name = role.title()
    window.update_ui_for_user()

    assert window.quiz_editor_btn.isHidden() is (not editors)
    assert window.flashcard_editor_btn.isHidden() is (not editors)
    assert window.role_action_btn.isHidden() is (not role_action)
    assert window.student_actions_row.isHidden() is (not student_actions)
    if action_kind:
        assert window.role_action_btn.property("role_action") == action_kind
    assert window.login_btn.isHidden() is (role != "guest")
    assert window.logout_btn.isHidden() is (role == "guest")

    window.close()
    app.processEvents()


def test_launcher_connection_indicator_exposes_readiness(monkeypatch):
    app = QApplication.instance() or QApplication([])
    controller = MainControllerStub()
    monkeypatch.setattr(main_window_module, "MainController", lambda: controller)
    window = main_window_module.MainLauncher(Path("missing.qss"), Path("missing.qss"))

    window._apply_connection_status(True)
    assert window.connection_status_label.text() == "● Online"
    assert window.connection_status_label.property("online") is True
    assert "json" in window.connection_status_label.toolTip()

    window._apply_connection_status(False)
    assert window.connection_status_label.text() == "● Offline"
    assert window.connection_status_label.property("online") is False

    window.close()
    app.processEvents()
