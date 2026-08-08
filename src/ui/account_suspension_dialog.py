"""Branded notice shown when a locally suspended account attempts to sign in."""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout


class AccountSuspensionDialog(QDialog):
    def __init__(self, reason: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Account Suspended")
        self.setModal(True)
        self.setFixedSize(430, 260)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 18, 18, 18)
        panel = QFrame()
        panel.setObjectName("suspension_panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(12)

        title = QLabel("Account Suspended")
        title.setObjectName("suspension_title")
        layout.addWidget(title)

        message = QLabel("Your account has been suspended by an administrator.")
        message.setObjectName("suspension_message")
        message.setWordWrap(True)
        layout.addWidget(message)

        reason_label = QLabel(f"Reason: {reason}")
        reason_label.setObjectName("suspension_reason")
        reason_label.setWordWrap(True)
        layout.addWidget(reason_label)

        help_text = QLabel("If you believe this is a mistake, please contact the app administrator.")
        help_text.setObjectName("suspension_help")
        help_text.setWordWrap(True)
        layout.addWidget(help_text)
        layout.addStretch()

        buttons = QHBoxLayout()
        buttons.addStretch()
        close = QPushButton("OK")
        close.setObjectName("suspension_close")
        close.clicked.connect(self.accept)
        buttons.addWidget(close)
        layout.addLayout(buttons)

        outer.addWidget(panel)
