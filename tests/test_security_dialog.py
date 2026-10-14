"""Focused UI checks for the Security settings surface."""

from pathlib import Path
from types import SimpleNamespace

import pytest
from PyQt6.QtWidgets import QFrame, QLineEdit, QMessageBox, QPushButton

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
    def __init__(self, count=2):
        self.terminated = []
        self.signed_out = 0
        self.count = count

    def list_active_sessions(self):
        sessions = [
            {"id": "current", "created_at": "2026-10-13T17:08:46-04:00", "last_activity_at": "2026-10-13T17:09:10-04:00", "ip_address": "127.0.0.1", "client_label": "Windows", "is_current": True},
            {"id": "other", "created_at": "2026-10-13T17:07:32-04:00", "last_activity_at": None, "ip_address": "127.0.0.1", "client_label": "Linux", "is_current": False},
        ]
        for index in range(2, self.count):
            sessions.append({"id": f"extra-{index}", "created_at": "2026-10-13T17:07:32-04:00", "last_activity_at": None, "ip_address": "127.0.0.1", "client_label": "Windows", "is_current": False})
        return {"last_successful_login_at": "2026-10-13T12:00:00Z", "sessions": sessions[:self.count]}

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


def test_account_settings_stays_compact_after_reopen_and_grows_for_message(qt_application):
    prior_stylesheet = qt_application.styleSheet()
    qt_application.setStyleSheet(Path("styles/style.qss").read_text(encoding="utf-8"))
    try:
        dialog = AccountSettingsDialog(_Controller())
        dialog.show()
        qt_application.processEvents()
        compact_height = dialog.height()
        assert compact_height < 500

        dialog.hide()
        dialog.resize(dialog.width(), 700)  # Simulate a previously saved window size.
        dialog.show()
        qt_application.processEvents()
        assert dialog.height() == compact_height

        dialog.show_message("Name changed", error=False)
        qt_application.processEvents()
        assert dialog.height() > compact_height
        dialog.close()
    finally:
        qt_application.setStyleSheet(prior_stylesheet)


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
    assert dialog.sessions_scroll.maximumHeight() == dialog.max_sessions_height


@pytest.mark.parametrize("count", [1, 2, 3, 4, 6])
def test_sessions_height_grows_through_three_then_scrolls(qt_application, count):
    prior_stylesheet = qt_application.styleSheet()
    qt_application.setStyleSheet(Path("styles/style.qss").read_text(encoding="utf-8"))
    try:
        dialog = SecurityDialog(_Controller(_Sessions(count)))
        dialog.refresh_security()
        dialog.show()
        qt_application.processEvents()
        qt_application.processEvents()
        cards = dialog._session_cards
        assert len(cards) == count
        visible_cards = cards[:min(count, 3)]
        margins = dialog.sessions_layout.contentsMargins()
        natural_height = (
            margins.top() + margins.bottom()
            + sum(card.height() for card in visible_cards)
            + dialog.sessions_layout.spacing() * (len(visible_cards) - 1)
            + 2
        )
        expected = min(
            natural_height,
            dialog.max_sessions_height,
            max(0, dialog.screen().availableGeometry().height() - 32 - dialog._base_dialog_height),
        )
        assert dialog.sessions_scroll.height() == expected
        assert dialog.sessions_scroll.verticalScrollBar().isVisible() is (count >= 4 or expected < natural_height)
        dialog.close()
    finally:
        qt_application.setStyleSheet(prior_stylesheet)


def test_sessions_panel_shrinks_after_other_sessions_end(qt_application):
    repo = _Sessions(6)
    dialog = SecurityDialog(_Controller(repo))
    dialog.refresh_security()
    dialog.show()
    qt_application.processEvents()
    qt_application.processEvents()
    crowded_height = dialog.sessions_scroll.height()
    assert dialog.sessions_scroll.verticalScrollBar().isVisible()

    repo.count = 1
    dialog.refresh_security()
    qt_application.processEvents()
    qt_application.processEvents()
    assert dialog.sessions_scroll.height() < crowded_height
    assert not dialog.sessions_scroll.verticalScrollBar().isVisible()
    dialog.close()


def test_reopening_crowded_security_dialog_keeps_footer_above_taskbar(qt_application):
    prior_stylesheet = qt_application.styleSheet()
    qt_application.setStyleSheet(Path("styles/style.qss").read_text(encoding="utf-8"))
    try:
        dialog = SecurityDialog(_Controller(_Sessions(6)))
        available = dialog.screen().availableGeometry()
        sizes = []
        for opening in range(2):
            if opening:
                dialog.hide()
                # The launcher restores a saved size before reopening.
                dialog.resize(600, 660)
            dialog.refresh_security()
            dialog.show()
            qt_application.processEvents()
            qt_application.processEvents()
            sizes.append((dialog.height(), dialog.sessions_scroll.height()))
            assert dialog.geometry().top() >= available.top() + 16
            assert dialog.geometry().bottom() <= available.bottom() - 16
            assert dialog.sign_out_others_btn.mapToGlobal(
                dialog.sign_out_others_btn.rect().bottomRight()
            ).y() < dialog.geometry().bottom()
            assert dialog.sessions_scroll.verticalScrollBar().isVisible()
        assert sizes[0] == sizes[1]
        dialog.close()
    finally:
        qt_application.setStyleSheet(prior_stylesheet)


def test_security_formats_iso_timestamps_for_display(qt_application):
    dialog = SecurityDialog(_Controller(_Sessions()))
    formatted = dialog._format_timestamp("2020-10-13T17:07:32.883359-04:00")
    assert "2020" in formatted
    assert "T17:07" not in formatted
    assert ".883359" not in formatted
    assert dialog._format_timestamp("invalid") == "—"
    dialog.refresh_security()
    assert "2026-10-13T12:00:00Z" not in dialog.last_login.text()


def test_password_visibility_actions_toggle_each_field(qt_application):
    dialog = SecurityDialog(_Controller(_Sessions()))
    for field in (dialog.current_password, dialog.new_password, dialog.confirm_password):
        assert field.echoMode() == QLineEdit.EchoMode.Password
        field.visibility_action.trigger()
        assert field.echoMode() == QLineEdit.EchoMode.Normal
        field.visibility_action.trigger()
        assert field.echoMode() == QLineEdit.EchoMode.Password


def test_session_cards_keep_terminate_inside_scroll_viewport(qt_application):
    prior_stylesheet = qt_application.styleSheet()
    qt_application.setStyleSheet(Path("styles/style.qss").read_text(encoding="utf-8"))
    try:
        dialog = SecurityDialog(_Controller(_Sessions()))
        dialog.refresh_security()
        dialog.show()
        qt_application.processEvents()
        cards = dialog.sessions_container.findChildren(QFrame, "security_session_card")
        assert len(cards) == 2
        terminate = cards[1].findChild(QPushButton, "security_terminate_btn")
        assert terminate is not None
        assert cards[0].findChild(QPushButton, "security_terminate_btn") is None
        assert terminate.geometry().right() < cards[1].width()
        assert cards[1].geometry().right() <= dialog.sessions_scroll.viewport().width()
        dialog.close()
    finally:
        qt_application.setStyleSheet(prior_stylesheet)


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
