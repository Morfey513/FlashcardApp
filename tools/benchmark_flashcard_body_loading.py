"""Benchmark authenticated PostgreSQL flashcard-body loading safely.

Only the disposable ``study_buddy_test`` database is accepted. Synthetic rows
use a run-specific prefix and are removed in nested ``finally`` blocks.
"""

from __future__ import annotations

import argparse
import os
import statistics
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, event, insert, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import sessionmaker


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.api.main import create_app
from src.storage.postgres_class_repository import PostgresClassRepository
from src.storage.postgres_content_body_repository import PostgresContentBodyRepository
from src.storage.postgres_content_history_repository import PostgresContentHistoryRepository
from src.storage.postgres_content_metadata_repository import PostgresContentMetadataRepository
from src.storage.postgres_learning_repository import PostgresLearningRepository
from src.storage.postgres_models import (
    FlashcardDeckMetadataModel, FlashcardMediaModel, FlashcardModel, MediaModel,
    UserModel,
)
from src.storage.postgres_session_repository import PostgresSessionRepository
from src.storage.postgres_user_repository import PostgresUserRepository


TEST_DATABASE_NAME = "study_buddy_test"
DEFAULT_SIZES = (10, 100, 1_000)
VARIANTS = ("without_media", "with_media")


@dataclass
class Measurement:
    cards: int
    variant: str
    http_requests: int
    sql_statements: int
    db_ms: float
    api_ms: float
    client_ms: float
    total_ms: float
    response_bytes: int


class SqlTimer:
    def __init__(self, engine: Engine):
        self.statements = 0
        self.elapsed = 0.0
        event.listen(engine, "before_cursor_execute", self._before)
        event.listen(engine, "after_cursor_execute", self._after)

    def _before(self, _conn, _cursor, _statement, _params, context, _many):
        context._flashcard_body_benchmark_started = time.perf_counter()

    def _after(self, _conn, _cursor, _statement, _params, context, _many):
        self.statements += 1
        self.elapsed += time.perf_counter() - context._flashcard_body_benchmark_started

    def reset(self):
        self.statements = 0
        self.elapsed = 0.0


def _database_url():
    value = os.getenv("STUDY_BUDDY_TEST_DATABASE_URL", "").strip()
    parsed = make_url(value) if value else None
    if parsed is None or parsed.get_backend_name() != "postgresql" or parsed.database != TEST_DATABASE_NAME:
        raise RuntimeError(
            "STUDY_BUDDY_TEST_DATABASE_URL must point to PostgreSQL database "
            f"{TEST_DATABASE_NAME!r}"
        )
    return value


def _seed(session_factory, prefix: str, card_count: int, with_media: bool):
    user_id = f"{prefix}-student"
    deck_id = f"{prefix}-deck"
    with session_factory.begin() as session:
        session.execute(insert(UserModel), [{
            "id": user_id, "username": f"deckbench_{prefix[-12:]}",
            "email": f"{prefix}@benchmark.invalid", "password_hash": "benchmark-only",
            "display_name": "Deck benchmark", "role": "student", "status": "active",
            "ban_reason": "",
        }])
        session.execute(insert(FlashcardDeckMetadataModel), [{
            "id": deck_id, "owner_id": None, "source_owner_id": "benchmark",
            "name": f"Deck benchmark {card_count}", "lifecycle": "published",
            "visibility": "public", "source_path": f"benchmark://flashcard-body/{prefix}",
            "content_version": 1,
        }])
        cards = [{
            "deck_id": deck_id, "card_id": f"card-{position:05d}",
            "front_text": f"Front {position}", "back_text": f"Back {position}",
            "hint_text": f"Hint {position}", "description_text": f"Description {position}",
            "position": position,
        } for position in range(card_count)]
        session.execute(insert(FlashcardModel), cards)
        if with_media:
            media_rows = []
            attachments = []
            for position in range(card_count):
                card_id = f"card-{position:05d}"
                for role, extension, media_type in (
                    ("image", "png", "image"),
                    ("audio_front", "front.mp3", "audio"),
                    ("audio_back", "back.mp3", "audio"),
                ):
                    storage_key = f"benchmark://flashcard-body/{prefix}/{position}.{extension}"
                    media_id = uuid.uuid5(uuid.NAMESPACE_URL, storage_key).hex
                    media_rows.append({
                        "id": media_id, "owner_id": None, "storage_key": storage_key,
                        "original_filename": Path(storage_key).name, "media_type": media_type,
                        "mime_type": "image/png" if media_type == "image" else "audio/mpeg",
                        "size_bytes": 128,
                    })
                    attachments.append({
                        "deck_id": deck_id, "card_id": card_id,
                        "media_id": media_id, "role": role,
                    })
            session.execute(insert(MediaModel), media_rows)
            session.execute(insert(FlashcardMediaModel), attachments)
    return user_id, deck_id


def _cleanup(session_factory, prefix: str):
    with session_factory.begin() as session:
        session.execute(delete(FlashcardDeckMetadataModel).where(
            FlashcardDeckMetadataModel.source_path.like(f"benchmark://flashcard-body/{prefix}%")
        ))
        session.execute(delete(MediaModel).where(
            MediaModel.storage_key.like(f"benchmark://flashcard-body/{prefix}/%")
        ))
        session.execute(delete(UserModel).where(UserModel.id.like(f"{prefix}-%")))


def _measure(client, token, deck_id, timer, cards, variant, repetitions):
    db_values, api_values, client_values, total_values = [], [], [], []
    statements, sizes = [], []
    for _ in range(repetitions):
        timer.reset()
        started = time.perf_counter()
        response = client.get(
            f"/api/v1/content/bodies/flashcard/{deck_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        api_finished = time.perf_counter()
        response.raise_for_status()
        body = response.json()
        finished = time.perf_counter()
        assert len(body["cards"]) == cards
        if variant == "with_media" and cards:
            assert body["cards"][0]["image"]
            assert set(body["cards"][0]["audio"]) == {"front", "back"}
        db_values.append(timer.elapsed * 1_000)
        api_values.append((api_finished - started) * 1_000)
        client_values.append((finished - api_finished) * 1_000)
        total_values.append((finished - started) * 1_000)
        statements.append(timer.statements)
        sizes.append(len(response.content))
    return Measurement(
        cards, variant, 1, round(statistics.median(statements)),
        round(statistics.median(db_values), 2), round(statistics.median(api_values), 2),
        round(statistics.median(client_values), 2), round(statistics.median(total_values), 2),
        round(statistics.median(sizes)),
    )


def _explain(session_factory, deck_id):
    statements = {
        "cards": (
            "SELECT card_id, front_text, back_text, hint_text, description_text, position "
            "FROM flashcards WHERE deck_id = :deck_id ORDER BY position"
        ),
        "media": (
            "SELECT fm.card_id, fm.role, m.storage_key FROM flashcard_media fm "
            "JOIN media m ON m.id = fm.media_id WHERE fm.deck_id = :deck_id "
            "ORDER BY fm.card_id, fm.role, fm.media_id"
        ),
    }
    results = []
    with session_factory() as session:
        for name, statement in statements.items():
            payload = session.execute(text(
                "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + statement
            ), {"deck_id": deck_id}).scalar_one()
            report = payload[0]
            plan = report["Plan"]
            nodes = []

            def collect(node):
                label = node["Node Type"]
                if node.get("Index Name"):
                    label += f"[{node['Index Name']}]"
                nodes.append(label)
                for child in node.get("Plans", ()):
                    collect(child)

            collect(plan)
            results.append((
                name, " > ".join(nodes), plan.get("Actual Rows", 0),
                report.get("Execution Time", 0.0), plan.get("Shared Hit Blocks", 0),
            ))
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sizes", type=int, nargs="+", default=list(DEFAULT_SIZES))
    parser.add_argument("--repetitions", type=int, default=1)
    parser.add_argument("--explain", action="store_true")
    args = parser.parse_args()
    engine = create_engine(_database_url(), pool_pre_ping=True)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    timer = SqlTimer(engine)
    users = PostgresUserRepository(session_factory)
    sessions = PostgresSessionRepository(session_factory)
    app = create_app(
        user_repository=users, session_repository=sessions,
        content_repository=PostgresContentMetadataRepository(session_factory),
        class_repository=PostgresClassRepository(session_factory),
        learning_repository=PostgresLearningRepository(session_factory),
        content_body_repository=PostgresContentBodyRepository(session_factory),
        content_history_repository=PostgresContentHistoryRepository(session_factory),
    )
    run_prefix = f"flashcard-body-bench-{uuid.uuid4().hex[:12]}"
    results, plans = [], []
    try:
        for variant in VARIANTS:
            for count in args.sizes:
                prefix = f"{run_prefix}-{variant}-{count}"
                user_id, deck_id = _seed(
                    session_factory, prefix, count, variant == "with_media",
                )
                try:
                    token, _ = sessions.create(user_id)
                    with TestClient(app) as client:
                        results.append(_measure(
                            client, token, deck_id, timer, count, variant, args.repetitions,
                        ))
                    if args.explain and variant == "with_media" and count == max(args.sizes):
                        plans = _explain(session_factory, deck_id)
                finally:
                    _cleanup(session_factory, prefix)
    finally:
        _cleanup(session_factory, run_prefix)
        with session_factory() as session:
            remaining_decks = session.execute(text(
                "SELECT count(*) FROM flashcard_decks "
                "WHERE source_path LIKE :prefix"
            ), {"prefix": f"benchmark://flashcard-body/{run_prefix}%"}).scalar_one()
            remaining_media = session.execute(text(
                "SELECT count(*) FROM media WHERE storage_key LIKE :prefix"
            ), {"prefix": f"benchmark://flashcard-body/{run_prefix}%"}).scalar_one()
        if remaining_decks or remaining_media:
            raise RuntimeError(
                f"Synthetic cleanup failed: decks={remaining_decks}, media={remaining_media}"
            )
        engine.dispose()

    print("variant cards http sql db_ms api_ms client_ms total_ms response_bytes")
    for row in results:
        print(
            f"{row.variant:>13} {row.cards:>5} {row.http_requests:>4} {row.sql_statements:>5} "
            f"{row.db_ms:>8.2f} {row.api_ms:>8.2f} {row.client_ms:>9.2f} "
            f"{row.total_ms:>8.2f} {row.response_bytes:>14}"
        )
    if plans:
        print("\ncategory plan rows execution_ms shared_hits")
        for name, node, rows, execution_ms, shared_hits in plans:
            print(f"{name}: {node}; rows={rows}; execution_ms={execution_ms:.3f}; shared_hits={shared_hits}")
    print("synthetic_cleanup_verified=true")


if __name__ == "__main__":
    main()
