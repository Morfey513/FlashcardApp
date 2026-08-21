# src/controllers/main_controller.py

import logging

from src.logic.translator import get_translator
from src.storage.repository_factory import configured_storage_backend, create_user_repository
from src.logic.user_session import UserSession
from src.logic.app_settings import AppSettings
from src.config import LAUNCHER_DEFAULT_SIZES, WINDOW_DEFAULT_SIZES

logger = logging.getLogger(__name__)


class MainController:
    """Controller for main window - handles authentication and settings."""

    def __init__(self):
        self.user_repo = create_user_repository()
        self.session = UserSession()
        self.settings = AppSettings()
        self.translator = get_translator()
        self.translator.set_language(self.settings.get_language(), persist=False)

        logger.info("MainController initialized")

    def get_storage_backend(self) -> str:
        """Return the configured persistence mode for status/help text."""
        return configured_storage_backend()

    def is_online(self) -> bool:
        """Report repository readiness without leaking backend exceptions to UI."""
        try:
            return bool(self.user_repo.is_online())
        except Exception as exc:
            logger.warning("Storage readiness check failed: %s", exc)
            return False

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
        self.user_repo.logout()
        self.session.logout()
        self.translator.set_language(self.settings.get_language(), persist=False)
        logger.info("User logged out")

    def continue_as_guest(self):
        """Set guest mode."""
        self.user_repo.logout()
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

    def get_launcher_size(self) -> tuple[int, int]:
        """Return this identity's saved launcher size or its role default."""
        role = self.get_current_role()
        if self.session.is_authenticated():
            value = self.session.current_user.get("preferences", {}).get("launcher_size")
        else:
            value = self.settings.get_launcher_size()

        if (
            isinstance(value, (list, tuple))
            and len(value) == 2
            and all(isinstance(item, int) and item > 0 for item in value)
        ):
            return int(value[0]), int(value[1])
        return LAUNCHER_DEFAULT_SIZES.get(role, LAUNCHER_DEFAULT_SIZES["guest"])

    def set_launcher_size(self, width: int, height: int):
        """Save launcher geometry independently for the active identity."""
        width, height = int(width), int(height)
        if width <= 0 or height <= 0:
            return
        if self.session.is_authenticated():
            preferences = self.session.current_user.setdefault("preferences", {})
            preferences["launcher_size"] = [width, height]
            self.user_repo.save_preferences(self.get_current_user_id(), preferences)
        else:
            self.settings.set_launcher_size(width, height)

    def get_window_size(self, key: str) -> tuple[int, int]:
        """Return a per-identity window size or that window's default."""
        if self.session.is_authenticated():
            values = self.session.current_user.get("preferences", {}).get(
                "window_sizes", {}
            )
            value = values.get(key) if isinstance(values, dict) else None
        else:
            value = self.settings.get_window_size(key)
        if (
            isinstance(value, (list, tuple))
            and len(value) == 2
            and all(isinstance(item, int) and item > 0 for item in value)
        ):
            return int(value[0]), int(value[1])
        return WINDOW_DEFAULT_SIZES.get(key, (800, 650))

    def set_window_size(self, key: str, width: int, height: int):
        """Save one window's dimensions without affecting other windows."""
        width, height = int(width), int(height)
        if not key or width <= 0 or height <= 0:
            return
        if self.session.is_authenticated():
            preferences = self.session.current_user.setdefault("preferences", {})
            values = preferences.setdefault("window_sizes", {})
            values[str(key)] = [width, height]
            self.user_repo.save_preferences(self.get_current_user_id(), preferences)
        else:
            self.settings.set_window_size(key, width, height)
