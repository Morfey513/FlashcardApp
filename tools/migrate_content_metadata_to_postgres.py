"""Import quiz/deck metadata and ownership while bodies remain in JSON."""

import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config import FLASHCARD_DIR, QUIZ_DIR
from src.storage.postgres_content_metadata_repository import (
    PostgresContentMetadataRepository,
)
from src.utils.paths import to_stored_path


def main() -> int:
    repository = PostgresContentMetadataRepository()
    candidates = [
        ("quiz", path) for path in QUIZ_DIR.glob("*/quiz.json")
    ] + [
        ("flashcard", path) for path in FLASHCARD_DIR.glob("*/deck.json")
    ]
    failed = []
    for kind, path in candidates:
        try:
            source = json.loads(path.read_text(encoding="utf-8"))
            imported = (
                repository.import_quiz(source, to_stored_path(path))
                if kind == "quiz"
                else repository.import_flashcard_deck(source, to_stored_path(path))
            )
        except (OSError, json.JSONDecodeError):
            imported = False
        if not imported:
            failed.append(str(path))
    if failed:
        print("Content metadata migration failed for:")
        for path in failed:
            print(f"- {path}")
        return 1
    quizzes = sum(kind == "quiz" for kind, _path in candidates)
    decks = len(candidates) - quizzes
    print(f"Imported {quizzes} quiz(es) and {decks} flashcard deck(s) into PostgreSQL.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
