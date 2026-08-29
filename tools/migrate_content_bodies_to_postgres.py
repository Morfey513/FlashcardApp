"""Import quiz questions, flashcards, and media metadata into PostgreSQL."""

import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config import FLASHCARD_DIR, QUIZ_DIR
from src.storage.postgres_content_body_repository import PostgresContentBodyRepository


def main() -> int:
    # This one-shot migration is the only path allowed to ingest trusted legacy
    # JSON filesystem references. Runtime/API body writes require opaque IDs.
    repository = PostgresContentBodyRepository()
    repository.allow_legacy_paths = True
    imported_quizzes = 0
    imported_decks = 0
    failed = []
    for path in QUIZ_DIR.glob("*/quiz.json"):
        try:
            success = repository.import_quiz(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            success = False
        if success:
            imported_quizzes += 1
        else:
            failed.append(str(path))
    for path in FLASHCARD_DIR.glob("*/deck.json"):
        try:
            success = repository.import_flashcard_deck(
                json.loads(path.read_text(encoding="utf-8"))
            )
        except (OSError, json.JSONDecodeError):
            success = False
        if success:
            imported_decks += 1
        else:
            failed.append(str(path))
    print(
        f"Imported bodies for {imported_quizzes} quiz(es) and "
        f"{imported_decks} flashcard deck(s)."
    )
    if failed:
        print("Content-body migration failed for:")
        for path in failed:
            print(f"- {path}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
