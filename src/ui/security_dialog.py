"""Security settings for password and active server sessions."""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from src.logic.translator import get_translator


class SecurityDialog(QDialog):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.translator = get_translator()
        self.resize(560, 700)
        self.setMinimumSize(520, 620)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._init_ui()
        self.retranslate_ui()

    def _init_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)
        panel = QFrame()
        panel.setObjectName("login_glass_panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(8)
        self.title = QLabel()
        self.title.setObjectName("login_title")
        layout.addWidget(self.title)
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
        self.last_login = QLabel()
        self.last_login.setObjectName("account_info_label")
        layout.addWidget(self.last_login)
        self.sessions_title = QLabel()
        self.sessions_title.setObjectName("account_field_label")
        layout.addWidget(self.sessions_title)
        self.sessions_scroll = QScrollArea()
        self.sessions_scroll.setWidgetResizable(True)
        self.sessions_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.sessions_scroll.setMaximumHeight(220)
        self.sessions_container = QWidget()
        self.sessions_layout = QVBoxLayout(self.sessions_container)
        self.sessions_layout.setContentsMargins(0, 0, 0, 0)
        self.sessions_scroll.setWidget(self.sessions_container)
        layout.addWidget(self.sessions_scroll)
        self.sign_out_others_btn = QPushButton()
        self.sign_out_others_btn.setObjectName("account_danger_btn")
        self.sign_out_others_btn.clicked.connect(self.sign_out_others)
        layout.addWidget(self.sign_out_others_btn)
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
        widget = QLineEdit()
        widget.setObjectName("account_input")
        widget.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addWidget(widget)
        return widget

    def retranslate_ui(self):
        t = self.translator
        sec = "security_settings"
        self.setWindowTitle(t.t(f"{sec}.title"))
        self.title.setText(t.t(f"{sec}.title"))
        self.password_title.setText(t.t(f"{sec}.password_title"))
        self.current_password.setPlaceholderText(t.t(f"{sec}.current_password"))
        self.new_password.setPlaceholderText(t.t(f"{sec}.new_password"))
        self.confirm_password.setPlaceholderText(t.t(f"{sec}.confirm_password"))
        self.change_password_btn.setText(t.t(f"{sec}.btn_change_password"))
        self.sessions_title.setText(t.t(f"{sec}.sessions_title"))
        self.sign_out_others_btn.setText(t.t(f"{sec}.btn_sign_out_others"))
        self.close_btn.setText(t.t(f"{sec}.btn_close"))

    def refresh_security(self):
        while self.sessions_layout.count():
            item = self.sessions_layout.takeAt(0)
            nested = item.layout()
            if nested is not None:
                while nested.count():
                    child = nested.takeAt(0)
                    if child.widget():
                        child.widget().deleteLater()
                nested.deleteLater()
            elif item.widget():
                item.widget().deleteLater()
        repo = self.controller.user_repo
        if not hasattr(repo, "list_active_sessions"):
            self.last_login.setText("")
            self.sessions_title.hide()
            self.sessions_scroll.hide()
            self.sign_out_others_btn.hide()
            return
        self.sessions_title.show()
        self.sessions_scroll.show()
        self.sign_out_others_btn.show()
        try:
            result = repo.list_active_sessions()
        except Exception as exc:
            self.show_message(str(exc))
            return
        last = result.get("last_successful_login_at") if isinstance(result, dict) else None
        self.last_login.setText(self.translator.t("security_settings.last_login", value=last or self.translator.t("security_settings.never")))
        sessions = result.get("sessions", []) if isinstance(result, dict) else []
        for session in sessions:
            row = QHBoxLayout()
            label = QLabel(self._session_text(session))
            label.setTextFormat(Qt.TextFormat.PlainText)
            row.addWidget(label)
            row.addStretch()
            if not session.get("is_current"):
                button = QPushButton(self.translator.t("security_settings.btn_terminate"))
                button.clicked.connect(lambda _checked=False, sid=session.get("id"): self.terminate_session(sid))
                row.addWidget(button)
            self.sessions_layout.addLayout(row)

    def _session_text(self, session):
        current = "  " + self.translator.t("security_settings.current") if session.get("is_current") else ""
        return f"{session.get('client_label') or self.translator.t('security_settings.unknown_device')} · {session.get('ip_address') or '—'}\n{session.get('created_at') or '—'} → {session.get('last_activity_at') or '—'}{current}"

    def save_password(self):
        if self.new_password.text() != self.confirm_password.text():
            self.show_message(self.translator.t("security_settings.msg_password_mismatch"))
            return
        success, message = self.controller.change_password(self.current_password.text(), self.new_password.text())
        if success:
            self.current_password.clear()
            self.new_password.clear()
            self.confirm_password.clear()
            self.show_message(self.translator.t("security_settings.msg_password_saved"), False)
        else:
            self.show_message(message)

    def terminate_session(self, session_id):
        answer = QMessageBox.question(self, self.translator.t("security_settings.confirm_title"), self.translator.t("security_settings.confirm_terminate"), QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if answer == QMessageBox.StandardButton.Yes and self.controller.user_repo.terminate_session(session_id):
            self.refresh_security()

    def sign_out_others(self):
        answer = QMessageBox.question(self, self.translator.t("security_settings.confirm_title"), self.translator.t("security_settings.confirm_sign_out_others"), QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if answer == QMessageBox.StandardButton.Yes and self.controller.user_repo.sign_out_other_sessions():
            self.refresh_security()

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
