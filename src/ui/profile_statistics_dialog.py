"""Searchable, collapsible read-only profile statistics window."""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QComboBox, QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QScrollArea, QVBoxLayout, QWidget

from src.logic.translator import get_translator
from src.ui.auto_scroll import AutoScrollArea


class ProfileStatisticsDialog(QDialog):
    PAGE_SIZE = 50

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.translator = get_translator()
        self._expanded = {}
        self._visible_limits = {}
        self.resize(620, 700)
        self.setMinimumSize(540, 560)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._init_ui()
        self.retranslate_ui()
        self.refresh_statistics()

    def _init_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)
        panel = QFrame()
        panel.setObjectName("login_glass_panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(26, 22, 26, 22)
        header = QHBoxLayout()
        self.close_btn = QPushButton()
        self.close_btn.setObjectName("mode_back_btn")
        self.close_btn.clicked.connect(self.accept)
        header.addWidget(self.close_btn)
        header.addStretch()
        layout.addLayout(header)
        self.title = QLabel()
        self.title.setObjectName("login_title")
        self.title.setCursor(Qt.CursorShape.SizeAllCursor)
        layout.addWidget(self.title)
        self.summary = QLabel()
        self.summary.setObjectName("profile_summary")
        self.summary.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.summary)
        controls = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setObjectName("profile_search")
        self.search_input.textChanged.connect(self._render_statistics)
        controls.addWidget(self.search_input, 1)
        self.filter_combo = QComboBox()
        self.filter_combo.setObjectName("profile_filter")
        self.filter_combo.currentIndexChanged.connect(self._render_statistics)
        controls.addWidget(self.filter_combo)
        layout.addLayout(controls)
        self.scroll = AutoScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setObjectName("profile_scroll")
        self.scroll.setToolTip("Middle-click to auto-scroll; press Escape to stop")
        self.content = QWidget()
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(4, 4, 4, 4)
        self.content_layout.setSpacing(10)
        self.scroll.setWidget(self.content)
        self.content.installEventFilter(self.scroll)
        layout.addWidget(self.scroll)
        footer = QVBoxLayout()
        secondary_actions = QHBoxLayout()
        self.reset_flashcards_btn = QPushButton()
        self.reset_flashcards_btn.setObjectName("profile_reset_secondary_btn")
        self.reset_flashcards_btn.clicked.connect(lambda: self.reset_all("flashcards"))
        self.reset_quizzes_btn = QPushButton()
        self.reset_quizzes_btn.setObjectName("profile_reset_secondary_btn")
        self.reset_quizzes_btn.clicked.connect(lambda: self.reset_all("quizzes"))
        self.clear_all_btn = QPushButton()
        self.clear_all_btn.setObjectName("profile_clear_all_btn")
        self.clear_all_btn.clicked.connect(lambda: self.reset_all(None))
        secondary_actions.addWidget(self.reset_flashcards_btn)
        secondary_actions.addWidget(self.reset_quizzes_btn)
        footer.addLayout(secondary_actions)
        footer.addWidget(self.clear_all_btn)
        layout.addLayout(footer)
        outer.addWidget(panel)

    def refresh_statistics(self):
        self._flashcards = self.controller.get_flashcard_stats()
        self._quizzes = self.controller.get_quiz_stats()
        self._render_statistics()

    def _render_statistics(self):
        if not hasattr(self, "_flashcards"):
            return
        self._clear_content()
        t = self.translator
        self.summary.setText(t.t("profile_statistics.summary", flashcards=f"{self._flashcards['mastered']}/{self._flashcards['total']}", quizzes=f"{self._quizzes['mastered']}/{self._quizzes['total']}"))
        self._add_section("flashcards", t.t("profile_statistics.flashcards"), self._flashcards)
        self._add_section("quizzes", t.t("profile_statistics.quizzes"), self._quizzes)
        self.content_layout.addStretch()
        self.scroll.track_auto_scroll_content(self.content)

    def _add_section(self, section_key, title, stats):
        t = self.translator
        heading = QLabel(title)
        heading.setObjectName("profile_section_title")
        self.content_layout.addWidget(heading)
        for collection in stats["collections"]:
            rows = self._filtered_rows(collection["rows"])
            if not rows and self.search_input.text().strip():
                continue
            collection_id = f"{section_key}:{collection['name']}"
            expanded = self._expanded.get(collection_id, False) or bool(self.search_input.text().strip())
            header = QHBoxLayout()
            toggle = QPushButton(t.t("profile_statistics.collection_progress", name=collection["name"], mastered=collection["mastered"], total=collection["total"]))
            toggle.setObjectName("profile_collection_toggle")
            toggle.setCheckable(True)
            toggle.setChecked(expanded)
            toggle.clicked.connect(lambda checked, key=collection_id: self._set_expanded(key, checked))
            header.addWidget(toggle, 1)
            reset = QPushButton(t.t("profile_statistics.btn_reset"))
            reset.setObjectName("profile_reset_btn")
            reset.setEnabled(collection["mastered"] > 0 or any(row["correct"] or row["wrong"] for row in collection["rows"]))
            reset.clicked.connect(lambda _checked=False, kind=section_key, name=collection["name"]: self.reset_collection(kind, name))
            header.addWidget(reset)
            self.content_layout.addLayout(header)
            if not expanded:
                continue
            limit = self._visible_limits.get(collection_id, self.PAGE_SIZE)
            for row in rows[:limit]:
                self._add_row(row)
            if len(rows) > limit:
                more = QPushButton(t.t("profile_statistics.btn_show_more", count=min(self.PAGE_SIZE, len(rows) - limit)))
                more.setObjectName("profile_show_more")
                more.clicked.connect(lambda _checked=False, key=collection_id: self._show_more(key))
                self.content_layout.addWidget(more)

    def _add_row(self, row):
        t = self.translator
        row_widget = QFrame()
        row_widget.setObjectName("profile_stat_row")
        row_layout = QHBoxLayout(row_widget)
        row_layout.setContentsMargins(10, 6, 10, 6)
        text = QLabel(row["text"])
        text.setWordWrap(True)
        status = QLabel(t.t("profile_statistics.mastered") if row["mastered"] else t.t("profile_statistics.not_mastered"))
        status.setObjectName("profile_mastered" if row["mastered"] else "profile_unmastered")
        attempts = QLabel(t.t("profile_statistics.attempts", correct=row["correct"], wrong=row["wrong"]))
        attempts.setObjectName("profile_attempts")
        row_layout.addWidget(text, 1)
        row_layout.addWidget(attempts)
        row_layout.addWidget(status)
        self.content_layout.addWidget(row_widget)

    def _filtered_rows(self, rows):
        search = self.search_input.text().strip().casefold()
        state = self.filter_combo.currentData()
        return [row for row in rows if (not search or search in row["text"].casefold()) and (state == "all" or (state == "mastered") == row["mastered"])]

    def _set_expanded(self, collection_id, expanded):
        self._expanded[collection_id] = expanded
        self._render_statistics()

    def _show_more(self, collection_id):
        self._visible_limits[collection_id] = self._visible_limits.get(collection_id, self.PAGE_SIZE) + self.PAGE_SIZE
        self._render_statistics()

    def reset_collection(self, collection_type, name):
        t = self.translator
        if QMessageBox.question(self, t.t("profile_statistics.confirm_reset_title"), t.t("profile_statistics.confirm_reset_collection", name=name), QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            self.controller.reset_collection(collection_type, name)
            self.refresh_statistics()

    def reset_all(self, collection_type):
        t = self.translator
        scope = t.t(f"profile_statistics.scope_{collection_type or 'all'}")
        if QMessageBox.question(self, t.t("profile_statistics.confirm_reset_title"), t.t("profile_statistics.confirm_reset_all", scope=scope), QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            self.controller.reset_all(collection_type)
            self.refresh_statistics()

    def _clear_content(self):
        self._clear_layout(self.content_layout)

    @classmethod
    def _clear_layout(cls, layout):
        """Remove widgets and nested header layouts before a filtered re-render."""
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                nested = item.layout()
                cls._clear_layout(nested)
                nested.deleteLater()

    def retranslate_ui(self):
        t = self.translator
        self.setWindowTitle(t.t("profile_statistics.title"))
        self.title.setText(t.t("profile_statistics.title"))
        self.search_input.setPlaceholderText(t.t("profile_statistics.search_placeholder"))
        saved_filter = self.filter_combo.currentData() or "all"
        self.filter_combo.blockSignals(True)
        self.filter_combo.clear()
        self.filter_combo.addItem(t.t("profile_statistics.filter_all"), "all")
        self.filter_combo.addItem(t.t("profile_statistics.filter_mastered"), "mastered")
        self.filter_combo.addItem(t.t("profile_statistics.filter_not_mastered"), "not_mastered")
        self.filter_combo.setCurrentIndex(max(0, self.filter_combo.findData(saved_filter)))
        self.filter_combo.blockSignals(False)
        self.reset_flashcards_btn.setText(t.t("profile_statistics.btn_reset_flashcards"))
        self.reset_quizzes_btn.setText(t.t("profile_statistics.btn_reset_quizzes"))
        self.clear_all_btn.setText(t.t("profile_statistics.btn_clear_all"))
        self.close_btn.setText("← " + t.t("profile_statistics.btn_close"))

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
