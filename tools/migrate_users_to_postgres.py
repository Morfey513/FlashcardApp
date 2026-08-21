"""Import the existing JSON accounts into the configured PostgreSQL database."""

import json
import sys
from pathlib import Path


# Direct execution (``python tools/migrate_users_to_postgres.py``) places the
# tools directory, rather than the project root, on sys.path. Add the root so
# the documented command can import the application's ``src`` package.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config import USERS_FILE
from src.storage.postgres_user_repository import PostgresUserRepository


def main() -> int:
    data = json.loads(USERS_FILE.read_text(encoding="utf-8"))
    repository = PostgresUserRepository()
    users = data.get("users", [])
    failed = [
        str(user.get("login", user.get("id", "unknown")))
        for user in users
        if not repository.import_json_user(user)
    ]
    if failed:
        print(f"User migration failed for: {', '.join(failed)}")
        return 1
    print(f"Imported {len(users)} user account(s) into PostgreSQL.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
