import logging
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QLineEdit, QFrame
)
from PyQt6.QtCore import Qt, pyqtSignal

from src.config import LOGIN_DIALOG_SIZE
from src.logic.translator import get_translator

logger = logging.getLogger(__name__)


class LoginDialog(QDialog):
    """
    Modern glass morphism-style login dialog with multi-language support.
    """

    login_success = pyqtSignal(str, str)  # (login, password)
    guest_mode = pyqtSignal()
    signup_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)

        # Initialize Translator
        self.translator = get_translator()

        # Window Setup
        self.setFixedSize(*LOGIN_DIALOG_SIZE)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self.init_ui()
        self.retranslate_ui()

    def init_ui(self):
        """Initialize the UI structure (layouts and widget instances)."""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)

        # Glass panel container
        self.glass_panel = QFrame()
        self.glass_panel.setObjectName("login_glass_panel")
        panel_layout = QVBoxLayout(self.glass_panel)
        panel_layout.setContentsMargins(30, 30, 30, 30)

        # Title
        self.title_label = QLabel()
        self.title_label.setObjectName("login_title")
        self.title_label.setCursor(Qt.CursorShape.SizeAllCursor)
        panel_layout.addWidget(self.title_label)

        # Email field
        self.email_label = QLabel()
        self.email_label.setObjectName("login_field_label")
        panel_layout.addWidget(self.email_label)

        self.email_input = QLineEdit()
        self.email_input.setObjectName("login_input")
        panel_layout.addWidget(self.email_input)

        # Password field
        self.password_label = QLabel()
        self.password_label.setObjectName("login_field_label")
        panel_layout.addWidget(self.password_label)

        self.password_input = QLineEdit()
        self.password_input.setObjectName("login_input")
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_input.returnPressed.connect(self.handle_login)
        panel_layout.addWidget(self.password_input)

        # Error message label (hidden by default)
        self.error_label = QLabel()
        self.error_label.setObjectName("login_error")
        self.error_label.hide()
        panel_layout.addWidget(self.error_label)

        # Sign in button
        self.sign_in_btn = QPushButton()
        self.sign_in_btn.setObjectName("login_signin_btn")
        # The password field handles Enter itself.  Without this, Qt may also
        # activate the dialog's default button and submit the same login twice.
        self.sign_in_btn.setAutoDefault(False)
        self.sign_in_btn.setDefault(False)
        self.sign_in_btn.clicked.connect(self.handle_login)
        panel_layout.addWidget(self.sign_in_btn)

        # Links row (Guest and Sign Up)
        links_layout = QHBoxLayout()

        self.guest_btn = QPushButton()
        self.guest_btn.setObjectName("login_link")
        self.guest_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        # A link must never become the dialog's implicit Enter action. Without
        # this, pressing Enter in the password field can also activate Guest.
        self.guest_btn.setAutoDefault(False)
        self.guest_btn.setDefault(False)
        self.guest_btn.clicked.connect(self.handle_guest)

        self.signup_btn = QPushButton()
        self.signup_btn.setObjectName("login_link")
        self.signup_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.signup_btn.setAutoDefault(False)
        self.signup_btn.setDefault(False)
        self.signup_btn.clicked.connect(lambda _checked=False: self.signup_requested.emit())

        links_layout.addWidget(self.guest_btn)
        links_layout.addStretch()
        links_layout.addWidget(self.signup_btn)

        panel_layout.addLayout(links_layout)
        main_layout.addWidget(self.glass_panel)

    def retranslate_ui(self):
        """Update all text components using the translator."""
        t = self.translator

        # Section key prefix
        sec = "login_dialog"

        # Static Text
        self.setWindowTitle(t.t(f"{sec}.title"))
        self.title_label.setText(t.t(f"{sec}.title"))
        self.email_label.setText(t.t(f"{sec}.email_label"))
        self.password_label.setText(t.t(f"{sec}.password_label"))

        # Placeholders
        self.email_input.setPlaceholderText(t.t(f"{sec}.email_placeholder"))
        self.password_input.setPlaceholderText(t.t(f"{sec}.password_placeholder"))

        # Buttons
        self.sign_in_btn.setText(t.t(f"{sec}.btn_signin"))
        self.guest_btn.setText(t.t(f"{sec}.btn_guest"))
        self.signup_btn.setText(t.t(f"{sec}.btn_signup"))

    def handle_login(self):
        """Emit login credentials or show localized error."""
        login = self.email_input.text().strip()
        password = self.password_input.text().strip()

        if not login or not password:
            self.show_error(self.translator.t("login_dialog.error_empty"))
            return

        self.error_label.hide()
        self.login_success.emit(login, password)

    def handle_guest(self):
        """Emit guest mode signal."""
        self.guest_mode.emit()

    def clear_password(self):
        """Do not retain credentials after the dialog is closed or reused."""
        self.password_input.clear()

    def clear_error(self):
        """Reset an old authentication error before showing a fresh dialog."""
        self.error_label.clear()
        self.error_label.hide()

    def show_error(self, message: str):
        """Display error message."""
        self.error_label.setText(message)
        self.error_label.show()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton and hasattr(self, "_drag_offset"):
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_offset = None
        super().mouseReleaseEvent(event)

