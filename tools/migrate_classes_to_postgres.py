"""Import embedded invitation/enrollment metadata into relational classes."""

import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config import FLASHCARD_DIR, QUIZ_DIR
from src.storage.postgres_class_repository import PostgresClassRepository


def main() -> int:
    repository = PostgresClassRepository()
    candidates = [
        ("quiz", path) for path in QUIZ_DIR.glob("*/quiz.json")
    ] + [
        ("flashcard", path) for path in FLASHCARD_DIR.glob("*/deck.json")
    ]
    imported = 0
    failed = []
    for kind, path in candidates:
        try:
            source = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            failed.append(str(path))
            continue
        metadata = source.get("moderation") or {}
        has_access_data = bool(metadata.get("invite") or metadata.get("enrollments"))
        if not has_access_data and metadata.get("visibility") != "class_only":
            continue
        if repository.import_content_access(source, kind):
            imported += 1
        else:
            failed.append(str(path))
    if failed:
        print("Class migration failed for:")
        for path in failed:
            print(f"- {path}")
        return 1
    print(f"Imported {imported} class roster(s) into PostgreSQL.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
