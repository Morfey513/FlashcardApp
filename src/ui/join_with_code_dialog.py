"""Small reusable prompt for joining class-only learning content."""

from PyQt6.QtWidgets import QDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout


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
