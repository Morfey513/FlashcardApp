# src/ui/flashcard_viewer.py

import logging
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QPushButton, QLabel,
    QFrame, QListWidget, QListWidgetItem, QStackedLayout, QSpacerItem,
    QSizePolicy, QProgressBar, QToolButton, QMessageBox
)
from PyQt6.QtGui import QPixmap
from PyQt6.QtCore import Qt, QSize, QPropertyAnimation, QEasingCurve, pyqtProperty, pyqtSignal

# Modular imports
from src.config import FLASHCARD_SIZE, ANIMATION_DURATION, MAX_FLASH_IMG_W, MAX_FLASH_IMG_H
from src.controllers.flashcard_controller import FlashcardController
from src.logic.translator import get_translator
from src.utils.text_to_speech import TextToSpeech
from src.utils.paths import resolve_stored_path
from src.utils.recorded_audio import RecordedAudioPlayer
from src.ui.scrolling_label import ScrollingLabel
from src.ui.status_badge import format_status_badge, show_moderation_reason
from src.ui.join_with_code_dialog import (
    configure_join_with_code_button,
    run_join_with_code_flow,
)
from src.storage.content_library import ContentLibrary

# Initialize Logger
logger = logging.getLogger(__name__)


class FlippableCard(QFrame):
    """The visual card component that handles the flipping animation."""

    flipped = pyqtSignal(bool)

    def __init__(self):
        super().__init__()
        self.setObjectName("flashcard_card")
        self.setFixedSize(*FLASHCARD_SIZE)
        self._is_flipped = False
        self._rotation = 0

        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(15, 15, 15, 15)

        self.front_widget = QWidget()
        self.front_layout = QVBoxLayout(self.front_widget)

        self.back_widget = QWidget()
        self.back_layout = QVBoxLayout(self.back_widget)
        self.back_widget.hide()

        self.main_layout.addWidget(self.front_widget)
        self.main_layout.addWidget(self.back_widget)

        self.animation = QPropertyAnimation(self, b"rotation")
        self.animation.setDuration(ANIMATION_DURATION)
        self.animation.setEasingCurve(QEasingCurve.Type.InOutCubic)

    @pyqtProperty(float)
    def rotation(self):
        return self._rotation

    @rotation.setter
    def rotation(self, value):
        self._rotation = value
        # ``_is_flipped`` is the destination side selected by ``flip()``.
        # Keep the current side visible until the animation reaches its edge,
        # then switch to that destination side at the 90-degree midpoint.
        if self._is_flipped and value >= 90:
            self.front_widget.hide()
            self.back_widget.show()
        elif not self._is_flipped and value <= 90:
            self.back_widget.hide()
            self.front_widget.show()

    def flip(self):
        self._is_flipped = not self._is_flipped
        self.flipped.emit(self._is_flipped)
        self.animation.setStartValue(180 if not self._is_flipped else 0)
        self.animation.setEndValue(0 if not self._is_flipped else 180)
        self.animation.start()

    def reset(self):
        self._is_flipped = False
        self.back_widget.hide()
        self.front_widget.show()
        self._rotation = 0

    @property
    def is_flipped(self):
        return self._is_flipped


class DeckListRow(QFrame):
    """A selectable deck row with progress and a per-deck reset action."""

    selected = pyqtSignal(str)
    moderation_clicked = pyqtSignal(str, str)
    keep_offline = pyqtSignal()

    def __init__(self, deck, progress_text):
        super().__init__()
        self.deck_name = deck["name"]
        self.setObjectName("deck_list_row")
        self.setProperty("selected", False)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(54)

        layout = QGridLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(10)

        name = ScrollingLabel(self.deck_name)
        name.setObjectName("deck_list_name")
        name.setMinimumWidth(0)
        name.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        name.setToolTip(self.deck_name)
        name.setWordWrap(False)
        layout.addWidget(name, 0, 0)

        progress = QProgressBar()
        progress.setObjectName("deck_progress")
        progress.setRange(0, max(deck["total"], 1))
        progress.setValue(deck["mastered"])
        progress.setTextVisible(False)
        progress.setFixedWidth(100)
        layout.addWidget(progress, 0, 1)

        count = QLabel(progress_text)
        count.setObjectName("deck_progress_text")
        count.setFixedWidth(100)
        layout.addWidget(count, 0, 2)

        status = "locked" if deck.get("locked") else deck.get("moderation_status", "published")
        displayed_status = deck.get("visibility", "public") if status == "published" else status
        is_actionable = deck.get("can_view_moderation_reason", deck.get("is_owner")) and status in {"rejected", "banned"}
        chip = QPushButton(format_status_badge(
            displayed_status,
            f"{status.replace('_', ' ').title()} (info)" if is_actionable else None,
        ))
        chip.setObjectName("content_status_chip")
        chip.setProperty("content_status", displayed_status)
        chip.setProperty("interactive", is_actionable)
        chip.setFixedWidth(max(78, chip.sizeHint().width()))
        chip.setFixedHeight(30)
        if is_actionable:
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            chip.setToolTip("Click to view the moderator's reason")
            chip.clicked.connect(
                lambda _checked=False, value=status, reason=deck.get("moderation_reason", ""):
                self.moderation_clicked.emit(value, reason)
            )
        else:
            chip.setCursor(Qt.CursorShape.ArrowCursor)
            chip.setEnabled(False)
        status_slot = QWidget()
        status_slot.setObjectName("content_status_slot")
        status_slot.setFixedWidth(120)
        status_layout = QHBoxLayout(status_slot)
        status_layout.setContentsMargins(0, 0, 0, 0)
        status_layout.addWidget(chip, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(status_slot, 0, 3)

        if deck.get("can_download") or deck.get("downloaded") or deck.get("offline_state") == "locked":
            offline_state = deck.get("offline_state")
            offline_text = {
                "update_available": "Update now", "updating": "Updating...",
                "update_failed": "Update failed — Retry", "stale": "Offline / stale",
                "synchronized": "Synchronized", "available_offline": "Available offline",
                "locked": "Locked",
            }.get(offline_state, "Keep offline")
            # A compact icon keeps the visibility chip and progress columns
            # readable on the default flashcard window width.
            offline = QPushButton("✓" if deck.get("downloaded") else "📥")
            offline.setObjectName("content_offline_btn")
            offline.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            offline.setMinimumSize(32, 28)
            offline.setMaximumSize(32, 28)
            offline.setFixedSize(32, 28)
            offline.setToolTip(offline_text)
            offline.setAccessibleName(offline_text)
            offline.setEnabled(bool(deck.get("can_download")) and (
                not deck.get("downloaded")
                or offline_state in {"update_available", "update_failed", "stale"}
            ))
            offline.clicked.connect(self.keep_offline.emit)
            offline_frame = QFrame()
            offline_frame.setObjectName("content_offline_frame")
            offline_frame.setFixedSize(34, 30)
            offline_frame_layout = QHBoxLayout(offline_frame)
            offline_frame_layout.setContentsMargins(0, 0, 0, 0)
            offline_frame_layout.addWidget(offline)
            layout.addWidget(offline_frame, 0, 4)
        if deck.get("media_state") in {"partially_available", "partial", "unavailable"}:
            media_label = QLabel("Media unavailable")
            media_label.setObjectName("content_media_state")
            layout.addWidget(media_label, 1, 0, 1, 5)
        layout.setColumnStretch(0, 1)
        layout.setColumnMinimumWidth(1, 100)
        layout.setColumnMinimumWidth(2, 100)


    def mousePressEvent(self, event):
        self.selected.emit(self.deck_name)
        super().mousePressEvent(event)

    def set_selected(self, selected):
        self.setProperty("selected", selected)
        self.style().unpolish(self)
        self.style().polish(self)


class FlashcardViewer(QWidget):
    finished = pyqtSignal()

    def __init__(self, controller: FlashcardController):
        super().__init__()
        self.controller = controller
        self.translator = get_translator()
        self.library = ContentLibrary(flashcard_repository=getattr(controller, "repo", None))
        base_repository = getattr(controller, "repo", None)
        configure = getattr(controller, "configure_downloaded_content", None)
        if callable(configure):
            configure(self.library, base_repository)
        self._install_library_repository()
        self.current_card_text = {"front": "", "back": "", "description": ""}
        self.current_hint_text = ""
        self.current_card_audio = {"front": "", "back": "", "hint": "", "description": ""}
        self._starting_deck = False

        self.resize(750, 770)
        self.setMinimumSize(700, 720)

        self.stack = QStackedLayout()
        self.setLayout(self.stack)

        # Initialize panels
        self.init_deck_selection_panel()
        self.init_study_panel()
        self.init_completion_panel()

        self.refresh_deck_list()

        self.retranslate_ui()
        self.stack.setCurrentWidget(self.deck_selection_panel)

    def retranslate_ui(self):
        """Standardized method to update all text in the UI."""
        t = self.translator
        sec = "flashcard_viewer"

        # Window title
        self.setWindowTitle(t.t(f"{sec}.title"))

        # Deck selection panel
        self.deck_title_label.setText(t.t(f"{sec}.title"))
        self.start_btn.setText(t.t(f"{sec}.btn_start"))
        self.back_btn.setText("← " + t.t(f"{sec}.btn_back_to_menu"))
        self.manage_progress_btn.setText(t.t(f"{sec}.btn_manage_progress"))
        self.join_with_code_btn.setText("🔑 Join with Code")
        self.refresh_deck_list()

        # Study panel buttons
        self.wrong_btn.setText(t.t(f"{sec}.btn_dont_know"))
        self.correct_btn.setText(t.t(f"{sec}.btn_know"))
        self.flip_btn.setText(t.t(f"{sec}.btn_flip"))
        self.exit_btn.setText(t.t(f"{sec}.btn_back"))
        tts_tooltip = t.t(
            f"{sec}.tooltip_read_card"
            if self.text_to_speech.is_available
            else f"{sec}.tooltip_tts_unavailable"
        )
        self.tts_btn.setToolTip(tts_tooltip)
        self.tts_btn.setAccessibleName(tts_tooltip)

        # Completion panel
        self.finish_btn.setText(t.t(f"{sec}.btn_finish"))

    # ======================
    # BRIDGE METHODS
    # ======================

    def update_ui_with_card(self, card_data):
        """Clean bridge method with safety checks."""
        if not card_data:
            logger.warning("UI: No card data received to update.")
            return

        try:
            self.blockSignals(True)
            t = self.translator
            sec = "flashcard_viewer"

            # 1. Reset visual state
            self.recorded_audio.stop()
            self.card.reset()
            self.hint_btn.setChecked(False)
            self.current_card_text = {
                "front": card_data.get("front", ""),
                "back": card_data.get("back", ""),
                "description": card_data.get("description", ""),
            }
            stored_audio = card_data.get("audio", {})
            # Older cards stored one string. Treat it as front audio so they
            # remain usable after the four-field audio upgrade.
            if isinstance(stored_audio, str):
                stored_audio = {"front": stored_audio}
            self.current_card_audio = {
                field: stored_audio.get(field, "")
                for field in ("front", "back", "hint", "description")
            }

            # 2. Update Progress
            self.progress_label.setText(self.controller.get_progress_string())

            # 3. Clear and Rebuild Front
            self.clear_layout(self.card.front_layout)
            self.add_text_to_layout(self.card.front_layout, card_data.get("front", ""))

            if card_data.get("image"):
                self.add_image_to_layout(self.card.front_layout, card_data["image"])

            # 4. Clear and Rebuild Back
            self.clear_layout(self.card.back_layout)
            self.add_back_content_to_layout(
                self.card.back_layout,
                card_data.get("back", ""),
                card_data.get("description", ""),
            )

            # 5. Re-initialize Hint Overlay
            hint = card_data.get("hint") or t.t(f"{sec}.hint_default")
            self.current_hint_text = hint
            self.setup_hint_overlay(hint)
            self._update_audio_buttons()
            self.tts_btn.raise_()

            # 6. Show/Hide the "Mark as Mastered" button
            if card_data.get('stats', {}).get('mastered'):
                self.master_btn.setText(t.t(f"{sec}.btn_unmaster"))
                self.master_btn.setEnabled(False)
                self.master_btn.show()
            elif card_data.get('can_master'):
                self.master_btn.setText(t.t(f"{sec}.btn_master"))
                self.master_btn.setEnabled(True)
                self.master_btn.show()
            else:
                self.master_btn.hide()

            self.blockSignals(False)

        except Exception as e:
            print(f"Hard crash prevented in UI: {e}")

    def start_selected_deck(self):
        if self._starting_deck:
            return
        item = self.deck_list.currentItem()
        if not item:
            return

        self._starting_deck = True
        try:
            deck_name = item.data(Qt.ItemDataRole.UserRole) or item.text()
            if self.controller.is_deck_complete(deck_name):
                if not self.confirm_completed_deck_reset(deck_name):
                    return
                self.controller.reset_deck_progress(deck_name)

            first_card = self.controller.start_deck(deck_name)
            if first_card:
                self.update_ui_with_card(first_card)
                self.stack.setCurrentWidget(self.study_panel)
            else:
                logger.error("Controller returned no card data.")
        except Exception as e:
            logger.exception(f"UI Error during deck start: {e}")
        finally:
            self._starting_deck = False

    def confirm_completed_deck_reset(self, deck_name):
        """Offer to reset a fully mastered deck before starting it again."""
        t = self.translator
        sec = "flashcard_viewer"
        dialog = QMessageBox(self)
        dialog.setIcon(QMessageBox.Icon.Information)
        dialog.setWindowTitle(t.t(f"{sec}.deck_complete_title"))
        dialog.setText(t.t(f"{sec}.deck_complete_message", deck=deck_name))
        reset_button = dialog.addButton(
            t.t(f"{sec}.btn_reset_and_restart"),
            QMessageBox.ButtonRole.AcceptRole,
        )
        back_button = dialog.addButton(
            t.t(f"{sec}.btn_completed_back"),
            QMessageBox.ButtonRole.RejectRole,
        )
        dialog.setDefaultButton(back_button)
        dialog.exec()
        return dialog.clickedButton() is reset_button

    def mark_answer(self, is_correct):
        next_card = self.controller.process_answer(is_correct)
        if next_card:
            self.update_ui_with_card(next_card)
        else:
            t = self.translator
            sec = "flashcard_viewer"
            stats = self.controller.get_session_summary()
            html = (
                f"<h2>{t.t(f'{sec}.session_complete')}</h2>"
                f"<p>{t.t(f'{sec}.stats_known', count=stats['known'])}</p>"
                f"<p>{t.t(f'{sec}.stats_unknown', count=stats['unknown'])}</p>"
                f"<p>{t.t(f'{sec}.stats_mastered', count=stats['mastered'], total=stats['total_cards'])}</p>"
            )
            self.stat_label.setText(html)
            self.stack.setCurrentWidget(self.completion_panel)

    def show_completion(self):
        """Show the shared session-complete panel."""
        t = self.translator
        sec = "flashcard_viewer"
        stats = self.controller.get_session_summary()
        html = (
            f"<h2>{t.t(f'{sec}.session_complete')}</h2>"
            f"<p>{t.t(f'{sec}.stats_known', count=stats['known'])}</p>"
            f"<p>{t.t(f'{sec}.stats_unknown', count=stats['unknown'])}</p>"
            f"<p>{t.t(f'{sec}.stats_mastered', count=stats['mastered'], total=stats['total_cards'])}</p>"
        )
        self.stat_label.setText(html)
        self.stack.setCurrentWidget(self.completion_panel)

    def toggle_master_card(self):
        """Mark/un-mark current card as mastered."""
        if not self.controller.session:
            return

        result = self.controller.toggle_current_card_mastery()

        if result is None:
            return

        new_state, next_card = result

        t = self.translator
        sec = "flashcard_viewer"

        if new_state:
            if next_card:
                self.update_ui_with_card(next_card)
            else:
                self.show_completion()
        else:
            card_data = self.controller.session.get_current_card()
            if card_data and card_data.get('can_master'):
                self.master_btn.setText(t.t(f"{sec}.btn_master"))
                self.master_btn.setEnabled(True)

    # ======================
    # UI INITIALIZATION
    # ======================

    def init_deck_selection_panel(self):
        self.deck_selection_panel = QFrame()
        layout = QVBoxLayout(self.deck_selection_panel)
        layout.setContentsMargins(40, 32, 40, 32)
        layout.setSpacing(16)

        header = QHBoxLayout()
        self.back_btn = QPushButton()
        self.back_btn.setObjectName("mode_back_btn")
        self.back_btn.clicked.connect(self.finished.emit)
        header.addWidget(self.back_btn)
        header.addStretch()
        self.join_with_code_btn = QPushButton()
        configure_join_with_code_button(
            self.join_with_code_btn,
            self.controller.user_id,
            self.join_with_code,
        )
        header.addWidget(self.join_with_code_btn)
        layout.addLayout(header)

        self.deck_title_label = QLabel()
        self.deck_title_label.setObjectName("title")
        layout.addWidget(self.deck_title_label, alignment=Qt.AlignmentFlag.AlignCenter)

        self.deck_list = QListWidget()
        self.deck_list.setObjectName("flashcard_deck_list")
        self.deck_list.itemDoubleClicked.connect(self.start_selected_deck)
        self.deck_list.currentItemChanged.connect(self.update_deck_selection)
        layout.addWidget(self.deck_list)

        self.manage_progress_btn = QPushButton()
        self.manage_progress_btn.setFixedSize(200, 50)
        self.manage_progress_btn.clicked.connect(self.show_manage_progress)

        btn_layout = QHBoxLayout()

        self.start_btn = QPushButton()
        self.start_btn.setFixedSize(200, 50)
        self.start_btn.clicked.connect(self.start_selected_deck)

        btn_layout.addStretch()
        btn_layout.addWidget(self.manage_progress_btn, alignment=Qt.AlignmentFlag.AlignVCenter)
        btn_layout.addStretch()
        btn_layout.addWidget(self.start_btn, alignment=Qt.AlignmentFlag.AlignVCenter)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)
        self.stack.addWidget(self.deck_selection_panel)

    def join_with_code(self):
        run_join_with_code_flow(self, self.controller, self.refresh_deck_list)

    def init_study_panel(self):
        self.study_panel = QFrame()
        layout = QVBoxLayout(self.study_panel)
        layout.setContentsMargins(30, 20, 30, 40)
        layout.setSpacing(10)

        top_bar_widget = QWidget()
        top_bar_widget.setFixedWidth(FLASHCARD_SIZE[0])
        top_bar = QHBoxLayout(top_bar_widget)
        top_bar.setContentsMargins(0, 0, 0, 0)

        # Keep the counter centered even while the right-side mastery control
        # is hidden by reserving an equal-width slot on the left.
        left_slot = QWidget()
        left_slot.setFixedSize(145, 32)
        top_bar.addWidget(left_slot)
        top_bar.addStretch()

        self.progress_label = QLabel()
        self.progress_label.setObjectName("progress")
        top_bar.addWidget(self.progress_label)
        top_bar.addStretch()

        self.master_btn = QPushButton()
        self.master_btn.setObjectName("flashcard_mastery")
        self.master_btn.setFixedSize(140, 32)
        self.master_btn.clicked.connect(self.toggle_master_card)
        self.master_btn.hide()

        master_slot = QWidget()
        master_slot.setFixedSize(145, 32)
        master_slot_layout = QHBoxLayout(master_slot)
        master_slot_layout.setContentsMargins(0, 0, 0, 0)
        master_slot_layout.addStretch()
        master_slot_layout.addWidget(self.master_btn)
        top_bar.addWidget(master_slot)

        layout.addWidget(top_bar_widget, alignment=Qt.AlignmentFlag.AlignCenter)

        # Content Card
        self.card = FlippableCard()
        self.card.mousePressEvent = lambda e: self.card.flip()
        self.card.flipped.connect(lambda _is_flipped: self.recorded_audio.stop())

        self.text_to_speech = TextToSpeech(self)
        self.recorded_audio = RecordedAudioPlayer(self.text_to_speech, self)
        self.tts_btn = QPushButton("📢", self.card)
        self.tts_btn.setObjectName("flashcard_audio_btn")
        self.tts_btn.setFixedSize(38, 38)
        self.tts_btn.move(28, 28)
        self.tts_btn.clicked.connect(self.speak_visible_card)
        self.tts_btn.setEnabled(self.text_to_speech.is_available)
        self.tts_btn.raise_()
        layout.addWidget(self.card, alignment=Qt.AlignmentFlag.AlignCenter)

        layout.addSpacerItem(QSpacerItem(20, 20, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding))

        # Action Buttons
        answer_row_widget = QWidget()
        answer_row_widget.setFixedWidth(FLASHCARD_SIZE[0])
        ans_row = QHBoxLayout(answer_row_widget)
        ans_row.setContentsMargins(0, 0, 0, 0)
        ans_row.setSpacing(0)

        self.wrong_btn = QPushButton()
        self.wrong_btn.setObjectName("danger")
        self.wrong_btn.setFixedSize(220, 75)
        self.wrong_btn.clicked.connect(lambda: self.mark_answer(False))

        self.hint_btn = QPushButton("❓")
        self.hint_btn.setCheckable(True)
        self.hint_btn.setObjectName("flashcard_hint")
        self.hint_btn.setFixedSize(55, 55)
        self.hint_btn.toggled.connect(self.toggle_hint)

        self.correct_btn = QPushButton()
        self.correct_btn.setObjectName("flashcard_correct")
        self.correct_btn.setFixedSize(220, 75)
        self.correct_btn.clicked.connect(lambda: self.mark_answer(True))

        ans_row.addWidget(self.wrong_btn)
        ans_row.addStretch()
        ans_row.addWidget(self.hint_btn)
        ans_row.addStretch()
        ans_row.addWidget(self.correct_btn)
        layout.addWidget(answer_row_widget, alignment=Qt.AlignmentFlag.AlignCenter)

        # Nav Buttons
        nav_row_widget = QWidget()
        nav_row_widget.setFixedWidth(FLASHCARD_SIZE[0])
        nav_row = QHBoxLayout(nav_row_widget)
        nav_row.setContentsMargins(0, 0, 0, 0)
        nav_row.setSpacing(68)
        nav_row.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.exit_btn = QPushButton()
        self.exit_btn.setFixedSize(255, 65)
        self.exit_btn.clicked.connect(self.return_to_deck_selection)

        self.flip_btn = QPushButton()
        self.flip_btn.setFixedSize(255, 65)
        self.flip_btn.clicked.connect(self.card.flip)

        nav_row.addWidget(self.exit_btn)
        nav_row.addWidget(self.flip_btn)
        layout.addWidget(nav_row_widget, alignment=Qt.AlignmentFlag.AlignCenter)

        self.stack.addWidget(self.study_panel)

    def init_completion_panel(self):
        self.completion_panel = QFrame()
        layout = QVBoxLayout(self.completion_panel)

        self.stat_label = QLabel()
        self.stat_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.stat_label.setTextFormat(Qt.TextFormat.RichText)

        self.finish_btn = QPushButton()
        self.finish_btn.clicked.connect(self.return_to_deck_selection)

        layout.addWidget(self.stat_label, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.finish_btn, alignment=Qt.AlignmentFlag.AlignCenter)
        self.stack.addWidget(self.completion_panel)

    # ======================
    # HELPERS & RENDERERS
    # ======================

    def toggle_hint(self, checked):
        if hasattr(self, 'hint_overlay'):
            if checked:
                w, h = 450, 80
                self.hint_overlay.setGeometry(
                    (self.card.width() - w) // 2,
                    self.card.height() - h - 25,
                    w, h
                )
                self.hint_overlay.show()
                self.hint_overlay.raise_()
            else:
                self.hint_overlay.hide()

    def speak_visible_card(self):
        """Read whichever side of the flashcard is currently visible."""
        if not self.card.is_flipped:
            self.recorded_audio.play_sequence((
                (self._audio_path("front"), self.current_card_text["front"]),
            ), pause_ms=0)
            return

        self.recorded_audio.play_sequence((
            (self._audio_path("back"), self.current_card_text["back"]),
            (self._audio_path("description"), self.current_card_text["description"]),
        ))

    def speak_hint(self):
        """Read the active hint without changing the card-side speech action."""
        self.recorded_audio.play_sequence((
            (self._audio_path("hint"), self.current_hint_text),
        ), pause_ms=0)

    def _audio_path(self, field):
        return resolve_stored_path(self.current_card_audio.get(field))

    def _update_audio_buttons(self):
        has_card_audio = bool(
            self.current_card_audio["front"]
            or self.current_card_audio["back"]
            or self.current_card_audio["description"]
        )
        self.tts_btn.setEnabled(self.text_to_speech.is_available or has_card_audio)
        self.hint_tts_btn.setEnabled(
            self.text_to_speech.is_available or bool(self.current_card_audio["hint"])
        )

    def setup_hint_overlay(self, hint_text):
        if hasattr(self, 'hint_overlay') and self.hint_overlay:
            self.hint_overlay.deleteLater()

        self.hint_overlay = QFrame(self.card)
        self.hint_overlay.setObjectName("flashcard_hint_overlay")
        self.hint_overlay.hide()
        h_layout = QHBoxLayout(self.hint_overlay)
        h_label = QLabel(hint_text)
        h_label.setObjectName("flashcard_hint_text")
        h_label.setWordWrap(True)
        h_layout.addWidget(h_label, 1)

        self.hint_tts_btn = QPushButton("🔊")
        self.hint_tts_btn.setObjectName("flashcard_hint_tts_btn")
        self.hint_tts_btn.setFixedSize(38, 38)
        self.hint_tts_btn.setEnabled(self.text_to_speech.is_available)
        tooltip = self.translator.t(
            "flashcard_viewer.tooltip_read_hint"
            if self.text_to_speech.is_available
            else "flashcard_viewer.tooltip_tts_unavailable"
        )
        self.hint_tts_btn.setToolTip(tooltip)
        self.hint_tts_btn.setAccessibleName(tooltip)
        self.hint_tts_btn.clicked.connect(self.speak_hint)
        h_layout.addWidget(self.hint_tts_btn, alignment=Qt.AlignmentFlag.AlignVCenter)

    def add_text_to_layout(self, layout, text):
        frame = QFrame()
        frame.setObjectName("flashcard_content_frame")
        frame.setMinimumHeight(120)
        l = QVBoxLayout(frame)
        lbl = QLabel(text)
        lbl.setObjectName("flashcard_question_text")
        lbl.setWordWrap(True)
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        l.addWidget(lbl)
        layout.addWidget(frame)

    def add_back_content_to_layout(self, layout, answer, description):
        """Display an answer and its optional explanation on a card's back."""
        frame = QFrame()
        frame.setObjectName("flashcard_content_frame")
        frame.setMinimumHeight(120)
        content_layout = QVBoxLayout(frame)

        answer_label = QLabel(answer)
        answer_label.setObjectName("flashcard_question_text")
        answer_label.setWordWrap(True)
        answer_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        content_layout.addWidget(answer_label)

        if description:
            description_label = QLabel(description)
            description_label.setObjectName("flashcard_explanation_text")
            description_label.setWordWrap(True)
            description_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            content_layout.addWidget(description_label)

        layout.addWidget(frame)

    def add_image_to_layout(self, layout, image_path):
        full_path = self.controller.get_absolute_image_path(image_path)
        if full_path and full_path.exists():
            pix = QPixmap(str(full_path))
            img_l = QLabel()
            img_l.setPixmap(pix.scaled(
                MAX_FLASH_IMG_W, MAX_FLASH_IMG_H,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            ))
            layout.addWidget(img_l, alignment=Qt.AlignmentFlag.AlignCenter)

    def return_to_deck_selection(self):
        """Switches the view back to the selection menu and cleans up the session."""
        logger.info("Returning to deck selection menu.")
        self.stack.setCurrentWidget(self.deck_selection_panel)
        self.refresh_deck_list()
        self.controller.end_session()

    def show_manage_progress(self):
        """Open the centralized progress manager for this user."""
        from src.controllers.profile_statistics_controller import ProfileStatisticsController
        from src.ui.profile_statistics_dialog import ProfileStatisticsDialog
        dialog = ProfileStatisticsDialog(ProfileStatisticsController(
            self.controller.user_id,
            user_repository=self.controller.user_repository,
        ), self)
        dialog.exec()
        self.refresh_deck_list()

    def clear_layout(self, layout):
        while layout.count():
            child = layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

    def refresh_deck_list(self):
        self.deck_list.clear()
        self.deck_rows = {}
        t = self.translator
        sec = "flashcard_viewer"
        list_loader = getattr(self.controller, "get_deck_list_items", None)
        decks = list_loader() if callable(list_loader) else self.controller.get_deck_summaries()
        known_ids = {str(item.get("id") or item.get("file")) for item in decks}
        for cached in self.library.list_downloaded("flashcard"):
            if str(cached["content_id"]) not in known_ids:
                accessible = self.library.can_access(
                    cached["manifest"], self.controller.user_id
                )
                decks.append({
                    "id": cached["content_id"], "name": cached["name"],
                    "mastered": 0, "total": 0,
                    "moderation_status": "published" if accessible else "locked",
                    "visibility": cached["visibility"], "downloaded": accessible,
                    "offline_state": "available_offline" if accessible else "locked",
                    "locked": not accessible,
                })
        for deck in decks:
            content_id = str(deck.get("id") or deck.get("file"))
            cached = self.library.get_downloaded("flashcard", content_id, self.controller.user_id)
            deck["downloaded"] = cached is not None
            deck["update_available"] = cached is not None and self.library.update_state(
                "flashcard", content_id, deck.get("content_version"), self.controller.user_id
            ) == "update_available"
            if cached is not None and getattr(self.controller, "downloaded_content", None):
                state_loader = getattr(self.controller, "get_cached_content_state", None)
                result = state_loader(content_id) if callable(state_loader) else None
                if result and result.get("state") in {"synchronized", "available_offline"}:
                    result = self.controller.check_downloaded_content(content_id) or result
                deck["offline_state"] = result.get("state") if result else None
                deck["locked"] = deck["offline_state"] == "locked"
                if result:
                    deck.update({key: result[key] for key in ("media_state",) if key in result})
            elif cached is not None:
                deck["offline_state"] = "available_offline"
            deck["can_download"] = bool(
                getattr(getattr(self.controller, "repo", None), "supports_offline_download", False)
                and not deck.get("locked")
            )
            progress_text = t.t(
                f"{sec}.deck_progress",
                mastered=deck["mastered"],
                total=deck["total"],
            )
            row = DeckListRow(deck, progress_text)
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, deck["name"])
            # Let QListWidget use its viewport width while preserving any
            # secondary media/download state line in the row.
            item.setSizeHint(QSize(0, max(58, row.sizeHint().height())))
            self.deck_list.addItem(item)
            self.deck_list.setItemWidget(item, row)
            self.deck_rows[deck["name"]] = row
            row.selected.connect(lambda name, current=item: self.select_deck(name, current))
            row.moderation_clicked.connect(self.show_moderation_reason)
            row.keep_offline.connect(lambda current=deck: self.keep_deck_offline(current))
        if self.deck_list.count():
            self.deck_list.setCurrentRow(0)

    def keep_deck_offline(self, deck):
        """Explicitly cache one currently visible remote deck."""
        content_id = str(deck.get("id") or deck.get("file"))
        if getattr(self.controller, "downloaded_content", None):
            result = self.controller.update_downloaded_content(content_id)
            self.refresh_deck_list()
            return bool(result and result.get("state") == "synchronized")
        return False

    def _install_library_repository(self):
        base = getattr(self.controller, "repo", None)
        if base is None:
            return
        repository = self.library.repository_for("flashcard", self.controller.user_id, base)
        self.controller.repo = repository
        if hasattr(self.controller, "moderation"):
            self.controller.moderation.flashcards = repository

    def select_deck(self, deck_name, item):
        """Keep custom deck rows selectable by mouse click."""
        if deck_name:
            self.deck_list.setCurrentItem(item)

    def show_moderation_reason(self, status, reason):
        """Explain an owner-visible lifecycle decision without opening study mode."""
        show_moderation_reason(self, status, reason)

    def update_deck_selection(self, current, _previous):
        selected_name = current.data(Qt.ItemDataRole.UserRole) if current else None
        for name, row in getattr(self, "deck_rows", {}).items():
            row.set_selected(name == selected_name)

    def reset_deck_progress(self, deck_name):
        t = self.translator
        sec = "flashcard_viewer"
        answer = QMessageBox.question(
            self,
            t.t(f"{sec}.confirm_reset_title"),
            t.t(f"{sec}.confirm_reset_message", deck=deck_name),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        if not self.controller.reset_deck_progress(deck_name):
            QMessageBox.information(self, t.t(f"{sec}.confirm_reset_title"), t.t(f"{sec}.msg_no_progress"))
        self.refresh_deck_list()

    def clear_guest_progress(self):
        t = self.translator
        sec = "flashcard_viewer"
        is_guest = self.controller.user_id == "guest"
        title_key = "confirm_clear_guest_title" if is_guest else "confirm_clear_my_title"
        message_key = "confirm_clear_guest_message" if is_guest else "confirm_clear_my_message"
        answer = QMessageBox.question(
            self,
            t.t(f"{sec}.{title_key}"),
            t.t(f"{sec}.{message_key}"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.controller.clear_all_progress()
            self.refresh_deck_list()
