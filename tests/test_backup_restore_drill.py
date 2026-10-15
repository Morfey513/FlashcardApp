"""Coverage for the disposable PostgreSQL backup/restore drill."""

import os
import secrets
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from tools import backup_restore_drill as drill


def _urls():
    return (
        "postgresql://study_buddy_test:template-secret@127.0.0.1:5432/study_buddy_test",
        "postgresql://admin:admin-secret@127.0.0.1:5432/postgres",
    )


def test_documented_script_entry_point_runs_without_import_error():
    result = subprocess.run(
        [sys.executable, str(drill.ROOT / "tools" / "backup_restore_drill.py"), "--help"],
        cwd=drill.ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "disposable PostgreSQL backup/restore verification drill" in result.stdout


def test_missing_postgres_client_tool_has_actionable_message(monkeypatch):
    monkeypatch.setattr(drill.shutil, "which", lambda _name: None)
    with pytest.raises(RuntimeError, match="pg_dump was not found on PATH"):
        drill._require_executable("pg_dump")


def test_pg_tools_use_pgpw_only_and_documented_flags(monkeypatch):
    url, _admin = _urls()
    captured = []

    class Result:
        returncode = 0

    def fake_run(command, **kwargs):
        captured.append((command, kwargs))
        return Result()

    monkeypatch.setattr(drill.shutil, "which", lambda name: name)
    monkeypatch.setattr(drill.subprocess, "run", fake_run)
    with tempfile.TemporaryDirectory() as temporary_root:
        dump = Path(temporary_root) / "round-trip.dump"
        drill.dump_database(url, dump)
        drill.restore_database(url, dump)

    for command, kwargs in captured:
        assert "template-secret" not in command
        assert "--password" not in command
        assert kwargs["env"]["PGPASSWORD"] == "template-secret"
    assert {"--format=custom", "--no-owner", "--no-privileges"} <= set(captured[0][0])
    assert {"--clean", "--if-exists", "--no-owner", "--no-privileges", "--single-transaction", "--exit-on-error"} <= set(captured[1][0])


@pytest.mark.parametrize("stderr, stdout, expected", [
    ("pg_restore: unsupported version (1.16) in file header; postgresql://study_buddy_test:template-secret@127.0.0.1/study_buddy_test", "", "unsupported version"),
    ("", "pg_dump: permission denied; password=template-secret", "permission denied"),
])
def test_pg_tool_failure_preserves_diagnostic_without_password(monkeypatch, stderr, stdout, expected):
    class Result:
        returncode = 1

    result = Result()
    result.stderr = stderr
    result.stdout = stdout
    monkeypatch.setattr(drill.subprocess, "run", lambda *_args, **_kwargs: result)

    with pytest.raises(RuntimeError) as error:
        drill._run_postgres_tool(["pg_restore"], _urls()[0], "pg_restore")

    assert expected in str(error.value)
    assert "template-secret" not in str(error.value)


def test_drill_cleanup_runs_after_forced_mid_run_failure(monkeypatch):
    url, admin_url = _urls()
    names = iter(("study_buddy_backup_source", "study_buddy_backup_target"))
    provisioned, cleaned = [], []
    with tempfile.TemporaryDirectory() as temporary_root:
        dump = Path(temporary_root) / "outside-repository.dump"
        dump.write_bytes(b"archive")
        monkeypatch.setattr(drill, "_scratch_name", lambda: next(names))
        monkeypatch.setattr(drill, "_temporary_dump_path", lambda: dump)
        monkeypatch.setattr(drill, "_require_executable", lambda _name: _name)
        monkeypatch.setattr(drill, "_assert_scratch_names_available", lambda *_args: None)
        monkeypatch.setattr(drill.bootstrap_server, "verify_database_reachable", lambda _url: None)
        monkeypatch.setattr(drill.bootstrap_server, "_provision_disposable_database", lambda _admin, target, name: provisioned.append((target, name)))
        monkeypatch.setattr(drill.bootstrap_server, "upgrade_schema", lambda _url: None)
        monkeypatch.setattr(drill.bootstrap_server, "seed_bundled_demo_content", lambda _url: None)
        monkeypatch.setattr(drill, "_register_user", lambda *_args: {"id": "user-1"})
        monkeypatch.setattr(drill, "_content_versions", lambda _url: {("quiz", "id"): 1})
        monkeypatch.setattr(drill, "_body_counts", lambda _url: drill.EXPECTED_BODY_COUNTS)
        monkeypatch.setattr(drill, "_body_snapshots", lambda _url: {"quiz": {"questions": [1]}})
        monkeypatch.setattr(drill, "dump_database", lambda source, path: path.write_bytes(b"archive"))
        monkeypatch.setattr(drill, "restore_database", lambda *_args: None)
        monkeypatch.setattr(drill, "_drop_scratch_database", lambda _admin, name, **_kwargs: cleaned.append(name))

        with pytest.raises(RuntimeError, match="forced drill failure"):
            drill.run_drill(url, admin_url, fail_after_restore=True)

        assert [name for _target, name in provisioned] == ["study_buddy_backup_source", "study_buddy_backup_target"]
        assert cleaned == ["study_buddy_backup_target", "study_buddy_backup_source"]
        assert not dump.exists()


def test_drill_does_not_pass_template_database_to_dump_or_restore(monkeypatch):
    url, admin_url = _urls()
    names = iter(("study_buddy_backup_source", "study_buddy_backup_target"))
    dumped, restored = [], []
    with tempfile.TemporaryDirectory() as temporary_root:
        dump = Path(temporary_root) / "outside-repository.dump"
        monkeypatch.setattr(drill, "_scratch_name", lambda: next(names))
        monkeypatch.setattr(drill, "_temporary_dump_path", lambda: dump)
        monkeypatch.setattr(drill, "_require_executable", lambda _name: _name)
        monkeypatch.setattr(drill, "_assert_scratch_names_available", lambda *_args: None)
        monkeypatch.setattr(drill.bootstrap_server, "verify_database_reachable", lambda _url: None)
        monkeypatch.setattr(drill.bootstrap_server, "_provision_disposable_database", lambda *_args: None)
        monkeypatch.setattr(drill.bootstrap_server, "upgrade_schema", lambda _url: None)
        monkeypatch.setattr(drill.bootstrap_server, "seed_bundled_demo_content", lambda _url: None)
        monkeypatch.setattr(drill, "_register_user", lambda *_args: {"id": "user-1"})
        monkeypatch.setattr(drill, "_content_versions", lambda _url: {("quiz", "id"): 1})
        monkeypatch.setattr(drill, "_body_counts", lambda _url: drill.EXPECTED_BODY_COUNTS)
        monkeypatch.setattr(drill, "_body_snapshots", lambda _url: {"quiz": {"questions": [1]}})
        monkeypatch.setattr(drill, "_verify_user", lambda *_args: None)
        monkeypatch.setattr(drill, "_start_restored_api", lambda *_args: (None, "http://127.0.0.1:1"))
        monkeypatch.setattr(drill, "_verify_api_content", lambda *_args: None)
        monkeypatch.setattr(drill, "_drop_scratch_database", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(drill, "dump_database", lambda source, path: dumped.append(source))
        monkeypatch.setattr(drill, "restore_database", lambda target, path: restored.append(target))

        drill.run_drill(url, admin_url)

    assert "study_buddy_test" not in dumped[0]
    assert "study_buddy_test" not in restored[0]
    assert "study_buddy_backup_source" in dumped[0]
    assert "study_buddy_backup_target" in restored[0]


def test_preflight_empty_role_cleanup_runs_after_provision_failure(monkeypatch):
    url, admin_url = _urls()
    names = iter(("study_buddy_backup_source", "study_buddy_backup_target"))
    cleaned = []
    monkeypatch.setattr(drill, "_scratch_name", lambda: next(names))
    monkeypatch.setattr(drill, "_require_executable", lambda _name: _name)
    monkeypatch.setattr(drill.bootstrap_server, "verify_database_reachable", lambda _url: None)
    monkeypatch.setattr(drill, "_assert_scratch_names_available", lambda *_args: None)
    monkeypatch.setattr(
        drill.bootstrap_server,
        "_provision_disposable_database",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("CREATE DATABASE failed after role creation")),
    )
    monkeypatch.setattr(
        drill,
        "_drop_scratch_database",
        lambda _admin, name, **kwargs: cleaned.append((name, kwargs["remove_preflight_empty_role"])),
    )

    with pytest.raises(RuntimeError, match="CREATE DATABASE failed"):
        drill.run_drill(url, admin_url)

    assert cleaned == [
        ("study_buddy_backup_target", True),
        ("study_buddy_backup_source", True),
    ]


@pytest.mark.skipif(
    not os.getenv("STUDY_BUDDY_TEST_DATABASE_URL") or not os.getenv("STUDY_BUDDY_BOOTSTRAP_ADMIN_URL"),
    reason="disposable PostgreSQL credentials are not configured",
)
@pytest.mark.skipif(
    not drill.shutil.which("pg_dump") or not drill.shutil.which("pg_restore"),
    reason="pg_dump and pg_restore must be available on PATH for the live backup/restore drill",
)
def test_live_backup_restore_drill_twice():
    """Run two isolated real dumps/restores; each run cleans its own artifacts."""
    url, admin_url = _urls()
    # Read configured values only here, after collection has established the opt-in gate.
    url = os.environ["STUDY_BUDDY_TEST_DATABASE_URL"]
    admin_url = os.environ["STUDY_BUDDY_BOOTSTRAP_ADMIN_URL"]
    drill.run_drill(url, admin_url)
    drill.run_drill(url, admin_url)


@pytest.mark.skipif(
    not os.getenv("STUDY_BUDDY_TEST_DATABASE_URL") or not os.getenv("STUDY_BUDDY_BOOTSTRAP_ADMIN_URL"),
    reason="disposable PostgreSQL credentials are not configured",
)
@pytest.mark.skipif(
    not drill.shutil.which("pg_dump") or not drill.shutil.which("pg_restore"),
    reason="pg_dump and pg_restore must be available on PATH for the live backup/restore drill",
)
def test_live_forced_failure_removes_both_scratch_databases(monkeypatch):
    url = os.environ["STUDY_BUDDY_TEST_DATABASE_URL"]
    admin_url = os.environ["STUDY_BUDDY_BOOTSTRAP_ADMIN_URL"]
    names = iter(("study_buddy_backup_" + secrets.token_hex(6), "study_buddy_backup_" + secrets.token_hex(6)))
    allocated = []

    def next_name():
        name = next(names)
        allocated.append(name)
        return name

    monkeypatch.setattr(drill, "_scratch_name", next_name)
    with pytest.raises(RuntimeError, match="forced drill failure"):
        drill.run_drill(url, admin_url, fail_after_restore=True)

    engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as connection:
            for name in allocated:
                assert connection.execute(text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": name}).scalar_one_or_none() is None
                assert connection.execute(text("SELECT 1 FROM pg_roles WHERE rolname = :name"), {"name": name}).scalar_one_or_none() is None
    finally:
        engine.dispose()
