"""Import authenticated progress and quiz attempts into PostgreSQL."""

import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config import FLASHCARD_DIR, QUIZ_DIR
from src.storage.postgres_learning_repository import PostgresLearningRepository


def _read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    repository = PostgresLearningRepository()
    imported = {"flashcard_progress": 0, "quiz_progress": 0, "attempts": 0}
    skipped_guests = 0
    failed = []

    for kind, root in (("flashcard", FLASHCARD_DIR), ("quiz", QUIZ_DIR)):
        for path in root.glob("*/progress/*.json"):
            user_id = path.stem
            if user_id.casefold() == "guest":
                skipped_guests += 1
                continue
            try:
                data = _read(path)
                content_id = path.parents[1].name
                success = (
                    repository.import_flashcard_progress(content_id, user_id, data)
                    if kind == "flashcard"
                    else repository.import_quiz_progress(content_id, user_id, data)
                )
            except (OSError, json.JSONDecodeError):
                success = False
            if success:
                imported[f"{kind}_progress"] += 1
            else:
                failed.append(str(path))

    for path in QUIZ_DIR.glob("*/attempts/*.json"):
        try:
            data = _read(path)
        except (OSError, json.JSONDecodeError):
            failed.append(str(path))
            continue
        if str(data.get("user_id", "")).casefold() == "guest":
            skipped_guests += 1
            continue
        if repository.import_quiz_attempt(data):
            imported["attempts"] += 1
        else:
            failed.append(str(path))

    print(
        "Imported "
        f"{imported['flashcard_progress']} flashcard progress file(s), "
        f"{imported['quiz_progress']} quiz progress file(s), and "
        f"{imported['attempts']} quiz attempt(s)."
    )
    print(f"Skipped {skipped_guests} guest record file(s); guest state remains local.")
    if failed:
        print("Learning-state migration failed for:")
        for path in failed:
            print(f"- {path}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
