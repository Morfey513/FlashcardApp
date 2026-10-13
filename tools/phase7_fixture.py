"""Prepare and clean an isolated Phase 7 fixture in ``study_buddy_test``.

This is developer tooling.  It deliberately has no HTTP endpoint and refuses
every database except the exactly named disposable PostgreSQL test database.
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import sys
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy.engine import make_url


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TEST_DATABASE_NAME = "study_buddy_test"
MANIFEST_VERSION = 1
CLASS_ID_NAMESPACE = uuid.UUID("a7926ea6-5a87-41f5-9f92-c2bceaad14bc")
TINY_PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR"
    b"\x00\x00\x00\x01"
    b"\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00"
    b"\x1f\x15\xc4\x89"
    b"\x00\x00\x00\x0cIDAT"
    b"\x08\xd7c\xf8\x0f\x04\x00\x09\xfb\x03\xfd"
    b"\x02\xfe\xa7\xd3"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)


def validate_database_url(value: str) -> str:
    """Fail closed unless *value* names exactly PostgreSQL/study_buddy_test."""
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


def normalize_base_url(value: str) -> str:
    """Accept only an origin-like HTTP(S) URL, without credentials or query."""
    parsed = urlsplit(value.strip())
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("base URL must be an HTTP(S) URL without credentials, query, or fragment")
    path = parsed.path.rstrip("/")
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def new_fixture_id() -> str:
    return f"phase7-{int(time.time())}-{secrets.token_hex(6)}"


def build_fixture_manifest(
    concurrency: int,
    base_url: str,
    *,
    fixture_id: str | None = None,
    password: str | None = None,
) -> dict:
    """Build the credential-bearing manifest before its rows are inserted."""
    if concurrency < 1:
        raise ValueError("concurrency must be positive")
    identity = fixture_id or new_fixture_id()
    if not identity.startswith("phase7-") or not identity.replace("-", "").isalnum():
        raise ValueError("fixture ID must use the phase7- prefix and contain only letters, digits, and hyphens")
    student_ids = [f"{identity}-student-{index}" for index in range(max(2, concurrency))]
    quiz_ids = {
        "primary": f"{identity}-quiz",
        "different_students": f"{identity}-different-students-quiz",
        "terminal_submit": f"{identity}-terminal-submit-quiz",
        "restricted": "missing",
    }
    primary_class_id = str(uuid.uuid5(CLASS_ID_NAMESPACE, f"quiz:{quiz_ids['primary']}"))
    return {
        "manifest_version": MANIFEST_VERSION,
        "fixture_id": identity,
        "fixture_version": "class-backed-assessment-v2",
        "base_url": normalize_base_url(base_url),
        "concurrency": concurrency,
        "accounts": {
            "teacher": {"username": f"{identity}-teacher"},
            "students": [{"username": item} for item in student_ids],
            "password": password or secrets.token_urlsafe(24),
        },
        "content_ids": {
            "quizzes": quiz_ids,
            "class": primary_class_id,
            "media": None,
            "content_version": None,
        },
    }


def validate_manifest(manifest: dict, *, require_seeded: bool = True) -> dict:
    """Validate identity-derived fields so cleanup cannot target arbitrary rows."""
    if manifest.get("manifest_version") != MANIFEST_VERSION:
        raise ValueError("unsupported Phase 7 fixture manifest version")
    identity = manifest.get("fixture_id")
    concurrency = manifest.get("concurrency")
    if not isinstance(identity, str) or not identity.startswith("phase7-") or not identity.replace("-", "").isalnum():
        raise ValueError("invalid Phase 7 fixture ID")
    if not isinstance(concurrency, int) or concurrency < 1:
        raise ValueError("invalid fixture concurrency")
    expected = build_fixture_manifest(
        concurrency,
        manifest.get("base_url", ""),
        fixture_id=identity,
        password=manifest.get("accounts", {}).get("password", ""),
    )
    if manifest.get("accounts") != expected["accounts"]:
        raise ValueError("fixture account identifiers do not match the fixture ID")
    actual_content = manifest.get("content_ids", {})
    for key in ("quizzes", "class"):
        if actual_content.get(key) != expected["content_ids"][key]:
            raise ValueError(f"fixture {key} identifiers do not match the fixture ID")
    if require_seeded and (
        not isinstance(actual_content.get("media"), str)
        or not isinstance(actual_content.get("content_version"), int)
    ):
        raise ValueError("fixture manifest does not describe a completed seed")
    return manifest


def require_migrated_schema(engine) -> None:
    required = {
        "users", "user_sessions", "quizzes", "quiz_questions", "quiz_attempts",
        "quiz_attempt_questions", "quiz_attempt_answers", "classes", "class_members",
        "class_quizzes", "media",
    }
    with engine.connect() as connection:
        existing = set(connection.dialect.get_table_names(connection))
    missing = required - existing
    if missing:
        raise RuntimeError("The PostgreSQL test database is not migrated; missing: " + ", ".join(sorted(missing)))


def seed_fixture(session_factory, metadata, bodies, classes, manifest: dict) -> dict:
    """Insert the exact fixture shape used by the established local harness."""
    from src.logic.passwords import PasswordHasher
    from src.storage.postgres_models import ClassMemberModel, ClassModel, ClassQuizModel, UserModel

    validate_manifest(manifest, require_seeded=False)
    fixture_id = manifest["fixture_id"]
    password = manifest["accounts"]["password"]
    teacher_id = manifest["accounts"]["teacher"]["username"]
    student_ids = [item["username"] for item in manifest["accounts"]["students"]]
    quiz_ids = manifest["content_ids"]["quizzes"]
    seeded_quizzes = (
        (quiz_ids["primary"], "Phase 7 same-user"),
        (quiz_ids["different_students"], "Phase 7 different students"),
        (quiz_ids["terminal_submit"], "Phase 7 terminal submit"),
    )
    with session_factory.begin() as session:
        for user_id, role in [(teacher_id, "teacher"), *((item, "student") for item in student_ids)]:
            session.add(UserModel(
                id=user_id,
                username=user_id,
                email=f"{user_id}@stress.invalid",
                password_hash=PasswordHasher.hash(password),
                display_name=role,
                role=role,
                status="active",
            ))
    for quiz_id, name in seeded_quizzes:
        if not metadata.import_quiz({
            "id": quiz_id,
            "name": name,
            "moderation": {"owner_id": teacher_id, "status": "published", "visibility": "class_only"},
            "test_settings": {"attempt_limit": 1},
        }, f"stress://{fixture_id}/{quiz_id}"):
            raise RuntimeError(f"failed to import Phase 7 quiz metadata {quiz_id}")
    uploaded = bodies.register_uploaded_media(teacher_id, TINY_PNG_BYTES, "phase7.png")
    for quiz_id, _name in seeded_quizzes:
        if not bodies.import_quiz({
            "id": quiz_id,
            "questions": [{
                "id": f"{quiz_id}-q1",
                "question": "One?",
                "type": "short_answer",
                "answer": "one",
                "image_path": uploaded["media_id"],
            }],
        }):
            raise RuntimeError(f"failed to import Phase 7 quiz body {quiz_id}")
    class_id = classes.class_id_for("quiz", quiz_ids["primary"])
    if class_id != manifest["content_ids"]["class"]:
        raise RuntimeError("class identifier convention differs from the fixture manifest")
    with session_factory.begin() as session:
        session.add(ClassModel(id=class_id, owner_id=teacher_id, name="Phase 7", status="active"))
        session.flush()
        for quiz_id, _name in seeded_quizzes:
            session.add(ClassQuizModel(class_id=class_id, quiz_id=quiz_id))
        for student_id in student_ids:
            session.add(ClassMemberModel(class_id=class_id, user_id=student_id, status="active"))
    manifest["content_ids"]["media"] = uploaded["media_id"]
    manifest["content_ids"]["content_version"] = metadata.get_by_id("quiz", quiz_ids["primary"])["content_version"]
    return validate_manifest(manifest)


def cleanup_fixture_rows(session_factory, manifest: dict) -> None:
    """Delete only manifest-derived rows, child first. Safe to repeat."""
    from sqlalchemy import delete, select
    from src.storage.postgres_models import (
        AccountModerationHistoryModel, ClassFlashcardDeckModel, ClassInvitationModel,
        ClassMemberModel, ClassModel, ClassQuizModel, FlashcardProgressModel, MediaModel,
        QuestionMediaModel, QuizAttemptAnswerModel, QuizAttemptModel,
        QuizAttemptQuestionModel, QuizEditHistoryModel, QuizMetadataModel,
        QuizModerationHistoryModel, QuizQuestionModel, QuizQuestionProgressModel,
        UserModel, UserSessionModel, UserSettingsModel,
    )

    validate_manifest(manifest, require_seeded=False)
    user_ids = [
        manifest["accounts"]["teacher"]["username"],
        *(item["username"] for item in manifest["accounts"]["students"]),
    ]
    quiz_ids = [
        manifest["content_ids"]["quizzes"][key]
        for key in ("primary", "different_students", "terminal_submit")
    ]
    class_id = manifest["content_ids"]["class"]
    media_id = manifest["content_ids"]["media"]
    with session_factory.begin() as session:
        attempt_ids = select(QuizAttemptModel.id).where(
            QuizAttemptModel.user_id.in_(user_ids), QuizAttemptModel.quiz_id.in_(quiz_ids)
        )
        session.execute(delete(UserSessionModel).where(UserSessionModel.user_id.in_(user_ids)))
        session.execute(delete(QuizAttemptAnswerModel).where(QuizAttemptAnswerModel.attempt_id.in_(attempt_ids)))
        session.execute(delete(QuizAttemptQuestionModel).where(QuizAttemptQuestionModel.attempt_id.in_(attempt_ids)))
        session.execute(delete(QuizAttemptModel).where(QuizAttemptModel.user_id.in_(user_ids), QuizAttemptModel.quiz_id.in_(quiz_ids)))
        session.execute(delete(QuizQuestionProgressModel).where(QuizQuestionProgressModel.user_id.in_(user_ids)))
        session.execute(delete(FlashcardProgressModel).where(FlashcardProgressModel.user_id.in_(user_ids)))
        session.execute(delete(ClassInvitationModel).where(ClassInvitationModel.class_id == class_id))
        session.execute(delete(ClassMemberModel).where(ClassMemberModel.class_id == class_id))
        session.execute(delete(ClassQuizModel).where(ClassQuizModel.class_id == class_id))
        session.execute(delete(ClassFlashcardDeckModel).where(ClassFlashcardDeckModel.class_id == class_id))
        session.execute(delete(ClassModel).where(ClassModel.id == class_id))
        session.execute(delete(QuestionMediaModel).where(QuestionMediaModel.quiz_id.in_(quiz_ids)))
        session.execute(delete(QuizEditHistoryModel).where(QuizEditHistoryModel.quiz_id.in_(quiz_ids)))
        session.execute(delete(QuizModerationHistoryModel).where(QuizModerationHistoryModel.quiz_id.in_(quiz_ids)))
        if media_id:
            session.execute(delete(MediaModel).where(MediaModel.id == media_id, MediaModel.owner_id.in_(user_ids)))
        session.execute(delete(QuizQuestionModel).where(QuizQuestionModel.quiz_id.in_(quiz_ids)))
        session.execute(delete(QuizMetadataModel).where(QuizMetadataModel.id.in_(quiz_ids)))
        session.execute(delete(UserSettingsModel).where(UserSettingsModel.user_id.in_(user_ids)))
        session.execute(delete(AccountModerationHistoryModel).where(AccountModerationHistoryModel.target_user_id.in_(user_ids)))
        session.execute(delete(UserModel).where(UserModel.id.in_(user_ids)))


def default_manifest_path(fixture_id: str) -> Path:
    return ROOT / ".temp" / "phase7" / "fixtures" / f"{fixture_id}.json"


def load_manifest(path: Path) -> dict:
    return validate_manifest(json.loads(path.read_text(encoding="utf-8")))


def write_manifest(path: Path, manifest: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(validate_manifest(manifest), indent=2), encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass


def _database_components(database_url: str, media_root: Path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from src.storage.postgres_class_repository import PostgresClassRepository
    from src.storage.postgres_content_body_repository import PostgresContentBodyRepository
    from src.storage.postgres_content_metadata_repository import PostgresContentMetadataRepository

    engine = create_engine(database_url, pool_pre_ping=True)
    require_migrated_schema(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    return engine, sessions, PostgresContentMetadataRepository(sessions), PostgresContentBodyRepository(sessions, media_root=media_root), PostgresClassRepository(sessions)


def prepare_fixture(database_url: str, base_url: str, concurrency: int, manifest_path: Path | None = None) -> tuple[Path, dict]:
    database_url = validate_database_url(database_url)
    manifest = build_fixture_manifest(concurrency, base_url)
    path = manifest_path or default_manifest_path(manifest["fixture_id"])
    media_root = path.parent / f"{path.stem}-media"
    if path.exists() or media_root.exists():
        raise FileExistsError("fixture manifest or media root already exists")
    media_root.mkdir(parents=True)
    engine = None
    sessions = None
    try:
        engine, sessions, metadata, bodies, classes = _database_components(database_url, media_root)
        seed_fixture(sessions, metadata, bodies, classes, manifest)
        manifest["media_root"] = str(media_root.resolve())
        write_manifest(path, manifest)
        return path, manifest
    except Exception:
        if sessions is not None:
            cleanup_fixture_rows(sessions, manifest)
        shutil.rmtree(media_root, ignore_errors=True)
        raise
    finally:
        if engine is not None:
            engine.dispose()


def cleanup_fixture(database_url: str, manifest_path: Path) -> None:
    database_url = validate_database_url(database_url)
    manifest = load_manifest(manifest_path)
    media_root = Path(manifest.get("media_root", ""))
    expected_media_root = manifest_path.parent / f"{manifest_path.stem}-media"
    if media_root.resolve() != expected_media_root.resolve():
        raise ValueError("manifest media root is not the fixture-dedicated directory")
    engine, sessions, _metadata, _bodies, _classes = _database_components(database_url, media_root)
    try:
        cleanup_fixture_rows(sessions, manifest)
        shutil.rmtree(media_root, ignore_errors=True)
    finally:
        engine.dispose()


def main() -> int:
    from src.runtime_config import load_runtime_environment

    load_runtime_environment()
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare", help="seed one isolated Phase 7 fixture")
    prepare.add_argument("--base-url", required=True)
    prepare.add_argument("--concurrency", required=True, type=int)
    prepare.add_argument("--manifest", type=Path)
    cleanup = commands.add_parser("cleanup", help="remove only the fixture named by a manifest")
    cleanup.add_argument("--manifest", required=True, type=Path)
    args = parser.parse_args()
    database_url = os.getenv("STUDY_BUDDY_TEST_DATABASE_URL", "")
    try:
        if args.command == "prepare":
            path, manifest = prepare_fixture(database_url, args.base_url, args.concurrency, args.manifest)
            print(json.dumps({
                "fixture_id": manifest["fixture_id"],
                "manifest": str(path.resolve()),
                "media_root": manifest["media_root"],
                "base_url": manifest["base_url"],
            }, indent=2))
        else:
            cleanup_fixture(database_url, args.manifest)
            print(json.dumps({"cleaned": True, "manifest": str(args.manifest.resolve())}, indent=2))
    except (OSError, RuntimeError, ValueError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
