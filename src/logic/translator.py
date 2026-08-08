# src/logic/translator.py

import json
import logging
from typing import Dict, Optional
from src.config import LANGUAGES_DIR

logger = logging.getLogger(__name__)


class Translator:
    """
    Singleton translator for handling multi-language support.
    Loads language files and provides translation strings.
    """

    _instance: Optional['Translator'] = None

    def __new__(cls):
        """Singleton pattern - only one instance exists."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        """Initialize translator (only runs once due to singleton)."""
        if self._initialized:
            return

        self.languages_dir = LANGUAGES_DIR
        self.translations: Dict[str, Dict[str, str]] = {}
        self._load_languages()

        from src.logic.app_settings import AppSettings
        saved_lang = AppSettings().get_language()
        self.current_language = saved_lang if saved_lang in self.translations else "en"

        self._initialized = True
        logger.info(f"Translator initialized with language: {self.current_language}")

    def _load_languages(self):
        """Load all language files from the languages directory."""
        if not self.languages_dir.exists():
            logger.warning(f"Languages directory not found: {self.languages_dir}")
            self.languages_dir.mkdir(parents=True, exist_ok=True)
            return

        for lang_file in self.languages_dir.glob("*.json"):
            lang_code = lang_file.stem  # 'en' from 'en.json'
            try:
                with open(lang_file, 'r', encoding='utf-8') as f:
                    self.translations[lang_code] = json.load(f)
                logger.info(f"Loaded language: {lang_code}")
            except Exception as e:
                logger.error(f"Error loading language file {lang_file}: {e}")

    def set_language(self, language_code: str, persist=True):
        if language_code in self.translations:
            self.current_language = language_code

            # ✅ Persist so next startup remembers it
            if persist:
                from src.logic.app_settings import AppSettings
                AppSettings().set_language(language_code)

            logger.info(f"Language changed to: {language_code}")
        else:
            logger.warning(f"Language '{language_code}' not available, using default")

    def get_language(self) -> str:
        """Get current language code."""
        return self.current_language

    def translate(self, key: str, **kwargs) -> str:
        """Get translated string using dot notation for nested keys."""
        lang_data = self.translations.get(self.current_language, {})

        # Traverse the nested dictionary (e.g., "main_window.title")
        keys = key.split('.')
        value = lang_data
        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
            else:
                value = None
                break

        # Fallback to English if not found
        if value is None and self.current_language != "en":
            en_data = self.translations.get("en", {})
            value = en_data
            for k in keys:
                if isinstance(value, dict):
                    value = value.get(k)
                else:
                    value = None
                    break

        if value is None:
            logger.warning(f"Translation key not found: {key}")
            return key

        # Substitute variables
        if kwargs:
            try:
                return value.format(**kwargs)
            except Exception as e:
                logger.error(f"Formatting error in '{key}': {e}")
                return value

        return value

    def t(self, key: str, **kwargs) -> str:
        """Shorthand for translate()."""
        return self.translate(key, **kwargs)


# Global translator instance
_translator = Translator()


def get_translator() -> Translator:
    """Get the global translator instance."""
    return _translator
