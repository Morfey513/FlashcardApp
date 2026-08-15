import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QDialog, QDialogButtonBox, QRadioButton

from src.ui.moderation_dialog import InterruptedAttemptDialog


def test_interrupted_attempt_apply_accepts_selected_resolution():
    app = QApplication.instance() or QApplication([])
    dialog = InterruptedAttemptDialog(
        "student32",
        {
            "started_at": "2026-08-14T19:44:43",
            "last_question": 1,
            "total": 1,
        },
    )

    mark_zero = next(
        radio
        for radio in dialog.findChildren(QRadioButton)
        if radio.property("value") == "mark_zero"
    )
    mark_zero.setChecked(True)
    apply_button = dialog.findChild(QDialogButtonBox).button(
        QDialogButtonBox.StandardButton.Apply
    )
    apply_button.click()

    assert dialog.selected_action() == "mark_zero"
    assert dialog.result() == QDialog.DialogCode.Accepted
    dialog.close()
    assert app is not None
