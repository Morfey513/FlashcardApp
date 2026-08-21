"""Import per-content edit and moderation history into PostgreSQL."""

import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config import CONTENT_EDIT_HISTORY_FILENAME, FLASHCARD_DIR, QUIZ_DIR
from src.storage.postgres_content_history_repository import PostgresContentHistoryRepository


def _read(path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []


def main() -> int:
    repository = PostgresContentHistoryRepository()
    counts = {"edit": 0, "moderation": 0}
    failed = []
    for kind, root, filename in (
        ("quiz", QUIZ_DIR, "quiz.json"),
        ("flashcard", FLASHCARD_DIR, "deck.json"),
    ):
        for content_file in root.glob(f"*/{filename}"):
            content_id = content_file.parent.name
            edit_file = content_file.parent / CONTENT_EDIT_HISTORY_FILENAME
            moderation_file = content_file.parent / "moderation_history.json"
            try:
                edits = _read(edit_file)
                moderation = _read(moderation_file)
                edit_ok = repository.import_edit_history(kind, content_id, edits)
                moderation_ok = repository.import_moderation_history(
                    kind, content_id, moderation
                )
            except (OSError, json.JSONDecodeError):
                edit_ok = moderation_ok = False
                edits = moderation = []
            if not edit_ok or not moderation_ok:
                failed.append(str(content_file.parent))
                continue
            counts["edit"] += len(edits)
            counts["moderation"] += len(moderation)
    print(
        f"Imported {counts['edit']} edit event(s) and "
        f"{counts['moderation']} moderation event(s)."
    )
    if failed:
        print("Content-history migration failed for:")
        for path in failed:
            print(f"- {path}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
