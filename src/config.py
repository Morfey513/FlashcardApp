# src/config.py

from pathlib import Path

# Base directory (where the project root is)
BASE_DIR = Path(__file__).resolve().parent.parent

# Data storage paths
DATA_DIR = BASE_DIR / "data"
CACHE_DIR = BASE_DIR / "cache"
QUIZ_DIR = DATA_DIR / "quizzes"
FLASHCARD_DIR = DATA_DIR / "flashcards"
IMAGE_DIR = DATA_DIR / "images"
AUDIO_DIR = DATA_DIR / "audio"
LANGUAGES_DIR = DATA_DIR / "languages"
# Log Files
LOG_DIR = BASE_DIR / "logs"
LOG_FILE = LOG_DIR / "quiz_app.log"
TEST_LOG_FILE = LOG_DIR / "test_results.log"

# Index Files
QUIZ_INDEX = DATA_DIR / "quizzes.json"
FLASHCARD_INDEX = DATA_DIR / "flashcard_decks.json"
SETTINGS_FILE = DATA_DIR / "settings.json"
USERS_FILE = DATA_DIR / "users.json"
CONTENT_EDIT_HISTORY_FILENAME = "edit_history.json"

# Styles
STYLES_DIR = BASE_DIR / "styles"
DARK_STYLE_PATH = STYLES_DIR / "style.qss"
LIGHT_STYLE_PATH = STYLES_DIR / "style_light.qss"

# Application Settings
APP_NAME = "Study Buddy"
DEFAULT_WINDOW_SIZE = (1000, 800)
# The launcher contains substantially different amounts of content by role.
# These defaults are used only until that guest/account manually resizes it.
LAUNCHER_DEFAULT_SIZES = {
    "guest": (700, 580),
    "student": (700, 660),
    "teacher": (760, 840),
    "admin": (760, 840),
}
# Independent defaults for navigable application windows. A manually resized
# window is stored per identity without changing the launcher's dimensions.
WINDOW_DEFAULT_SIZES = {
    "quiz_editor": (900, 650),
    "flashcard_editor": (900, 650),
    "quiz_mode": (900, 800),
    "flashcard_mode": (750, 770),
    "profile_statistics": (620, 700),
    "account_settings": (520, 700),
    "moderation_admin": (1100, 560),
    "my_classes": (900, 480),
}
MAX_IMAGE_WIDTH = 600
MAX_IMAGE_HEIGHT = 350

MAX_FLASH_IMG_W = 580
MAX_FLASH_IMG_H = 300
FLASHCARD_SIZE = (620, 480)
ANIMATION_DURATION = 400

# Flashcard learning behaviour
FLASHCARD_SESSION_CARD_LIMIT = 20
# Shared learning-mastery rule used by flashcards and quizzes.
MASTERY_REQUIRED_SCORE = 5
MASTERY_WRONG_PENALTY = 1.5
FLASHCARD_REQUEUE_DISTANCE = 3
FLASHCARD_MAX_REQUEUES_PER_CARD = 1

LOGIN_DIALOG_SIZE = (420, 450)


def ensure_directories():
    """Create data directories if they don't exist yet."""
    paths = [
        QUIZ_DIR,
        FLASHCARD_DIR,
        IMAGE_DIR,
        AUDIO_DIR,
        LANGUAGES_DIR,
        LOG_DIR
    ]
    for path in paths:
        path.mkdir(parents=True, exist_ok=True)
