"""Reusable UI flow for joining class-only learning content."""

from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)


class JoinWithCodeDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Enroll in Class / Quiz")
        self.setModal(True)
        self.setMinimumWidth(390)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(14)
        title = QLabel("Enroll in Class / Quiz")
        title.setObjectName("title")
        layout.addWidget(title)
        layout.addWidget(QLabel("Enter invitation code:"))
        self.code_input = QLineEdit()
        self.code_input.setPlaceholderText("MATH-8X2K")
        self.code_input.setMaxLength(16)
        self.code_input.returnPressed.connect(self.accept)
        layout.addWidget(self.code_input)
        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        enroll = QPushButton("Enroll Now")
        enroll.setObjectName("publish_btn")
        enroll.clicked.connect(self.accept)
        buttons.addWidget(enroll)
        layout.addLayout(buttons)

    @classmethod
    def get_code(cls, parent=None):
        dialog = cls(parent)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        return dialog.code_input.text().strip()


def configure_join_with_code_button(button, user_id, callback):
    """Give quiz and flashcard launchers one consistent join action."""
    button.setObjectName("mode_header_action")
    button.setEnabled(True)
    button.clicked.connect(callback)
    button.setToolTip(
        "Enter an invitation code. Sign-in is required to complete enrollment."
        if user_id == "guest"
        else "Join class-only content with an invitation code."
    )


def run_join_with_code_flow(parent, controller, refresh_content):
    """Prompt for a code, enroll through the active controller, and refresh."""
    code = JoinWithCodeDialog.get_code(parent)
    if code is None:
        return

    success, message = controller.join_with_code(code)
    if success:
        refresh_content()
        QMessageBox.information(parent, "Enrollment complete", message)
    else:
        QMessageBox.warning(parent, "Unable to enroll", message)
