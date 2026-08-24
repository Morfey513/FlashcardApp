# src/ui/settings_panel.py

import logging
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QComboBox, QFrame, QGraphicsDropShadowEffect
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor

from src.logic.translator import get_translator

logger = logging.getLogger(__name__)


class SettingsPanel(QWidget):
    """
    Settings panel supporting multiple positions and instant language switching.
    """

    theme_changed = pyqtSignal(str)  # Emits "dark" or "light"
    language_changed = pyqtSignal(str)  # Emits "en" or "fr"
    clear_all_progress_requested = pyqtSignal()
    clear_downloaded_data_requested = pyqtSignal()
    account_requested = pyqtSignal()
    closed = pyqtSignal()

    def __init__(self, position="side", parent=None):
        super().__init__(parent)
        self.translator = get_translator()
        self.position = position

        self.setObjectName("settings_panel")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        # Apply shadow for side panel elevation
        if position == "side":
            shadow = QGraphicsDropShadowEffect(self)
            shadow.setBlurRadius(20)
            shadow.setXOffset(-5)
            shadow.setYOffset(0)
            shadow.setColor(QColor(0, 0, 0, 100))
            self.setGraphicsEffect(shadow)

        self.init_ui()
        self.retranslate_ui()

    def init_ui(self):
        """Initialize the layout structure based on panel position."""
        if self.position == "top":
            self._setup_horizontal_layout()
        else:
            self._setup_vertical_layout()

    def _setup_vertical_layout(self):
        """Side panel layout with rows."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(20)

        # Header
        header = QHBoxLayout()
        self.settings_title = QLabel()
        self.settings_title.setObjectName("settings_title")
        header.addWidget(self.settings_title)
        header.addStretch()

        self.close_btn = QPushButton("✕")
        self.close_btn.setObjectName("settings_close_btn")
        self.close_btn.setFixedSize(30, 30)
        self.close_btn.clicked.connect(self.closed.emit)
        header.addWidget(self.close_btn)
        layout.addLayout(header)

        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setObjectName("settings_separator")
        layout.addWidget(sep)

        # Theme Row
        theme_row = QHBoxLayout()
        self.theme_label = QLabel()
        self.theme_label.setObjectName("settings_section_label")
        self.theme_combo = QComboBox()
        self.theme_combo.setObjectName("settings_combo")
        self.theme_combo.setFixedWidth(120)
        self.theme_combo.currentIndexChanged.connect(self._handle_theme_selection)

        theme_row.addWidget(self.theme_label)
        theme_row.addStretch()
        theme_row.addWidget(self.theme_combo)
        layout.addLayout(theme_row)

        # Language Row
        lang_row = QHBoxLayout()
        self.lang_label = QLabel()
        self.lang_label.setObjectName("settings_section_label")
        self.lang_combo = QComboBox()
        self.lang_combo.setObjectName("settings_combo")
        self.lang_combo.setFixedWidth(120)
        self.lang_combo.currentIndexChanged.connect(self._handle_lang_selection)

        lang_row.addWidget(self.lang_label)
        lang_row.addStretch()
        lang_row.addWidget(self.lang_combo)
        layout.addLayout(lang_row)

        self.clear_all_progress_btn = QPushButton()
        self.clear_all_progress_btn.setObjectName("settings_clear_progress_btn")
        self.clear_all_progress_btn.clicked.connect(self.clear_all_progress_requested.emit)
        layout.addWidget(self.clear_all_progress_btn)

        self.clear_downloaded_data_btn = QPushButton("Clear Downloaded Data")
        self.clear_downloaded_data_btn.setObjectName("settings_clear_downloaded_btn")
        self.clear_downloaded_data_btn.clicked.connect(self.clear_downloaded_data_requested.emit)
        layout.addWidget(self.clear_downloaded_data_btn)

        self.account_btn = QPushButton()
        self.account_btn.setObjectName("settings_account_btn")
        self.account_btn.clicked.connect(self.account_requested.emit)
        self.account_btn.hide()
        layout.addWidget(self.account_btn)

        layout.addStretch()

    def retranslate_ui(self):
        """Update all text and repopulate combo boxes with localized strings."""
        t = self.translator
        sec = "settings_panel"

        # Static Labels
        self.settings_title.setText(t.t(f"{sec}.title"))
        self.theme_label.setText(t.t(f"{sec}.theme_label"))
        self.lang_label.setText(t.t(f"{sec}.language_label"))
        self.clear_all_progress_btn.setText(t.t(f"{sec}.btn_clear_guest_data"))
        self.account_btn.setText(t.t(f"{sec}.btn_account_settings"))

        # Rebuild Theme Combo
        self.theme_combo.blockSignals(True)
        current_theme = self.theme_combo.currentData()
        self.theme_combo.clear()
        self.theme_combo.addItem(t.t(f"{sec}.theme_dark"), "dark")
        self.theme_combo.addItem(t.t(f"{sec}.theme_light"), "light")
        self._restore_combo_index(self.theme_combo, current_theme)
        self.theme_combo.blockSignals(False)

        # Rebuild Language Combo
        self.lang_combo.blockSignals(True)
        current_lang = self.lang_combo.currentData()
        self.lang_combo.clear()
        self.lang_combo.addItem(t.t(f"{sec}.lang_english"), "en")
        self.lang_combo.addItem(t.t(f"{sec}.lang_french"), "fr")
        self._restore_combo_index(self.lang_combo, current_lang)
        self.lang_combo.blockSignals(False)

    def _restore_combo_index(self, combo: QComboBox, data_value: str):
        """Find and set the index for a given data value after a clear()."""
        index = combo.findData(data_value)
        if index >= 0:
            combo.setCurrentIndex(index)

    def _handle_theme_selection(self, index: int):
        """Emit internal theme key ('dark'/'light')."""
        theme = self.theme_combo.itemData(index)
        if theme:
            self.theme_changed.emit(theme)

    def _handle_lang_selection(self, index: int):
        """Emit internal language key ('en'/'fr')."""
        lang = self.lang_combo.itemData(index)
        if lang:
            self.language_changed.emit(lang)

    def set_theme(self, theme: str):
        """Programmatically set the theme combo box."""
        index = self.theme_combo.findData(theme)
        if index >= 0:
            self.theme_combo.setCurrentIndex(index)

    def set_language(self, lang: str):
        """Programmatically set the language combo box."""
        index = self.lang_combo.findData(lang)
        if index >= 0:
            self.lang_combo.setCurrentIndex(index)

    def set_authenticated(self, authenticated: bool):
        """Keep destructive account data inside Account Settings when signed in."""
        self.account_btn.setVisible(authenticated)
        self.clear_all_progress_btn.setVisible(not authenticated)
