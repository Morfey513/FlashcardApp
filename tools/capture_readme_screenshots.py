"""Capture representative README screenshots on a graphical Windows desktop.

Run this script outside headless/off-screen mode, with the application closed:
    ./.venv/Scripts/python.exe tools/capture_readme_screenshots.py
"""

from pathlib import Path
import sys

from PyQt6.QtWidgets import QApplication

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.config import DARK_STYLE_PATH, LIGHT_STYLE_PATH
from src.controllers.flashcard_controller import FlashcardController
from src.controllers.flashcard_editor_controller import FlashcardEditorController
from src.controllers.quiz_controller import QuizController
from src.controllers.quiz_editor_controller import QuizEditorController
from src.controllers.profile_statistics_controller import ProfileStatisticsController
from src.ui.account_settings_dialog import AccountSettingsDialog
from src.ui.account_suspension_dialog import AccountSuspensionDialog
from src.ui.editor.flashcard_editor import FlashcardEditor
from src.ui.editor.quiz_editor import QuizEditor
from src.ui.flashcard_viewer import FlashcardViewer
from src.ui.login_dialog import LoginDialog
from src.ui.main_window import MainLauncher
from src.ui.moderation_dialog import ImagePreviewDialog, ModerationDialog
from src.ui.profile_statistics_dialog import ProfileStatisticsDialog
from src.ui.quiz_view import QuizViewer
from src.ui.registration_dialog import RegistrationDialog


SCREENSHOT_DIR = PROJECT_ROOT / "docs" / "screenshots"


def capture(app: QApplication, widget, destination: Path) -> None:
    """Show, render, capture, and close a window without user interaction."""
    widget.show()
    app.processEvents()
    app.processEvents()
    if not widget.grab().save(str(destination)):
        raise RuntimeError(f"Could not save screenshot: {destination}")
    widget.close()


def launcher_for(login: str | None = None, password: str | None = None) -> MainLauncher:
    """Return a launcher in guest mode or as a local test account."""
    launcher = MainLauncher(DARK_STYLE_PATH, LIGHT_STYLE_PATH)
    if login:
        success, message = launcher.controller.attempt_login(login, password or "")
        if not success:
            raise RuntimeError(f"Could not authenticate {login!r}: {message}")
        launcher.update_ui_for_user()
    return launcher


def first_image() -> Path | None:
    """Find a bundled image for the optional image-preview dialog capture."""
    for suffix in ("*.png", "*.jpg", "*.jpeg", "*.webp", "*.bmp", "*.gif"):
        image = next((path for path in (PROJECT_ROOT / "data").rglob(suffix) if path.is_file()), None)
        if image:
            return image
    return None


def main() -> None:
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    app = QApplication(sys.argv)

    dark = DARK_STYLE_PATH.read_text(encoding="utf-8")
    light = LIGHT_STYLE_PATH.read_text(encoding="utf-8")

    app.setStyleSheet(dark)
    guest = launcher_for()
    capture(app, guest, SCREENSHOT_DIR / "01-guest-launcher.png")

    app.setStyleSheet(light)
    student = launcher_for("student", "student123")
    capture(app, student, SCREENSHOT_DIR / "02-student-launcher.png")

    app.setStyleSheet(dark)
    admin = launcher_for("admin", "admin123")
    capture(app, admin, SCREENSHOT_DIR / "03-admin-launcher.png")
    admin.stack.setCurrentWidget(admin.editor_panel)
    capture(app, admin, SCREENSHOT_DIR / "04-editor-selection.png")

    capture(app, LoginDialog(), SCREENSHOT_DIR / "05-login-dialog.png")
    capture(app, RegistrationDialog(), SCREENSHOT_DIR / "06-registration-dialog.png")

    settings_host = launcher_for()
    settings_host.show_settings()
    capture(app, settings_host, SCREENSHOT_DIR / "07-settings-panel.png")

    account_host = launcher_for("admin", "admin123")
    capture(
        app,
        AccountSettingsDialog(account_host.controller),
        SCREENSHOT_DIR / "08-account-settings.png",
    )
    capture(
        app,
        ProfileStatisticsDialog(ProfileStatisticsController("1")),
        SCREENSHOT_DIR / "09-my-progress.png",
    )

    app.setStyleSheet(light)
    capture(
        app,
        QuizViewer(QuizController(user_id="guest", role="guest")),
        SCREENSHOT_DIR / "10-quiz-selection.png",
    )
    capture(
        app,
        FlashcardViewer(FlashcardController(user_id="guest", role="guest")),
        SCREENSHOT_DIR / "11-flashcard-selection.png",
    )

    app.setStyleSheet(dark)
    capture(
        app,
        QuizEditor(QuizEditorController(owner_id="1", role="admin")),
        SCREENSHOT_DIR / "12-quiz-editor.png",
    )
    capture(
        app,
        FlashcardEditor(FlashcardEditorController(owner_id="1", role="admin")),
        SCREENSHOT_DIR / "13-flashcard-editor.png",
    )

    moderation = ModerationDialog("1")
    capture(app, moderation, SCREENSHOT_DIR / "14-moderation-content.png")
    moderation = ModerationDialog("1")
    moderation.tabs.setCurrentIndex(1)
    capture(app, moderation, SCREENSHOT_DIR / "15-moderation-users.png")
    capture(
        app,
        AccountSuspensionDialog("Example moderation reason."),
        SCREENSHOT_DIR / "16-account-suspension.png",
    )

    image = first_image()
    if image:
        capture(app, ImagePreviewDialog(image), SCREENSHOT_DIR / "17-image-preview.png")
    print(f"Created README screenshots in {SCREENSHOT_DIR}")


if __name__ == "__main__":
    main()
