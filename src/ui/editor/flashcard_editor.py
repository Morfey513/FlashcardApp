# src/ui/editor/flashcard_editor.py

import logging
from functools import partial

from PyQt6.QtWidgets import (
    QWidget, QPushButton, QLabel, QVBoxLayout, QHBoxLayout, QGridLayout,
    QListWidget, QListWidgetItem, QLineEdit, QStackedLayout, QFrame,
    QMessageBox, QTextEdit, QInputDialog, QFileDialog, QToolButton, QComboBox, QApplication, QToolTip, QSizePolicy
)
from PyQt6.QtGui import QPixmap, QCursor
from PyQt6.QtCore import Qt, QSize, pyqtSignal

from src.config import AUDIO_DIR, IMAGE_DIR
from src.controllers.flashcard_editor_controller import FlashcardEditorController
from src.logic.access_control import VISIBILITIES, VISIBILITY_LABELS, default_visibility_for_status
from src.logic.translator import get_translator
from src.ui.auto_scroll import AutoScrollArea
from src.ui.scrolling_label import ScrollingLabel
from src.ui.status_badge import format_status_badge, show_moderation_reason

logger = logging.getLogger(__name__)


class FlashcardEditor(QWidget):
    finished = pyqtSignal()

    def __init__(self, controller: FlashcardEditorController):
        super().__init__()
        self.controller = controller
        self.translator = get_translator()
        self.resize(900, 700)
        self.setMinimumSize(700, 560)

        # UI State
        self.has_unsaved_changes = False
        self.current_editing_cards = []
        self.current_editing_card_index = None
        self.current_content_banned = False

        self.stack = QStackedLayout()
        self.setLayout(self.stack)

        self.init_deck_menu_panel()
        self.init_deck_editor_panel()
        self.init_card_editor_panel()

        self.retranslate_ui()
        self.stack.setCurrentWidget(self.deck_menu_panel)
        self.refresh_deck_list()
        logger.info("Flashcard Editor initialized.")

    def retranslate_ui(self):
        """Standardized method to update all text in the UI."""
        t = self.translator
        sec = "flashcard_editor"

        self.setWindowTitle(t.t(f"{sec}.title"))

        # Deck menu panel
        self.deck_menu_title.setText(t.t(f"{sec}.title"))
        self.deck_menu_subtitle.setText(t.t(f"{sec}.subtitle"))
        self.create_deck_btn.setText("+ " + t.t(f"{sec}.btn_create_deck"))
        self.back_to_main_btn.setText(t.t(f"{sec}.btn_back_to_main"))

        # Deck editor panel
        self.add_card_btn.setText("+ " + t.t(f"{sec}.btn_add_card"))
        self.back_to_menu_btn.setText(t.t(f"{sec}.btn_back_to_menu"))
        self.visibility_label.setText("Visibility:")
        self.save_deck_btn.setText("Save Changes")

        # Card editor panel
        self.card_editor_title.setText(t.t(f"{sec}.card_editor_title"))
        self.front_label.setText(t.t(f"{sec}.label_front"))
        self.edit_front.setPlaceholderText(t.t(f"{sec}.placeholder_front"))
        self.back_label.setText(t.t(f"{sec}.label_back"))
        self.edit_back.setPlaceholderText(t.t(f"{sec}.placeholder_back"))
        self.hint_label.setText(t.t(f"{sec}.label_hint"))
        self.edit_hint.setPlaceholderText(t.t(f"{sec}.placeholder_hint"))
        self.desc_label.setText(t.t(f"{sec}.label_description"))
        self.edit_description.setPlaceholderText(t.t(f"{sec}.placeholder_description"))
        self.image_label.setText(t.t(f"{sec}.label_image"))
        self.edit_has_image_btn.setText(t.t(f"{sec}.btn_add_image"))
        self.edit_image_path.setPlaceholderText(t.t(f"{sec}.placeholder_image_path"))
        self.browse_image_btn.setText(t.t(f"{sec}.btn_browse"))
        self.audio_label.setText(t.t(f"{sec}.label_audio"))
        self.edit_has_audio_btn.setText(t.t(f"{sec}.btn_add_audio"))
        for field, path_input in self.edit_audio_paths.items():
            self.audio_field_labels[field].setText(t.t(f"{sec}.label_audio_{field}"))
            path_input.setPlaceholderText(t.t(f"{sec}.placeholder_audio_path"))
            self.browse_audio_btns[field].setText(t.t(f"{sec}.btn_browse"))
        self.cancel_card_btn.setText(t.t(f"{sec}.btn_cancel"))
        self.save_card_btn.setText(t.t(f"{sec}.btn_save_card"))

    # =========================================================
    # Deck Management Panel
    # =========================================================

    def init_deck_menu_panel(self):
        self.deck_menu_panel = QFrame()
        layout = QVBoxLayout(self.deck_menu_panel)
        layout.setContentsMargins(40, 40, 40, 40)
        layout.setSpacing(14)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)

        self.deck_menu_title = QLabel()
        self.deck_menu_title.setObjectName("title")
        self.deck_menu_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.deck_menu_title)

        self.deck_menu_subtitle = QLabel()
        self.deck_menu_subtitle.setObjectName("subtitle")
        self.deck_menu_subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.deck_menu_subtitle)

        header = QHBoxLayout()
        header.addStretch()
        self.create_deck_btn = QPushButton()
        self.create_deck_btn.clicked.connect(self.create_new_deck)
        header.addWidget(self.create_deck_btn)
        layout.addLayout(header)

        self.deck_list = QListWidget()
        self.deck_list.setObjectName("editor_deck_list")
        self.deck_list.setSpacing(6)
        # Let the list absorb window-height changes while the navigation
        # button remains a separate footer below it.
        self.deck_list.setMinimumHeight(160)
        self.deck_list.itemDoubleClicked.connect(self.edit_selected_deck)
        self.deck_list.currentRowChanged.connect(lambda _row: self._sync_inline_selection(self.deck_list))
        layout.addWidget(self.deck_list, stretch=1)

        self.back_to_main_btn = QPushButton()
        self.back_to_main_btn.setMinimumWidth(200)
        self.back_to_main_btn.clicked.connect(self.return_to_main)
        layout.addWidget(self.back_to_main_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        self.stack.addWidget(self.deck_menu_panel)

    def init_deck_editor_panel(self):
        self.deck_editor_panel = QFrame()
        layout = QVBoxLayout(self.deck_editor_panel)
        layout.setContentsMargins(40, 40, 40, 40)
        layout.setSpacing(20)

        title_row = QHBoxLayout()
        self.deck_editor_title = QLabel()
        self.deck_editor_title.setObjectName("title")
        self.deck_editor_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_row.addWidget(self.deck_editor_title)
        self.add_card_btn = QPushButton()
        self.add_card_btn.clicked.connect(self.add_new_card)
        title_row.addWidget(self.add_card_btn)
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

        self.card_list = QListWidget()
        self.card_list.setObjectName("editor_card_list")
        self.card_list.setSpacing(6)
        self.card_list.setMinimumHeight(350)
        self.card_list.itemDoubleClicked.connect(self.edit_selected_card)
        self.card_list.currentRowChanged.connect(lambda _row: self._sync_inline_selection(self.card_list))
        layout.addWidget(self.card_list)

        nav_btn_layout = QHBoxLayout()

        self.back_to_menu_btn = QPushButton()
        self.back_to_menu_btn.clicked.connect(self.back_to_deck_menu_with_warning)
        nav_btn_layout.addWidget(self.back_to_menu_btn)

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

        self.save_deck_btn = QPushButton()
        self.save_deck_btn.setObjectName("publish_btn")
        self.save_deck_btn.clicked.connect(self.save_current_deck)
        nav_btn_layout.addWidget(self.save_deck_btn)

        layout.addLayout(nav_btn_layout)
        self.invite_toolbar = QFrame()
        self.invite_toolbar.setObjectName("invite_code_toolbar")
        invite_layout = QHBoxLayout(self.invite_toolbar)
        self.invite_code_label = QLabel()
        invite_layout.addWidget(self.invite_code_label)
        invite_layout.addStretch()
        self.copy_invite_btn = QPushButton("Copy Code")
        self.copy_invite_btn.clicked.connect(self.copy_current_invite_code)
        invite_layout.addWidget(self.copy_invite_btn)
        self.rotate_invite_btn = QPushButton()
        self.rotate_invite_btn.clicked.connect(self.generate_or_rotate_current_invite_code)
        invite_layout.addWidget(self.rotate_invite_btn)
        self.invite_toolbar.hide()
        layout.addWidget(self.invite_toolbar)

        self.stack.addWidget(self.deck_editor_panel)

    def init_card_editor_panel(self):
        self.card_editor_panel = QFrame()

        scroll = AutoScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        content_widget = QWidget()
        layout = QVBoxLayout(content_widget)
        layout.setContentsMargins(40, 40, 40, 40)
        layout.setSpacing(20)

        self.card_editor_title = QLabel()
        self.card_editor_title.setObjectName("title")
        self.card_editor_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.card_editor_title)

        # Front
        self.front_label = QLabel()
        self.front_label.setObjectName("flashcard_editor_label")
        layout.addWidget(self.front_label)
        self.edit_front = QTextEdit()
        self.edit_front.setMinimumHeight(80)
        self.edit_front.setMaximumHeight(100)
        layout.addWidget(self.edit_front)

        # Back
        self.back_label = QLabel()
        self.back_label.setObjectName("flashcard_editor_label")
        layout.addWidget(self.back_label)
        self.edit_back = QTextEdit()
        self.edit_back.setMinimumHeight(80)
        self.edit_back.setMaximumHeight(100)
        layout.addWidget(self.edit_back)

        # Hint
        self.hint_label = QLabel()
        self.hint_label.setObjectName("flashcard_editor_label")
        layout.addWidget(self.hint_label)
        self.edit_hint = QLineEdit()
        layout.addWidget(self.edit_hint)

        # Description
        self.desc_label = QLabel()
        self.desc_label.setObjectName("flashcard_editor_label")
        layout.addWidget(self.desc_label)
        self.edit_description = QTextEdit()
        self.edit_description.setMinimumHeight(80)
        self.edit_description.setMaximumHeight(100)
        layout.addWidget(self.edit_description)

        # Image section
        image_section = QFrame()
        image_section.setObjectName("flashcard_editor_section")
        image_layout = QVBoxLayout(image_section)

        self.image_label = QLabel()
        self.image_label.setObjectName("flashcard_editor_label")
        image_layout.addWidget(self.image_label)

        self.edit_has_image_btn = QPushButton()
        self.edit_has_image_btn.setCheckable(True)
        self.edit_has_image_btn.clicked.connect(self.toggle_image_section)
        image_layout.addWidget(self.edit_has_image_btn)

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
        self.edit_image_preview.setObjectName("flashcard_editor_preview")
        self.edit_image_preview.setMaximumHeight(200)
        img_container_layout.addWidget(self.edit_image_preview)

        image_layout.addWidget(self.edit_image_container)
        layout.addWidget(image_section)

        # Audio section
        audio_section = QFrame()
        audio_section.setObjectName("flashcard_editor_section")
        audio_layout = QVBoxLayout(audio_section)

        self.audio_label = QLabel()
        self.audio_label.setObjectName("flashcard_editor_label")
        audio_layout.addWidget(self.audio_label)

        self.edit_has_audio_btn = QPushButton()
        self.edit_has_audio_btn.setCheckable(True)
        self.edit_has_audio_btn.clicked.connect(self.toggle_audio_section)
        audio_layout.addWidget(self.edit_has_audio_btn)

        self.edit_audio_container = QFrame()
        self.edit_audio_container.hide()
        audio_container_layout = QVBoxLayout(self.edit_audio_container)
        self.edit_audio_paths = {}
        self.audio_field_labels = {}
        self.browse_audio_btns = {}
        for field in ("front", "back", "hint", "description"):
            field_layout = QHBoxLayout()
            field_label = QLabel()
            field_label.setText(self.translator.t(f"flashcard_editor.label_audio_{field}"))
            self.audio_field_labels[field] = field_label
            field_layout.addWidget(field_label)
            path_input = QLineEdit()
            path_input.setPlaceholderText(self.translator.t("flashcard_editor.placeholder_audio_path"))
            self.edit_audio_paths[field] = path_input
            field_layout.addWidget(path_input)
            browse_button = QPushButton()
            browse_button.setText(self.translator.t("flashcard_editor.btn_browse"))
            browse_button.clicked.connect(partial(self.browse_audio, field))
            self.browse_audio_btns[field] = browse_button
            field_layout.addWidget(browse_button)
            audio_container_layout.addLayout(field_layout)

        audio_layout.addWidget(self.edit_audio_container)
        layout.addWidget(audio_section)

        # Buttons
        layout.addSpacing(20)
        btn_layout = QHBoxLayout()

        self.cancel_card_btn = QPushButton()
        self.cancel_card_btn.setObjectName("danger")
        self.cancel_card_btn.clicked.connect(self.cancel_card_edit)
        btn_layout.addWidget(self.cancel_card_btn)

        btn_layout.addStretch()

        self.save_card_btn = QPushButton()
        self.save_card_btn.clicked.connect(self.save_card_edit)
        btn_layout.addWidget(self.save_card_btn)

        layout.addLayout(btn_layout)

        scroll.setWidget(content_widget)
        scroll.track_auto_scroll_content(content_widget)
        scroll.setToolTip("Middle-click to auto-scroll; press Escape to stop")
        panel_layout = QVBoxLayout(self.card_editor_panel)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        panel_layout.addWidget(scroll)

        self.stack.addWidget(self.card_editor_panel)

    # =========================================================
    # Repository Integration
    # =========================================================

    def refresh_deck_list(self):
        self.deck_list.clear()
        for deck in self.controller.get_deck_entries():
            self._add_deck_row(
                deck["name"], deck["status"], deck.get("visibility", "private"),
                deck.get("moderation_reason", ""),
            )
        self._sync_inline_selection(self.deck_list)

    def _add_deck_row(self, name, status, visibility, moderation_reason=""):
        item = QListWidgetItem()
        item.setData(Qt.ItemDataRole.UserRole, name)
        row = QWidget()
        row.setObjectName("editor_inline_row")
        row.setMinimumHeight(54)
        layout = QGridLayout(row)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(10)
        label = ScrollingLabel(name)
        label.setObjectName("editor_row_label")
        label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        label.setToolTip(name)
        layout.addWidget(label, 0, 0)
        displayed_status = visibility if status == "published" else status
        is_actionable = status in {"rejected", "banned"}
        status_label = QPushButton(format_status_badge(
            displayed_status,
            f"{status.replace('_', ' ').title()} (info)" if is_actionable else None,
        ))
        status_label.setObjectName("content_status_chip")
        status_label.setProperty("content_status", displayed_status)
        status_label.setProperty("interactive", is_actionable)
        status_label.setFixedHeight(30)
        status_label.setFixedWidth(max(78, status_label.sizeHint().width()))
        if is_actionable:
            status_label.setCursor(Qt.CursorShape.PointingHandCursor)
            status_label.setToolTip("Click to view the moderator's reason")
            status_label.clicked.connect(
                lambda _checked=False: show_moderation_reason(self, status, moderation_reason)
            )
        else:
            status_label.setCursor(Qt.CursorShape.ArrowCursor)
            status_label.setEnabled(False)
        status_slot = QWidget()
        status_slot.setObjectName("content_status_slot")
        status_slot.setFixedWidth(120)
        status_slot_layout = QHBoxLayout(status_slot)
        status_slot_layout.setContentsMargins(0, 0, 0, 0)
        status_slot_layout.addWidget(status_label, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(status_slot, 0, 1)
        code_button = QPushButton()
        code_button.setFixedSize(30, 30)
        code_button.setObjectName("inline_action")
        if visibility == "class_only":
            code_button.setText("🔑️")
            code_button.setToolTip("Copy invitation code")
            code_button.clicked.connect(lambda: self.copy_invite_code(name))
        else:
            code_button.setEnabled(False)
        layout.addWidget(code_button, 0, 2, alignment=Qt.AlignmentFlag.AlignCenter)
        for column, (icon, tooltip, action) in enumerate((
            ("✏", "Edit", lambda: self.edit_deck_by_name(name)),
            ("⧉", "Copy", lambda: self.copy_deck_by_name(name)),
            ("🗑️", "Delete", lambda: self.delete_deck_by_name(name)),
        ), start=3):
            button = QPushButton()
            button.setText(icon)
            button.setToolTip(tooltip)
            button.setObjectName("inline_action")
            button.setFixedSize(30, 30)
            button.clicked.connect(action)
            layout.addWidget(button, 0, column, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.setColumnStretch(0, 1)
        layout.setColumnMinimumWidth(1, 120)
        for column in range(2, 6):
            layout.setColumnMinimumWidth(column, 44)
        item.setSizeHint(QSize(0, 54))
        self.deck_list.addItem(item)
        self.deck_list.setItemWidget(item, row)

    @staticmethod
    def _sync_inline_selection(list_widget):
        selected_row = list_widget.currentRow()
        for index in range(list_widget.count()):
            row = list_widget.itemWidget(list_widget.item(index))
            if row is None:
                continue
            row.setProperty("selected", index == selected_row)
            row.style().unpolish(row)
            row.style().polish(row)

    def create_new_deck(self):
        t = self.translator
        sec = "flashcard_editor"
        name, ok = QInputDialog.getText(
            self,
            t.t(f"{sec}.dialog_create_title"),
            t.t(f"{sec}.dialog_create_label")
        )
        if ok and name:
            if self.controller.create_deck(name):
                self.refresh_deck_list()
                QMessageBox.information(
                    self,
                    t.t(f"{sec}.msg_success_title"),
                    t.t(f"{sec}.msg_deck_created", name=name)
                )

    def edit_selected_deck(self):
        item = self.deck_list.currentItem()
        if item:
            self.edit_deck_by_name(item.data(Qt.ItemDataRole.UserRole) or item.text())

    def edit_deck_by_name(self, name):
        if self.controller.load_deck(name):
            self.current_editing_cards = self.controller.current_cards
            self.open_deck_editor(name)

    def copy_selected_deck(self):
        t = self.translator
        sec = "flashcard_editor"
        item = self.deck_list.currentItem()
        if not item:
            return

        self.copy_deck_by_name(item.data(Qt.ItemDataRole.UserRole) or item.text())

    def copy_deck_by_name(self, original_name):
        t = self.translator
        sec = "flashcard_editor"

        new_name, ok = QInputDialog.getText(
            self,
            t.t(f"{sec}.dialog_copy_title"),
            t.t(f"{sec}.dialog_copy_label"),
            text=f"{original_name} Copy"
        )

        if ok and new_name:
            if self.controller.copy_deck(original_name, new_name):
                self.refresh_deck_list()
                QMessageBox.information(
                    self,
                    t.t(f"{sec}.msg_success_title"),
                    t.t(f"{sec}.msg_deck_copied")
                )
            else:
                QMessageBox.warning(
                    self,
                    t.t(f"{sec}.msg_error_title"),
                    t.t(f"{sec}.msg_copy_failed")
                )

    def delete_selected_deck(self):
        t = self.translator
        sec = "flashcard_editor"
        item = self.deck_list.currentItem()
        if not item:
            return

        self.delete_deck_by_name(item.data(Qt.ItemDataRole.UserRole) or item.text())

    def delete_deck_by_name(self, deck_name):
        t = self.translator
        sec = "flashcard_editor"

        ret = QMessageBox.question(
            self,
            t.t(f"{sec}.dialog_delete_title"),
            t.t(f"{sec}.dialog_delete_deck_text", name=deck_name)
        )

        if ret == QMessageBox.StandardButton.Yes:
            delete_result = getattr(self.controller, "delete_deck_result", None)
            result = (
                delete_result(deck_name) if callable(delete_result)
                else {"status": "deleted" if self.controller.delete_deck(deck_name) else "failed"}
            )
            outcome = result.get("status")
            if outcome in {"deleted", "not_found"}:
                self.refresh_deck_list()
            if outcome == "not_found":
                QMessageBox.information(self, "Deck not found", "This deck no longer exists.")
            elif outcome == "forbidden":
                QMessageBox.warning(self, "Deletion rejected", "You are not authorized to delete this deck.")
            elif outcome != "deleted":
                QMessageBox.warning(self, "Delete failed", "The deck could not be deleted.")

    def open_deck_editor(self, deck_name):
        t = self.translator
        self.deck_editor_title.setText(
            t.t("flashcard_editor.editing_deck", name=deck_name)
        )
        self._update_moderation_banner()
        self.refresh_card_list()
        self.stack.setCurrentWidget(self.deck_editor_panel)

    def _update_moderation_banner(self):
        metadata = self.controller.get_current_moderation()
        status = metadata.get("status", "draft")
        visibility = metadata.get("visibility", default_visibility_for_status(status))
        self.visibility_selector.setCurrentIndex(max(0, self.visibility_selector.findData(visibility)))
        self._update_invite_code_toolbar()
        reason = metadata.get("review_note", "").strip() or "No moderation reason was provided."
        self.current_content_banned = status == "banned"
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
        for widget in (self.add_card_btn, self.card_list, self.visibility_selector, self.save_deck_btn):
            widget.setEnabled(not self.current_content_banned)

    def _update_invite_code_toolbar(self):
        class_only = self.visibility_selector.currentData() == "class_only"
        self.invite_toolbar.setVisible(class_only and not self.current_content_banned)
        if not class_only:
            return
        code = self.controller.get_current_invite_code()
        self.invite_code_label.setText(f"🔑 Active Code: {code}" if code else "🔑 No code generated yet")
        self.copy_invite_btn.setEnabled(bool(code))
        self.rotate_invite_btn.setText("Rotate Code" if code else "Generate Code")

    def copy_invite_code(self, name):
        code = self.controller.get_invite_code(name)
        if not code:
            QMessageBox.information(self, "No invitation code", "Set this deck to Class-Only, then generate a code in its editor.")
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

    def refresh_card_list(self):
        self.card_list.clear()
        for idx, card in enumerate(self.controller.current_cards):
            front_preview = card.get('front', 'Untitled')[:50]
            item = QListWidgetItem()
            row = QWidget()
            row.setObjectName("editor_inline_row")
            row.setMinimumHeight(42)
            layout = QHBoxLayout(row)
            layout.setContentsMargins(10, 3, 10, 3)
            label = QLabel(f"{idx + 1}. {front_preview}...")
            label.setObjectName("editor_row_label")
            layout.addWidget(label)
            layout.addStretch()
            for icon, tooltip, action in (
                ("✏", "Edit", lambda _=False, value=idx: self.edit_card_at(value)),
                ("⧉", "Copy", lambda _=False, value=idx: self.copy_card_at(value)),
                ("🗑️", "Delete", lambda _=False, value=idx: self.delete_card_at(value)),
            ):
                button = QPushButton()
                button.setText(icon)
                button.setToolTip(tooltip)
                button.setObjectName("inline_action")
                button.clicked.connect(action)
                layout.addWidget(button)
            item.setSizeHint(QSize(0, 42))
            self.card_list.addItem(item)
            self.card_list.setItemWidget(item, row)
        self._sync_inline_selection(self.card_list)

    def save_current_deck(self):
        t = self.translator
        sec = "flashcard_editor"
        logger.info("ACTION: Saving deck changes.")

        visibility = self.visibility_selector.currentData()
        if self.controller.save_deck(self.current_editing_cards, visibility=visibility):
            self.has_unsaved_changes = False
            message = (
                "Deck saved as a private draft."
                if visibility == "private"
                else "Deck submitted for moderation."
            )
            QMessageBox.information(
                self,
                t.t(f"{sec}.msg_success_title"),
                message,
            )
            return True

        QMessageBox.critical(
            self,
            t.t(f"{sec}.msg_error_title"),
            t.t(f"{sec}.msg_save_failed")
        )
        return False

    def publish_current_deck(self):
        """Backward-compatible programmatic shortcut for public submission."""
        self.visibility_selector.setCurrentIndex(self.visibility_selector.findData("public"))
        return self.save_current_deck()

    def maybe_save_changes(self):
        """Unified check for unsaved changes."""
        has_changes = self.has_unsaved_changes or self.controller.has_unsaved_changes
        logger.debug(f"STATE: Checking for unsaved changes. Result: {has_changes}")

        if not has_changes:
            return True

        t = self.translator
        sec = "flashcard_editor"

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
            logger.info("USER: Chose SAVE.")
            return self.save_current_deck()
        elif ret == QMessageBox.StandardButton.Discard:
            logger.info("USER: Chose DISCARD.")
            self.has_unsaved_changes = False
            self.controller.has_unsaved_changes = False
            return True

        logger.info("USER: Chose CANCEL.")
        return False

    def closeEvent(self, event):
        logger.info("EVENT: closeEvent triggered.")
        if self.maybe_save_changes():
            logger.info("EVENT: closeEvent accepted.")
            self.blockSignals(True)
            self.finished.emit()
            event.accept()
        else:
            logger.info("EVENT: closeEvent ignored.")
            event.ignore()

    def return_to_main(self):
        logger.info("NAV: 'Back to Main' clicked.")
        if self.maybe_save_changes():
            logger.info("NAV: Proceeding to return to main menu.")
            self.finished.emit()
        else:
            logger.info("NAV: Return to main cancelled by user.")

    def back_to_deck_menu_with_warning(self):
        logger.info("NAV: Returning to deck menu.")
        if not self.maybe_save_changes():
            return

        self.setUpdatesEnabled(False)
        try:
            self.stack.setCurrentWidget(self.deck_menu_panel)
            self.refresh_deck_list()
            logger.info("NAV: Switch successful.")
        finally:
            self.setUpdatesEnabled(True)

    # =========================================================
    # Card Management Methods
    # =========================================================

    def add_new_card(self):
        logger.debug("Opening Card Editor for a NEW card.")
        self.current_editing_card_index = None
        self.load_card_editor({
            "front": "", "back": "", "hint": "",
            "description": "", "image": "", "audio": {}
        })

    def edit_selected_card(self):
        t = self.translator
        item = self.card_list.currentItem()
        if not item:
            QMessageBox.warning(
                self,
                t.t("flashcard_editor.msg_no_selection_title"),
                t.t("flashcard_editor.msg_no_selection_text")
            )
            return

        idx = self.card_list.currentRow()
        if idx < 0:
            return

        self.current_editing_card_index = idx
        self.load_card_editor(self.controller.current_cards[idx])

    def edit_card_at(self, index):
        self.card_list.setCurrentRow(index)
        self.edit_selected_card()

    def copy_selected_card(self):
        idx = self.card_list.currentRow()
        if idx >= 0:
            if self.controller.duplicate_card(idx):
                self.refresh_card_list()

    def copy_card_at(self, index):
        self.card_list.setCurrentRow(index)
        self.copy_selected_card()

    def delete_selected_card(self):
        t = self.translator
        sec = "flashcard_editor"
        idx = self.card_list.currentRow()
        if idx < 0:
            return

        ret = QMessageBox.question(
            self,
            t.t(f"{sec}.dialog_delete_title"),
            t.t(f"{sec}.dialog_delete_card_text")
        )
        if ret == QMessageBox.StandardButton.Yes:
            if self.controller.remove_card(idx):
                self.refresh_card_list()

    def delete_card_at(self, index):
        self.card_list.setCurrentRow(index)
        self.delete_selected_card()

    # =========================================================
    # Card Editor Methods
    # =========================================================

    def load_card_editor(self, card_data):
        self.edit_front.setPlainText(card_data.get("front", ""))
        self.edit_back.setPlainText(card_data.get("back", ""))
        self.edit_hint.setText(card_data.get("hint", ""))
        self.edit_description.setPlainText(card_data.get("description", ""))

        has_image = bool(card_data.get("image"))
        self.edit_has_image_btn.setChecked(has_image)
        self.edit_image_container.setVisible(has_image)
        self.edit_image_path.setText(card_data.get("image", ""))
        if has_image and card_data.get("image"):
            self.update_image_preview(card_data.get("image"))

        stored_audio = card_data.get("audio", {})
        if isinstance(stored_audio, str):
            stored_audio = {"front": stored_audio}
        has_audio = bool(stored_audio)
        self.edit_has_audio_btn.setChecked(has_audio)
        self.edit_audio_container.setVisible(has_audio)
        for field, path_input in self.edit_audio_paths.items():
            path_input.setText(stored_audio.get(field, ""))

        self.stack.setCurrentWidget(self.card_editor_panel)

    def toggle_image_section(self):
        self.edit_image_container.setVisible(self.edit_has_image_btn.isChecked())

    def toggle_audio_section(self):
        self.edit_audio_container.setVisible(self.edit_has_audio_btn.isChecked())

    def browse_image(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, self.translator.t("flashcard_editor.dialog_select_image"),
            str(IMAGE_DIR), "Images (*.png *.jpg *.jpeg *.webp *.gif)"
        )
        if file_path:
            rel_path = self.controller.process_image_path(file_path)
            self.edit_image_path.setText(rel_path)
            self.update_image_preview(rel_path)

    def browse_audio(self, field):
        file_path, _ = QFileDialog.getOpenFileName(
            self, self.translator.t("flashcard_editor.dialog_select_audio"),
            str(AUDIO_DIR), "Audio (*.mp3 *.wav *.ogg *.m4a)"
        )
        if file_path:
            rel_path = self.controller.process_audio_path(file_path)
            self.edit_audio_paths[field].setText(rel_path)

    def update_image_preview(self, stored_path: str):
        t = self.translator
        if not stored_path:
            self.edit_image_preview.setText(t.t("flashcard_editor.preview_no_image"))
            return

        full_path = self.controller.get_absolute_path(stored_path)
        if full_path and full_path.exists():
            pix = QPixmap(str(full_path))
            if not pix.isNull():
                self.edit_image_preview.setPixmap(
                    pix.scaled(300, 200,
                               Qt.AspectRatioMode.KeepAspectRatio,
                               Qt.TransformationMode.SmoothTransformation)
                )
                self.edit_image_preview.setText("")
                return

        self.edit_image_preview.setText(t.t("flashcard_editor.preview_not_found"))

    def save_card_edit(self):
        t = self.translator
        card_data = {
            "front": self.edit_front.toPlainText().strip(),
            "back": self.edit_back.toPlainText().strip(),
            "hint": self.edit_hint.text().strip(),
            "description": self.edit_description.toPlainText().strip(),
            "image": self.edit_image_path.text().strip() if self.edit_has_image_btn.isChecked() else "",
            "audio": (
                {
                    field: path_input.text().strip()
                    for field, path_input in self.edit_audio_paths.items()
                    if path_input.text().strip()
                }
                if self.edit_has_audio_btn.isChecked() else {}
            )
        }

        if not card_data["front"] or not card_data["back"]:
            QMessageBox.warning(
                self,
                t.t("flashcard_editor.msg_error_title"),
                t.t("flashcard_editor.msg_fields_required")
            )
            return

        if self.current_editing_card_index is None:
            self.controller.add_card(card_data)
        else:
            self.controller.update_card(self.current_editing_card_index, card_data)

        self.refresh_card_list()
        self.stack.setCurrentWidget(self.deck_editor_panel)

    def cancel_card_edit(self):
        logger.info("User cancelled card edit. Returning to Deck Editor.")
        self.stack.setCurrentWidget(self.deck_editor_panel)
