"""Run a disposable PostgreSQL backup/restore verification drill.

The drill creates two unique ``study_buddy_backup_*`` databases, migrates and
seeds the source, exercises the documented pg_dump/pg_restore flags, and
removes both databases, roles, and the temporary archive before returning.
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import URL, make_url

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import bootstrap_server


DEMO_IDS = (
    ("quiz", "da5430fa-b771-4262-9383-90e4e3abc3f0"),
    ("flashcard", "8f348fc7-0545-413c-96c6-52b0800b4ef0"),
)
EXPECTED_BODY_COUNTS = {"quiz_questions": 6, "flashcards": 2}


def _require_executable(name: str) -> str:
    executable = shutil.which(name)
    if executable is None:
        raise RuntimeError(f"{name} was not found on PATH. Install PostgreSQL client tools and retry.")
    return executable


def _validate_template_url(value: str) -> URL:
    # The configured URL is a credential template only.  The drill never uses
    # its study_buddy_test database as a source or target.
    bootstrap_server.validate_database_url(value)
    parsed = make_url(value)
    if not parsed.username or parsed.password is None:
        raise ValueError("STUDY_BUDDY_TEST_DATABASE_URL must include an application role and password")
    return parsed


def _scratch_url(template: URL, name: str) -> str:
    return template.set(username=name, password=secrets.token_urlsafe(24), database=name).render_as_string(hide_password=False)


def _scratch_name() -> str:
    return "study_buddy_backup_" + secrets.token_hex(6)


def _temporary_dump_path() -> Path:
    temporary_root = Path(tempfile.gettempdir()).resolve()
    if temporary_root == ROOT or ROOT in temporary_root.parents:
        raise RuntimeError("OS temporary directory must be outside the repository before running the backup/restore drill")
    with tempfile.NamedTemporaryFile(prefix="study_buddy_backup_", suffix=".dump", dir=temporary_root, delete=False) as temporary:
        return Path(temporary.name)


def _subprocess_environment(database_url: str) -> dict[str, str]:
    parsed = make_url(database_url)
    password = parsed.password
    if password is None:
        raise ValueError("scratch database URL is missing a password")
    environment = os.environ.copy()
    environment["PGPASSWORD"] = password
    return environment


def _pg_connection_arguments(database_url: str) -> list[str]:
    parsed = make_url(database_url)
    if not parsed.host or not parsed.username or not parsed.database:
        raise ValueError("scratch database URL is incomplete")
    return ["-h", parsed.host, "-p", str(parsed.port or 5432), "-U", parsed.username, "-d", parsed.database]


def dump_database(database_url: str, dump_path: Path) -> None:
    command = [_require_executable("pg_dump"), *_pg_connection_arguments(database_url), "--format=custom", "--no-owner", "--no-privileges", "--file", str(dump_path)]
    _run_postgres_tool(command, database_url, "pg_dump")


def restore_database(database_url: str, dump_path: Path) -> None:
    command = [_require_executable("pg_restore"), *_pg_connection_arguments(database_url), "--clean", "--if-exists", "--no-owner", "--no-privileges", "--single-transaction", "--exit-on-error", str(dump_path)]
    _run_postgres_tool(command, database_url, "pg_restore")


def _run_postgres_tool(command: list[str], database_url: str, label: str) -> None:
    try:
        result = subprocess.run(command, env=_subprocess_environment(database_url), capture_output=True, text=True, check=False)
    except OSError as exc:
        raise RuntimeError(f"{label} could not be started; verify PostgreSQL client tools are installed.") from exc
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip() or "PostgreSQL client tool provided no diagnostic output"
        raise RuntimeError(f"{label} failed: {bootstrap_server.public_error(RuntimeError(detail))}")


def _assert_scratch_names_available(admin_url: str, names: tuple[str, str]) -> None:
    """Prove generated names were unused before granting orphan-role cleanup."""
    engine = create_engine(admin_url, pool_pre_ping=True, connect_args={"connect_timeout": 3})
    try:
        with engine.connect() as connection:
            for name in names:
                database_exists = connection.execute(text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": name}).scalar_one_or_none()
                role_exists = connection.execute(text("SELECT 1 FROM pg_roles WHERE rolname = :name"), {"name": name}).scalar_one_or_none()
                if database_exists is not None or role_exists is not None:
                    raise RuntimeError("generated backup drill scratch name already exists; retry the drill")
    finally:
        engine.dispose()


def _drop_scratch_database(admin_url: str, name: str, *, remove_preflight_empty_role: bool = False) -> None:
    if not name.startswith("study_buddy_backup_"):
        raise ValueError("refusing to remove a database outside the backup drill scratch prefix")
    quoted = bootstrap_server._quote_identifier(name)
    engine = create_engine(admin_url, isolation_level="AUTOCOMMIT", pool_pre_ping=True, connect_args={"connect_timeout": 3})
    try:
        with engine.connect() as connection:
            owner = connection.execute(text(
                "SELECT r.rolname FROM pg_database d JOIN pg_roles r ON r.oid = d.datdba WHERE d.datname = :name"
            ), {"name": name}).scalar_one_or_none()
            if owner is not None and owner != name:
                raise RuntimeError("refusing to remove a scratch database owned by a different role")
            if owner == name:
                connection.execute(text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = :name AND pid <> pg_backend_pid()"), {"name": name})
                connection.exec_driver_sql(f"DROP DATABASE {quoted}")
                # The ownership check above is the authorization to remove the
                # matching role; never remove a standalone same-named role.
                connection.exec_driver_sql(f"DROP ROLE {quoted}")
            elif remove_preflight_empty_role:
                # `run_drill` checks the name was absent before provisioning.
                # This handles a role created before CREATE DATABASE failed.
                role_exists = connection.execute(text("SELECT 1 FROM pg_roles WHERE rolname = :name"), {"name": name}).scalar_one_or_none()
                if role_exists is not None:
                    connection.exec_driver_sql(f"DROP ROLE {quoted}")
    finally:
        engine.dispose()


def _content_versions(database_url: str) -> dict[tuple[str, str], int]:
    from src.storage.postgres_models import FlashcardDeckMetadataModel, QuizMetadataModel
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            return {
                ("quiz", DEMO_IDS[0][1]): connection.scalar(select(QuizMetadataModel.content_version).where(QuizMetadataModel.id == DEMO_IDS[0][1])),
                ("flashcard", DEMO_IDS[1][1]): connection.scalar(select(FlashcardDeckMetadataModel.content_version).where(FlashcardDeckMetadataModel.id == DEMO_IDS[1][1])),
            }
    finally:
        engine.dispose()


def _body_counts(database_url: str) -> dict[str, int]:
    from src.storage.postgres_models import FlashcardModel, QuizQuestionModel
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            return {
                "quiz_questions": connection.scalar(select(func.count()).select_from(QuizQuestionModel).where(QuizQuestionModel.quiz_id == DEMO_IDS[0][1])),
                "flashcards": connection.scalar(select(func.count()).select_from(FlashcardModel).where(FlashcardModel.deck_id == DEMO_IDS[1][1])),
            }
    finally:
        engine.dispose()


def _body_snapshots(database_url: str) -> dict[str, dict]:
    """Read complete canonical demo bodies for source/target comparison."""
    from src.storage.database import create_session_factory
    from src.storage.postgres_content_body_repository import PostgresContentBodyRepository
    repository = PostgresContentBodyRepository(create_session_factory(database_url))
    quiz = repository.get_quiz(DEMO_IDS[0][1], include_answers=True)
    deck = repository.get_flashcard_deck(DEMO_IDS[1][1])
    if quiz is None or deck is None:
        raise RuntimeError("bundled demo body is missing")
    return {"quiz": quiz, "flashcard": deck}


def _register_user(database_url: str, login: str, password: str) -> dict:
    from src.storage.database import create_session_factory
    from src.storage.postgres_user_repository import PostgresUserRepository
    repository = PostgresUserRepository(create_session_factory(database_url))
    success, message, user = repository.register("Backup Drill User", login, password)
    if not success or user is None:
        raise RuntimeError(f"could not create drill user: {message}")
    return user


def _verify_user(database_url: str, user_id: str, login: str, password: str) -> None:
    from src.storage.database import create_session_factory
    from src.storage.postgres_user_repository import PostgresUserRepository
    repository = PostgresUserRepository(create_session_factory(database_url))
    user = repository.get_user_by_id(user_id)
    if user is None or user.get("login") != login or repository.authenticate(login, password) is None:
        raise RuntimeError("restored drill user could not be looked up and authenticated")


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _endpoint_status(base_url: str, endpoint: str) -> int | None:
    try:
        with urlopen(base_url + endpoint, timeout=2) as response:
            return response.status
    except (URLError, OSError):
        return None


def _start_restored_api(database_url: str, timeout_seconds: float) -> tuple[subprocess.Popen, str]:
    port = _free_port()
    environment = os.environ.copy()
    environment["STUDY_BUDDY_DATABASE_URL"] = database_url
    environment["STUDY_BUDDY_STORAGE"] = "api"
    process = subprocess.Popen([sys.executable, "-m", "uvicorn", "src.api.main:app", "--host", "127.0.0.1", "--port", str(port)], cwd=ROOT, env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base_url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if _endpoint_status(base_url, "/health") == 200 and _endpoint_status(base_url, "/ready") == 200:
            return process, base_url
        if process.poll() is not None:
            break
        time.sleep(0.2)
    _stop_process(process)
    raise RuntimeError("restored API did not become healthy and ready")


def _stop_process(process: subprocess.Popen | None) -> None:
    if process is not None and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def _api_json(url: str, *, method: str = "GET", payload: dict | None = None, token: str | None = None) -> object:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"} if data is not None else {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(request, timeout=3) as response:
            if response.status != 200:
                raise RuntimeError("restored API did not return success")
            return json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, OSError, ValueError) as exc:
        raise RuntimeError("restored API authentication or content verification failed") from exc


def _verify_api_content(base_url: str, login: str, password: str) -> None:
    login_result = _api_json(base_url + "/api/v1/auth/login", method="POST", payload={"login": login, "password": password})
    if not isinstance(login_result, dict) or not isinstance(login_result.get("access_token"), str):
        raise RuntimeError("restored API did not authenticate the drill user")
    token = login_result["access_token"]
    for kind, content_id in DEMO_IDS:
        item = _api_json(base_url + f"/api/v1/content/metadata/{kind}/{content_id}", token=token)
        if not isinstance(item, dict) or item.get("id") != content_id:
            raise RuntimeError("restored API did not expose bundled demo content")
        body = _api_json(base_url + f"/api/v1/content/bodies/{kind}/{content_id}", token=token)
        items_key, expected_count = ("questions", 6) if kind == "quiz" else ("cards", 2)
        if not isinstance(body, dict) or body.get("id") != content_id or not isinstance(body.get(items_key), list) or len(body[items_key]) != expected_count:
            raise RuntimeError("restored API did not expose bundled demo question or flashcard bodies")


def run_drill(test_database_url: str, admin_url: str, *, timeout_seconds: float = 20, fail_after_dump: bool = False, fail_after_restore: bool = False) -> None:
    """Run the complete drill and always clean every created disposable artifact."""
    template = _validate_template_url(test_database_url)
    admin_url = bootstrap_server.validate_admin_database_url(admin_url)
    bootstrap_server.validate_same_postgresql_server(admin_url, test_database_url)
    _require_executable("pg_dump")
    _require_executable("pg_restore")
    bootstrap_server.verify_database_reachable(admin_url)
    source_name, target_name = _scratch_name(), _scratch_name()
    while target_name == source_name:
        target_name = _scratch_name()
    source_url, target_url = _scratch_url(template, source_name), _scratch_url(template, target_name)
    dump_path: Path | None = None
    api_process: subprocess.Popen | None = None
    cleanup_errors: list[BaseException] = []
    names_preflight_verified = False
    user_password = secrets.token_urlsafe(24)
    login = "backup-drill-" + secrets.token_hex(6)
    try:
        _assert_scratch_names_available(admin_url, (source_name, target_name))
        names_preflight_verified = True
        bootstrap_server._provision_disposable_database(admin_url, source_url, source_name)
        bootstrap_server.upgrade_schema(source_url)
        bootstrap_server.seed_bundled_demo_content(source_url)
        user = _register_user(source_url, login, user_password)
        source_versions = _content_versions(source_url)
        source_body_counts = _body_counts(source_url)
        if source_body_counts != EXPECTED_BODY_COUNTS:
            raise RuntimeError("source bundled demo bodies do not have the expected question and card counts")
        source_body_snapshots = _body_snapshots(source_url)
        dump_path = _temporary_dump_path()
        dump_database(source_url, dump_path)
        if fail_after_dump:
            raise RuntimeError("forced drill failure after dump")
        bootstrap_server._provision_disposable_database(admin_url, target_url, target_name)
        restore_database(target_url, dump_path)
        if fail_after_restore:
            raise RuntimeError("forced drill failure after restore")
        if _content_versions(target_url) != source_versions or any(value is None for value in source_versions.values()):
            raise RuntimeError("restored bundled demo content IDs or versions differ from source")
        if _body_counts(target_url) != source_body_counts:
            raise RuntimeError("restored bundled demo question or flashcard bodies differ from source")
        if _body_snapshots(target_url) != source_body_snapshots:
            raise RuntimeError("restored bundled demo body content differs from source")
        _verify_user(target_url, user["id"], login, user_password)
        api_process, base_url = _start_restored_api(target_url, timeout_seconds)
        _verify_api_content(base_url, login, user_password)
    finally:
        _stop_process(api_process)
        if dump_path is not None:
            try:
                dump_path.unlink(missing_ok=True)
            except OSError as exc:
                cleanup_errors.append(exc)
        # Source and target are always unique names generated in this function.
        if names_preflight_verified:
            for name in (target_name, source_name):
                try:
                    _drop_scratch_database(admin_url, name, remove_preflight_empty_role=True)
                except Exception as exc:
                    cleanup_errors.append(exc)
        if cleanup_errors and sys.exc_info()[0] is None:
            raise RuntimeError("backup/restore drill cleanup did not complete; inspect disposable PostgreSQL permissions") from cleanup_errors[0]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=float, default=20)
    args = parser.parse_args(argv)
    try:
        run_drill(os.getenv("STUDY_BUDDY_TEST_DATABASE_URL", ""), os.getenv("STUDY_BUDDY_BOOTSTRAP_ADMIN_URL", ""), timeout_seconds=args.timeout)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"Backup/restore drill failed: {bootstrap_server.public_error(exc)}", file=sys.stderr)
        return 1
    except Exception:
        print("Backup/restore drill failed: an unexpected disposable drill error occurred.", file=sys.stderr)
        return 1
    print("Backup/restore drill complete: disposable dump, restore, content, user, health, and readiness verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
