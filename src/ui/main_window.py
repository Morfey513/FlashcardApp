# src/ui/main_window.py

import logging
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QPushButton, QLabel,
    QApplication, QStackedWidget, QMessageBox, QFrame
)
from PyQt6.QtCore import Qt

from src.controllers.main_controller import MainController
from src.logic.translator import get_translator
from src.ui.login_dialog import LoginDialog
from src.ui.registration_dialog import RegistrationDialog
from src.ui.account_settings_dialog import AccountSettingsDialog
from src.ui.profile_statistics_dialog import ProfileStatisticsDialog
from src.ui.settings_panel import SettingsPanel
from src.ui.account_suspension_dialog import AccountSuspensionDialog

logger = logging.getLogger(__name__)


class MainLauncher(QWidget):
    """Main application window with authentication and settings."""

    def __init__(self, dark_path, light_path):
        super().__init__()

        # Paths for themes
        self.dark_path = dark_path
        self.light_path = light_path

        # Controller
        self.controller = MainController()

        # Active window reference
        self.active_window = None

        # Overlay management
        self.login_dialog = None
        self.registration_dialog = None
        self.account_settings_dialog = None
        self.profile_statistics_dialog = None
        self.settings_panel = None
        self.overlay_widget = None  # Semi-transparent overlay

        # Get translator
        self.translator = get_translator()

        self.setWindowTitle("Learning App")
        self.resize(700, 620)

        # Main stack
        self.stack = QStackedWidget()
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(self.stack)

        # Create overlay widget (hidden by default)
        self.create_overlay()

        # Initialize panels
        self.init_main_panel()
        self.init_editor_selection_panel()

        # Apply initial theme
        self.apply_theme(self.controller.get_theme())

        # START IN GUEST MODE
        self.controller.continue_as_guest()
        self.update_ui_for_user()

        # Show main panel immediately
        self.stack.setCurrentWidget(self.main_panel)

    # =========================================================
    # OVERLAY WIDGET
    # =========================================================

    def create_overlay(self):
        """Create semi-transparent overlay for settings panel."""
        self.overlay_widget = QWidget(self)
        self.overlay_widget.setObjectName("settings_overlay")

        self.overlay_widget.hide()

        # Make overlay clickable to close settings
        self.overlay_widget.mousePressEvent = lambda event: self.hide_settings()

    def update_overlay_geometry(self):
        """Update overlay to cover the entire window."""
        if self.overlay_widget:
            self.overlay_widget.setGeometry(0, 0, self.width(), self.height())
            self.overlay_widget.raise_()  # Keep it on top

            # Keep settings panel above overlay
            if self.settings_panel and self.settings_panel.isVisible():
                self.settings_panel.raise_()

    # =========================================================
    # OVERLAY MANAGEMENT
    # =========================================================

    def close_all_overlays(self, except_overlay=None):
        """
        Close all open overlays (dialogs, panels).

        Args:
            except_overlay: Optional overlay to keep open (e.g., 'login', 'settings')
        """
        # Close login dialog
        if except_overlay != 'login' and self.login_dialog:
            if self.login_dialog.isVisible():
                self.login_dialog.hide()
                logger.debug("Closed login dialog")

        if except_overlay != 'registration' and self.registration_dialog:
            if self.registration_dialog.isVisible():
                self.registration_dialog.hide()

        if except_overlay != 'account' and self.account_settings_dialog:
            if self.account_settings_dialog.isVisible():
                self.account_settings_dialog.hide()

        # Close settings panel
        if except_overlay != 'settings' and self.settings_panel:
            if self.settings_panel.isVisible():
                self.settings_panel.hide()
                self.overlay_widget.hide()
                logger.debug("Closed settings panel")

    # =========================================================
    # AUTHENTICATION
    # =========================================================

    def show_login_dialog(self):
        """Show login dialog."""
        self.close_all_overlays(except_overlay='login')

        if self.login_dialog and self.login_dialog.isVisible():
            self.login_dialog.hide()
            return

        if not self.login_dialog:
            self.login_dialog = LoginDialog(self)
            self.login_dialog.login_success.connect(self.handle_login)
            self.login_dialog.guest_mode.connect(self.handle_guest_mode)
            self.login_dialog.signup_requested.connect(self.show_registration_dialog)
            self.login_dialog.setWindowModality(Qt.WindowModality.NonModal)

        self.login_dialog.clear_error()
        self.login_dialog.clear_password()

        # Position in center
        self.login_dialog.move(
            self.x() + (self.width() - self.login_dialog.width()) // 2,
            self.y() + (self.height() - self.login_dialog.height()) // 2
        )

        self.login_dialog.show()
        self.login_dialog.raise_()
        logger.debug("Opened login dialog")

    def show_registration_dialog(self):
        """Open local registration using the same visual language as login."""
        if self.login_dialog:
            self.login_dialog.hide()
        if not self.registration_dialog:
            self.registration_dialog = RegistrationDialog(self)
            self.registration_dialog.registration_requested.connect(self.handle_registration)
            self.registration_dialog.rejected.connect(self.show_login_dialog)
        self.registration_dialog.move(
            self.x() + (self.width() - self.registration_dialog.width()) // 2,
            self.y() + (self.height() - self.registration_dialog.height()) // 2,
        )
        self.registration_dialog.show()
        self.registration_dialog.raise_()

    def handle_registration(self, name: str, login: str, password: str):
        success, message = self.controller.register(name, login, password)
        if not success:
            self.registration_dialog.show_error(message)
            return
        self.registration_dialog.clear_passwords()
        self.registration_dialog.hide()
        self.apply_theme(self.controller.get_theme())
        self.change_language(self.controller.get_language())
        self.update_ui_for_user()

    def handle_login(self, login: str, password: str):
        """Handle login attempt."""
        success, message = self.controller.attempt_login(login, password)

        if success:
            logger.info(f"Login successful: {self.controller.get_current_user_name()}")

            if self.login_dialog:
                self.login_dialog.clear_password()
                self.login_dialog.hide()

            self.apply_theme(self.controller.get_theme())
            self.change_language(self.controller.get_language())
            self.update_ui_for_user()
        else:
            if self.login_dialog:
                self.login_dialog.show_error(message)
                # A failed non-modal attempt must remain visible and focused.
                self.login_dialog.show()
                self.login_dialog.raise_()
                self.login_dialog.activateWindow()
                if message.startswith("Account suspended."):
                    reason = message.removeprefix("Account suspended. Reason: ")
                    AccountSuspensionDialog(reason, self.login_dialog).exec()

    def handle_guest_mode(self):
        """Handle guest mode selection."""
        self.controller.continue_as_guest()
        self.update_ui_for_user()

        if self.login_dialog:
            self.login_dialog.hide()

        logger.info("Continuing as guest")

    def logout(self):
        """Logout current user and return to guest mode."""
        t = self.translator
        answer = QMessageBox.question(
            self,
            t.t("main_window.confirm_logout_title"),
            t.t("main_window.confirm_logout_message"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.controller.logout()
        if self.login_dialog:
            self.login_dialog.clear_password()
        self.apply_theme(self.controller.get_theme())
        self.change_language(self.controller.get_language())
        self.update_ui_for_user()
        self.stack.setCurrentWidget(self.main_panel)

        self.close_all_overlays()

        logger.info("Logged out, returned to guest mode")

    def update_ui_for_user(self):
        """Update UI with role-specific logic using structured keys."""
        t = self.translator
        role = self.controller.get_current_role()
        name = self.controller.get_current_user_name()
        is_guest = (role == "guest")

        if is_guest:
            # Note the new nested key format
            self.welcome_label.setText(t.t('main_window.welcome_guest'))
        else:
            self.welcome_label.setText(t.t('main_window.welcome_user', name=name))
            self.logged_in_user_label.setText(t.t('editor_selection.logged_in_as', name=name))

        self.login_btn.setVisible(is_guest)
        self.logout_btn.setVisible(not is_guest)
        can_edit = self.controller.can_access_editor()
        self.quiz_editor_btn.setVisible(can_edit)
        self.flashcard_editor_btn.setVisible(can_edit)
        # A single, role-specific full-width management action prevents two
        # hidden buttons from sharing one grid cell (which caused artefacts in
        # the dark stylesheet).
        self.role_action_btn.setVisible(role in {"teacher", "admin"})
        if role == "teacher":
            self.role_action_btn.setText("🏫 My Classes / Roster")
            self.role_action_btn.setProperty("role_action", "classes")
        elif role == "admin":
            self.role_action_btn.setText(t.t('main_window.btn_moderation'))
            self.role_action_btn.setProperty("role_action", "moderation")
        is_student = role == "student"
        # Students already have My Progress in their compact launcher.
        self.profile_btn.setVisible(not is_guest and not is_student)
        self.guest_actions_row.setVisible(is_guest)
        self.student_actions_row.setVisible(is_student)
        self.study_label.setVisible(not is_guest and not is_student)
        self.study_row.setVisible(not is_guest and not is_student)
        self.quit_btn.setVisible(not is_guest and not is_student)
        show_management = can_edit or role == "admin"
        self.management_label.setVisible(show_management)
        self.management_divider.setVisible(show_management)
        self.management_row.setVisible(show_management)

    # =========================================================
    # PANELS
    # =========================================================

    def init_main_panel(self):
        """Initialize main panel with translatable elements."""
        self.main_panel = QWidget()
        layout = QVBoxLayout(self.main_panel)
        layout.setContentsMargins(60, 60, 60, 60)
        layout.setSpacing(20)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Top bar
        top_bar = QHBoxLayout()
        self.welcome_label = QLabel()  # Text set in update_ui_for_user
        self.welcome_label.setObjectName("welcome_label")
        top_bar.addWidget(self.welcome_label)
        top_bar.addStretch()

        self.settings_btn = QPushButton("⚙️")
        self.settings_btn.setObjectName("settings_btn")
        self.settings_btn.clicked.connect(self.toggle_settings)
        top_bar.addWidget(self.settings_btn)

        self.login_btn = QPushButton("🔑")
        self.login_btn.setObjectName("login_btn")
        self.login_btn.clicked.connect(self.show_login_dialog)
        top_bar.addWidget(self.login_btn)

        self.logout_btn = QPushButton("🚪")
        self.logout_btn.setObjectName("logout_btn")
        self.logout_btn.clicked.connect(self.logout)
        self.logout_btn.hide()
        top_bar.addWidget(self.logout_btn)

        layout.addLayout(top_bar)
        layout.addSpacing(40)

        # Labels
        self.title_label = QLabel()
        self.title_label.setObjectName("title")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.title_label)

        self.subtitle_label = QLabel()
        self.subtitle_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.subtitle_label.setObjectName("subtitle_label")
        layout.addWidget(self.subtitle_label)

        layout.addSpacing(20)

        # Study controls are grouped so the two modes use the available width
        # without making the launch screen feel like one long button column.
        self.study_label = QLabel("STUDY MODES")
        self.study_label.setObjectName("section_label")
        layout.addWidget(self.study_label)

        self.study_row = QWidget()
        study_layout = QHBoxLayout(self.study_row)
        study_layout.setContentsMargins(0, 0, 0, 0)
        study_layout.setSpacing(20)
        self.quiz_btn = QPushButton()
        self.quiz_btn.clicked.connect(self.open_quiz_mode)
        study_layout.addWidget(self.quiz_btn)

        self.flashcard_btn = QPushButton()
        self.flashcard_btn.clicked.connect(self.open_flashcard_mode)
        study_layout.addWidget(self.flashcard_btn)
        layout.addWidget(self.study_row)

        # Guests and students have fewer actions.  Keep those launchers in a
        # calm, familiar vertical column instead of stretching a few controls
        # across the full window.
        self.guest_actions_row = QWidget()
        guest_actions_layout = QVBoxLayout(self.guest_actions_row)
        guest_actions_layout.setContentsMargins(0, 0, 0, 0)
        guest_actions_layout.setSpacing(14)
        self.guest_quiz_btn = QPushButton()
        self.guest_quiz_btn.clicked.connect(self.open_quiz_mode)
        guest_actions_layout.addWidget(self.guest_quiz_btn, alignment=Qt.AlignmentFlag.AlignCenter)
        self.guest_flashcard_btn = QPushButton()
        self.guest_flashcard_btn.clicked.connect(self.open_flashcard_mode)
        guest_actions_layout.addWidget(self.guest_flashcard_btn, alignment=Qt.AlignmentFlag.AlignCenter)
        self.guest_quit_btn = QPushButton()
        self.guest_quit_btn.clicked.connect(self.close)
        guest_actions_layout.addWidget(self.guest_quit_btn, alignment=Qt.AlignmentFlag.AlignCenter)
        self.guest_actions_row.hide()
        layout.addWidget(self.guest_actions_row)

        self.student_actions_row = QWidget()
        student_actions_layout = QVBoxLayout(self.student_actions_row)
        student_actions_layout.setContentsMargins(0, 0, 0, 0)
        student_actions_layout.setSpacing(14)
        self.student_quiz_btn = QPushButton()
        self.student_quiz_btn.clicked.connect(self.open_quiz_mode)
        student_actions_layout.addWidget(self.student_quiz_btn, alignment=Qt.AlignmentFlag.AlignCenter)
        self.student_flashcard_btn = QPushButton()
        self.student_flashcard_btn.clicked.connect(self.open_flashcard_mode)
        student_actions_layout.addWidget(self.student_flashcard_btn, alignment=Qt.AlignmentFlag.AlignCenter)
        self.student_progress_btn = QPushButton()
        self.student_progress_btn.clicked.connect(self.show_profile_statistics)
        student_actions_layout.addWidget(self.student_progress_btn, alignment=Qt.AlignmentFlag.AlignCenter)
        self.student_quit_btn = QPushButton()
        self.student_quit_btn.clicked.connect(self.close)
        student_actions_layout.addWidget(self.student_quit_btn, alignment=Qt.AlignmentFlag.AlignCenter)
        self.student_actions_row.hide()
        layout.addWidget(self.student_actions_row)

        self.profile_btn = QPushButton()
        self.profile_btn.clicked.connect(self.show_profile_statistics)
        self.profile_btn.hide()
        layout.addWidget(self.profile_btn)

        self.management_divider = QFrame()
        self.management_divider.setFrameShape(QFrame.Shape.HLine)
        self.management_divider.setObjectName("management_divider")
        layout.addWidget(self.management_divider)
        self.management_label = QLabel("MANAGEMENT")
        self.management_label.setObjectName("section_label")
        self.management_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.management_label)

        self.management_row = QWidget()
        management_layout = QGridLayout(self.management_row)
        management_layout.setContentsMargins(0, 0, 0, 0)
        management_layout.setSpacing(20)

        self.quiz_editor_btn = QPushButton()
        self.quiz_editor_btn.clicked.connect(self.open_quiz_editor)
        self.quiz_editor_btn.hide()
        management_layout.addWidget(self.quiz_editor_btn, 0, 0)

        self.flashcard_editor_btn = QPushButton()
        self.flashcard_editor_btn.clicked.connect(self.open_flashcard_editor)
        self.flashcard_editor_btn.hide()
        management_layout.addWidget(self.flashcard_editor_btn, 0, 1)

        self.role_action_btn = QPushButton()
        self.role_action_btn.clicked.connect(self.open_role_management)
        self.role_action_btn.hide()
        management_layout.addWidget(self.role_action_btn, 1, 0, 1, 2)
        layout.addWidget(self.management_row)

        layout.addSpacing(20)

        self.quit_btn = QPushButton()
        self.quit_btn.clicked.connect(self.close)
        layout.addWidget(self.quit_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        layout.addStretch()
        self.stack.addWidget(self.main_panel)

    def init_editor_selection_panel(self):
        """Initialize editor selection panel with translatable elements."""
        self.editor_panel = QWidget()
        layout = QVBoxLayout(self.editor_panel)
        layout.setContentsMargins(60, 60, 60, 60)
        layout.setSpacing(30)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Top bar
        top_bar = QHBoxLayout()
        self.logged_in_user_label = QLabel()
        self.logged_in_user_label.setObjectName("welcome_label")
        top_bar.addWidget(self.logged_in_user_label)
        top_bar.addStretch()

        editor_settings_btn = QPushButton("⚙️")  # Reuse logic
        editor_settings_btn.setObjectName("settings_btn")
        editor_settings_btn.clicked.connect(self.toggle_settings)
        top_bar.addWidget(editor_settings_btn)

        layout.addLayout(top_bar)

        self.editor_title_label = QLabel()
        self.editor_title_label.setObjectName("title")
        self.editor_title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.editor_title_label)

        self.editor_subtitle_label = QLabel()
        self.editor_subtitle_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.editor_subtitle_label.setObjectName("subtitle_label")
        layout.addWidget(self.editor_subtitle_label)

        layout.addSpacing(20)

        self.editor_panel_quiz_btn = QPushButton()
        self.editor_panel_quiz_btn.clicked.connect(self.open_quiz_editor)
        layout.addWidget(self.editor_panel_quiz_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        self.editor_panel_flashcard_btn = QPushButton()
        self.editor_panel_flashcard_btn.clicked.connect(self.open_flashcard_editor)
        layout.addWidget(self.editor_panel_flashcard_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        layout.addSpacing(20)

        self.back_btn = QPushButton()
        self.back_btn.clicked.connect(lambda: self.stack.setCurrentWidget(self.main_panel))
        layout.addWidget(self.back_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        layout.addStretch()
        self.stack.addWidget(self.editor_panel)

        # Call refresh once after both panels are ready
        self.refresh_translations()

    # =========================================================
    # SETTINGS
    # =========================================================

    def toggle_settings(self):
        """Toggle settings panel visibility."""
        if self.settings_panel and self.settings_panel.isVisible():
            self.hide_settings()
        else:
            self.show_settings()

    def show_settings(self):
        """Show settings panel on the right side."""
        self.close_all_overlays(except_overlay='settings')

        if not self.settings_panel:
            self.settings_panel = SettingsPanel(position="side", parent=self)
            self.settings_panel.theme_changed.connect(self.apply_theme)
            self.settings_panel.language_changed.connect(self.change_language)
            self.settings_panel.clear_all_progress_requested.connect(self.clear_all_learning_progress)
            self.settings_panel.account_requested.connect(self.show_account_settings)
            self.settings_panel.closed.connect(self.hide_settings)

        self.settings_panel.set_theme(self.controller.get_theme())
        self.settings_panel.set_language(self.controller.get_language())
        self.settings_panel.set_authenticated(self.controller.session.is_authenticated())

        # Show overlay first
        self.update_overlay_geometry()
        self.overlay_widget.show()

        # Position settings panel
        panel_width = 280
        self.settings_panel.setGeometry(
            self.width() - panel_width,
            0,
            panel_width,
            self.height()
        )

        self.settings_panel.show()
        self.settings_panel.raise_()
        logger.debug("Settings panel shown with overlay")

    def hide_settings(self):
        """Hide settings panel and overlay."""
        if self.settings_panel:
            self.settings_panel.hide()

        # Hide overlay
        if self.overlay_widget:
            self.overlay_widget.hide()

        logger.debug("Settings panel and overlay hidden")

    def show_account_settings(self):
        """Open personal account settings for the signed-in user."""
        if not self.controller.session.is_authenticated():
            return
        self.hide_settings()
        if not self.account_settings_dialog:
            self.account_settings_dialog = AccountSettingsDialog(self.controller, self)
            self.account_settings_dialog.profile_saved.connect(self.update_ui_for_user)
            self.account_settings_dialog.clear_all_progress_requested.connect(self.clear_all_learning_progress)
        self.account_settings_dialog.refresh_account()
        self.account_settings_dialog.move(
            self.x() + (self.width() - self.account_settings_dialog.width()) // 2,
            self.y() + (self.height() - self.account_settings_dialog.height()) // 2,
        )
        self.account_settings_dialog.show()
        self.account_settings_dialog.raise_()

    def clear_current_user_progress(self):
        """Confirm and clear only the active user's flashcard progress."""
        t = self.translator
        answer = QMessageBox.question(
            self,
            t.t("settings_panel.confirm_clear_progress_title"),
            t.t(
                "settings_panel.confirm_clear_progress_message",
                name=self.controller.get_current_user_name(),
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        from src.storage.flashcard_repository import FlashcardRepository
        removed = FlashcardRepository().clear_user_progress(self.controller.get_current_user_id())
        logger.info("Cleared %s flashcard progress files for the active user", removed)

    def clear_all_learning_progress(self):
        """Clear both learning modes but preserve account and preference data."""
        t = self.translator
        if QMessageBox.question(self, t.t("profile_statistics.confirm_reset_title"), t.t("profile_statistics.confirm_reset_all", scope=t.t("profile_statistics.scope_all")), QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        from src.storage.flashcard_repository import FlashcardRepository
        from src.storage.quiz_repository import QuizRepository
        user_id = self.controller.get_current_user_id()
        FlashcardRepository().clear_user_progress(user_id)
        QuizRepository().clear_user_progress(user_id)

    def clear_current_user_quiz_progress(self):
        """Confirm and clear only the active user's quiz learning progress."""
        t = self.translator
        answer = QMessageBox.question(
            self,
            t.t("settings_panel.confirm_clear_quiz_title"),
            t.t(
                "settings_panel.confirm_clear_quiz_message",
                name=self.controller.get_current_user_name(),
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        from src.storage.quiz_repository import QuizRepository
        removed = QuizRepository().clear_user_progress(self.controller.get_current_user_id())
        logger.info("Cleared %s quiz progress files for the active user", removed)

    def resizeEvent(self, event):
        """Handle window resize to reposition overlays."""
        super().resizeEvent(event)

        # Update overlay geometry
        self.update_overlay_geometry()

        # Reposition settings panel if visible
        if self.settings_panel and self.settings_panel.isVisible():
            panel_width = 280
            self.settings_panel.setGeometry(
                self.width() - panel_width,
                0,
                panel_width,
                self.height()
            )

    # =========================================================
    # THEME & LANGUAGE
    # =========================================================

    def apply_theme(self, theme: str):
        """Apply theme stylesheet."""
        self.controller.set_theme(theme)

        path = self.dark_path if theme == "dark" else self.light_path

        try:
            stylesheet = path.read_text(encoding="utf-8")
            QApplication.instance().setStyleSheet(stylesheet)
            logger.info(f"Applied {theme} theme")
        except Exception as e:
            logger.error(f"Failed to apply theme: {e}")

    def change_language(self, lang: str):
        """Change application language."""
        self.controller.set_language(lang)
        self.refresh_translations()

        logger.info(f"Language changed to: {lang}")

    def refresh_translations(self):
        """Refresh all UI text across the main window and all active sub-components."""
        t = self.translator

        # 1. Update Main Window Elements
        self.setWindowTitle(t.t('common.app_title'))
        self.settings_btn.setToolTip(t.t('main_window.tooltip_settings'))
        self.login_btn.setToolTip(t.t('main_window.tooltip_login'))
        self.logout_btn.setToolTip(t.t('main_window.tooltip_logout'))

        self.title_label.setText(t.t('common.app_title'))
        self.subtitle_label.setText(t.t('main_window.subtitle_study'))
        self.quiz_btn.setText(t.t('main_window.btn_quiz_mode'))
        self.flashcard_btn.setText(t.t('main_window.btn_flashcard_mode'))
        self.guest_quiz_btn.setText(t.t('main_window.btn_quiz_mode'))
        self.guest_flashcard_btn.setText(t.t('main_window.btn_flashcard_mode'))
        self.guest_quit_btn.setText(t.t('common.btn_quit'))
        self.student_quiz_btn.setText(t.t('main_window.btn_quiz_mode'))
        self.student_flashcard_btn.setText(t.t('main_window.btn_flashcard_mode'))
        self.student_progress_btn.setText(t.t('main_window.btn_my_progress'))
        self.student_quit_btn.setText(t.t('common.btn_quit'))
        self.profile_btn.setText(t.t('main_window.btn_my_progress'))
        self.quit_btn.setText(t.t('common.btn_quit'))

        self.editor_title_label.setText(t.t('editor_selection.title'))
        self.editor_subtitle_label.setText(t.t('editor_selection.subtitle'))
        self.quiz_editor_btn.setText(t.t('editor_selection.btn_quiz_editor'))
        self.flashcard_editor_btn.setText(t.t('editor_selection.btn_flashcard_editor'))
        self.editor_panel_quiz_btn.setText(t.t('editor_selection.btn_quiz_editor'))
        self.editor_panel_flashcard_btn.setText(t.t('editor_selection.btn_flashcard_editor'))
        self.back_btn.setText(t.t('common.btn_back'))

        # 2. Update the "Kids" (Sub-components)
        # We check if they exist because they are created lazily
        if self.settings_panel:
            self.settings_panel.retranslate_ui()
            logger.debug("Settings panel retranslated")

        if self.login_dialog:
            self.login_dialog.retranslate_ui()
            logger.debug("Login dialog retranslated")
        if self.registration_dialog:
            self.registration_dialog.retranslate_ui()
        if self.account_settings_dialog:
            self.account_settings_dialog.retranslate_ui()
        if self.profile_statistics_dialog:
            self.profile_statistics_dialog.retranslate_ui()
            self.profile_statistics_dialog.refresh_statistics()

        # 3. Update dynamic labels (Welcome Guest / Name)
        self.update_ui_for_user()

    # =========================================================
    # NAVIGATION
    # =========================================================

    def _launch_sub_window(self, window_class, *args):
        """Launch sub-window."""
        self.close_all_overlays()

        if self.active_window:
            self.active_window.close()

        try:
            self.active_window = window_class(*args)
            self.active_window.finished.connect(self.on_child_window_closed)
            self.active_window.show()
            self.hide()
            logger.info(f"Launched {window_class.__name__}")
        except Exception as e:
            logger.error(f"Failed to launch window: {e}", exc_info=True)
            self.show()

    def open_editor_selection(self):
        """Navigate to editor selection."""
        if not self.controller.can_access_editor():
            logger.warning("User attempted to access editor without permissions")
            return

        self.close_all_overlays()
        self.stack.setCurrentWidget(self.editor_panel)

    def open_quiz_mode(self):
        from src.ui.quiz_view import QuizViewer
        from src.controllers.quiz_controller import QuizController

        controller = QuizController(
            self.controller.get_current_user_id(),
            role=self.controller.get_current_role(),
        )
        self._launch_sub_window(QuizViewer, controller)

    def show_profile_statistics(self):
        """Show the authenticated learner's saved flashcard and quiz progress."""
        if not self.controller.session.is_authenticated():
            return
        from src.controllers.profile_statistics_controller import ProfileStatisticsController

        stats_controller = ProfileStatisticsController(self.controller.get_current_user_id())
        # A fresh dialog deliberately resets filters, expanded groups, scroll
        # position, and temporary render state every time it is opened.
        self.profile_statistics_dialog = ProfileStatisticsDialog(stats_controller, self)
        self.profile_statistics_dialog.move(
            self.x() + (self.width() - self.profile_statistics_dialog.width()) // 2,
            self.y() + (self.height() - self.profile_statistics_dialog.height()) // 2,
        )
        self.profile_statistics_dialog.show()
        self.profile_statistics_dialog.raise_()

    def open_quiz_editor(self):
        from src.ui.editor.quiz_editor import QuizEditor
        from src.controllers.quiz_editor_controller import QuizEditorController

        controller = QuizEditorController(
            self.controller.get_current_user_id(), self.controller.get_current_role()
        )
        self._launch_sub_window(QuizEditor, controller)

    def open_flashcard_mode(self):
        from src.ui.flashcard_viewer import FlashcardViewer
        from src.controllers.flashcard_controller import FlashcardController

        controller = FlashcardController(
            self.controller.get_current_user_id(),
            role=self.controller.get_current_role(),
        )
        self._launch_sub_window(FlashcardViewer, controller)

    def open_moderation(self):
        role = self.controller.get_current_role()
        if role != "admin":
            return
        from src.ui.moderation_dialog import ModerationDialog
        ModerationDialog(self.controller.get_current_user_id(), role, self).exec()

    def open_role_management(self):
        """Route the one management action shown for the current role."""
        if self.role_action_btn.property("role_action") == "classes":
            self.open_my_classes()
        else:
            self.open_moderation()

    def open_my_classes(self):
        """Open the current teacher/admin's own class roster directly."""
        role = self.controller.get_current_role()
        if role != "teacher":
            return
        from src.ui.moderation_dialog import ModerationDialog
        ModerationDialog(
            self.controller.get_current_user_id(), role, self, initial_tab="classes"
        ).exec()

    def open_flashcard_editor(self):
        from src.ui.editor.flashcard_editor import FlashcardEditor
        from src.controllers.flashcard_editor_controller import FlashcardEditorController

        controller = FlashcardEditorController(
            self.controller.get_current_user_id(), self.controller.get_current_role()
        )
        self._launch_sub_window(FlashcardEditor, controller)

    def on_child_window_closed(self):
        """Handle child window closing."""
        self.show()
        if self.active_window:
            self.active_window.deleteLater()
            self.active_window = None
