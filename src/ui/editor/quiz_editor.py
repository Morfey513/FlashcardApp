# src/ui/editor/quiz_editor.py

import logging

from PyQt6.QtWidgets import (
    QWidget, QPushButton, QLabel, QVBoxLayout, QHBoxLayout,
    QListWidget, QListWidgetItem, QLineEdit, QStackedLayout, QFrame,
    QMessageBox, QComboBox, QTextEdit, QInputDialog, QFileDialog, QToolButton,
    QApplication, QToolTip, QSpinBox, QDateTimeEdit, QCheckBox
)
from PyQt6.QtGui import QPixmap, QCursor
from PyQt6.QtCore import Qt, QSize, pyqtSignal, QDateTime

from src.controllers.quiz_editor_controller import QuizEditorController
from src.logic.access_control import VISIBILITIES, VISIBILITY_LABELS, default_visibility_for_status
from src.logic.translator import get_translator
from src.ui.auto_scroll import AutoScrollArea

logger = logging.getLogger(__name__)


class SignedSpinBox(QSpinBox):
    """Spin box with explicit, themeable signs over its arrow buttons."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._up_sign = QLabel("⌃", self)
        self._down_sign = QLabel("⌄", self)
        self._up_sign.setObjectName("spinbox_arrow_sign")
        self._down_sign.setObjectName("spinbox_arrow_sign")
        for sign in (self._up_sign, self._down_sign):
            sign.setAlignment(Qt.AlignmentFlag.AlignCenter)
            sign.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            sign.raise_()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        button_width = 30
        upper_height = self.height() // 2
        self._up_sign.setGeometry(
            self.width() - button_width, 0, button_width, upper_height
        )
        self._down_sign.setGeometry(
            self.width() - button_width,
            upper_height,
            button_width,
            self.height() - upper_height,
        )


class QuizEditor(QWidget):
    """Quiz editor interface - create and edit quizzes and questions"""
    finished = pyqtSignal()

    def __init__(self, controller: QuizEditorController):
        super().__init__()
        self.controller = controller
        self.translator = get_translator()

        self.editor_menu_panel = None
        self.edit_question_text = None

        self.resize(900, 700)
        # The editor may become shorter (the settings column scrolls), but
        # keep enough horizontal room for Questions + Settings + navigation.
        self.setMinimumSize(860, 560)

        self.current_editing_question_index = None
        self.current_editing_questions = []
        self.current_content_banned = False

        self.stack = QStackedLayout()
        self.setLayout(self.stack)

        self.init_editor_menu_panel()
        self.init_quiz_editor_panel()
        self.init_question_editor_panel()

        self.retranslate_ui()
        self.stack.setCurrentWidget(self.editor_menu_panel)
        self.refresh_quiz_list()

    def retranslate_ui(self):
        """Standardized method to update all text in the UI."""
        t = self.translator
        sec = "quiz_editor"

        self.setWindowTitle(t.t(f"{sec}.title"))

        # Editor menu panel
        self.editor_menu_title.setText(t.t(f"{sec}.title"))
        self.editor_menu_subtitle.setText(t.t(f"{sec}.subtitle"))
        self.create_quiz_btn.setText("+ " + t.t(f"{sec}.btn_create_quiz"))
        self.back_to_main_btn.setText(t.t(f"{sec}.btn_back_to_main"))

        # Quiz editor panel
        self.add_question_btn.setText("+ " + t.t(f"{sec}.btn_add_question"))
        self.back_to_editor_btn.setText(t.t(f"{sec}.btn_back_to_menu"))
        self.visibility_label.setText("Visibility:")
        self.save_quiz_btn.setText("Save Changes")

        # Question editor panel
        self.question_editor_title.setText(t.t(f"{sec}.question_editor_title"))
        self.q_text_label.setText(t.t(f"{sec}.label_question"))
        self.edit_question_text.setPlaceholderText(t.t(f"{sec}.placeholder_question"))
        self.q_type_label.setText(t.t(f"{sec}.label_type"))
        self.image_section_label.setText(t.t(f"{sec}.label_image"))
        self.edit_has_image_checkbox.setText(t.t(f"{sec}.btn_add_image"))
        self.edit_image_path.setPlaceholderText(t.t(f"{sec}.placeholder_image_path"))
        self.browse_image_btn.setText(t.t(f"{sec}.btn_browse"))
        self.cancel_question_btn.setText(t.t(f"{sec}.btn_cancel"))
        self.save_question_btn.setText(t.t(f"{sec}.btn_save_question"))

    # =========================================================
    # Navigation & Safety
    # =========================================================

    def maybe_save_changes(self):
        if not self.controller.has_unsaved_changes:
            return True

        t = self.translator
        sec = "quiz_editor"

        msg_box = QMessageBox(self)
        msg_box.setWindowTitle(t.t(f"{sec}.msg_unsaved_title"))
        msg_box.setText(t.t(f"{sec}.msg_unsaved_text"))
        msg_box.setStandardButtons(
            QMessageBox.StandardButton.Save |
            QMessageBox.StandardButton.Discard |
            QMessageBox.StandardButton.Cancel
        )
        msg_box.setDefaultButton(QMessageBox.StandardButton.Save)
        ret = msg_box.exec()

        if ret == QMessageBox.StandardButton.Save:
            return self.save_current_quiz()
        if ret == QMessageBox.StandardButton.Discard:
            self.controller.has_unsaved_changes = False
            return True
        return False

    def closeEvent(self, event):
        if self.maybe_save_changes():
            self.finished.emit()
            event.accept()
        else:
            event.ignore()

    def return_to_main(self):
        if self.maybe_save_changes():
            self.finished.emit()
            self.close()

    def back_to_editor_menu_with_warning(self):
        if self.maybe_save_changes():
            self.current_editing_questions = []
            self.current_editing_question_index = None
            self.stack.setCurrentWidget(self.editor_menu_panel)
            self.refresh_quiz_list()

    # =========================================================
    # UI Initialization
    # =========================================================

    def init_editor_menu_panel(self):
        self.editor_menu_panel = QFrame()
        layout = QVBoxLayout(self.editor_menu_panel)
        layout.setContentsMargins(40, 40, 40, 40)
        layout.setSpacing(14)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)

        self.editor_menu_title = QLabel()
        self.editor_menu_title.setObjectName("title")
        self.editor_menu_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.editor_menu_title)

        self.editor_menu_subtitle = QLabel()
        self.editor_menu_subtitle.setObjectName("subtitle")
        self.editor_menu_subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.editor_menu_subtitle)

        layout.addSpacing(20)

        header = QHBoxLayout()
        header.addStretch()
        self.create_quiz_btn = QPushButton()
        self.create_quiz_btn.clicked.connect(self.create_new_quiz)
        header.addWidget(self.create_quiz_btn)
        layout.addLayout(header)

        self.editor_quiz_list = QListWidget()
        self.editor_quiz_list.setObjectName("editor_quiz_list")
        # This is the flexible part of the menu.  A large fixed minimum made
        # the list consume the footer's space when a saved window was short.
        self.editor_quiz_list.setMinimumHeight(160)
        self.editor_quiz_list.itemDoubleClicked.connect(self.edit_selected_quiz)
        self.editor_quiz_list.currentRowChanged.connect(
            lambda _row: self._sync_inline_selection(self.editor_quiz_list)
        )
        layout.addWidget(self.editor_quiz_list, stretch=1)

        self.back_to_main_btn = QPushButton()
        self.back_to_main_btn.setMinimumWidth(200)
        self.back_to_main_btn.clicked.connect(self.return_to_main)
        layout.addWidget(self.back_to_main_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        self.stack.addWidget(self.editor_menu_panel)

    def init_quiz_editor_panel(self):
        self.quiz_editor_panel = QFrame()
        layout = QVBoxLayout(self.quiz_editor_panel)
        layout.setContentsMargins(40, 40, 40, 40)
        layout.setSpacing(20)

        title_row = QHBoxLayout()
        self.quiz_editor_title = QLabel()
        self.quiz_editor_title.setObjectName("title")
        self.quiz_editor_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_row.addWidget(self.quiz_editor_title)
        self.add_question_btn = QPushButton()
        self.add_question_btn.clicked.connect(self.add_new_question)
        title_row.addWidget(self.add_question_btn)
        layout.addLayout(title_row)

        self.moderation_banner = QFrame()
        self.moderation_banner.setObjectName("moderation_banner")
        banner_layout = QVBoxLayout(self.moderation_banner)
        banner_layout.setContentsMargins(12, 8, 12, 8)
        self.moderation_banner_title = QLabel()
        self.moderation_banner_title.setObjectName("moderation_banner_title")
        banner_layout.addWidget(self.moderation_banner_title)
        self.moderation_banner_reason = QLabel()
        self.moderation_banner_reason.setObjectName("moderation_banner_reason")
        self.moderation_banner_reason.setWordWrap(True)
        banner_layout.addWidget(self.moderation_banner_reason)
        self.moderation_banner.hide()
        layout.addWidget(self.moderation_banner)

        content_row = QHBoxLayout()
        content_row.setSpacing(18)

        questions_frame = QFrame()
        questions_layout = QVBoxLayout(questions_frame)
        questions_layout.setContentsMargins(0, 0, 0, 0)
        questions_title = QLabel("QUESTIONS LIST")
        questions_title.setObjectName("section_label")
        questions_layout.addWidget(questions_title)

        self.editor_question_list = QListWidget()
        self.editor_question_list.setObjectName("editor_question_list")
        self.editor_question_list.setMinimumHeight(350)
        self.editor_question_list.itemDoubleClicked.connect(self.edit_selected_question)
        self.editor_question_list.currentRowChanged.connect(
            lambda _row: self._sync_inline_selection(self.editor_question_list)
        )
        questions_layout.addWidget(self.editor_question_list)
        content_row.addWidget(questions_frame, 1)

        self.assessment_panel = QFrame()
        self.assessment_panel.setObjectName("assessment_settings_panel")
        self.assessment_panel.setMinimumWidth(270)
        settings_layout = QVBoxLayout(self.assessment_panel)
        settings_layout.setContentsMargins(16, 14, 16, 14)
        settings_layout.setSpacing(10)

        settings_title = QLabel("⚙ TEST & ACCESS SETTINGS")
        settings_title.setObjectName("assessment_settings_title")
        settings_layout.addWidget(settings_title)

        self.due_date_enabled = QCheckBox("📅 Due Date")
        self.due_date_enabled.toggled.connect(self._toggle_due_date)
        settings_layout.addWidget(self.due_date_enabled)
        self.due_date_input = QDateTimeEdit(QDateTime.currentDateTime().addDays(7))
        self.due_date_input.setCalendarPopup(True)
        self.due_date_input.setDisplayFormat("yyyy-MM-dd  HH:mm")
        self.due_date_input.setEnabled(False)
        self.due_date_input.dateTimeChanged.connect(self._mark_settings_changed)
        settings_layout.addWidget(self.due_date_input)

        self.time_limit_input = SignedSpinBox()
        self.time_limit_input.setRange(0, 1440)
        self.time_limit_input.setSuffix(" minutes")
        self.time_limit_input.setSpecialValueText("No limit")
        settings_layout.addWidget(QLabel("⏱ Time Limit"))
        settings_layout.addWidget(self.time_limit_input)
        time_help = QLabel("0 = no time limit")
        time_help.setObjectName("field_help")
        settings_layout.addWidget(time_help)

        self.passing_grade_input = SignedSpinBox()
        self.passing_grade_input.setRange(1, 100)
        self.passing_grade_input.setSuffix(" %")
        settings_layout.addWidget(QLabel("🎯 Passing Grade"))
        settings_layout.addWidget(self.passing_grade_input)

        self.attempt_limit_input = SignedSpinBox()
        self.attempt_limit_input.setRange(0, 100)
        self.attempt_limit_input.setSuffix(" attempts")
        self.attempt_limit_input.setSpecialValueText("Unlimited")
        settings_layout.addWidget(QLabel("🔄 Attempt Limit"))
        settings_layout.addWidget(self.attempt_limit_input)
        attempt_help = QLabel("0 = unlimited attempts")
        attempt_help.setObjectName("field_help")
        settings_layout.addWidget(attempt_help)

        settings_layout.addWidget(QLabel("👁 Answer Review"))
        self.answer_review_input = QComboBox()
        self.answer_review_input.addItem("Immediately after submission", "immediate")
        self.answer_review_input.addItem("After the due date", "after_due_date")
        self.answer_review_input.addItem("Never show correct answers", "never")
        self.answer_review_input.currentIndexChanged.connect(self._mark_settings_changed)
        settings_layout.addWidget(self.answer_review_input)

        for input_widget in (
            self.time_limit_input, self.passing_grade_input, self.attempt_limit_input,
        ):
            input_widget.valueChanged.connect(self._mark_settings_changed)

        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setObjectName("management_divider")
        settings_layout.addWidget(separator)

        invite_title = QLabel("🔑 INVITATION CODE")
        invite_title.setObjectName("assessment_settings_title")
        settings_layout.addWidget(invite_title)

        self.invite_toolbar = QFrame()
        self.invite_toolbar.setObjectName("invite_code_toolbar")
        invite_layout = QVBoxLayout(self.invite_toolbar)
        invite_layout.setContentsMargins(0, 0, 0, 0)
        self.invite_code_label = QLabel()
        self.invite_code_label.setWordWrap(True)
        invite_layout.addWidget(self.invite_code_label)
        invite_buttons = QHBoxLayout()
        self.copy_invite_btn = QPushButton("Copy")
        self.copy_invite_btn.clicked.connect(self.copy_current_invite_code)
        invite_buttons.addWidget(self.copy_invite_btn)
        self.rotate_invite_btn = QPushButton()
        self.rotate_invite_btn.clicked.connect(self.generate_or_rotate_current_invite_code)
        invite_buttons.addWidget(self.rotate_invite_btn)
        invite_layout.addLayout(invite_buttons)
        settings_layout.addWidget(self.invite_toolbar)
        settings_layout.addStretch()
        self.assessment_scroll = AutoScrollArea()
        self.assessment_scroll.setObjectName("assessment_settings_scroll")
        self.assessment_scroll.setWidgetResizable(True)
        self.assessment_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.assessment_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.assessment_scroll.setFixedWidth(305)
        self.assessment_scroll.setWidget(self.assessment_panel)
        self.assessment_scroll.track_auto_scroll_content(self.assessment_panel)
        self.assessment_scroll.setToolTip(
            "Middle-click to auto-scroll; press Escape to stop"
        )
        self.assessment_scroll.hide()
        content_row.addWidget(self.assessment_scroll)
        layout.addLayout(content_row, 1)

        nav_btn_layout = QHBoxLayout()

        self.back_to_editor_btn = QPushButton()
        self.back_to_editor_btn.clicked.connect(self.back_to_editor_menu_with_warning)
        nav_btn_layout.addWidget(self.back_to_editor_btn)

        nav_btn_layout.addStretch()

        self.visibility_label = QLabel()
        nav_btn_layout.addWidget(self.visibility_label)
        self.visibility_selector = QComboBox()
        for visibility in VISIBILITIES:
            self.visibility_selector.addItem(VISIBILITY_LABELS[visibility], visibility)
        self.visibility_selector.setToolTip(
            "Draft is creator-only. Class-Only and Public are submitted for moderation."
        )
        self.visibility_selector.currentIndexChanged.connect(self._update_invite_code_toolbar)
        nav_btn_layout.addWidget(self.visibility_selector)

        self.save_quiz_btn = QPushButton()
        self.save_quiz_btn.setObjectName("publish_btn")
        self.save_quiz_btn.clicked.connect(self.save_current_quiz)
        nav_btn_layout.addWidget(self.save_quiz_btn)

        layout.addLayout(nav_btn_layout)
        self.stack.addWidget(self.quiz_editor_panel)

    def init_question_editor_panel(self):
        self.question_editor_panel = QFrame()

        scroll = AutoScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        content_widget = QWidget()
        layout = QVBoxLayout(content_widget)
        layout.setContentsMargins(40, 40, 40, 40)
        layout.setSpacing(20)

        self.question_editor_title = QLabel()
        self.question_editor_title.setObjectName("title")
        self.question_editor_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.question_editor_title)

        self.q_text_label = QLabel()
        self.q_text_label.setObjectName("quiz_editor_label")
        layout.addWidget(self.q_text_label)
        self.edit_question_text = QLineEdit()
        layout.addWidget(self.edit_question_text)

        self.q_type_label = QLabel()
        self.q_type_label.setObjectName("quiz_editor_label")
        layout.addWidget(self.q_type_label)
        self.edit_question_type = QComboBox()
        self.edit_question_type.addItems([
            "short_answer", "single_choice", "multiple_choice",
            "true_false", "matching", "ordering"
        ])
        self.edit_question_type.currentTextChanged.connect(self.on_question_type_changed)
        layout.addWidget(self.edit_question_type)

        self.edit_dynamic_container = QFrame()
        self.edit_dynamic_layout = QVBoxLayout(self.edit_dynamic_container)
        layout.addWidget(self.edit_dynamic_container)

        # Image section
        image_section = QFrame()
        image_section.setObjectName("quiz_editor_section")
        image_layout = QVBoxLayout(image_section)

        self.image_section_label = QLabel()
        self.image_section_label.setObjectName("quiz_editor_label")
        image_layout.addWidget(self.image_section_label)

        self.edit_has_image_checkbox = QPushButton()
        self.edit_has_image_checkbox.setCheckable(True)
        self.edit_has_image_checkbox.clicked.connect(self.toggle_image_section)
        image_layout.addWidget(self.edit_has_image_checkbox)

        self.edit_image_container = QFrame()
        self.edit_image_container.hide()
        img_container_layout = QVBoxLayout(self.edit_image_container)

        img_path_layout = QHBoxLayout()
        self.edit_image_path = QLineEdit()
        img_path_layout.addWidget(self.edit_image_path)

        self.browse_image_btn = QPushButton()
        self.browse_image_btn.clicked.connect(self.browse_image)
        img_path_layout.addWidget(self.browse_image_btn)

        img_container_layout.addLayout(img_path_layout)

        self.edit_image_preview = QLabel()
        self.edit_image_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.edit_image_preview.setObjectName("quiz_editor_preview")
        self.edit_image_preview.setMaximumHeight(200)
        img_container_layout.addWidget(self.edit_image_preview)

        image_layout.addWidget(self.edit_image_container)
        layout.addWidget(image_section)

        layout.addSpacing(20)
        btn_layout = QHBoxLayout()

        self.cancel_question_btn = QPushButton()
        self.cancel_question_btn.setObjectName("danger")
        self.cancel_question_btn.clicked.connect(self.cancel_question_edit)
        btn_layout.addWidget(self.cancel_question_btn)

        btn_layout.addStretch()

        self.save_question_btn = QPushButton()
        self.save_question_btn.clicked.connect(self.save_question_edit)
        btn_layout.addWidget(self.save_question_btn)

        layout.addLayout(btn_layout)

        scroll.setWidget(content_widget)
        scroll.track_auto_scroll_content(content_widget)
        scroll.setToolTip("Middle-click to auto-scroll; press Escape to stop")
        panel_layout = QVBoxLayout(self.question_editor_panel)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        panel_layout.addWidget(scroll)

        self.stack.addWidget(self.question_editor_panel)

    # =========================================================
    # Quiz Management Methods
    # =========================================================

    def refresh_quiz_list(self):
        self.editor_quiz_list.clear()
        for quiz in self.controller.get_quiz_entries():
            self._add_quiz_row(quiz["name"], quiz["status"], quiz.get("visibility", "private"))
        self._sync_inline_selection(self.editor_quiz_list)

    def _add_quiz_row(self, name, status, visibility):
        item = QListWidgetItem()
        item.setData(Qt.ItemDataRole.UserRole, name)
        row = QWidget()
        row.setObjectName("editor_inline_row")
        row.setMinimumHeight(42)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(10, 3, 10, 3)
        name_label = QLabel(name)
        name_label.setObjectName("editor_row_label")
        layout.addWidget(name_label)
        status_label = QLabel(f"[ {visibility.replace('_', ' ')} ]")
        status_label.setObjectName("editor_status")
        layout.addWidget(status_label)
        layout.addStretch()
        if visibility == "class_only":
            code_button = QToolButton()
            code_button.setText("🔑")
            code_button.setToolTip("Copy invitation code")
            code_button.setObjectName("inline_action")
            code_button.clicked.connect(lambda: self.copy_invite_code(name))
            layout.addWidget(code_button)
        for icon, tooltip, action in (
            ("✏", "Edit", lambda: self.edit_quiz_by_name(name)),
            ("⧉", "Copy", lambda: self.copy_quiz_by_name(name)),
            ("🗑", "Delete", lambda: self.delete_quiz_by_name(name)),
        ):
            button = QToolButton()
            button.setText(icon)
            button.setToolTip(tooltip)
            button.setObjectName("inline_action")
            button.clicked.connect(action)
            layout.addWidget(button)
        item.setSizeHint(QSize(0, 42))
        self.editor_quiz_list.addItem(item)
        self.editor_quiz_list.setItemWidget(item, row)

    @staticmethod
    def _sync_inline_selection(list_widget):
        """Paint selection on custom rows, not on QListWidget's hidden item."""
        selected_row = list_widget.currentRow()
        for index in range(list_widget.count()):
            row = list_widget.itemWidget(list_widget.item(index))
            if row is None:
                continue
            row.setProperty("selected", index == selected_row)
            row.style().unpolish(row)
            row.style().polish(row)

    def create_new_quiz(self):
        t = self.translator
        sec = "quiz_editor"
        name, ok = QInputDialog.getText(
            self,
            t.t(f"{sec}.dialog_create_title"),
            t.t(f"{sec}.dialog_create_label")
        )
        if ok and name:
            if self.controller.create_new_quiz(name):
                self.refresh_quiz_list()

    def edit_selected_quiz(self):
        item = self.editor_quiz_list.currentItem()
        if item:
            self.edit_quiz_by_name(item.data(Qt.ItemDataRole.UserRole) or item.text())

    def edit_quiz_by_name(self, name):
        if self.controller.load_quiz(name):
            self.current_editing_questions = self.controller.current_questions
            self.quiz_editor_title.setText(
                self.translator.t("quiz_editor.editing_quiz", name=name)
            )
            self._update_moderation_banner()
            self.refresh_question_list()
            self.stack.setCurrentWidget(self.quiz_editor_panel)

    def _update_invite_code_toolbar(self):
        class_only = self.visibility_selector.currentData() == "class_only"
        show_settings = class_only and not self.current_content_banned
        self.assessment_panel.setVisible(show_settings)
        self.assessment_scroll.setVisible(show_settings)
        if not class_only:
            return
        code = self.controller.get_current_invite_code()
        self.invite_code_label.setText(f"🔑 Active Code: {code}" if code else "🔑 No code generated yet")
        self.copy_invite_btn.setEnabled(bool(code))
        self.rotate_invite_btn.setText("Rotate Code" if code else "Generate Code")

    def _mark_settings_changed(self):
        if self.controller.current_quiz_info:
            self.controller.has_unsaved_changes = True

    def _toggle_due_date(self, enabled):
        self.due_date_input.setEnabled(enabled)
        self._mark_settings_changed()

    def copy_invite_code(self, name):
        code = self.controller.get_invite_code(name)
        if not code:
            QMessageBox.information(self, "No invitation code", "Set this quiz to Class-Only, then generate a code in its editor.")
            return
        QApplication.clipboard().setText(code)
        QToolTip.showText(QCursor.pos(), f"Code {code} copied!", self)

    def copy_current_invite_code(self):
        code = self.controller.get_current_invite_code()
        if code:
            QApplication.clipboard().setText(code)
            QToolTip.showText(QCursor.pos(), f"Code {code} copied!", self)

    def generate_or_rotate_current_invite_code(self):
        success, value = self.controller.generate_or_rotate_invite_code()
        if success:
            self._update_invite_code_toolbar()
            QToolTip.showText(QCursor.pos(), f"Code {value} ready to share.", self)
        else:
            QMessageBox.warning(self, "Invitation code", value)

    def _update_moderation_banner(self):
        metadata = self.controller.get_current_moderation()
        status = metadata.get("status", "draft")
        self.current_content_banned = status == "banned"
        visibility = metadata.get("visibility", default_visibility_for_status(status))
        settings = self.controller.get_current_test_settings()
        due_at = settings.get("due_at")
        self.due_date_enabled.blockSignals(True)
        self.due_date_enabled.setChecked(bool(due_at))
        self.due_date_enabled.blockSignals(False)
        self.due_date_input.setEnabled(bool(due_at))
        if due_at:
            parsed_due = QDateTime.fromString(due_at, Qt.DateFormat.ISODate)
            if parsed_due.isValid():
                self.due_date_input.blockSignals(True)
                self.due_date_input.setDateTime(parsed_due.toLocalTime())
                self.due_date_input.blockSignals(False)
        for widget, value in (
            (self.time_limit_input, settings["time_limit_minutes"]),
            (self.passing_grade_input, settings["passing_grade_percent"]),
            (self.attempt_limit_input, settings["attempt_limit"]),
        ):
            widget.blockSignals(True)
            widget.setValue(value)
            widget.blockSignals(False)
        review_policy = settings.get("answer_review_policy", "immediate")
        self.answer_review_input.blockSignals(True)
        self.answer_review_input.setCurrentIndex(
            max(0, self.answer_review_input.findData(review_policy))
        )
        self.answer_review_input.blockSignals(False)
        self.visibility_selector.setCurrentIndex(max(0, self.visibility_selector.findData(visibility)))
        self._update_invite_code_toolbar()
        reason = metadata.get("review_note", "").strip() or "No moderation reason was provided."
        if status not in {"rejected", "banned"}:
            self.moderation_banner.hide()
        else:
            self.moderation_banner.setProperty("status", status)
            self.moderation_banner_title.setText(
                "CONTENT BANNED" if status == "banned" else "PUBLICATION REJECTED BY MODERATOR"
            )
            self.moderation_banner_reason.setText(f"Reason: {reason}")
            self.moderation_banner.show()
            self.moderation_banner.style().unpolish(self.moderation_banner)
            self.moderation_banner.style().polish(self.moderation_banner)

        for widget in (
            self.add_question_btn, self.editor_question_list,
            self.visibility_selector, self.save_quiz_btn,
            self.time_limit_input, self.passing_grade_input, self.attempt_limit_input,
            self.due_date_enabled,
            self.answer_review_input,
        ):
            widget.setEnabled(not self.current_content_banned)
        self.due_date_input.setEnabled(
            not self.current_content_banned and self.due_date_enabled.isChecked()
        )

    def copy_selected_quiz(self):
        t = self.translator
        sec = "quiz_editor"
        item = self.editor_quiz_list.currentItem()
        if not item:
            return

        self.copy_quiz_by_name(item.data(Qt.ItemDataRole.UserRole) or item.text())

    def copy_quiz_by_name(self, original_name):
        t = self.translator
        sec = "quiz_editor"

        new_name, ok = QInputDialog.getText(
            self,
            t.t(f"{sec}.dialog_copy_title"),
            t.t(f"{sec}.dialog_copy_label"),
            text=f"{original_name} (Copy)"
        )
        if ok and new_name:
            if self.controller.copy_quiz(original_name, new_name):
                self.refresh_quiz_list()

    def delete_selected_quiz(self):
        t = self.translator
        sec = "quiz_editor"
        item = self.editor_quiz_list.currentItem()
        if not item:
            return

        self.delete_quiz_by_name(item.data(Qt.ItemDataRole.UserRole) or item.text())

    def delete_quiz_by_name(self, name):
        t = self.translator
        sec = "quiz_editor"

        confirm = QMessageBox.question(
            self,
            t.t(f"{sec}.dialog_delete_title"),
            t.t(f"{sec}.dialog_delete_quiz_text", name=name)
        )
        if confirm == QMessageBox.StandardButton.Yes:
            delete_result = getattr(self.controller, "delete_quiz_result", None)
            result = (
                delete_result(name) if callable(delete_result)
                else {"status": "deleted" if self.controller.delete_quiz(name) else "failed"}
            )
            outcome = result.get("status")
            if outcome in {"deleted", "not_found"}:
                self.refresh_quiz_list()
            if outcome == "not_found":
                QMessageBox.information(self, "Quiz not found", "This quiz no longer exists.")
            elif outcome == "forbidden":
                QMessageBox.warning(self, "Deletion rejected", "You are not authorized to delete this quiz.")
            elif outcome != "deleted":
                QMessageBox.warning(self, "Delete failed", "The quiz could not be deleted.")

    def refresh_question_list(self):
        self.editor_question_list.clear()
        for idx, q in enumerate(self.current_editing_questions):
            text = q.get('question', 'Untitled Question')
            item = QListWidgetItem()
            row = QWidget()
            row.setObjectName("editor_inline_row")
            row.setMinimumHeight(42)
            layout = QHBoxLayout(row)
            layout.setContentsMargins(10, 3, 10, 3)
            question_label = QLabel(f"{idx + 1}. {text}")
            question_label.setObjectName("editor_row_label")
            layout.addWidget(question_label)
            layout.addStretch()
            for icon, tooltip, action in (
                ("✏", "Edit", lambda _=False, value=idx: self.edit_question_at(value)),
                ("⧉", "Copy", lambda _=False, value=idx: self.copy_question_at(value)),
                ("🗑", "Delete", lambda _=False, value=idx: self.delete_question_at(value)),
            ):
                button = QToolButton()
                button.setText(icon)
                button.setToolTip(tooltip)
                button.setObjectName("inline_action")
                button.clicked.connect(action)
                layout.addWidget(button)
            item.setSizeHint(QSize(0, 42))
            self.editor_question_list.addItem(item)
            self.editor_question_list.setItemWidget(item, row)
        self._sync_inline_selection(self.editor_question_list)

    def save_current_quiz(self):
        t = self.translator
        sec = "quiz_editor"
        valid_ids = {q.get('id') for q in self.controller.current_questions if q.get('id')}

        visibility = self.visibility_selector.currentData()
        test_settings = {
            "time_limit_minutes": self.time_limit_input.value(),
            "passing_grade_percent": self.passing_grade_input.value(),
            "attempt_limit": self.attempt_limit_input.value(),
            "due_at": (
                self.due_date_input.dateTime().toUTC().toString(Qt.DateFormat.ISODate)
                if self.due_date_enabled.isChecked() else None
            ),
            "answer_review_policy": self.answer_review_input.currentData(),
        }
        if (
            test_settings["answer_review_policy"] == "after_due_date"
            and not test_settings["due_at"]
        ):
            QMessageBox.warning(
                self,
                "Due date required",
                "Answer review cannot be scheduled for after the due date until a due date is enabled.",
            )
            return False
        if self.controller.save_quiz(
            self.controller.current_questions, valid_ids,
            visibility=visibility, test_settings=test_settings,
        ):
            message = (
                "Quiz saved as a private draft."
                if visibility == "private"
                else "Quiz submitted for moderation."
            )
            QMessageBox.information(
                self,
                t.t(f"{sec}.msg_success_title"),
                message,
            )
            return True
        QMessageBox.critical(self, "Save failed", "The quiz could not be saved.")
        return False

    def publish_current_quiz(self):
        """Backward-compatible programmatic shortcut for public submission."""
        self.visibility_selector.setCurrentIndex(self.visibility_selector.findData("public"))
        return self.save_current_quiz()

    # =========================================================
    # Question Management Methods
    # =========================================================

    def add_new_question(self):
        self.current_editing_question_index = None
        self.load_question_editor({
            "question": "", "type": "short_answer",
            "answer": "", "has_image": False, "image_path": ""
        })

    def edit_selected_question(self):
        t = self.translator
        item = self.editor_question_list.currentItem()
        if not item:
            QMessageBox.warning(
                self,
                t.t("quiz_editor.msg_no_selection_title"),
                t.t("quiz_editor.msg_no_selection_edit_text")
            )
            return

        idx = self.editor_question_list.currentRow()
        self.current_editing_question_index = idx
        self.load_question_editor(self.current_editing_questions[idx])

    def edit_question_at(self, index):
        self.editor_question_list.setCurrentRow(index)
        self.edit_selected_question()

    def copy_selected_question(self):
        idx = self.editor_question_list.currentRow()
        if self.controller.duplicate_question(idx):
            self.refresh_question_list()

    def copy_question_at(self, index):
        self.editor_question_list.setCurrentRow(index)
        self.copy_selected_question()

    def delete_selected_question(self):
        t = self.translator
        sec = "quiz_editor"
        item = self.editor_question_list.currentItem()
        if not item:
            QMessageBox.warning(
                self,
                t.t(f"{sec}.msg_no_selection_title"),
                t.t(f"{sec}.msg_no_selection_delete_text")
            )
            return

        ret = QMessageBox.question(
            self,
            t.t(f"{sec}.dialog_delete_title"),
            t.t(f"{sec}.dialog_delete_question_text"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if ret == QMessageBox.StandardButton.Yes:
            idx = self.editor_question_list.currentRow()
            if self.controller.delete_question(idx):
                self.refresh_question_list()

    def delete_question_at(self, index):
        self.editor_question_list.setCurrentRow(index)
        self.delete_selected_question()

    # =========================================================
    # Question Editor Methods
    # =========================================================

    def load_question_editor(self, question_data):
        self.edit_question_text.setText(question_data.get("question", ""))
        self.edit_question_type.setCurrentText(question_data.get("type", "short_answer"))

        has_image = question_data.get("has_image", False)
        self.edit_has_image_checkbox.setChecked(has_image)
        self.edit_image_container.setVisible(has_image)
        self.edit_image_path.setText(question_data.get("image_path", ""))

        if has_image and question_data.get("image_path"):
            self.update_image_preview(question_data.get("image_path"))

        self.on_question_type_changed(question_data.get("type", "short_answer"), question_data)
        self.stack.setCurrentWidget(self.question_editor_panel)

    def on_question_type_changed(self, q_type, existing_data=None):
        """Update dynamic editor fields based on question type."""
        while self.edit_dynamic_layout.count():
            item = self.edit_dynamic_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if existing_data is None:
            existing_data = {}

        t = self.translator
        sec = "quiz_editor"

        if q_type == "short_answer":
            lbl = QLabel(t.t(f"{sec}.label_correct_answer"))
            lbl.setObjectName("quiz_editor_label")
            self.edit_dynamic_layout.addWidget(lbl)
            self.edit_answer_field = QLineEdit()
            self.edit_answer_field.setPlaceholderText(t.t(f"{sec}.placeholder_required"))
            self.edit_answer_field.setText(str(existing_data.get("answer", "")))
            self.edit_dynamic_layout.addWidget(self.edit_answer_field)

        elif q_type in ("single_choice", "multiple_choice"):
            lbl = QLabel(t.t(f"{sec}.label_choices"))
            lbl.setObjectName("quiz_editor_label")
            self.edit_dynamic_layout.addWidget(lbl)
            self.edit_choices_field = QTextEdit()
            self.edit_choices_field.setMaximumHeight(150)
            self.edit_choices_field.setPlaceholderText(t.t(f"{sec}.placeholder_choices"))
            choices = existing_data.get("choices", [])
            self.edit_choices_field.setPlainText("\n".join(choices))
            self.edit_dynamic_layout.addWidget(self.edit_choices_field)

            lbl2 = QLabel(t.t(f"{sec}.label_correct_answers"))
            lbl2.setObjectName("quiz_editor_label")
            self.edit_dynamic_layout.addWidget(lbl2)
            self.edit_answer_field = QLineEdit()
            answer = existing_data.get("answer", "")
            if isinstance(answer, list):
                answer = ", ".join(answer)
            self.edit_answer_field.setPlaceholderText(t.t(f"{sec}.placeholder_answers_multiple"))
            self.edit_answer_field.setText(str(answer))
            self.edit_dynamic_layout.addWidget(self.edit_answer_field)

        elif q_type == "true_false":
            lbl = QLabel(t.t(f"{sec}.label_correct_answer"))
            lbl.setObjectName("quiz_editor_label")
            self.edit_dynamic_layout.addWidget(lbl)
            self.edit_tf_field = QComboBox()
            self.edit_tf_field.addItems(["true", "false"])
            answer = existing_data.get("answer", True)
            self.edit_tf_field.setCurrentText("true" if answer else "false")
            self.edit_dynamic_layout.addWidget(self.edit_tf_field)

        elif q_type == "matching":
            lbl = QLabel(t.t(f"{sec}.label_pairs"))
            lbl.setObjectName("quiz_editor_label")
            self.edit_dynamic_layout.addWidget(lbl)
            self.edit_pairs_field = QTextEdit()
            self.edit_pairs_field.setMaximumHeight(150)
            pairs = existing_data.get("pairs", [])
            pairs_text = "\n".join([f"{p['prompt']} | {p['answer']}" for p in pairs])
            self.edit_pairs_field.setPlaceholderText(t.t(f"{sec}.placeholder_pairs"))
            self.edit_pairs_field.setPlainText(pairs_text)
            self.edit_dynamic_layout.addWidget(self.edit_pairs_field)

        elif q_type == "ordering":
            lbl = QLabel(t.t(f"{sec}.label_ordering"))
            lbl.setObjectName("quiz_editor_label")
            self.edit_dynamic_layout.addWidget(lbl)
            self.edit_ordering_field = QTextEdit()
            self.edit_ordering_field.setMaximumHeight(150)
            self.edit_ordering_field.setPlaceholderText(t.t(f"{sec}.placeholder_ordering"))
            answer = existing_data.get("answer", [])
            self.edit_ordering_field.setPlainText("\n".join(answer))
            self.edit_dynamic_layout.addWidget(self.edit_ordering_field)

    def toggle_image_section(self):
        self.edit_image_container.setVisible(self.edit_has_image_checkbox.isChecked())

    def browse_image(self):
        from src.config import IMAGE_DIR
        file_path, _ = QFileDialog.getOpenFileName(
            self, self.translator.t("quiz_editor.dialog_select_image"),
            str(IMAGE_DIR), "Images (*.png *.jpg *.jpeg *.webp *.gif)"
        )
        if file_path:
            rel_path = self.controller.process_image_path(file_path)
            self.edit_image_path.setText(rel_path)
            self.update_image_preview(rel_path)

    def update_image_preview(self, stored_path):
        t = self.translator
        if not stored_path:
            self.edit_image_preview.setText(t.t("quiz_editor.preview_no_image"))
            return

        full_path = self.controller.get_absolute_image_path(stored_path)
        if full_path.exists():
            pix = QPixmap(str(full_path))
            if not pix.isNull():
                self.edit_image_preview.setPixmap(
                    pix.scaled(300, 200, Qt.AspectRatioMode.KeepAspectRatio,
                               Qt.TransformationMode.SmoothTransformation)
                )
                self.edit_image_preview.setText("")
                return

        self.edit_image_preview.setText(t.t("quiz_editor.preview_not_found"))

    def save_question_edit(self):
        t = self.translator
        sec = "quiz_editor"

        question_text = self.edit_question_text.text().strip()
        if not question_text:
            QMessageBox.warning(
                self,
                t.t(f"{sec}.msg_validation_title"),
                t.t(f"{sec}.msg_question_required")
            )
            return

        q_type = self.edit_question_type.currentText()
        question = {
            "question": question_text,
            "type": q_type,
            "has_image": self.edit_has_image_checkbox.isChecked(),
            "image_path": self.edit_image_path.text() if self.edit_has_image_checkbox.isChecked() else ""
        }

        try:
            if q_type == "short_answer":
                answer = self.edit_answer_field.text().strip()
                if not answer:
                    raise ValueError(t.t(f"{sec}.err_answer_required"))
                question["answer"] = answer

            elif q_type in ("single_choice", "multiple_choice"):
                choices = [c.strip() for c in self.edit_choices_field.toPlainText().split("\n") if c.strip()]
                if len(choices) < 2:
                    raise ValueError(t.t(f"{sec}.err_choices_min"))

                answer_text = self.edit_answer_field.text().strip()
                if not answer_text:
                    raise ValueError(t.t(f"{sec}.err_answer_required"))

                if q_type == "multiple_choice":
                    answers = [a.strip() for a in answer_text.split(",")]
                    for a in answers:
                        if a not in choices:
                            raise ValueError(t.t(f"{sec}.err_answer_not_in_choices", answer=a))
                    question["answer"] = answers
                else:
                    if answer_text not in choices:
                        raise ValueError(t.t(f"{sec}.err_answer_not_in_choices", answer=answer_text))
                    question["answer"] = answer_text

                question["choices"] = choices

            elif q_type == "true_false":
                question["answer"] = self.edit_tf_field.currentText() == "true"

            elif q_type == "matching":
                pairs_text = self.edit_pairs_field.toPlainText().strip()
                if not pairs_text:
                    raise ValueError(t.t(f"{sec}.err_pairs_required"))

                pairs = []
                for line in pairs_text.split("\n"):
                    if "|" not in line:
                        continue
                    left, right = line.split("|", 1)
                    pairs.append({"prompt": left.strip(), "answer": right.strip()})

                if not pairs:
                    raise ValueError(t.t(f"{sec}.err_pairs_format"))
                question["pairs"] = pairs

            elif q_type == "ordering":
                items = [i.strip() for i in self.edit_ordering_field.toPlainText().split("\n") if i.strip()]
                if len(items) < 2:
                    raise ValueError(t.t(f"{sec}.err_ordering_min"))
                question["answer"] = items

        except ValueError as e:
            QMessageBox.warning(self, t.t(f"{sec}.msg_validation_title"), str(e))
            return

        if self.current_editing_question_index is None:
            self.current_editing_questions.append(question)
        else:
            self.current_editing_questions[self.current_editing_question_index] = question

        self.controller.has_unsaved_changes = True
        self.stack.setCurrentWidget(self.quiz_editor_panel)
        self.refresh_question_list()
        QMessageBox.information(
            self,
            t.t(f"{sec}.msg_success_title"),
            t.t(f"{sec}.msg_question_saved")
        )

    def cancel_question_edit(self):
        self.stack.setCurrentWidget(self.quiz_editor_panel)
