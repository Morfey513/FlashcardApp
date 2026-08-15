"""Settings for the currently authenticated local account."""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout

from src.logic.translator import get_translator


class AccountSettingsDialog(QDialog):
    profile_saved = pyqtSignal()
    clear_all_progress_requested = pyqtSignal()

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.translator = get_translator()
        self.resize(520, 700)
        self.setMinimumSize(500, 620)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._init_ui()
        self.refresh_account()
        self.retranslate_ui()

    def _init_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)
        panel = QFrame()
        panel.setObjectName("login_glass_panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(10)
        self.title = QLabel()
        self.title.setObjectName("login_title")
        self.title.setCursor(Qt.CursorShape.SizeAllCursor)
        layout.addWidget(self.title)

        self.name_label = QLabel()
        self.name_label.setObjectName("account_field_label")
        self.name_input = QLineEdit()
        self.name_input.setObjectName("account_input")
        self.save_name_btn = QPushButton()
        self.save_name_btn.setObjectName("account_action_btn")
        self.save_name_btn.setFixedHeight(38)
        self.save_name_btn.clicked.connect(self.save_name)
        layout.addWidget(self.name_label)
        layout.addWidget(self.name_input)
        layout.addWidget(self.save_name_btn)

        self.login_info = QLabel()
        self.role_info = QLabel()
        self.login_info.setObjectName("account_info_label")
        self.role_info.setObjectName("account_info_label")
        layout.addWidget(self.login_info)
        layout.addWidget(self.role_info)

        self.password_title = QLabel()
        self.password_title.setObjectName("account_field_label")
        layout.addWidget(self.password_title)
        self.current_password = self._password_input(layout)
        self.new_password = self._password_input(layout)
        self.confirm_password = self._password_input(layout)
        self.change_password_btn = QPushButton()
        self.change_password_btn.setObjectName("account_action_btn")
        self.change_password_btn.setFixedHeight(38)
        self.change_password_btn.clicked.connect(self.save_password)
        layout.addWidget(self.change_password_btn)

        self.data_title = QLabel()
        self.data_title.setObjectName("account_field_label")
        layout.addWidget(self.data_title)
        self.clear_all_progress_btn = QPushButton()
        self.clear_all_progress_btn.setObjectName("account_danger_btn")
        self.clear_all_progress_btn.setFixedHeight(38)
        self.clear_all_progress_btn.clicked.connect(self.clear_all_progress_requested.emit)
        layout.addWidget(self.clear_all_progress_btn)

        self.message = QLabel()
        self.message.setObjectName("login_error")
        self.message.hide()
        layout.addWidget(self.message)
        self.close_btn = QPushButton()
        self.close_btn.setObjectName("login_link")
        self.close_btn.clicked.connect(self.accept)
        layout.addWidget(self.close_btn, alignment=Qt.AlignmentFlag.AlignRight)
        outer.addWidget(panel)

    def _password_input(self, layout):
        input_widget = QLineEdit()
        input_widget.setObjectName("account_input")
        input_widget.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addWidget(input_widget)
        return input_widget

    def refresh_account(self):
        user = self.controller.session.current_user or {}
        self.name_input.setText(user.get("name", ""))
        self.login_info.setText(f"Login: {user.get('login', '')}")
        self.role_info.setText(f"Role: {user.get('role', '')}")

    def retranslate_ui(self):
        t = self.translator
        sec = "account_settings"
        self.setWindowTitle(t.t(f"{sec}.title"))
        self.title.setText(t.t(f"{sec}.title"))
        self.name_label.setText(t.t(f"{sec}.name_label"))
        self.name_input.setPlaceholderText(t.t(f"{sec}.name_placeholder"))
        self.save_name_btn.setText(t.t(f"{sec}.btn_save_name"))
        self.password_title.setText(t.t(f"{sec}.password_title"))
        self.current_password.setPlaceholderText(t.t(f"{sec}.current_password"))
        self.new_password.setPlaceholderText(t.t(f"{sec}.new_password"))
        self.confirm_password.setPlaceholderText(t.t(f"{sec}.confirm_password"))
        self.change_password_btn.setText(t.t(f"{sec}.btn_change_password"))
        self.data_title.setText(t.t(f"{sec}.data_title"))
        self.clear_all_progress_btn.setText(t.t(f"{sec}.btn_clear_all_progress"))
        self.close_btn.setText(t.t(f"{sec}.btn_close"))

    def save_name(self):
        if self.controller.update_display_name(self.name_input.text()):
            self.show_message(self.translator.t("account_settings.msg_name_saved"), error=False)
            self.profile_saved.emit()
        else:
            self.show_message(self.translator.t("account_settings.msg_name_error"))

    def save_password(self):
        if self.new_password.text() != self.confirm_password.text():
            self.show_message(self.translator.t("account_settings.msg_password_mismatch"))
            return
        success, message = self.controller.change_password(self.current_password.text(), self.new_password.text())
        if success:
            self.current_password.clear()
            self.new_password.clear()
            self.confirm_password.clear()
            self.show_message(self.translator.t("account_settings.msg_password_saved"), error=False)
        else:
            self.show_message(message)

    def show_message(self, message, error=True):
        self.message.setText(message)
        self.message.setProperty("error", error)
        self.message.show()

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
