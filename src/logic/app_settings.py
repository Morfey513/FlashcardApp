# src/logic/app_settings.py

import json
import logging
from pathlib import Path
from src.config import SETTINGS_FILE

logger = logging.getLogger(__name__)


class AppSettings:
    """Manages application settings (theme, language, etc.)."""

    def __init__(self):
        self.settings_file = SETTINGS_FILE
        self.settings = self._load_settings()

    def _load_settings(self) -> dict:
        """Load settings from file or create defaults."""
        if self.settings_file.exists():
            try:
                with open(self.settings_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Error loading settings: {e}")

        # Default settings
        return {
            "theme": "dark",
            "language": "en"
        }

    def save(self):
        """Save current settings to file."""
        try:
            self.settings_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.settings_file, 'w', encoding='utf-8') as f:
                json.dump(self.settings, f, indent=4)
            logger.debug("Settings saved")
        except Exception as e:
            logger.error(f"Error saving settings: {e}")

    def get_theme(self) -> str:
        """Get current theme ('dark' or 'light')."""
        return self.settings.get("theme", "dark")

    def set_theme(self, theme: str):
        """Set theme and save."""
        self.settings["theme"] = theme
        self.save()

    def get_language(self) -> str:
        """Get current language ('en' or 'fr')."""
        return self.settings.get("language", "en")

    def set_language(self, lang: str):
        """Set language and save."""
        self.settings["language"] = lang
        self.save()

    def get_launcher_size(self):
        """Return the guest launcher's saved size, if one is available."""
        return self.settings.get("launcher_size")

    def set_launcher_size(self, width: int, height: int):
        """Persist the locally shared guest launcher size."""
        self.settings["launcher_size"] = [int(width), int(height)]
        self.save()

    def get_window_size(self, key: str):
        """Return one guest window's saved size, if available."""
        values = self.settings.get("window_sizes", {})
        return values.get(key) if isinstance(values, dict) else None

    def set_window_size(self, key: str, width: int, height: int):
        """Persist a guest window size independently from the launcher."""
        values = self.settings.setdefault("window_sizes", {})
        values[str(key)] = [int(width), int(height)]
        self.save()
