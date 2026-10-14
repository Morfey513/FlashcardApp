"""Security settings for password and active server sessions."""

import logging
from datetime import datetime

from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtGui import QAction, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PyQt6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from src.logic.translator import get_translator


logger = logging.getLogger(__name__)


class SecurityDialog(QDialog):
    max_visible_sessions = 3
    max_sessions_height = 360

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.translator = get_translator()
        self._sessions_loaded = False
        self._session_cards = []
        self._base_dialog_height = None
        self.resize(600, 760)
        self.setMinimumSize(540, 660)
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
        layout.addSpacing(12)
        self.sessions_panel = QFrame()
        self.sessions_panel.setObjectName("security_sessions_panel")
        sessions_panel_layout = QVBoxLayout(self.sessions_panel)
        sessions_panel_layout.setContentsMargins(14, 14, 14, 14)
        sessions_panel_layout.setSpacing(8)
        self.sessions_title = QLabel()
        self.sessions_title.setObjectName("account_field_label")
        sessions_panel_layout.addWidget(self.sessions_title)
        self.last_login = QLabel()
        self.last_login.setObjectName("account_info_label")
        sessions_panel_layout.addWidget(self.last_login)
        self.sessions_scroll = QScrollArea()
        self.sessions_scroll.setObjectName("security_sessions_scroll")
        self.sessions_scroll.setWidgetResizable(True)
        self.sessions_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.sessions_scroll.setMaximumHeight(self.max_sessions_height)
        self.sessions_container = QWidget()
        self.sessions_container.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.sessions_layout = QVBoxLayout(self.sessions_container)
        self.sessions_layout.setContentsMargins(2, 2, 2, 2)
        self.sessions_layout.setSpacing(8)
        self.sessions_scroll.setWidget(self.sessions_container)
        sessions_panel_layout.addWidget(self.sessions_scroll)
        layout.addWidget(self.sessions_panel)
        layout.addSpacing(12)
        self.sign_out_others_btn = QPushButton()
        self.sign_out_others_btn.setObjectName("security_sign_out_others")
        self.sign_out_others_btn.setFixedHeight(38)
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
        visibility = QAction(widget)
        visibility.setIcon(self._eye_icon(False))
        visibility.triggered.connect(lambda _checked=False, field=widget: self._toggle_password(field))
        widget.addAction(visibility, QLineEdit.ActionPosition.TrailingPosition)
        widget.visibility_action = visibility
        layout.addWidget(widget)
        return widget

    @staticmethod
    def _eye_icon(visible):
        pixmap = QPixmap(20, 20)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(Qt.GlobalColor.gray, 1.7))
        outline = QPainterPath()
        outline.moveTo(2, 10)
        outline.cubicTo(6, 4, 14, 4, 18, 10)
        outline.cubicTo(14, 16, 6, 16, 2, 10)
        painter.drawPath(outline)
        painter.drawEllipse(8, 8, 4, 4)
        if visible:
            painter.drawLine(3, 17, 17, 3)
        painter.end()
        return QIcon(pixmap)

    def _toggle_password(self, field):
        visible = field.echoMode() == QLineEdit.EchoMode.Password
        field.setEchoMode(QLineEdit.EchoMode.Normal if visible else QLineEdit.EchoMode.Password)
        field.visibility_action.setIcon(self._eye_icon(visible))
        self._set_visibility_tooltip(field)

    def _set_visibility_tooltip(self, field):
        key = "hide_password" if field.echoMode() == QLineEdit.EchoMode.Normal else "show_password"
        field.visibility_action.setToolTip(self.translator.t(f"security_settings.{key}"))

    def _format_timestamp(self, value):
        if not value:
            return "—"
        try:
            moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if moment.tzinfo is not None:
                moment = moment.astimezone()
        except (TypeError, ValueError):
            return "—"
        language = self.translator.current_language
        clock = moment.strftime("%I:%M %p").lstrip("0") if language == "en" else moment.strftime("%H:%M")
        if moment.date() == datetime.now().astimezone().date():
            return self.translator.t("security_settings.today_at", time=clock)
        date = f"{moment.strftime('%b')} {moment.day}, {moment.year}" if language == "en" else moment.strftime("%d/%m/%Y")
        return self.translator.t("security_settings.date_at", date=date, time=clock)

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
        for field in (self.current_password, self.new_password, self.confirm_password):
            self._set_visibility_tooltip(field)
        if self._sessions_loaded:
            self.refresh_security()

    def refresh_security(self):
        self._session_cards = []
        while self.sessions_layout.count():
            item = self.sessions_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        repo = self.controller.user_repo
        if not hasattr(repo, "list_active_sessions"):
            self.last_login.setText("")
            self.sessions_panel.hide()
            self.sign_out_others_btn.hide()
            return
        self.sessions_panel.show()
        self.sign_out_others_btn.show()
        try:
            result = repo.list_active_sessions()
        except Exception:
            logger.exception("Could not load active sessions")
            self.show_message(self.translator.t("security_settings.msg_load_failed"))
            return
        self._sessions_loaded = True
        last = result.get("last_successful_login_at") if isinstance(result, dict) else None
        self.last_login.setText(self.translator.t("security_settings.last_login", value=self._format_timestamp(last) if last else self.translator.t("security_settings.never")))
        sessions = result.get("sessions", []) if isinstance(result, dict) else []
        self.sessions_scroll.setVisible(bool(sessions))
        for session in sessions:
            card = QFrame()
            card.setObjectName("security_session_card")
            row = QHBoxLayout(card)
            row.setContentsMargins(12, 10, 12, 10)
            row.setSpacing(10)
            icon = QLabel(self._device_icon(session.get("client_label")))
            icon.setObjectName("security_device_icon")
            row.addWidget(icon, alignment=Qt.AlignmentFlag.AlignTop)
            details = QVBoxLayout()
            details.setSpacing(3)
            name = QLabel(str(session.get("client_label") or self.translator.t("security_settings.unknown_device")))
            name.setObjectName("security_device_name")
            name.setTextFormat(Qt.TextFormat.PlainText)
            name.setWordWrap(True)
            name.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            details.addWidget(name)
            ip = QLabel(str(session.get("ip_address") or "—"))
            ip.setObjectName("security_session_meta")
            ip.setTextFormat(Qt.TextFormat.PlainText)
            details.addWidget(ip)
            created = QLabel(self.translator.t("security_settings.active_since", value=self._format_timestamp(session.get("created_at"))))
            created.setObjectName("security_session_meta")
            created.setWordWrap(True)
            created.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            details.addWidget(created)
            activity = session.get("last_activity_at")
            if activity:
                last_active = QLabel(self.translator.t("security_settings.last_active", value=self._format_timestamp(activity)))
                last_active.setObjectName("security_session_meta")
                last_active.setWordWrap(True)
                last_active.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
                details.addWidget(last_active)
            row.addLayout(details, 1)
            if session.get("is_current"):
                badge = QLabel(self.translator.t("security_settings.this_device"))
                badge.setObjectName("security_current_badge")
                row.addWidget(badge, alignment=Qt.AlignmentFlag.AlignTop)
            else:
                button = QPushButton(self.translator.t("security_settings.btn_terminate"))
                button.setObjectName("security_terminate_btn")
                button.setFixedWidth(100)
                button.setFixedHeight(32)
                button.clicked.connect(lambda _checked=False, sid=session.get("id"): self.terminate_session(sid))
                row.addWidget(button, alignment=Qt.AlignmentFlag.AlignVCenter)
            self.sessions_layout.addWidget(card)
            self._session_cards.append(card)
        self.sessions_layout.addStretch()
        if self.isVisible():
            QTimer.singleShot(0, self._fit_sessions_height)

    def showEvent(self, event):
        super().showEvent(event)
        if self._sessions_loaded:
            QTimer.singleShot(0, self._fit_sessions_height)

    def _fit_sessions_height(self):
        """Fit rows within the available screen, preserving a footer and taskbar gap."""
        if not self.isVisible() or not self._session_cards:
            return
        self.sessions_layout.activate()
        visible_cards = self._session_cards[:self.max_visible_sessions]
        margins = self.sessions_layout.contentsMargins()
        desired = (
            margins.top() + margins.bottom()
            + sum(card.height() for card in visible_cards)
            + self.sessions_layout.spacing() * (len(visible_cards) - 1)
            + 2
        )
        # Establish the rows' preferred size first. On the first show, Qt may
        # still report the old layout hint until this scroll height changes.
        self.sessions_scroll.setFixedHeight(min(desired, self.max_sessions_height))
        self.sessions_panel.layout().activate()
        self.layout().activate()
        # sizeHint reflects the full dialog content even when a prior managed
        # resize has made its current geometry too short to show the footer.
        if self._base_dialog_height is None:
            self._base_dialog_height = self.sizeHint().height() - self.sessions_scroll.height()
        base_height = self._base_dialog_height
        screen = self.screen()
        margin = 16
        if screen is not None:
            available = screen.availableGeometry()
            max_dialog_height = max(320, available.height() - 2 * margin)
        else:
            available = None
            max_dialog_height = base_height + self.max_sessions_height
        self.setMinimumHeight(min(660, max_dialog_height))
        viewport_allowance = max(0, max_dialog_height - base_height)
        height = min(desired, self.max_sessions_height, viewport_allowance)
        self.sessions_scroll.setFixedHeight(height)
        target_height = min(max_dialog_height, max(self.minimumHeight(), base_height + height))
        self.resize(self.width(), target_height)
        if available is not None:
            left = available.left() + margin
            top = available.top() + margin
            right = available.right() - margin - self.width() + 1
            bottom = available.bottom() - margin - self.height() + 1
            self.move(min(max(self.x(), left), max(left, right)),
                      min(max(self.y(), top), max(top, bottom)))

    @staticmethod
    def _device_icon(label):
        name = str(label or "").casefold()
        if not name:
            return "💻"
        if any(word in name for word in ("android", "iphone", "ios", "mobile", "phone")):
            return "📱"
        if any(word in name for word in ("laptop", "notebook", "macbook")):
            return "💻"
        return "🖥️"

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
