# src/controllers/main_controller.py

import logging

from src.logic.translator import get_translator
from src.storage.user_repository import UserRepository
from src.logic.user_session import UserSession
from src.logic.app_settings import AppSettings

logger = logging.getLogger(__name__)


class MainController:
    """Controller for main window - handles authentication and settings."""

    def __init__(self):
        self.user_repo = UserRepository()
        self.session = UserSession()
        self.settings = AppSettings()
        self.translator = get_translator()
        self.translator.set_language(self.settings.get_language(), persist=False)

        logger.info("MainController initialized")

    # =========================================================
    # AUTHENTICATION
    # =========================================================

    def attempt_login(self, login: str, password: str) -> tuple[bool, str]:
        """
        Attempt to authenticate user.

        Returns:
            (success: bool, message: str)
        """
        if not login or not password:
            return False, "Please enter both login and password"

        user = self.user_repo.authenticate(login, password)
        if user:
            self.session.login(user)
            self.translator.set_language(self.get_language(), persist=False)
            return True, f"Welcome, {user.get('name')}!"

        ban_message = self.user_repo.get_ban_message(login)
        if ban_message:
            return False, ban_message

        return False, "Invalid login or password"

    def register(self, name: str, login: str, password: str) -> tuple[bool, str]:
        success, message, user = self.user_repo.register(name, login, password)
        if success and user:
            self.session.login(user)
            self.translator.set_language(self.get_language(), persist=False)
        return success, message

    def logout(self):
        """Logout current user."""
        self.session.logout()
        self.translator.set_language(self.settings.get_language(), persist=False)
        logger.info("User logged out")

    def continue_as_guest(self):
        """Set guest mode."""
        self.session.logout()  # Ensures guest state
        logger.info("Continuing as guest")

    def can_access_editor(self) -> bool:
        """Check if current user can access editor mode."""
        return self.session.can_edit()

    def get_current_user_name(self) -> str:
        """Get current user's display name."""
        return self.session.get_name()

    def get_current_role(self) -> str:
        """Get current user's role."""
        return self.session.get_role()

    def get_current_user_id(self) -> str:
        """Return the stable owner key for persisted learning progress."""
        if self.session.is_guest or not self.session.current_user:
            return "guest"
        return str(self.session.current_user.get("id", "guest"))

    def update_display_name(self, name: str) -> bool:
        if not self.session.is_authenticated():
            return False
        if self.user_repo.update_display_name(self.get_current_user_id(), name):
            self.session.current_user["name"] = name.strip()
            return True
        return False

    def change_password(self, current_password: str, new_password: str) -> tuple[bool, str]:
        if not self.session.is_authenticated():
            return False, "You must be signed in"
        return self.user_repo.change_password(self.get_current_user_id(), current_password, new_password)

    # =========================================================
    # SETTINGS
    # =========================================================

    def get_theme(self) -> str:
        """Get current theme."""
        if self.session.is_authenticated():
            return self.session.current_user.get("preferences", {}).get("theme", "dark")
        return self.settings.get_theme()

    def toggle_theme(self) -> str:
        """Toggle theme and return new theme."""
        current = self.get_theme()
        new_theme = "light" if current == "dark" else "dark"
        self.set_theme(new_theme)
        return new_theme

    def set_theme(self, theme: str):
        if self.session.is_authenticated():
            preferences = self.session.current_user.setdefault("preferences", {})
            preferences["theme"] = theme
            self.user_repo.save_preferences(self.get_current_user_id(), preferences)
        else:
            self.settings.set_theme(theme)

    def get_language(self) -> str:
        """Get current language."""
        if self.session.is_authenticated():
            return self.session.current_user.get("preferences", {}).get("language", "en")
        return self.settings.get_language()

    def set_language(self, lang_code: str):
        self.translator.set_language(lang_code, persist=False)
        if self.session.is_authenticated():
            preferences = self.session.current_user.setdefault("preferences", {})
            preferences["language"] = lang_code
            self.user_repo.save_preferences(self.get_current_user_id(), preferences)
        else:
            self.settings.set_language(lang_code)

        from PyQt6.QtWidgets import QApplication
        from src.main import load_qt_translations
        load_qt_translations(QApplication.instance(), lang_code)

        logger.info(f"Language changed to: {lang_code}")
