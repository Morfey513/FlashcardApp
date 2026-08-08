# src/ui/quiz_view.py

import logging
from PyQt6.QtWidgets import (
    QWidget, QPushButton, QLabel, QVBoxLayout, QHBoxLayout,
    QListWidget, QLineEdit, QScrollArea, QStackedLayout, QFrame,
    QMessageBox, QComboBox, QFormLayout, QListWidgetItem, QProgressBar,
    QToolButton
)
from PyQt6.QtGui import QPixmap
from PyQt6.QtCore import Qt, QSize, pyqtSignal

from src.config import MAX_IMAGE_WIDTH, MAX_IMAGE_HEIGHT
from src.controllers.quiz_controller import QuizController
from src.logic.translator import get_translator

logger = logging.getLogger(__name__)


class QuizListRow(QFrame):
    """Quiz selector row with the active user's learning progress."""

    selected = pyqtSignal(str)
    moderation_clicked = pyqtSignal(str, str)

    def __init__(self, quiz, progress_text):
        super().__init__()
        self.quiz_name = quiz["name"]
        self.setObjectName("quiz_list_row")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(54)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(10)

        name = QLabel(quiz["name"])
        name.setObjectName("quiz_list_name")
        name.setMaximumWidth(300)
        layout.addWidget(name, 1)

        bar = QProgressBar()
        bar.setObjectName("quiz_progress_bar")
        bar.setRange(0, max(quiz["total"], 1))
        bar.setValue(quiz["mastered"])
        bar.setTextVisible(False)
        bar.setFixedWidth(120)
        layout.addWidget(bar)

        count = QLabel(progress_text)
        count.setObjectName("quiz_progress_text")
        count.setMinimumWidth(110)
        layout.addWidget(count)

        status = quiz.get("moderation_status", "published")
        is_actionable = quiz.get("can_view_moderation_reason", quiz.get("is_owner")) and status in {"rejected", "banned"}
        chip = QPushButton(
            f"{status.replace('_', ' ').title()} (info)" if is_actionable
            else status.replace("_", " ").title()
        )
        chip.setObjectName("content_status_chip")
        chip.setProperty("content_status", status)
        chip.setProperty("interactive", is_actionable)
        chip.setFixedSize(120, 30)
        if is_actionable:
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            chip.setToolTip("Click to view the moderator's reason")
            chip.clicked.connect(
                lambda _checked=False, value=status, reason=quiz.get("moderation_reason", ""):
                self.moderation_clicked.emit(value, reason)
            )
        else:
            chip.setCursor(Qt.CursorShape.ArrowCursor)
            chip.setEnabled(False)
        layout.addWidget(chip)


    def mousePressEvent(self, event):
        self.selected.emit(self.quiz_name)
        super().mousePressEvent(event)


class QuizViewer(QWidget):
    finished = pyqtSignal()

    def __init__(self, controller: QuizController):
        super().__init__()
        self.controller = controller
        self.translator = get_translator()

        self.setMinimumSize(900, 800)
        self.return_to_review = False
        self.answer_group = []
        self.answer_input = None

        self.stack = QStackedLayout()
        self.setLayout(self.stack)

        # Initialize all panels
        self.init_menu_panel()
        self.init_quiz_panel()
        self.init_review_panel()
        self.init_result_panel()

        self.retranslate_ui()
        self.stack.setCurrentWidget(self.menu_panel)

    def retranslate_ui(self):
        """Standardized method to update all text in the UI."""
        t = self.translator
        sec = "quiz_view"

        # Window Title
        self.setWindowTitle(t.t(f"{sec}.menu_title"))

        # Menu Panel
        self.menu_title_label.setText(t.t(f"{sec}.menu_title"))
        self.start_quiz_btn.setText(t.t(f"{sec}.btn_start_quiz"))
        self.return_launcher_btn.setText(t.t(f"{sec}.btn_return_launcher"))
        self.manage_progress_btn.setText(t.t(f"{sec}.btn_manage_progress"))
        self.refresh_quiz_list()

        # Quiz Panel
        self.quit_quiz_btn.setText(t.t(f"{sec}.btn_quit_quiz"))
        self.submit_btn.setText(t.t(f"{sec}.btn_submit"))
        self.next_btn.setText(t.t(f"{sec}.btn_skip"))
        self.preview_btn.setText(t.t(f"{sec}.btn_preview"))
        self.finish_btn.setText(t.t(f"{sec}.btn_finalize"))

        # Review Panel
        self.review_title_label.setText(t.t(f"{sec}.review_title"))
        self.back_to_quiz_btn.setText(t.t(f"{sec}.btn_back_to_quiz"))
        self.finish_quiz_btn.setText(t.t(f"{sec}.btn_finish_quiz"))

        # Result Panel
        self.done_btn.setText(t.t(f"{sec}.btn_done"))

        # If currently in a quiz or review, we need to refresh dynamic content
        if self.stack.currentWidget() == self.quiz_panel:
            # We refresh the current question to update Submit/Save buttons
            current_card = self.controller.get_current_card()
            if current_card:
                self.update_ui_with_question(current_card)

        elif self.stack.currentWidget() == self.review_panel:
            self.review_answers(save_current=False)

    # ======================
    # BRIDGE METHODS
    # ======================

    def update_ui_with_question(self, card_data):
        if not card_data:
            return
        t = self.translator

        self.progress_label.setText(self.controller.get_progress_text())
        self.question_label.setText(card_data.get("question", ""))

        # Handle Image
        img_path = card_data.get("image_path")
        self.image_label.setVisible(False)
        if img_path:
            full_path = self.controller.get_absolute_image_path(img_path)
            if full_path and full_path.exists():
                pix = QPixmap(str(full_path))
                self.image_label.setPixmap(pix.scaled(
                    MAX_IMAGE_WIDTH, MAX_IMAGE_HEIGHT,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                ))
                self.image_label.setVisible(True)

        self.render_answer_widget(card_data)

        # Navigation Logic with Localized text
        status = self.controller.get_navigation_status()
        if self.return_to_review:
            self.submit_btn.setText(t.t("quiz_view.btn_save_return"))
            self.submit_btn.setVisible(True)
            self.next_btn.setVisible(False)
            self.preview_btn.setVisible(False)
            self.finish_btn.setVisible(False)
        else:
            self.submit_btn.setText(t.t("quiz_view.btn_submit"))
            self.submit_btn.setVisible(status.get("show_submit", True))
            self.next_btn.setVisible(status.get("show_skip", True))
            self.preview_btn.setVisible(status.get("show_preview", False))
            self.finish_btn.setVisible(status.get("show_finish", False))

        if self.answer_input:
            self.answer_input.setFocus()

    def start_quiz_from_selection(self):
        item = self.quiz_list.currentItem()
        if not item:
            QMessageBox.warning(self,
                                self.translator.t("quiz_view.msg_no_selection_title"),
                                self.translator.t("quiz_view.msg_no_selection_text"))
            return

        quiz_name = item.data(Qt.ItemDataRole.UserRole) or item.text()
        if self.controller.is_quiz_complete(quiz_name):
            if not self.confirm_completed_quiz_reset(quiz_name):
                return
            self.controller.reset_quiz_progress(quiz_name)

        first_card = self.controller.load_quiz_by_name(quiz_name)
        if first_card:
            self.return_to_review = False
            self.update_ui_with_question(first_card)
            self.stack.setCurrentWidget(self.quiz_panel)

    def confirm_completed_quiz_reset(self, quiz_name):
        t = self.translator
        dialog = QMessageBox(self)
        dialog.setIcon(QMessageBox.Icon.Information)
        dialog.setWindowTitle(t.t("quiz_view.quiz_complete_title"))
        dialog.setText(t.t("quiz_view.quiz_complete_message", quiz=quiz_name))
        reset = dialog.addButton(
            t.t("quiz_view.btn_reset_and_restart"), QMessageBox.ButtonRole.AcceptRole
        )
        back = dialog.addButton(t.t("quiz_view.btn_completed_back"), QMessageBox.ButtonRole.RejectRole)
        dialog.setDefaultButton(back)
        dialog.exec()
        return dialog.clickedButton() is reset

    def submit_answer_and_next(self):
        user_input = self.get_user_input()
        if user_input is None and not self.return_to_review:
            t = self.translator
            QMessageBox.warning(self,
                                t.t("quiz_view.msg_required_title"),
                                t.t("quiz_view.msg_required_text"))
            return

        result = self.controller.submit_answer(user_input if user_input is not None else "")

        if self.return_to_review:
            logger.info("UI: Returning to review panel after edit.")
            self.return_to_review = False
            self.review_answers(save_current=False)
            return

        if result.get("type") == "review":
            self.review_answers(save_current=False)
        elif result.get("next_card"):
            self.update_ui_with_question(result["next_card"])

    # ======================
    # UI INITIALIZATION
    # ======================

    def init_menu_panel(self):
        self.menu_panel = QFrame()
        layout = QVBoxLayout(self.menu_panel)
        layout.setContentsMargins(50, 40, 50, 40)
        layout.setSpacing(20)

        self.menu_title_label = QLabel()
        self.menu_title_label.setObjectName("title")
        layout.addWidget(self.menu_title_label, alignment=Qt.AlignmentFlag.AlignCenter)

        self.quiz_list = QListWidget()
        self.quiz_list.setObjectName("quiz_learning_list")
        self.refresh_quiz_list()
        self.quiz_list.itemDoubleClicked.connect(self.start_quiz_from_selection)
        layout.addWidget(self.quiz_list)

        btn_container = QHBoxLayout()
        self.manage_progress_btn = QPushButton()
        self.manage_progress_btn.clicked.connect(self.show_manage_progress)
        self.start_quiz_btn = QPushButton()
        self.start_quiz_btn.setFixedSize(250, 60)
        self.start_quiz_btn.clicked.connect(self.start_quiz_from_selection)

        self.return_launcher_btn = QPushButton()
        self.return_launcher_btn.setObjectName("danger")
        self.return_launcher_btn.setFixedSize(250, 60)
        self.return_launcher_btn.clicked.connect(self.return_to_main)

        btn_container.addWidget(self.manage_progress_btn)
        btn_container.addStretch()
        btn_container.addWidget(self.return_launcher_btn)
        btn_container.addWidget(self.start_quiz_btn)
        layout.addLayout(btn_container)
        self.stack.addWidget(self.menu_panel)

    def init_quiz_panel(self):
        self.quiz_panel = QFrame()
        panel_layout = QVBoxLayout(self.quiz_panel)
        panel_layout.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setObjectName("quiz_scroll_area")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        content = QWidget()
        main_layout = QVBoxLayout(content)
        main_layout.setContentsMargins(60, 40, 60, 40)
        main_layout.setSpacing(20)

        self.progress_label = QLabel()
        self.progress_label.setObjectName("progress")
        main_layout.addWidget(self.progress_label)

        self.question_label = QLabel()
        self.question_label.setObjectName("question")
        self.question_label.setWordWrap(True)
        main_layout.addWidget(self.question_label)

        self.image_label = QLabel(alignment=Qt.AlignmentFlag.AlignCenter)
        self.image_label.setObjectName("quiz_image_holder")
        main_layout.addWidget(self.image_label)

        self.answer_container = QFrame()
        self.answer_layout = QVBoxLayout(self.answer_container)
        main_layout.addWidget(self.answer_container)

        main_layout.addStretch()

        btn_row = QHBoxLayout()
        self.quit_quiz_btn = QPushButton()
        self.quit_quiz_btn.setObjectName("danger")
        self.quit_quiz_btn.setFixedSize(180, 55)
        self.quit_quiz_btn.clicked.connect(self.return_to_menu)

        self.submit_btn = QPushButton()
        self.submit_btn.setFixedSize(180, 55)
        self.submit_btn.clicked.connect(self.submit_answer_and_next)

        self.next_btn = QPushButton()
        self.next_btn.setFixedSize(180, 55)
        self.next_btn.clicked.connect(self.next_question)

        self.preview_btn = QPushButton()
        self.preview_btn.setFixedSize(180, 55)
        self.preview_btn.clicked.connect(self.review_answers)
        self.preview_btn.hide()

        self.finish_btn = QPushButton()
        self.finish_btn.setFixedSize(180, 55)
        self.finish_btn.clicked.connect(self.finish_quiz)
        self.finish_btn.hide()

        btn_row.addWidget(self.quit_quiz_btn)
        btn_row.addStretch()
        btn_row.addWidget(self.submit_btn)
        btn_row.addWidget(self.next_btn)
        btn_row.addWidget(self.preview_btn)
        btn_row.addWidget(self.finish_btn)

        main_layout.addLayout(btn_row)
        scroll.setWidget(content)
        panel_layout.addWidget(scroll)
        self.stack.addWidget(self.quiz_panel)

    def init_review_panel(self):
        self.review_panel = QFrame()
        layout = QVBoxLayout(self.review_panel)
        layout.setContentsMargins(40, 40, 40, 40)

        self.review_title_label = QLabel()
        self.review_title_label.setObjectName("title")
        layout.addWidget(self.review_title_label, alignment=Qt.AlignmentFlag.AlignCenter)

        self.review_list_widget = QWidget()
        self.review_list_layout = QVBoxLayout(self.review_list_widget)

        scroll = QScrollArea()
        scroll.setObjectName("quiz_scroll_area")
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.review_list_widget)
        layout.addWidget(scroll)

        btn_row = QHBoxLayout()
        self.back_to_quiz_btn = QPushButton()
        self.back_to_quiz_btn.setFixedSize(180, 55)
        self.back_to_quiz_btn.clicked.connect(self.back_to_quiz)

        self.finish_quiz_btn = QPushButton()
        self.finish_quiz_btn.setFixedSize(180, 55)
        self.finish_quiz_btn.clicked.connect(self.finish_quiz)

        btn_row.addWidget(self.back_to_quiz_btn)
        btn_row.addStretch()
        btn_row.addWidget(self.finish_quiz_btn)
        layout.addLayout(btn_row)
        self.stack.addWidget(self.review_panel)

    def init_result_panel(self):
        self.result_panel = QFrame()
        layout = QVBoxLayout(self.result_panel)
        layout.setContentsMargins(40, 40, 40, 40)

        self.result_label = QLabel()
        self.result_label.setObjectName("result_title")
        self.result_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.result_label)

        self.result_list_widget = QWidget()
        self.result_list_layout = QVBoxLayout(self.result_list_widget)
        self.result_list_layout.setContentsMargins(10, 10, 10, 10)
        self.result_list_layout.setSpacing(8)

        scroll = QScrollArea()
        scroll.setObjectName("quiz_scroll_area")
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.result_list_widget)
        layout.addWidget(scroll)

        self.done_btn = QPushButton()
        self.done_btn.setFixedSize(220, 60)
        self.done_btn.clicked.connect(self.return_to_menu)
        layout.addWidget(self.done_btn, alignment=Qt.AlignmentFlag.AlignCenter)
        self.stack.addWidget(self.result_panel)

    # ======================
    # RENDERERS
    # ======================

    def render_answer_widget(self, card_data):
        self.clear_layout(self.answer_layout)
        self.answer_group = []
        self.answer_input = None
        self.combos = []
        t = self.translator
        q_type = card_data.get("type")

        if q_type in ("short_answer", "open", "text"):
            self.answer_input = QLineEdit()
            self.answer_layout.addWidget(self.answer_input)
            self.answer_group = [self.answer_input]

        elif q_type in ("true_false", "single_choice", "multiple_choice"):
            if q_type == "true_false":
                options = [t.t("quiz_view.option_true"), t.t("quiz_view.option_false")]
            else:
                options = card_data.get("options", [])

            for opt in options:
                btn = QPushButton(str(opt))
                btn.setCheckable(True)
                btn.setMinimumHeight(50)
                if q_type != "multiple_choice":
                    btn.clicked.connect(lambda _, b=btn: self.toggle_single_choice(b))
                self.answer_group.append(btn)
                self.answer_layout.addWidget(btn)

        elif q_type in ("matching", "ordering"):
            form = QFormLayout()
            self.combos = []
            prompts = card_data.get("prompts", [])
            dropdowns = [t.t("quiz_view.option_select")] + card_data.get("dropdown_options", [])

            for p_text in prompts:
                combo = QComboBox()
                combo.addItems(dropdowns)
                combo.currentIndexChanged.connect(self.validate_unique_selection)
                form.addRow(QLabel(p_text), combo)
                self.answer_group.append(combo)
                self.combos.append(combo)
            self.answer_layout.addLayout(form)

    def validate_unique_selection(self):
        """Visual feedback if the user selects the same thing twice."""
        selections = [c.currentText() for c in self.combos if c.currentIndex() > 0]
        duplicates = [item for item in selections if selections.count(item) > 1]

        for combo in self.combos:
            is_invalid = combo.currentText() in duplicates and combo.currentIndex() > 0
            combo.setProperty("invalid", is_invalid)
            # Dynamic properties are read when QSS is polished. Refresh only
            # this combo so the validation color follows the active theme.
            combo.style().unpolish(combo)
            combo.style().polish(combo)

    def show_results(self):
        t = self.translator
        stats = self.controller.get_final_results()

        score_label = t.t("quiz_view.result_score")
        self.result_label.setText(
            f"{score_label}: {stats['score']}/{stats['total']} ({stats['percent']}%)"
        )

        label_your_answer = t.t("quiz_view.result_your_answer")
        label_correct = t.t("quiz_view.result_correct")

        self.clear_layout(self.result_list_layout)
        for item in stats["results"]:
            row = QHBoxLayout()
            details = QLabel(
                f"<p><strong>{item['question']}</strong></p>"
                f"<p><i>{label_your_answer}:</i> {item['user_answer']}</p>"
                f"<p><i>{label_correct}:</i> {item['correct_answer']}</p>"
                f"<p><i>Attempts:</i> {item['stats']['correct']} correct, "
                f"{item['stats']['wrong']} wrong</p>"
            )
            details.setWordWrap(True)
            details.setTextFormat(Qt.TextFormat.RichText)
            row.addWidget(details, 1)

            if item["mastered"] or item["can_master"]:
                mastery_btn = QPushButton(
                    t.t("quiz_view.btn_unmaster_question")
                    if item["mastered"]
                    else t.t("quiz_view.btn_master_question")
                )
                mastery_btn.setObjectName("quiz_mastery_btn")
                mastery_btn.setFixedSize(150, 42)
                mastery_btn.clicked.connect(
                    lambda _, question_id=item["question_id"]: self.toggle_question_mastery(question_id)
                )
                row.addWidget(mastery_btn, alignment=Qt.AlignmentFlag.AlignRight)

            frame = QFrame()
            frame.setObjectName("quiz_result_row")
            frame.setLayout(row)
            self.result_list_layout.addWidget(frame)

        self.result_list_layout.addStretch()
        self.stack.setCurrentWidget(self.result_panel)

    def toggle_question_mastery(self, question_id):
        self.controller.toggle_question_mastery(question_id)
        self.show_results()

    def review_answers(self, save_current=True):
        t = self.translator
        if save_current:
            user_input = self.get_user_input()
            if user_input is not None:
                self.controller.submit_answer(user_input)

        self.clear_layout(self.review_list_layout)
        self.return_to_review = True
        summary = self.controller.get_review_summary()

        for i, item in enumerate(summary):
            row = QHBoxLayout()
            lbl = QLabel(f"<b>Q{i + 1}:</b> {item['question'][:60]}...")

            status_text = t.t("quiz_view.status_answered") if item['answered'] else t.t("quiz_view.status_unanswered")
            status_lbl = QLabel(status_text)

            edit_btn = QPushButton(t.t("quiz_view.btn_edit"))
            edit_btn.setFixedSize(70, 30)
            edit_btn.clicked.connect(lambda _, idx=i: self.jump_to_question(idx))

            row.addWidget(lbl)
            row.addStretch()
            row.addWidget(status_lbl)
            row.addWidget(edit_btn)

            frame = QFrame()
            frame.setObjectName("review_item_row")
            frame.setLayout(row)
            self.review_list_layout.addWidget(frame)

        self.review_list_layout.addStretch()
        self.stack.setCurrentWidget(self.review_panel)

    def finish_quiz(self):
        t = self.translator
        if self.stack.currentWidget() == self.quiz_panel:
            ui_ans = self.get_user_input()
            if ui_ans is not None:
                self.controller.submit_answer(ui_ans)

        if self.controller.has_unanswered():
            ret = QMessageBox.question(
                self, t.t("quiz_view.msg_unfinished_title"),
                t.t("quiz_view.msg_unfinished_text"),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if ret == QMessageBox.StandardButton.No:
                return

        self.show_results()

    def get_user_input(self):
        """Safely extracts data without using sip."""
        try:
            # 1. Text-based
            # Check if the attribute exists AND isn't None
            if getattr(self, 'answer_input', None):
                # The try block catches the 'wrapped C/C++ object deleted' error
                try:
                    val = self.answer_input.text().strip()
                    return val if val else None
                except RuntimeError:
                    # Widget was deleted by clear_layout
                    self.answer_input = None
                    return None

            # 2. Group-based (Buttons/Combos)
            if hasattr(self, 'answer_group') and self.answer_group:
                try:
                    # Test the first widget to see if it's alive
                    _ = self.answer_group[0].isVisible()
                except (RuntimeError, IndexError):
                    self.answer_group = []
                    return None

                # Choice-based
                if isinstance(self.answer_group[0], QPushButton):
                    selected = [btn.text() for btn in self.answer_group if btn.isChecked()]
                    if not selected:
                        return None

                    card_type = self.controller.get_current_card_type()
                    return selected if card_type == "multiple_choice" else selected[0]

                # Selection-based
                if isinstance(self.answer_group[0], QComboBox):
                    selections = [combo.currentText() for combo in self.answer_group]
                    card_type = self.controller.get_current_card_type()
                    if card_type == "matching":
                        keys = self.controller.get_current_matching_keys()
                        return [{"prompt": k, "answer": v} for k, v in zip(keys, selections)]
                    return selections

        except Exception as e:
            logger.error(f"UI: Error in get_user_input: {e}")
            return None

        return None

    def jump_to_question(self, index):
        logger.debug(f"UI: Jumping to question index {index}")
        card_data = self.controller.jump_to(index)

        if card_data:
            self.return_to_review = True
            self.update_ui_with_question(card_data)
            self.stack.setCurrentWidget(self.quiz_panel)

    def next_question(self):
        next_card = self.controller.skip_question()
        if next_card:
            self.update_ui_with_question(next_card)

    def return_to_main(self):
        self.finished.emit()

    def return_to_menu(self):
        self.refresh_quiz_list()
        self.stack.setCurrentWidget(self.menu_panel)

    def reset_quiz_progress(self, quiz_name):
        t = self.translator
        answer = QMessageBox.question(
            self,
            t.t("quiz_view.confirm_reset_title"),
            t.t("quiz_view.confirm_reset_message", quiz=quiz_name),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.controller.reset_quiz_progress(quiz_name)
            self.refresh_quiz_list()

    def clear_all_quiz_progress(self):
        t = self.translator
        answer = QMessageBox.question(
            self,
            t.t("quiz_view.confirm_clear_title"),
            t.t("quiz_view.confirm_clear_message"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.controller.clear_all_progress()
            self.refresh_quiz_list()

    def show_manage_progress(self):
        """Open the centralized progress manager for this user."""
        from src.controllers.profile_statistics_controller import ProfileStatisticsController
        from src.ui.profile_statistics_dialog import ProfileStatisticsDialog
        dialog = ProfileStatisticsDialog(ProfileStatisticsController(self.controller.user_id), self)
        dialog.exec()
        self.refresh_quiz_list()

    def back_to_quiz(self):
        self.stack.setCurrentWidget(self.quiz_panel)

    def clear_layout(self, layout):
        if layout:
            while layout.count():
                item = layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
                elif item.layout():
                    self.clear_layout(item.layout())

    def toggle_single_choice(self, selected_btn):
        for btn in self.answer_group:
            btn.setChecked(btn is selected_btn)

    def refresh_quiz_list(self):
        """Helper to sync the list with the repository index."""
        self.quiz_list.clear()
        t = self.translator
        for quiz in self.controller.get_quiz_summaries():
            row = QuizListRow(quiz, t.t("quiz_view.quiz_progress", mastered=quiz["mastered"], total=quiz["total"]))
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, quiz["name"])
            item.setSizeHint(QSize(0, 58))
            self.quiz_list.addItem(item)
            self.quiz_list.setItemWidget(item, row)
            row.selected.connect(lambda name, current=item: self.select_quiz(name, current))
            row.moderation_clicked.connect(self.show_moderation_reason)
        if self.quiz_list.count():
            self.quiz_list.setCurrentRow(0)

    def select_quiz(self, quiz_name, item):
        if quiz_name:
            self.quiz_list.setCurrentItem(item)

    def show_moderation_reason(self, status, reason):
        if status not in {"rejected", "banned"}:
            QMessageBox.information(self, "Content status", f"Status: {status.replace('_', ' ').title()}")
            return
        QMessageBox.information(
            self,
            f"Content {status.title()}",
            f"Status: {status.title()}\n\nReason: {reason or 'No reason was provided by the moderator.'}",
        )
