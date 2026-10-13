"""Bootstrap the disposable local Study Buddy server.

This tool deliberately accepts only the dedicated ``study_buddy_test``
PostgreSQL database.  It migrates it, imports the bundled demo quiz and deck,
starts a localhost API when necessary, and verifies both system endpoints.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import urlopen

from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TEST_DATABASE_NAME = "study_buddy_test"
ADMIN_DATABASE_NAME = "postgres"
DEFAULT_BASE_URL = "http://127.0.0.1:8000"
API_MARKER_PATH = ROOT / ".temp" / "bootstrap_server_api.json"
DEMO_CONTENT = (
    ("quiz", ROOT / "data" / "quizzes" / "da5430fa-b771-4262-9383-90e4e3abc3f0" / "quiz.json"),
    ("flashcard", ROOT / "data" / "flashcards" / "8f348fc7-0545-413c-96c6-52b0800b4ef0" / "deck.json"),
)


def validate_database_url(value: str) -> str:
    """Fail closed before a connection can touch a non-disposable database."""
    if not value or not value.strip():
        raise ValueError("STUDY_BUDDY_TEST_DATABASE_URL must be set")
    try:
        parsed = make_url(value.strip())
    except Exception as exc:
        raise ValueError("STUDY_BUDDY_TEST_DATABASE_URL is not a valid database URL") from exc
    if parsed.get_backend_name() != "postgresql" or parsed.database != TEST_DATABASE_NAME:
        raise ValueError(
            "STUDY_BUDDY_TEST_DATABASE_URL must target PostgreSQL database "
            "'study_buddy_test' exactly"
        )
    return value.strip()


def validate_admin_database_url(value: str) -> str:
    if not value or not value.strip():
        raise ValueError("STUDY_BUDDY_BOOTSTRAP_ADMIN_URL must be set")
    try:
        parsed = make_url(value.strip())
    except Exception as exc:
        raise ValueError("STUDY_BUDDY_BOOTSTRAP_ADMIN_URL is not a valid database URL") from exc
    if parsed.get_backend_name() != "postgresql" or parsed.database != ADMIN_DATABASE_NAME:
        raise ValueError("STUDY_BUDDY_BOOTSTRAP_ADMIN_URL must target PostgreSQL maintenance database 'postgres'")
    return value.strip()


def validate_same_postgresql_server(admin_url: str, database_url: str) -> None:
    admin = make_url(admin_url)
    target = make_url(database_url)
    if (admin.host, admin.port or 5432) != (target.host, target.port or 5432):
        raise ValueError("bootstrap administrator and target URLs must use the same PostgreSQL host and port")


def base_url_for_port(port: int) -> str:
    if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
        raise ValueError("bootstrap port must be an integer from 1 through 65535")
    return f"http://127.0.0.1:{port}"


def public_error(exc: BaseException) -> str:
    """Make failures actionable without allowing a URL password into output."""
    message = str(exc)
    message = re.sub(r"(postgres(?:ql)?(?:\+[\w]+)?://[^:\s/@]+:)[^@\s]+@", r"\1***@", message)
    message = re.sub(r"(?i)(password\s*[=:]\s*)[^\s,;]+", r"\1***", message)
    return message or exc.__class__.__name__


def verify_database_reachable(database_url: str) -> None:
    # A short connection timeout makes an unavailable local service fail
    # predictably instead of leaving bootstrap waiting on a TCP timeout.
    engine = create_engine(database_url, pool_pre_ping=True, connect_args={"connect_timeout": 3})
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("SELECT 1")
    except Exception as exc:
        raise RuntimeError(
            "PostgreSQL is unreachable. Start PostgreSQL and verify "
            "STUDY_BUDDY_TEST_DATABASE_URL targets study_buddy_test."
        ) from exc
    finally:
        engine.dispose()


def _quote_identifier(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
        raise ValueError("bootstrap application role name contains unsupported characters")
    return f'"{value}"'


def _password_verifier(connection, password: str, role: str) -> str:
    """Build a SCRAM verifier locally so cleartext never enters SQL or server logs."""
    raw = connection.connection.driver_connection
    pgconn = getattr(raw, "pgconn", None)
    if pgconn is None:
        raise RuntimeError("bootstrap role creation requires the psycopg PostgreSQL driver")
    verifier = pgconn.encrypt_password(
        password.encode("utf-8"), role.encode("utf-8"), b"scram-sha-256"
    )
    return verifier.decode("ascii")


def provision_disposable_database(admin_url: str, database_url: str) -> None:
    """Create the application role/database once, refusing ownership conflicts."""
    target = make_url(database_url)
    role = str(target.username or "")
    password = target.password
    if not role or password is None:
        raise ValueError("STUDY_BUDDY_TEST_DATABASE_URL must include an application role and password")
    quoted_role = _quote_identifier(role)
    engine = create_engine(admin_url, isolation_level="AUTOCOMMIT", pool_pre_ping=True, connect_args={"connect_timeout": 3})
    try:
        with engine.connect() as connection:
            existing_role = connection.exec_driver_sql(
                "SELECT rolname, rolcanlogin FROM pg_roles WHERE rolname = %s", (role,)
            ).first()
            if existing_role is None:
                # Only the salted SCRAM verifier crosses the SQL boundary.
                verifier = _password_verifier(connection, password, role)
                statement = connection.exec_driver_sql(
                    "SELECT format('CREATE ROLE %%I LOGIN PASSWORD %%L', %s::text, %s::text)",
                    (role, verifier),
                ).scalar_one()
                connection.exec_driver_sql(statement)
            elif not existing_role.rolcanlogin:
                raise RuntimeError("existing bootstrap application role cannot log in")
            owner = connection.exec_driver_sql(
                "SELECT r.rolname FROM pg_database d JOIN pg_roles r ON r.oid = d.datdba WHERE d.datname = %s",
                (TEST_DATABASE_NAME,),
            ).scalar_one_or_none()
            if owner is None:
                connection.exec_driver_sql(f"CREATE DATABASE {TEST_DATABASE_NAME} OWNER {quoted_role}")
            elif owner != role:
                raise RuntimeError("existing study_buddy_test database is owned by a different role")
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(
            "Could not provision study_buddy_test. Verify the bootstrap administrator has role and database creation privileges."
        ) from exc
    finally:
        engine.dispose()


def upgrade_schema(database_url: str) -> None:
    from alembic import command
    from alembic.config import Config

    previous = os.environ.get("STUDY_BUDDY_DATABASE_URL")
    os.environ["STUDY_BUDDY_DATABASE_URL"] = database_url
    try:
        command.upgrade(Config(str(ROOT / "alembic.ini")), "head")
    finally:
        if previous is None:
            os.environ.pop("STUDY_BUDDY_DATABASE_URL", None)
        else:
            os.environ["STUDY_BUDDY_DATABASE_URL"] = previous


def seed_bundled_demo_content(database_url: str) -> None:
    """Import only the two canonical bundled demos, refusing conflicting rows."""
    from sqlalchemy.orm import sessionmaker
    from src.storage.postgres_content_body_repository import PostgresContentBodyRepository
    from src.storage.postgres_content_metadata_repository import PostgresContentMetadataRepository
    from src.storage.postgres_models import FlashcardDeckMetadataModel, QuizMetadataModel

    engine = create_engine(database_url, pool_pre_ping=True)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    metadata = PostgresContentMetadataRepository(sessions)
    # The bundled deck contains project-relative legacy media paths.  This
    # repository mode copies their validated bytes into managed server media;
    # it never stores the original paths in PostgreSQL.
    bodies = PostgresContentBodyRepository(sessions, allow_legacy_paths=True)
    try:
        for kind, path in DEMO_CONTENT:
            source = json.loads(path.read_text(encoding="utf-8"))
            content_id = str(source["id"])
            relative_path = path.relative_to(ROOT).as_posix()
            model = QuizMetadataModel if kind == "quiz" else FlashcardDeckMetadataModel
            with sessions() as session:
                by_id = session.get(model, content_id)
                by_path = session.scalar(select(model).where(model.source_path == relative_path))
                expected_owner = str((source.get("moderation") or {}).get("owner_id") or "legacy")
                def is_matching_demo(row) -> bool:
                    return row is not None and (
                        row.id == content_id
                        and row.source_path == relative_path
                        and row.source_owner_id == expected_owner
                        and row.name == str(source["name"])
                    )
                existing = by_id or by_path
                if existing is not None and not is_matching_demo(existing):
                    raise RuntimeError(f"Bundled {kind} ID '{content_id}' belongs to existing non-demo content")
                if existing is not None:
                    stored_body = (
                        bodies._stored_quiz_canonical(session, content_id)
                        if kind == "quiz"
                        else bodies._stored_deck_canonical(session, content_id)
                    )
                    expected_body = (
                        bodies._source_quiz_canonical(source)
                        if kind == "quiz"
                        else bodies._source_deck_canonical(source)
                    )
                    if stored_body != expected_body:
                        raise RuntimeError(
                            f"Bundled {kind} '{content_id}' has divergent existing body content"
                        )
                    # A verified canonical row is deliberately a no-op.  This
                    # preserves its content revision and managed media exactly.
                    continue
            imported_metadata = (
                metadata.import_quiz(source, relative_path)
                if kind == "quiz"
                else metadata.import_flashcard_deck(source, relative_path)
            )
            imported_body = bodies.import_quiz(source) if kind == "quiz" else bodies.import_flashcard_deck(source)
            if not imported_metadata or not imported_body:
                raise RuntimeError(f"Could not seed bundled {kind} '{content_id}'")
    finally:
        engine.dispose()


def endpoint_status(base_url: str, endpoint: str) -> int | None:
    try:
        with urlopen(base_url.rstrip("/") + endpoint, timeout=2) as response:
            return response.status
    except (URLError, OSError):
        return None


def _api_identity(database_url: str) -> dict[str, str | int | None]:
    parsed = make_url(database_url)
    return {
        "host": parsed.host,
        "port": parsed.port,
        "database": parsed.database,
        "username": parsed.username,
    }


def _owned_api_is_running(database_url: str, base_url: str) -> bool:
    try:
        marker = json.loads(API_MARKER_PATH.read_text(encoding="utf-8"))
        pid = int(marker["pid"])
        if marker.get("base_url") != base_url or marker.get("database") != _api_identity(database_url):
            return False
        return _pid_is_running(pid)
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return False


def _pid_is_running(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            exit_code = ctypes.c_ulong()
            return bool(kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))) and exit_code.value == 259
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _write_api_marker(pid: int, database_url: str, base_url: str) -> None:
    API_MARKER_PATH.parent.mkdir(parents=True, exist_ok=True)
    API_MARKER_PATH.write_text(
        json.dumps({"pid": pid, "base_url": base_url, "database": _api_identity(database_url)}),
        encoding="utf-8",
    )


def start_and_verify_api(database_url: str, base_url: str, timeout_seconds: float) -> None:
    """Leave a local API process running once its health and readiness pass."""
    parsed = urlsplit(base_url)
    if parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or not parsed.port or parsed.path:
        raise ValueError("bootstrap API origin must be a localhost 127.0.0.1 port")
    healthy = endpoint_status(base_url, "/health") == 200
    if healthy and not _owned_api_is_running(database_url, base_url):
        raise RuntimeError("port 8000 is serving an API not started by this bootstrap; stop it and retry")
    process = None
    if not healthy:
        environment = os.environ.copy()
        environment["STUDY_BUDDY_DATABASE_URL"] = database_url
        environment["STUDY_BUDDY_STORAGE"] = "api"
        process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "src.api.main:app", "--host", "127.0.0.1", "--port", str(parsed.port)],
            cwd=ROOT,
            env=environment,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        )
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if endpoint_status(base_url, "/health") == 200 and endpoint_status(base_url, "/ready") == 200:
            if process is not None:
                _write_api_marker(process.pid, database_url, base_url)
            return
        time.sleep(0.2)
    raise RuntimeError("API did not become healthy and ready; check that port 8000 is available")


def bootstrap(database_url: str, admin_url: str, *, port: int = 8000, timeout_seconds: float = 15) -> None:
    database_url = validate_database_url(database_url)
    admin_url = validate_admin_database_url(admin_url)
    validate_same_postgresql_server(admin_url, database_url)
    verify_database_reachable(admin_url)
    provision_disposable_database(admin_url, database_url)
    verify_database_reachable(database_url)
    upgrade_schema(database_url)
    seed_bundled_demo_content(database_url)
    base_url = base_url_for_port(port)
    start_and_verify_api(database_url, base_url, timeout_seconds)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--timeout", type=float, default=15)
    args = parser.parse_args(argv)
    try:
        bootstrap(
            os.getenv("STUDY_BUDDY_TEST_DATABASE_URL", ""),
            os.getenv("STUDY_BUDDY_BOOTSTRAP_ADMIN_URL", ""),
            port=args.port,
            timeout_seconds=args.timeout,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"Bootstrap failed: {public_error(exc)}", file=sys.stderr)
        return 1
    except Exception:
        print("Bootstrap failed: an unexpected bootstrap error occurred; inspect local PostgreSQL service configuration.", file=sys.stderr)
        return 1
    print("Bootstrap complete: schema migrated, bundled demo content seeded, API health and readiness verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
