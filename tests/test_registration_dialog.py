import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from src.ui.registration_dialog import RegistrationDialog


def test_registration_rejects_mismatch_then_emits_normalized_account_data():
    app = QApplication.instance() or QApplication([])
    dialog = RegistrationDialog()
    submitted = []
    dialog.registration_requested.connect(
        lambda name, login, password: submitted.append((name, login, password))
    )

    dialog.name_input.setText(" Student User ")
    dialog.login_input.setText(" student32 ")
    dialog.password_input.setText("password-a")
    dialog.confirm_input.setText("password-b")
    dialog.submit()
    assert submitted == []
    assert dialog.error_label.isHidden() is False

    dialog.confirm_input.setText("password-a")
    dialog.submit()
    assert submitted == [("Student User", "student32", "password-a")]
    assert dialog.error_label.isHidden() is True

    dialog.clear_passwords()
    assert dialog.password_input.text() == ""
    assert dialog.confirm_input.text() == ""
    dialog.close()
    assert app is not None
