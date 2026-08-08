"""Local-account registration dialog styled to match the login dialog."""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout

from src.config import LOGIN_DIALOG_SIZE
from src.logic.translator import get_translator


class RegistrationDialog(QDialog):
    registration_requested = pyqtSignal(str, str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.translator = get_translator()
        self.setFixedSize(LOGIN_DIALOG_SIZE[0], 590)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._init_ui()
        self.retranslate_ui()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        panel = QFrame()
        panel.setObjectName("login_glass_panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(30, 30, 30, 30)
        self.title_label = QLabel()
        self.title_label.setObjectName("login_title")
        self.title_label.setCursor(Qt.CursorShape.SizeAllCursor)
        layout.addWidget(self.title_label)
        self.name_input = self._add_field(layout, "name")
        self.login_input = self._add_field(layout, "login")
        self.password_input = self._add_field(layout, "password", password=True)
        self.confirm_input = self._add_field(layout, "confirm", password=True)
        self.confirm_input.returnPressed.connect(self.submit)
        self.error_label = QLabel()
        self.error_label.setObjectName("login_error")
        self.error_label.hide()
        layout.addWidget(self.error_label)
        self.create_btn = QPushButton()
        self.create_btn.setObjectName("login_signin_btn")
        self.create_btn.clicked.connect(self.submit)
        layout.addWidget(self.create_btn)
        links = QHBoxLayout()
        self.back_btn = QPushButton()
        self.back_btn.setObjectName("login_link")
        self.back_btn.clicked.connect(self.reject)
        links.addWidget(self.back_btn)
        links.addStretch()
        layout.addLayout(links)
        main_layout.addWidget(panel)

    def _add_field(self, layout, field, password=False):
        label = QLabel()
        label.setObjectName("login_field_label")
        input_widget = QLineEdit()
        input_widget.setObjectName("login_input")
        if password:
            input_widget.setEchoMode(QLineEdit.EchoMode.Password)
        setattr(self, f"{field}_label", label)
        layout.addWidget(label)
        layout.addWidget(input_widget)
        return input_widget

    def retranslate_ui(self):
        t = self.translator
        sec = "registration_dialog"
        self.setWindowTitle(t.t(f"{sec}.title"))
        self.title_label.setText(t.t(f"{sec}.title"))
        for field in ("name", "login", "password", "confirm"):
            getattr(self, f"{field}_label").setText(t.t(f"{sec}.{field}_label"))
            getattr(self, f"{field}_input").setPlaceholderText(t.t(f"{sec}.{field}_placeholder"))
        self.create_btn.setText(t.t(f"{sec}.btn_create"))
        self.back_btn.setText(t.t(f"{sec}.btn_back"))

    def submit(self):
        if self.password_input.text() != self.confirm_input.text():
            self.show_error(self.translator.t("registration_dialog.error_password_mismatch"))
            return
        if not all((self.name_input.text().strip(), self.login_input.text().strip(), self.password_input.text())):
            self.show_error(self.translator.t("registration_dialog.error_empty"))
            return
        self.error_label.hide()
        self.registration_requested.emit(self.name_input.text().strip(), self.login_input.text().strip(), self.password_input.text())

    def show_error(self, message):
        self.error_label.setText(message)
        self.error_label.show()

    def clear_passwords(self):
        self.password_input.clear()
        self.confirm_input.clear()

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
