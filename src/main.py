# src/main.py

import sys
from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtCore import QTranslator, QLibraryInfo
import logging

# Modular imports
from src.config import DARK_STYLE_PATH, LIGHT_STYLE_PATH, ensure_directories
from src.ui.main_window import MainLauncher
from src.utils.logger_setup import setup_logging

logger = logging.getLogger(__name__)
_qt_translator: QTranslator | None = None
_showing_unhandled_error = False


def handle_unhandled_exception(exc_type, exc, tb):
    """Keep an exception from a Qt callback visible without aborting the app."""
    global _showing_unhandled_error
    logger.error("Unhandled exception in Qt callback", exc_info=(exc_type, exc, tb))
    app = QApplication.instance()
    if app is None or _showing_unhandled_error:
        return
    _showing_unhandled_error = True
    try:
        QMessageBox.warning(
            app.activeWindow(),
            "Unexpected error",
            "An unexpected error occurred. Details were saved to the application log.",
        )
    except Exception:
        logger.exception("Could not display the unexpected-error message")
    finally:
        _showing_unhandled_error = False


def install_exception_hook():
    sys.excepthook = handle_unhandled_exception


def load_qt_translations(app: QApplication, lang_code: str) -> bool:
    global _qt_translator

    # Remove the old translator first
    if _qt_translator is not None:
        app.removeTranslator(_qt_translator)

    translator = QTranslator(app)
    path = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)

    if translator.load(f"qt_{lang_code}", path):
        app.installTranslator(translator)
        _qt_translator = translator
        logger.info(f"Qt translations loaded for: {lang_code}")
        return True

    logger.warning(f"Qt translations not found for: {lang_code} (path: {path})")
    _qt_translator = None
    return False


def load_stylesheet(path):
    """Loads a QSS file if it exists."""
    try:
        if path.exists():
            return path.read_text(encoding="utf-8")
        else:
            logger.error(f"Stylesheet missing at: {path}")
            return ""
    except Exception as e:
        logger.error(f"Failed to read stylesheet: {e}")
        return ""


def main():
    setup_logging()
    install_exception_hook()
    ensure_directories()

    app = QApplication(sys.argv)
    app.setApplicationName("Learning App Pro")
    app.setOrganizationName("YourNameOrBrand")  # for settings storage

    # load Qt's built-in translations
    from src.logic.translator import get_translator
    lang_code = get_translator().get_language()
    load_qt_translations(app, lang_code)

    # Initial stylesheet
    initial_style = load_stylesheet(DARK_STYLE_PATH)
    if not initial_style:
        # Emergency Fallback: If CSS is missing, apply at least some basic legible colors
        logger.warning("Using emergency fallback styles.")
        app.setStyleSheet("QWidget { background-color: #222; color: white; }")
    else:
        app.setStyleSheet(initial_style)

    window = MainLauncher(DARK_STYLE_PATH, LIGHT_STYLE_PATH)
    load_qt_translations(app, get_translator().get_language())
    window.show()

    logger.info("Application started successfully")
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
