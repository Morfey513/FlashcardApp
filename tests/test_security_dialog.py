"""Focused UI checks for the Security settings surface."""

from types import SimpleNamespace

from PyQt6.QtWidgets import QMessageBox

from src.ui.account_settings_dialog import AccountSettingsDialog
from src.ui.security_dialog import SecurityDialog
from src.ui.settings_panel import SettingsPanel


class _Controller:
    def __init__(self, repo=None):
        self.session = SimpleNamespace(
            current_user={"id": "user-1", "name": "Alice", "login": "alice", "role": "student"},
            is_authenticated=lambda: True,
        )
        self.user_repo = repo or SimpleNamespace()
        self.password_calls = []

    def change_password(self, current, new):
        self.password_calls.append((current, new))
        return True, "Password changed"

    def update_display_name(self, name):
        return True


class _Sessions:
    def __init__(self):
        self.terminated = []
        self.signed_out = 0

    def list_active_sessions(self):
        return {"last_successful_login_at": "2026-10-13T12:00:00Z", "sessions": [
            {"id": "current", "created_at": "today", "last_activity_at": "now", "ip_address": "127.0.0.1", "client_label": "Windows", "is_current": True},
            {"id": "other", "created_at": "yesterday", "last_activity_at": "then", "ip_address": "127.0.0.1", "client_label": "Linux", "is_current": False},
        ]}

    def terminate_session(self, session_id):
        self.terminated.append(session_id)
        return True

    def sign_out_other_sessions(self):
        self.signed_out += 1
        return True


def test_account_settings_has_no_password_controls(qt_application):
    dialog = AccountSettingsDialog(_Controller())
    assert not hasattr(dialog, "current_password")
    assert not hasattr(dialog, "new_password")
    assert not hasattr(dialog, "confirm_password")
    assert not hasattr(dialog, "change_password_btn")


def test_security_password_form_delegates_to_controller(qt_application):
    controller = _Controller(_Sessions())
    dialog = SecurityDialog(controller)
    dialog.current_password.setText("old")
    dialog.new_password.setText("new-password")
    dialog.confirm_password.setText("new-password")
    dialog.save_password()
    assert controller.password_calls == [("old", "new-password")]


def test_active_sessions_are_in_bounded_scroll_area(qt_application):
    dialog = SecurityDialog(_Controller(_Sessions()))
    dialog.refresh_security()
    assert dialog.sessions_scroll.widget() is dialog.sessions_container
    assert dialog.sessions_scroll.maximumHeight() == 220


def test_settings_security_button_only_visible_when_authenticated(qt_application):
    panel = SettingsPanel()
    panel.set_authenticated(False)
    assert panel.security_btn.isHidden()
    panel.set_authenticated(True)
    assert not panel.security_btn.isHidden()


def test_terminate_confirmation_default_no_blocks_and_yes_permits(qt_application, monkeypatch):
    repo = _Sessions()
    dialog = SecurityDialog(_Controller(repo))
    answers = iter([QMessageBox.StandardButton.No, QMessageBox.StandardButton.Yes])
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *args, **kwargs: next(answers)))
    dialog.terminate_session("other")
    assert repo.terminated == []
    dialog.terminate_session("other")
    assert repo.terminated == ["other"]


def test_sign_out_others_confirmation_default_no_blocks_and_yes_permits(qt_application, monkeypatch):
    repo = _Sessions()
    dialog = SecurityDialog(_Controller(repo))
    answers = iter([QMessageBox.StandardButton.No, QMessageBox.StandardButton.Yes])
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *args, **kwargs: next(answers)))
    dialog.sign_out_others()
    assert repo.signed_out == 0
    dialog.sign_out_others()
    assert repo.signed_out == 1
