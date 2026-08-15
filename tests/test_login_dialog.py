import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from src.ui.login_dialog import LoginDialog


def test_login_error_can_be_cleared_before_reopening_dialog():
    app = QApplication.instance() or QApplication([])
    dialog = LoginDialog()
    dialog.show_error("Invalid login or password")
    assert dialog.error_label.isHidden() is False

    dialog.clear_error()
    assert dialog.error_label.isHidden() is True
    assert dialog.error_label.text() == ""
    dialog.close()
    assert app is not None


def test_guest_and_signup_links_cannot_become_implicit_enter_actions():
    app = QApplication.instance() or QApplication([])
    dialog = LoginDialog()

    assert dialog.sign_in_btn.autoDefault() is False
    assert dialog.guest_btn.autoDefault() is False
    assert dialog.signup_btn.autoDefault() is False
    dialog.close()
    assert app is not None


def test_login_requires_both_fields_and_emits_credentials_once():
    app = QApplication.instance() or QApplication([])
    dialog = LoginDialog()
    submitted = []
    dialog.login_success.connect(lambda login, password: submitted.append((login, password)))

    dialog.email_input.setText("student")
    dialog.handle_login()
    assert submitted == []
    assert dialog.error_label.isHidden() is False

    dialog.password_input.setText("secret")
    dialog.handle_login()
    assert submitted == [("student", "secret")]
    assert dialog.error_label.isHidden() is True

    dialog.clear_password()
    assert dialog.password_input.text() == ""
    dialog.close()
    assert app is not None
