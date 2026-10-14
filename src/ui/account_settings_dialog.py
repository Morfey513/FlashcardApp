"""Settings for the currently authenticated local account."""

from PyQt6.QtCore import QTimer, Qt, pyqtSignal
from PyQt6.QtWidgets import QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout

from src.logic.translator import get_translator


class AccountSettingsDialog(QDialog):
    profile_saved = pyqtSignal()
    clear_all_progress_requested = pyqtSignal()

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.translator = get_translator()
        self.resize(520, 440)
        self.setMinimumWidth(500)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._init_ui()
        self.refresh_account()
        self.retranslate_ui()
        self._fit_height()

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
        self.data_title.setText(t.t(f"{sec}.data_title"))
        self.clear_all_progress_btn.setText(t.t(f"{sec}.btn_clear_all_progress"))
        self.close_btn.setText(t.t(f"{sec}.btn_close"))
        self._fit_height()

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, self._fit_height)

    def _fit_height(self):
        """Keep the account dialog as tall as its remaining controls require."""
        self.layout().activate()
        height = self.sizeHint().height()
        self.setMaximumHeight(height)
        self.resize(self.width(), height)

    def save_name(self):
        if self.controller.update_display_name(self.name_input.text()):
            self.show_message(self.translator.t("account_settings.msg_name_saved"), error=False)
            self.profile_saved.emit()
        else:
            self.show_message(self.translator.t("account_settings.msg_name_error"))

    def show_message(self, message, error=True):
        self.message.setText(message)
        self.message.setProperty("error", error)
        self.message.show()
        QTimer.singleShot(0, self._fit_height)

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
