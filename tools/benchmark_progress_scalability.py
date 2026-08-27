"""Benchmark the current per-content progress API against PostgreSQL.

This is deliberately an opt-in diagnostic, not a migration or a production
feature.  It only accepts the disposable ``study_buddy_test`` PostgreSQL
database named by ``STUDY_BUDDY_TEST_DATABASE_URL``.  Every generated row has
a run-specific prefix and is removed in a ``finally`` block.

Example (from the repository root)::

    .venv\\Scripts\\python tools\\benchmark_progress_scalability.py

The HTTP figures use FastAPI's in-process TestClient.  They therefore include
the real route, authentication, authorization, repositories, JSON encoding,
and sequential request fan-out, but exclude TCP/TLS and a separate Uvicorn
process.  ``--repetitions`` can be increased where the test database is not
shared with other work.
"""

from __future__ import annotations

import argparse
import gc
import json
import os
import statistics
import sys
import time
import tracemalloc
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

from sqlalchemy import and_, create_engine, delete, event, func, insert, select
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import sessionmaker


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient

from src.api.main import create_app
from src.storage.postgres_content_body_repository import PostgresContentBodyRepository
from src.storage.postgres_content_metadata_repository import PostgresContentMetadataRepository
from src.storage.postgres_learning_repository import PostgresLearningRepository
from src.storage.postgres_models import (
    FlashcardDeckMetadataModel,
    FlashcardModel,
    FlashcardProgressModel,
    UserModel,
)
from src.storage.postgres_session_repository import PostgresSessionRepository
from src.storage.postgres_user_repository import PostgresUserRepository


TEST_DATABASE_NAME = "study_buddy_test"
DEFAULT_SIZES = (100, 1_000, 10_000)


@dataclass
class Measurement:
    operation: str
    decks: int
    repetitions: int
    requests: int
    sql_statements: int
    sql_ms: float
    total_ms: float
    app_ms: float
    payload_bytes: int | None
    peak_memory_bytes: int | None


class SqlTimer:
    """Count statements and driver execution time for one shared engine."""

    def __init__(self, engine: Engine):
        self.statements = 0
        self.elapsed_seconds = 0.0
        event.listen(engine, "before_cursor_execute", self._before)
        event.listen(engine, "after_cursor_execute", self._after)

    def _before(self, _conn, _cursor, _statement, _parameters, context, _executemany):
        context._progress_benchmark_started_at = time.perf_counter()

    def _after(self, _conn, _cursor, _statement, _parameters, context, _executemany):
        self.statements += 1
        self.elapsed_seconds += time.perf_counter() - context._progress_benchmark_started_at

    def reset(self) -> None:
        self.statements = 0
        self.elapsed_seconds = 0.0


def _database_url() -> str:
    url = os.getenv("STUDY_BUDDY_TEST_DATABASE_URL", "").strip()
    if not url:
        raise RuntimeError("STUDY_BUDDY_TEST_DATABASE_URL must be set")
    parsed = make_url(url)
    if parsed.get_backend_name() != "postgresql" or parsed.database != TEST_DATABASE_NAME:
        raise RuntimeError(
            "STUDY_BUDDY_TEST_DATABASE_URL must point to the disposable "
            f"PostgreSQL database {TEST_DATABASE_NAME!r}"
        )
    return url


def _require_schema(engine: Engine) -> None:
    required = {"users", "flashcard_decks", "flashcards", "flashcard_progress"}
    with engine.connect() as connection:
        existing = set(connection.dialect.get_table_names(connection))
    missing = required - existing
    if missing:
        raise RuntimeError(
            "The PostgreSQL test database is not migrated; missing: " + ", ".join(sorted(missing))
        )


def _seed(session_factory, prefix: str, deck_count: int) -> tuple[str, list[str]]:
    """Insert one minimal card and one progress row per public deck."""
    user_id = f"{prefix}-user"
    deck_ids = [f"{prefix}-d{index}" for index in range(deck_count)]
    with session_factory.begin() as session:
        session.execute(insert(UserModel), [{
            "id": user_id,
            "username": f"bench_{prefix[-12:]}",
            "email": f"{prefix}@benchmark.invalid",
            "password_hash": "benchmark-only",
            "display_name": "Progress benchmark",
            "role": "student",
            "status": "active",
            "ban_reason": "",
        }])
        session.execute(insert(FlashcardDeckMetadataModel), [{
            "id": deck_id,
            "owner_id": None,
            "source_owner_id": "benchmark",
            "name": f"Benchmark deck {index}",
            "lifecycle": "published",
            "visibility": "public",
            "source_path": f"benchmark://{prefix}/{index}",
            "content_version": 1,
        } for index, deck_id in enumerate(deck_ids)])
        session.execute(insert(FlashcardModel), [{
            "deck_id": deck_id,
            "card_id": f"c{index}",
            "front_text": "Minimal benchmark prompt",
            "back_text": "Minimal benchmark answer",
            "hint_text": "",
            "description_text": "",
            "position": 0,
        } for index, deck_id in enumerate(deck_ids)])
        session.execute(insert(FlashcardProgressModel), [{
            "user_id": user_id,
            "deck_id": deck_id,
            "card_id": f"c{index}",
            "correct_count": 1,
            "wrong_count": 0,
            "mastered": True,
        } for index, deck_id in enumerate(deck_ids)])
    return user_id, deck_ids


def _cleanup(session_factory, prefix: str) -> None:
    """Remove only this run's generated rows (database FKs clean children)."""
    with session_factory.begin() as session:
        session.execute(delete(FlashcardDeckMetadataModel).where(
            FlashcardDeckMetadataModel.id.like(f"{prefix}-%")
        ))
        session.execute(delete(UserModel).where(UserModel.id == f"{prefix}-user"))


def _measure(
    operation: str,
    decks: int,
    repetitions: int,
    timer: SqlTimer,
    work: Callable[[], tuple[int, int | None]],
    memory: bool,
) -> Measurement:
    totals: list[float] = []
    sql_times: list[float] = []
    statement_counts: list[int] = []
    payloads: list[int] = []
    peaks: list[int] = []
    requests = 0
    for _ in range(repetitions):
        gc.collect()
        timer.reset()
        if memory:
            tracemalloc.start()
        started = time.perf_counter()
        request_count, payload = work()
        elapsed = time.perf_counter() - started
        if memory:
            _current, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()
            peaks.append(peak)
        totals.append(elapsed)
        sql_times.append(timer.elapsed_seconds)
        statement_counts.append(timer.statements)
        requests = request_count
        if payload is not None:
            payloads.append(payload)
    total_ms = statistics.median(totals) * 1_000
    sql_ms = statistics.median(sql_times) * 1_000
    return Measurement(
        operation=operation,
        decks=decks,
        repetitions=repetitions,
        requests=requests,
        sql_statements=round(statistics.median(statement_counts)),
        sql_ms=round(sql_ms, 2),
        total_ms=round(total_ms, 2),
        app_ms=round(max(0.0, total_ms - sql_ms), 2),
        payload_bytes=round(statistics.median(payloads)) if payloads else None,
        peak_memory_bytes=max(peaks) if peaks else None,
    )


def _http_work(client: TestClient, token: str, deck_ids: list[str]) -> tuple[int, int]:
    payload_bytes = 0
    headers = {"Authorization": f"Bearer {token}"}
    # Intentionally sequential: this matches HttpLearningRepository's current UI path.
    for deck_id in deck_ids:
        response = client.get(f"/api/v1/progress/flashcard/{deck_id}?include_items=true", headers=headers)
        response.raise_for_status()
        payload_bytes += len(response.content)
    return len(deck_ids), payload_bytes


def _http_summary_work(client: TestClient, token: str) -> tuple[int, int]:
    response = client.get(
        "/api/v1/progress/summary?include_items=true",
        headers={"Authorization": f"Bearer {token}"},
    )
    response.raise_for_status()
    return 1, len(response.content)


def _repository_work(repository, user_id: str, deck_ids: list[str]) -> tuple[int, None]:
    for deck_id in deck_ids:
        repository.get_flashcard_progress(deck_id, user_id)
    return 0, None


def _aggregate_work(session_factory, user_id: str, deck_ids: list[str]) -> tuple[int, int]:
    """Candidate one-query normalized-table aggregation; not a production endpoint."""
    with session_factory() as session:
        rows = session.execute(
            select(
                FlashcardDeckMetadataModel.id,
                func.count(FlashcardModel.card_id).label("total_items"),
                func.count(FlashcardProgressModel.card_id)
                .filter(FlashcardProgressModel.mastered.is_(True)).label("mastered_items"),
            )
            .outerjoin(FlashcardModel, FlashcardModel.deck_id == FlashcardDeckMetadataModel.id)
            .outerjoin(FlashcardProgressModel, and_(
                FlashcardProgressModel.deck_id == FlashcardDeckMetadataModel.id,
                FlashcardProgressModel.card_id == FlashcardModel.card_id,
                FlashcardProgressModel.user_id == user_id,
            ))
            .where(FlashcardDeckMetadataModel.id.in_(deck_ids))
            .group_by(FlashcardDeckMetadataModel.id)
        ).all()
    # Mimic simple endpoint serialization so Python row conversion is represented.
    encoded = json.dumps([
        {"id": row.id, "total": row.total_items, "mastered": row.mastered_items}
        for row in rows
    ], separators=(",", ":")).encode("utf-8")
    return 1, len(encoded)


def _print_table(measurements: list[Measurement]) -> None:
    print("\noperation                 decks requests sql  db ms  total ms  app ms  payload B  peak MiB")
    for row in measurements:
        payload = "-" if row.payload_bytes is None else str(row.payload_bytes)
        peak = "-" if row.peak_memory_bytes is None else f"{row.peak_memory_bytes / 1024 / 1024:.2f}"
        print(
            f"{row.operation:24} {row.decks:>5} {row.requests:>8} {row.sql_statements:>3} "
            f"{row.sql_ms:>6.2f} {row.total_ms:>9.2f} {row.app_ms:>7.2f} {payload:>10} {peak:>9}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sizes", type=int, nargs="+", default=list(DEFAULT_SIZES))
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--no-memory", action="store_true", help="Skip tracemalloc peak measurements")
    parser.add_argument(
        "--old-max-size", type=int, default=1_000,
        help="Skip legacy HTTP/repository fan-out above this dataset size (0 skips all)",
    )
    parser.add_argument("--json-output", type=Path, help="Optional path for machine-readable results")
    args = parser.parse_args()
    if args.repetitions < 1 or any(size < 1 for size in args.sizes):
        parser.error("sizes and repetitions must be positive")

    engine = create_engine(_database_url(), pool_pre_ping=True)
    _require_schema(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    timer = SqlTimer(engine)
    user_repository = PostgresUserRepository(session_factory)
    session_repository = PostgresSessionRepository(session_factory)
    content_repository = PostgresContentMetadataRepository(session_factory)
    learning_repository = PostgresLearningRepository(session_factory)
    bodies_repository = PostgresContentBodyRepository(session_factory)
    app = create_app(
        user_repository=user_repository,
        session_repository=session_repository,
        content_repository=content_repository,
        learning_repository=learning_repository,
        content_body_repository=bodies_repository,
    )
    results: list[Measurement] = []
    prefix = f"progress-bench-{uuid.uuid4().hex[:16]}"
    try:
        for deck_count in args.sizes:
            user_id, deck_ids = _seed(session_factory, f"{prefix}-{deck_count}", deck_count)
            try:
                token, _expires = session_repository.create(user_id)
                with TestClient(app) as client:
                    if 0 < deck_count <= args.old_max_size:
                        results.append(_measure(
                            "http_sequential", deck_count, args.repetitions, timer,
                            lambda: _http_work(client, token, deck_ids), not args.no_memory,
                        ))
                    results.append(_measure(
                        "http_batched_summary", deck_count, args.repetitions, timer,
                        lambda: _http_summary_work(client, token), not args.no_memory,
                    ))
                if 0 < deck_count <= args.old_max_size:
                    results.append(_measure(
                        "repository_per_deck", deck_count, args.repetitions, timer,
                        lambda: _repository_work(learning_repository, user_id, deck_ids), not args.no_memory,
                    ))
                results.append(_measure(
                    "normalized_aggregate", deck_count, args.repetitions, timer,
                    lambda: _aggregate_work(session_factory, user_id, deck_ids), not args.no_memory,
                ))
            finally:
                _cleanup(session_factory, f"{prefix}-{deck_count}")
        _print_table(results)
        if args.json_output:
            args.json_output.write_text(json.dumps([asdict(row) for row in results], indent=2), encoding="utf-8")
            print(f"\nWrote {args.json_output}")
        return 0
    finally:
        # Covers exceptions during seeding as well as normal per-dataset cleanup.
        for deck_count in args.sizes:
            _cleanup(session_factory, f"{prefix}-{deck_count}")
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
