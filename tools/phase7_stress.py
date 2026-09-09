"""Bounded, reproducible Phase 7 stress harness.

This is deliberately a diagnostic tool, not a production load-test framework.
Live runs require ``STUDY_BUDDY_TEST_DATABASE_URL`` to target exactly the
disposable PostgreSQL database ``study_buddy_test``.  ``--dry-run`` validates
the selected workload and emits its plan without requiring PostgreSQL.

Examples::

    .venv\\Scripts\\python tools\\phase7_stress.py --dry-run --profile all
    .venv\\Scripts\\python tools\\phase7_stress.py --profile multi-account --shape ramp --concurrency 16

The live runner is intentionally in-process (FastAPI TestClient per worker):
it exercises routes, authorization and PostgreSQL concurrency, but excludes
network/TLS and Uvicorn worker behaviour.  Run it only against a dedicated,
migrated test database.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import statistics
import sys
import threading
import time
import tempfile
import socket
import hashlib
import subprocess
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Iterable
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from sqlalchemy.engine import make_url


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TEST_DATABASE_NAME = "study_buddy_test"
SHAPES = {"burst", "ramp", "soak"}
REQUIRED_TABLES = {"users", "user_sessions", "quizzes", "quiz_questions", "quiz_attempts", "quiz_attempt_questions", "quiz_attempt_answers", "classes", "class_members", "class_quizzes", "media"}
DEFERRED_SLICES = ("hot-row metadata/body/shared-media writes (published-content write policy)", "deterministic database failure injection; no automatic write retries")
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


@dataclass(frozen=True)
class OperationDefinition:
    name: str
    method: str
    path: str
    expected_statuses: tuple[int, ...] = (200,)
    notes: str = ""


@dataclass(frozen=True)
class ProfileDefinition:
    name: str
    purpose: str
    operations: tuple[OperationDefinition, ...]
    invariants: tuple[str, ...]


PROFILES: dict[str, ProfileDefinition] = {
    "multi-account": ProfileDefinition(
        "multi-account", "Independent account authentication and available-content reads.",
        (OperationDefinition("login", "POST", "/api/v1/auth/login"),
         OperationDefinition("available_metadata", "GET", "/api/v1/content/metadata"),
         OperationDefinition("preview", "GET", "/api/v1/content/bodies/quiz/{quiz_id}"),
         OperationDefinition("practice_download", "GET", "/api/v1/content/practice-packages/quiz/{quiz_id}"),
         OperationDefinition("media_manifest", "GET", "/api/v1/content/media-manifests/quiz/{quiz_id}"),
         OperationDefinition("restricted_denied", "GET", "/api/v1/content/bodies/quiz/{restricted_quiz_id}", (404,))),
        ("No account observes restricted content belonging to another actor.",),
    ),
    "same-account-sessions": ProfileDefinition(
        "same-account-sessions", "Two devices for one account, including logout isolation.",
        (OperationDefinition("login_a", "POST", "/api/v1/auth/login"),
         OperationDefinition("login_b", "POST", "/api/v1/auth/login"),
         OperationDefinition("session_a_logout", "POST", "/api/v1/auth/logout", (204,)),
         OperationDefinition("session_a_rejected", "GET", "/api/v1/users/me", (401,)),
         OperationDefinition("session_b_stays_valid", "GET", "/api/v1/users/me"),
         OperationDefinition("session_b_reads", "GET", "/api/v1/content/metadata")),
        ("Revoking token A never invalidates independently issued token B.",),
    ),
    "assessment-cohort": ProfileDefinition(
        "assessment-cohort", "Concurrent assessment start/checkpoint/submit and attempt-limit checks.",
        (OperationDefinition("assessment_start", "POST", "/api/v1/quizzes/{class_quiz_id}/assessments", (200, 409)),
         OperationDefinition("assessment_checkpoint", "PUT", "/api/v1/quizzes/{class_quiz_id}/assessments/{attempt_id}/responses/0"),
         OperationDefinition("assessment_submit", "POST", "/api/v1/quizzes/{class_quiz_id}/assessments/{attempt_id}/submit", (200, 409))),
        ("At most one active assessment exists per user/quiz.", "Charged attempts never exceed the configured limit."),
    ),
    "assessment-different-students": ProfileDefinition(
        "assessment-different-students", "Different authorized class members concurrently start, checkpoint, and submit the same assessment.",
        (OperationDefinition("different_student_start", "POST", "/api/v1/quizzes/{class_quiz_id}/assessments"),
         OperationDefinition("different_student_checkpoint", "PUT", "/api/v1/quizzes/{class_quiz_id}/assessments/{attempt_id}/responses/0"),
         OperationDefinition("different_student_submit", "POST", "/api/v1/quizzes/{class_quiz_id}/assessments/{attempt_id}/submit", (200, 409))),
        ("Each authorized student has an independent attempt and attempt limit.", "Answers and terminal states remain associated with their owning attempt."),
    ),
    "assessment-terminal-submit": ProfileDefinition(
        "assessment-terminal-submit", "Concurrent tokens for one authorized student submit one active assessment.",
        (OperationDefinition("terminal_submit", "POST", "/api/v1/quizzes/{class_quiz_id}/assessments/{attempt_id}/submit", (200, 409)),),
        ("Exactly one terminal submission succeeds.", "The attempt is charged once and has no duplicate answers."),
    ),
    "hot-row": ProfileDefinition(
        "hot-row", "Deferred: conflicting content body/metadata/shared-media writes require a writable test-only API path.",
        (OperationDefinition("metadata_write", "PUT", "/api/v1/content/metadata/quiz/{owned_quiz_id}", (200, 400, 403)),
         OperationDefinition("body_write", "PUT", "/api/v1/content/bodies/quiz/{owned_quiz_id}", (200, 400, 403)),
         OperationDefinition("practice_read", "GET", "/api/v1/content/practice-packages/quiz/{owned_quiz_id}", (200, 409)),
         OperationDefinition("media_read", "GET", "/api/v1/content/media/quiz/{owned_quiz_id}/{media_id}?expected_content_version={content_version}", (200, 404, 409))),
        ("A reader receives a single content version or an explicit 409; no mixed projection is accepted.",),
    ),
}


@dataclass(frozen=True)
class RunConfig:
    profile: str = "all"
    shape: str = "burst"
    concurrency: int = 8
    requests_per_worker: int = 4
    ramp_seconds: float = 2.0
    soak_seconds: float = 15.0
    database_url: str = ""
    dry_run: bool = False

    def validate(self) -> None:
        if self.profile != "all" and self.profile not in PROFILES:
            raise ValueError(f"Unknown profile {self.profile!r}; choose all or: {', '.join(PROFILES)}")
        if self.shape not in SHAPES:
            raise ValueError(f"shape must be one of {', '.join(sorted(SHAPES))}")
        if self.concurrency < 1 or self.requests_per_worker < 1:
            raise ValueError("concurrency and requests-per-worker must be positive")
        if self.ramp_seconds < 0 or self.soak_seconds <= 0:
            raise ValueError("ramp-seconds must be non-negative and soak-seconds positive")
        if not self.dry_run:
            validate_database_url(self.database_url)


def validate_database_url(value: str) -> str:
    """Fail closed: only the dedicated PostgreSQL stress database is allowed."""
    if not value or not value.strip():
        raise ValueError("STUDY_BUDDY_TEST_DATABASE_URL must be set for a live run")
    try:
        parsed = make_url(value.strip())
    except Exception as exc:  # SQLAlchemy supplies several URL parsing errors.
        raise ValueError("STUDY_BUDDY_TEST_DATABASE_URL is not a valid database URL") from exc
    if parsed.get_backend_name() != "postgresql" or parsed.database != TEST_DATABASE_NAME:
        raise ValueError("STUDY_BUDDY_TEST_DATABASE_URL must target PostgreSQL database 'study_buddy_test'")
    return value.strip()


def cleanup_plan() -> tuple[str, ...]:
    """Deletion order for one run prefix; children are explicit even with cascades."""
    return ("user_sessions", "quiz_attempt_answers", "quiz_attempt_questions", "quiz_attempts",
            "quiz_question_progress", "flashcard_progress", "class_invitations", "class_members",
            "class_quizzes", "class_flashcard_decks", "classes", "question_media", "flashcard_media",
            "quiz_edit_history", "flashcard_edit_history", "quiz_moderation_history", "flashcard_moderation_history",
            "media", "quiz_questions", "flashcards", "quizzes", "flashcard_decks", "user_settings", "users")


def require_migrated_schema(engine) -> None:
    with engine.connect() as connection:
        existing = set(connection.dialect.get_table_names(connection))
    missing = REQUIRED_TABLES - existing
    if missing:
        raise RuntimeError("The PostgreSQL test database is not migrated; missing: " + ", ".join(sorted(missing)))


@dataclass
class Observation:
    operation: str
    status: int | None
    latency_ms: float
    expected: bool
    error: str | None = None


@dataclass
class OperationMetrics:
    operation: str
    requests: int
    successful: int
    expected_non_success: int
    unexpected: int
    throughput_per_second: float
    latency_p50_ms: float | None
    latency_p90_ms: float | None
    latency_p95_ms: float | None
    latency_p99_ms: float | None
    latency_max_ms: float | None
    statuses: dict[str, int]
    errors: dict[str, int]


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, int((len(ordered) - 1) * fraction)))]


def aggregate(observations: Iterable[Observation], elapsed_seconds: float) -> list[OperationMetrics]:
    grouped: dict[str, list[Observation]] = {}
    for item in observations:
        grouped.setdefault(item.operation, []).append(item)
    result = []
    for name, rows in sorted(grouped.items()):
        statuses = Counter(str(item.status) for item in rows if item.status is not None)
        errors = Counter(item.error for item in rows if item.error)
        successful = sum(item.expected and item.status is not None and 200 <= item.status < 300 for item in rows)
        expected_non_success = sum(item.expected and (item.status is None or not 200 <= item.status < 300) for item in rows)
        result.append(OperationMetrics(name, len(rows), successful, expected_non_success,
            sum(not item.expected for item in rows), round(len(rows) / max(elapsed_seconds, .001), 2),
            round(percentile([item.latency_ms for item in rows], .50) or 0, 2),
            round(percentile([item.latency_ms for item in rows], .90) or 0, 2),
            round(percentile([item.latency_ms for item in rows], .95) or 0, 2),
            round(percentile([item.latency_ms for item in rows], .99) or 0, 2),
            round(max(item.latency_ms for item in rows), 2), dict(statuses), dict(errors)))
    return result


def worker_start_delay(worker: int, config: RunConfig) -> float:
    if config.shape != "ramp" or config.concurrency == 1:
        return 0.0
    return config.ramp_seconds * worker / (config.concurrency - 1)


def execute(config: RunConfig, operation: Callable[[], Observation]) -> list[OperationMetrics]:
    """Execute one prepared operation concurrently; callers own seed/cleanup.

    Keeping transport/fixture setup outside this small executor makes the
    runner usable from live PostgreSQL tests and avoids a second app server.
    """
    config.validate()
    started = time.perf_counter()
    stop_at = started + config.soak_seconds
    lock = threading.Lock()
    observations: list[Observation] = []

    def run_worker(index: int) -> None:
        delay = worker_start_delay(index, config)
        if delay:
            time.sleep(delay)
        remaining = config.requests_per_worker
        while remaining and (config.shape != "soak" or time.perf_counter() < stop_at):
            try:
                observation = operation()
            except Exception as exc:  # capture failures in the report, don't hide them.
                observation = Observation("harness", None, 0.0, False, type(exc).__name__)
            with lock:
                observations.append(observation)
            remaining -= 1

    with ThreadPoolExecutor(max_workers=config.concurrency) as pool:
        futures = [pool.submit(run_worker, index) for index in range(config.concurrency)]
        for future in as_completed(futures):
            future.result()
    return aggregate(observations, time.perf_counter() - started)


def selected_profiles(name: str) -> list[ProfileDefinition]:
    return list(PROFILES.values()) if name == "all" else [PROFILES[name]]


def run_provenance(config: RunConfig, fixture: dict) -> dict:
    """Capture reproducibility data without disclosing the database URL."""
    try:
        application_revision = subprocess.check_output(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        application_revision = "unavailable"
    try:
        branch = subprocess.check_output(
            ["git", "-C", str(ROOT), "branch", "--show-current"], text=True, stderr=subprocess.DEVNULL,
        ).strip() or "detached"
    except Exception:
        branch = "unavailable"
    return {
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "application_revision": application_revision,
        "branch": branch,
        # The harness was not committed at the time of the September 8 run;
        # the content hash is therefore its exact reproducibility identifier.
        "harness_revision": "uncommitted-source",
        "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "configuration": public_config(config),
        "database_identifier": f"postgresql/{TEST_DATABASE_NAME}",
        "fixture": fixture,
    }


def write_results(metrics: list[OperationMetrics], json_path: Path | None, csv_path: Path | None, *, provenance: dict | None = None) -> None:
    rows = [asdict(item) for item in metrics]
    if json_path:
        json_path.parent.mkdir(parents=True, exist_ok=True)
        payload = rows if provenance is None else {"provenance": provenance, "results": rows}
        json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    if csv_path:
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        with csv_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]) if rows else ["operation"])
            writer.writeheader()
            for row in rows:
                row["statuses"] = json.dumps(row["statuses"], sort_keys=True)
                row["errors"] = json.dumps(row["errors"], sort_keys=True)
                writer.writerow(row)


def default_result_paths() -> tuple[Path, Path]:
    """Keep generated Phase 7 results out of the repository root."""
    run_id = f"phase7-{int(time.time())}-{os.urandom(4).hex()}"
    return (
        Path(".temp") / "phase7" / f"{run_id}.json",
        Path(".csv") / "phase7" / f"{run_id}.csv",
    )


def public_config(config: RunConfig) -> dict:
    """Return report-safe configuration; connection strings never leave memory."""
    result = asdict(config)
    result.pop("database_url", None)
    return result


def _http(base_url: str, definition: OperationDefinition, *, token: str = "", body=None, values=None) -> Observation:
    path = definition.path.format(**(values or {}))
    data = None if body is None else json.dumps(body).encode("utf-8")
    headers = {"Content-Type": "application/json"} if data else {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    started = time.perf_counter()
    try:
        with urlopen(Request(base_url + path, data=data, headers=headers, method=definition.method), timeout=15) as response:
            status = response.status
    except HTTPError as exc:
        status = exc.code
    except Exception as exc:
        return Observation(definition.name, None, (time.perf_counter() - started) * 1000, False, type(exc).__name__)
    return Observation(definition.name, status, (time.perf_counter() - started) * 1000, status in definition.expected_statuses)


def _json_request(base_url: str, method: str, path: str, token: str, body=None) -> tuple[int, dict]:
    data = None if body is None else json.dumps(body).encode("utf-8")
    headers = {"Authorization": f"Bearer {token}"}
    if data:
        headers["Content-Type"] = "application/json"
    try:
        with urlopen(Request(base_url + path, data=data, headers=headers, method=method), timeout=15) as response:
            return response.status, json.loads(response.read() or b"{}")
    except HTTPError as exc:
        return exc.code, {}


def _start_server(app):
    """Start a real loopback Uvicorn server; returned cleanup always stops it."""
    import uvicorn
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", access_log=False))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            with urlopen(base_url + "/ready", timeout=1) as response:
                if response.status == 200:
                    def shutdown():
                        server.should_exit = True
                        thread.join(10)
                        if thread.is_alive():
                            raise RuntimeError("loopback Uvicorn server did not stop within 10 seconds")
                    return base_url, shutdown
        except Exception:
            time.sleep(.05)
    server.should_exit = True
    thread.join(2)
    raise RuntimeError("loopback Uvicorn server did not become ready")


def run_live(config: RunConfig) -> tuple[list[OperationMetrics], dict]:
    """Run a small real-HTTP, PostgreSQL-backed scenario and clean its own data."""
    config.validate()
    from sqlalchemy import create_engine, delete, func, select
    from sqlalchemy.orm import sessionmaker
    from src.api.main import create_app
    from src.logic.passwords import PasswordHasher
    from src.storage.postgres_class_repository import PostgresClassRepository
    from src.storage.postgres_content_body_repository import PostgresContentBodyRepository
    from src.storage.postgres_content_history_repository import PostgresContentHistoryRepository
    from src.storage.postgres_content_metadata_repository import PostgresContentMetadataRepository
    from src.storage.postgres_learning_repository import PostgresLearningRepository
    from src.storage.postgres_models import (
        AccountModerationHistoryModel, ClassFlashcardDeckModel, ClassInvitationModel, ClassMemberModel, ClassModel, ClassQuizModel,
        FlashcardDeckMetadataModel, FlashcardEditHistoryModel, FlashcardMediaModel, FlashcardModel, FlashcardModerationHistoryModel,
        FlashcardProgressModel, MediaModel, QuestionMediaModel, QuizAttemptAnswerModel, QuizAttemptModel, QuizAttemptQuestionModel,
        QuizEditHistoryModel, QuizMetadataModel, QuizModerationHistoryModel, QuizQuestionModel, QuizQuestionProgressModel,
        UserModel, UserSessionModel, UserSettingsModel,
    )
    from src.storage.postgres_session_repository import PostgresSessionRepository
    from src.storage.postgres_user_repository import PostgresUserRepository

    prefix = f"phase7-{int(time.time())}-{os.urandom(4).hex()}"
    engine = create_engine(config.database_url, pool_pre_ping=True, pool_size=max(5, config.concurrency), max_overflow=0)
    require_migrated_schema(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    media_temp = tempfile.TemporaryDirectory(prefix=prefix + "-")
    previous_media_root = os.environ.get("STUDY_BUDDY_MEDIA_ROOT")
    base_url = None
    shutdown = None
    try:
        os.environ["STUDY_BUDDY_MEDIA_ROOT"] = media_temp.name
        users = PostgresUserRepository(sessions)
        session_repo = PostgresSessionRepository(sessions)
        metadata = PostgresContentMetadataRepository(sessions)
        bodies = PostgresContentBodyRepository(sessions, media_root=Path(media_temp.name))
        classes = PostgresClassRepository(sessions)
        app = create_app(user_repository=users, session_repository=session_repo, content_repository=metadata,
                         class_repository=classes, learning_repository=PostgresLearningRepository(sessions),
                         content_body_repository=bodies, content_history_repository=PostgresContentHistoryRepository(sessions))
        teacher_id = f"{prefix}-teacher"
        # The different-student profile needs one distinct authorized identity
        # per worker, including c=20; do not silently reduce that contention.
        student_ids = [f"{prefix}-student-{index}" for index in range(max(2, config.concurrency))]
        student_id = student_ids[0]
        quiz_id = f"{prefix}-quiz"
        different_quiz_id = f"{prefix}-different-students-quiz"
        terminal_quiz_id = f"{prefix}-terminal-submit-quiz"
        with sessions.begin() as session:
            for user_id, role in [(teacher_id, "teacher"), *((item, "student") for item in student_ids)]:
                session.add(UserModel(id=user_id, username=user_id, email=f"{user_id}@stress.invalid", password_hash=PasswordHasher.hash("password1"), display_name=role, role=role, status="active"))
        for seeded_quiz_id, name in ((quiz_id, "Phase 7 same-user"), (different_quiz_id, "Phase 7 different students"), (terminal_quiz_id, "Phase 7 terminal submit")):
            assert metadata.import_quiz({"id": seeded_quiz_id, "name": name, "moderation": {"owner_id": teacher_id, "status": "published", "visibility": "class_only"}, "test_settings": {"attempt_limit": 1}}, f"stress://{prefix}/{seeded_quiz_id}")
        uploaded = bodies.register_uploaded_media(teacher_id, TINY_PNG_BYTES, "phase7.png")
        for seeded_quiz_id in (quiz_id, different_quiz_id, terminal_quiz_id):
            assert bodies.import_quiz({"id": seeded_quiz_id, "questions": [{"id": f"{seeded_quiz_id}-q1", "question": "One?", "type": "short_answer", "answer": "one", "image_path": uploaded["media_id"]}]})
        class_id = classes.class_id_for("quiz", quiz_id)
        with sessions.begin() as session:
            session.add(ClassModel(id=class_id, owner_id=teacher_id, name="Phase 7", status="active"))
            session.flush()
            for seeded_quiz_id in (quiz_id, different_quiz_id, terminal_quiz_id):
                session.add(ClassQuizModel(class_id=class_id, quiz_id=seeded_quiz_id))
            for member_id in student_ids:
                session.add(ClassMemberModel(class_id=class_id, user_id=member_id, status="active"))
        base_url, shutdown = _start_server(app)
        login = OperationDefinition("login", "POST", "/api/v1/auth/login")
        # Two distinct sessions are deliberately required by the product rule.
        def login_token():
            request = Request(base_url + login.path, data=json.dumps({"login": student_id, "password": "password1"}).encode(), headers={"Content-Type": "application/json"}, method="POST")
            with urlopen(request, timeout=15) as response:
                return json.loads(response.read())["access_token"]
        token_a, token_b = login_token(), login_token()
        account_tokens = [token_a]
        for account in student_ids[1:]:
            request = Request(base_url + login.path, data=json.dumps({"login": account, "password": "password1"}).encode(), headers={"Content-Type": "application/json"}, method="POST")
            with urlopen(request, timeout=15) as response:
                account_tokens.append(json.loads(response.read())["access_token"])
        metrics = aggregate([_http(base_url, login, body={"login": student_id, "password": "password1"})], .001)
        profiles = {item.name for item in selected_profiles(config.profile)}
        account_token_by_student = dict(zip(student_ids, account_tokens, strict=True))
        current_version = metadata.get_by_id("quiz", quiz_id)["content_version"]
        values = {"quiz_id": quiz_id, "class_quiz_id": quiz_id, "owned_quiz_id": quiz_id, "restricted_quiz_id": "missing", "attempt_id": "", "media_id": uploaded["media_id"], "content_version": current_version}
        if "multi-account" in profiles:
            read = [OperationDefinition("available_metadata", "GET", "/api/v1/content/metadata"), OperationDefinition("preview", "GET", "/api/v1/content/bodies/quiz/{quiz_id}"), OperationDefinition("practice_download", "GET", "/api/v1/content/practice-packages/quiz/{quiz_id}"), OperationDefinition("media_manifest", "GET", "/api/v1/content/media-manifests/quiz/{quiz_id}"), OperationDefinition("media_read", "GET", "/api/v1/content/media/quiz/{quiz_id}/{media_id}?expected_content_version={content_version}"), OperationDefinition("restricted_denied", "GET", "/api/v1/content/bodies/quiz/{restricted_quiz_id}", (404,))]
            for definition in read:
                cursor = iter(range(config.concurrency * config.requests_per_worker))
                cursor_lock = threading.Lock()
                def account_read(definition=definition):
                    with cursor_lock:
                        index = next(cursor, 0)
                    return _http(base_url, definition, token=account_tokens[index % len(account_tokens)], values=values)
                metrics.extend(execute(config, account_read))
        if "same-account-sessions" in profiles:
            # Both devices read concurrently before logout; neither is invalidated by the other.
            metrics.extend(execute(config, lambda: _http(base_url, OperationDefinition("same_account_concurrent_read", "GET", "/api/v1/content/metadata"), token=token_a if int(time.time_ns()) % 2 else token_b)))
            session_observations = [_http(base_url, OperationDefinition("session_a_logout", "POST", "/api/v1/auth/logout", (204,)), token=token_a),
                _http(base_url, OperationDefinition("session_a_rejected", "GET", "/api/v1/users/me", (401,)), token=token_a),
                _http(base_url, OperationDefinition("session_b_stays_valid", "GET", "/api/v1/users/me"), token=token_b),
                _http(base_url, OperationDefinition("session_b_reads", "GET", "/api/v1/content/metadata"), token=token_b)]
            metrics.extend(aggregate(session_observations, .001))
            token_b = login_token()  # reauthentication is explicit, but does not affect token B's prior validity.
            account_tokens[0] = token_b
            account_token_by_student[student_id] = token_b
        if "assessment-cohort" in profiles:
            start = OperationDefinition("assessment_start", "POST", "/api/v1/quizzes/{class_quiz_id}/assessments", (200, 409))
            metrics.extend(execute(config, lambda: _http(base_url, start, token=token_b, values=values)))
            status, attempt = _json_request(base_url, "POST", f"/api/v1/quizzes/{quiz_id}/assessments", token_b)
            attempt_id = attempt.get("id", "")
            if status == 200 and attempt_id:
                values["attempt_id"] = attempt_id
                checkpoint = OperationDefinition("assessment_checkpoint", "PUT", "/api/v1/quizzes/{class_quiz_id}/assessments/{attempt_id}/responses/0")
                submit = OperationDefinition("assessment_submit", "POST", "/api/v1/quizzes/{class_quiz_id}/assessments/{attempt_id}/submit", (200, 409))
                metrics.extend(aggregate([_http(base_url, checkpoint, token=token_b, body={"user_answer": "one"}, values=values),
                                          _http(base_url, submit, token=token_b, body={"responses": {"0": "one"}}, values=values),
                                          _http(base_url, start, token=token_b, values=values)], .001))
                with sessions() as session:
                    active = session.scalar(select(func.count()).select_from(QuizAttemptModel).where(
                        QuizAttemptModel.user_id == student_id, QuizAttemptModel.quiz_id == quiz_id,
                        QuizAttemptModel.status.in_(("in_progress", "abandoned")))) or 0
                    charged = session.scalar(select(func.count()).select_from(QuizAttemptModel).where(
                        QuizAttemptModel.user_id == student_id, QuizAttemptModel.quiz_id == quiz_id,
                        QuizAttemptModel.counts_toward_limit.is_(True), QuizAttemptModel.status != "refunded")) or 0
                    submitted = session.scalar(select(func.count()).select_from(QuizAttemptModel).where(
                        QuizAttemptModel.user_id == student_id, QuizAttemptModel.quiz_id == quiz_id,
                        QuizAttemptModel.status == "submitted")) or 0
                metrics.extend(aggregate([
                    Observation("invariant_active_attempts", 200 if active <= 1 else 500, 0, active <= 1, None if active <= 1 else f"active={active}"),
                    Observation("invariant_attempt_limit", 200 if charged <= 1 else 500, 0, charged <= 1, None if charged <= 1 else f"charged={charged}"),
                    Observation("invariant_terminal_submission", 200 if submitted >= 1 else 500, 0, submitted >= 1, None if submitted >= 1 else "no_submitted_attempt"),
                ], .001))
        if "assessment-different-students" in profiles:
            different_values = {**values, "class_quiz_id": different_quiz_id}
            start = OperationDefinition("different_student_start", "POST", "/api/v1/quizzes/{class_quiz_id}/assessments")
            next_student = iter(student_ids)
            next_student_lock = threading.Lock()

            def different_start():
                with next_student_lock:
                    member_id = next(next_student, student_ids[-1])
                return _http(base_url, start, token=account_token_by_student[member_id], values=different_values)

            metrics.extend(execute(config, different_start))
            with sessions() as session:
                different_attempts = session.scalars(select(QuizAttemptModel).where(
                    QuizAttemptModel.quiz_id == different_quiz_id,
                    QuizAttemptModel.user_id.in_(student_ids),
                    QuizAttemptModel.status == "in_progress",
                )).all()
            attempts_by_student = {attempt.user_id: attempt.id for attempt in different_attempts}
            expected_students = set(student_ids)
            metrics.extend(aggregate([
                Observation("invariant_different_student_attempts", 200 if set(attempts_by_student) == expected_students else 500, 0,
                            set(attempts_by_student) == expected_students,
                            None if set(attempts_by_student) == expected_students else f"attempt_users={len(attempts_by_student)}"),
            ], .001))
            if set(attempts_by_student) == expected_students:
                mapped_attempts = list(attempts_by_student.items())
                checkpoint = OperationDefinition("different_student_checkpoint", "PUT", "/api/v1/quizzes/{class_quiz_id}/assessments/{attempt_id}/responses/0")
                submit = OperationDefinition("different_student_submit", "POST", "/api/v1/quizzes/{class_quiz_id}/assessments/{attempt_id}/submit", (200, 409))
                checkpoint_cursor = iter(mapped_attempts)
                checkpoint_lock = threading.Lock()

                def different_checkpoint():
                    with checkpoint_lock:
                        member_id, attempt_id = next(checkpoint_cursor, mapped_attempts[-1])
                    return _http(base_url, checkpoint, token=account_token_by_student[member_id], body={"user_answer": "one"}, values={**different_values, "attempt_id": attempt_id})

                metrics.extend(execute(config, different_checkpoint))
                submit_cursor = iter(mapped_attempts)
                submit_lock = threading.Lock()

                def different_submit():
                    with submit_lock:
                        member_id, attempt_id = next(submit_cursor, mapped_attempts[-1])
                    return _http(base_url, submit, token=account_token_by_student[member_id], body={"responses": {"0": "one"}}, values={**different_values, "attempt_id": attempt_id})

                metrics.extend(execute(config, different_submit))
                with sessions() as session:
                    terminal_count = session.scalar(select(func.count()).select_from(QuizAttemptModel).where(
                        QuizAttemptModel.quiz_id == different_quiz_id, QuizAttemptModel.user_id.in_(student_ids),
                        QuizAttemptModel.status == "submitted", QuizAttemptModel.counts_toward_limit.is_(True),
                    )) or 0
                    answer_count = session.scalar(select(func.count()).select_from(QuizAttemptAnswerModel).join(
                        QuizAttemptModel, QuizAttemptAnswerModel.attempt_id == QuizAttemptModel.id,
                    ).where(QuizAttemptModel.quiz_id == different_quiz_id)) or 0
                metrics.extend(aggregate([
                    Observation("invariant_different_student_terminal", 200 if terminal_count == len(student_ids) else 500, 0, terminal_count == len(student_ids), None if terminal_count == len(student_ids) else f"submitted={terminal_count}"),
                    Observation("invariant_different_student_answers", 200 if answer_count == len(student_ids) else 500, 0, answer_count == len(student_ids), None if answer_count == len(student_ids) else f"answers={answer_count}"),
                ], .001))
        if "assessment-terminal-submit" in profiles:
            terminal_values = {**values, "class_quiz_id": terminal_quiz_id}
            start_status, terminal_attempt = _json_request(base_url, "POST", f"/api/v1/quizzes/{terminal_quiz_id}/assessments", token_b)
            terminal_attempt_id = terminal_attempt.get("id", "")
            if start_status == 200 and terminal_attempt_id:
                terminal_values["attempt_id"] = terminal_attempt_id
                checkpoint = OperationDefinition("terminal_checkpoint", "PUT", "/api/v1/quizzes/{class_quiz_id}/assessments/{attempt_id}/responses/0")
                metrics.extend(aggregate([_http(base_url, checkpoint, token=token_b, body={"user_answer": "one"}, values=terminal_values)], .001))
                terminal_tokens = [login_token() for _ in range(config.concurrency)]
                terminal_submit = OperationDefinition("terminal_submit", "POST", "/api/v1/quizzes/{class_quiz_id}/assessments/{attempt_id}/submit", (200, 409))
                token_cursor = iter(terminal_tokens)
                token_lock = threading.Lock()

                def submit_terminal():
                    with token_lock:
                        token = next(token_cursor, terminal_tokens[-1])
                    return _http(base_url, terminal_submit, token=token, body={"responses": {"0": "one"}}, values=terminal_values)

                metrics.extend(execute(config, submit_terminal))
                with sessions() as session:
                    row = session.get(QuizAttemptModel, terminal_attempt_id)
                    answer_count = session.scalar(select(func.count()).select_from(QuizAttemptAnswerModel).where(
                        QuizAttemptAnswerModel.attempt_id == terminal_attempt_id,
                    )) or 0
                valid_terminal = row is not None and row.status == "submitted" and row.counts_toward_limit and answer_count == 1
                metrics.extend(aggregate([
                    Observation("invariant_terminal_submit_once", 200 if valid_terminal else 500, 0, valid_terminal, None if valid_terminal else f"status={getattr(row, 'status', None)}, answers={answer_count}"),
                ], .001))
        if "hot-row" in profiles:
            # Same owner writes are intentionally omitted: published teacher content cannot be mutated by this API.
            # The concurrent assessment start above remains the hot-row write collision exercised safely.
            metrics.extend(aggregate([Observation("hot_row_deferred", None, 0, True, "published_content_write_policy")], .001))
        return metrics, {
            "identity": prefix,
            "version": "class-backed-assessment-v2",
            "pool": {"pool_pre_ping": True, "pool_size": max(5, config.concurrency), "max_overflow": 0},
        }
    finally:
        original_error = sys.exc_info()[0]
        cleanup_error = None
        try:
            if shutdown:
                shutdown()
            # Explicit child-first cleanup prevents this diagnostic from leaving
            # rows behind even if future migrations relax a cascade.
            with sessions.begin() as session:
                user_ids = [teacher_id, *student_ids] if "teacher_id" in locals() else []
                class_ids = [class_id] if "class_id" in locals() else []
                attempt_ids = select(QuizAttemptModel.id).where(QuizAttemptModel.user_id.in_(user_ids), QuizAttemptModel.quiz_id.like(prefix + "%"))
                session.execute(delete(UserSessionModel).where(UserSessionModel.user_id.in_(user_ids)))
                session.execute(delete(QuizAttemptAnswerModel).where(QuizAttemptAnswerModel.attempt_id.in_(attempt_ids)))
                session.execute(delete(QuizAttemptQuestionModel).where(QuizAttemptQuestionModel.attempt_id.in_(attempt_ids)))
                session.execute(delete(QuizAttemptModel).where(QuizAttemptModel.user_id.in_(user_ids), QuizAttemptModel.quiz_id.like(prefix + "%")))
                session.execute(delete(QuizQuestionProgressModel).where(QuizQuestionProgressModel.user_id.in_(user_ids)))
                session.execute(delete(FlashcardProgressModel).where(FlashcardProgressModel.user_id.in_(user_ids)))
                session.execute(delete(ClassInvitationModel).where(ClassInvitationModel.class_id.in_(class_ids)))
                session.execute(delete(ClassMemberModel).where(ClassMemberModel.class_id.in_(class_ids)))
                session.execute(delete(ClassQuizModel).where(ClassQuizModel.class_id.in_(class_ids)))
                session.execute(delete(ClassFlashcardDeckModel).where(ClassFlashcardDeckModel.class_id.in_(class_ids)))
                session.execute(delete(ClassModel).where(ClassModel.id.in_(class_ids)))
                session.execute(delete(QuestionMediaModel).where(QuestionMediaModel.quiz_id.like(prefix + "%")))
                session.execute(delete(FlashcardMediaModel).where(FlashcardMediaModel.deck_id.like(prefix + "%")))
                session.execute(delete(QuizEditHistoryModel).where(QuizEditHistoryModel.quiz_id.like(prefix + "%")))
                session.execute(delete(FlashcardEditHistoryModel).where(FlashcardEditHistoryModel.deck_id.like(prefix + "%")))
                session.execute(delete(QuizModerationHistoryModel).where(QuizModerationHistoryModel.quiz_id.like(prefix + "%")))
                session.execute(delete(FlashcardModerationHistoryModel).where(FlashcardModerationHistoryModel.deck_id.like(prefix + "%")))
                session.execute(delete(MediaModel).where(MediaModel.owner_id.in_(user_ids)))
                session.execute(delete(QuizQuestionModel).where(QuizQuestionModel.quiz_id.like(prefix + "%")))
                session.execute(delete(FlashcardModel).where(FlashcardModel.deck_id.like(prefix + "%")))
                session.execute(delete(QuizMetadataModel).where(QuizMetadataModel.id.like(prefix + "%")))
                session.execute(delete(FlashcardDeckMetadataModel).where(FlashcardDeckMetadataModel.id.like(prefix + "%")))
                session.execute(delete(UserSettingsModel).where(UserSettingsModel.user_id.in_(user_ids)))
                session.execute(delete(AccountModerationHistoryModel).where(AccountModerationHistoryModel.target_user_id.in_(user_ids)))
                session.execute(delete(UserModel).where(UserModel.id.in_(user_ids)))
        except Exception as exc:
            cleanup_error = exc
        finally:
            media_temp.cleanup()
            if previous_media_root is None:
                os.environ.pop("STUDY_BUDDY_MEDIA_ROOT", None)
            else:
                os.environ["STUDY_BUDDY_MEDIA_ROOT"] = previous_media_root
            engine.dispose()
        if cleanup_error and original_error is None:
            raise cleanup_error




def main() -> int:
    # Match the gated integration tests: local runtime settings may hold only
    # the disposable test-database URL, so load them before validating a run.
    from src.runtime_config import load_runtime_environment
    load_runtime_environment()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default="all", choices=["all", *PROFILES])
    parser.add_argument("--shape", default="burst", choices=sorted(SHAPES))
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--requests-per-worker", type=int, default=4)
    parser.add_argument("--ramp-seconds", type=float, default=2.0)
    parser.add_argument("--soak-seconds", type=float, default=15.0)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--csv-output", type=Path)
    args = parser.parse_args()
    default_json, default_csv = default_result_paths()
    args.json_output = args.json_output or default_json
    args.csv_output = args.csv_output or default_csv
    config = RunConfig(args.profile, args.shape, args.concurrency, args.requests_per_worker,
                       args.ramp_seconds, args.soak_seconds,
                       os.getenv("STUDY_BUDDY_TEST_DATABASE_URL", ""), args.dry_run)
    try:
        config.validate()
    except ValueError as exc:
        parser.error(str(exc))
    plan = {"config": public_config(config), "profiles": [asdict(profile) for profile in selected_profiles(config.profile)], "deferred": DEFERRED_SLICES}
    if config.dry_run:
        print(json.dumps(plan, indent=2))
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(json.dumps(plan, indent=2), encoding="utf-8")
        args.csv_output.parent.mkdir(parents=True, exist_ok=True)
        with args.csv_output.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=["profile", "operation", "method", "path", "expected_statuses"])
            writer.writeheader()
            for profile in selected_profiles(config.profile):
                for operation in profile.operations:
                    writer.writerow({"profile": profile.name, "operation": operation.name, "method": operation.method, "path": operation.path, "expected_statuses": "/".join(map(str, operation.expected_statuses))})
        return 0
    metrics, fixture = run_live(config)
    provenance = run_provenance(config, fixture)
    write_results(metrics, args.json_output, args.csv_output, provenance=provenance)
    print(json.dumps({"provenance": provenance, "deferred": DEFERRED_SLICES, "results": [asdict(item) for item in metrics]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
