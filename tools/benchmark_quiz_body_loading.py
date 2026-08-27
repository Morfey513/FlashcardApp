"""Benchmark authenticated PostgreSQL quiz-body loading without production data.

Only the disposable ``study_buddy_test`` database is accepted. Every row uses
a run-specific prefix and cleanup runs both per-size and from the outer finally.
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
    MatchingPairModel, MediaModel, QuestionMediaModel, QuestionOptionModel,
    QuizMetadataModel, QuizQuestionModel, ShortAnswerVariantModel, UserModel,
)
from src.storage.postgres_session_repository import PostgresSessionRepository
from src.storage.postgres_user_repository import PostgresUserRepository


TEST_DATABASE_NAME = "study_buddy_test"
DEFAULT_SIZES = (10, 100, 1_000)


@dataclass
class Measurement:
    questions: int
    repetitions: int
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
        context._quiz_body_benchmark_started = time.perf_counter()

    def _after(self, _conn, _cursor, _statement, _params, context, _many):
        self.statements += 1
        self.elapsed += time.perf_counter() - context._quiz_body_benchmark_started

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


def _seed(session_factory, prefix: str, question_count: int):
    user_id = f"{prefix}-student"
    quiz_id = f"{prefix}-quiz"
    with session_factory.begin() as session:
        session.execute(insert(UserModel), [{
            "id": user_id, "username": f"quizbench_{prefix[-12:]}",
            "email": f"{prefix}@benchmark.invalid", "password_hash": "benchmark-only",
            "display_name": "Quiz benchmark", "role": "student", "status": "active",
            "ban_reason": "",
        }])
        session.execute(insert(QuizMetadataModel), [{
            "id": quiz_id, "owner_id": None, "source_owner_id": "benchmark",
            "name": f"Quiz benchmark {question_count}", "lifecycle": "published",
            "visibility": "public", "source_path": f"benchmark://quiz-body/{prefix}",
            "content_version": 1, "time_limit_minutes": 0,
            "passing_grade_percent": 80, "attempt_limit": 1,
            "answer_review_policy": "immediate",
        }])

        types = ("single_choice", "multiple_choice", "true_false", "short_answer", "matching", "ordering")
        questions = []
        options = []
        pairs = []
        variants = []
        media = []
        attachments = []
        for position in range(question_count):
            question_type = types[position % len(types)]
            question_id = f"q{position}"
            answer = {
                "single_choice": "B", "multiple_choice": ["A", "C"],
                "true_false": True, "short_answer": ["answer", "alternate"],
                "matching": [{"prompt": "P1", "answer": "A1"},
                             {"prompt": "P2", "answer": "A2"}],
                "ordering": ["first", "second", "third"],
            }[question_type]
            questions.append({
                "quiz_id": quiz_id, "question_id": question_id,
                "question_text": f"Benchmark question {position}",
                "question_type": question_type, "position": position,
                "correct_answer": answer,
            })
            if question_type in {"single_choice", "multiple_choice"}:
                for option_position, value in enumerate(("A", "B", "C", "D")):
                    options.append({
                        "quiz_id": quiz_id, "question_id": question_id,
                        "position": option_position, "option_text": value,
                        "is_correct": value in (answer if isinstance(answer, list) else [answer]),
                    })
            elif question_type == "ordering":
                for option_position, value in enumerate(answer):
                    options.append({
                        "quiz_id": quiz_id, "question_id": question_id,
                        "position": option_position, "option_text": value,
                        "is_correct": True,
                    })
            elif question_type == "matching":
                for pair_position, pair in enumerate(answer):
                    pairs.append({
                        "quiz_id": quiz_id, "question_id": question_id,
                        "position": pair_position, **pair,
                    })
            elif question_type == "short_answer":
                for variant_position, value in enumerate(answer):
                    variants.append({
                        "quiz_id": quiz_id, "question_id": question_id,
                        "position": variant_position, "answer_text": value,
                    })
            if position % 10 == 0:
                media_id = f"{prefix}-media-{position}"
                media.append({
                    "id": media_id, "owner_id": None,
                    "storage_key": f"benchmark://quiz-body/{prefix}/{position}.png",
                    "original_filename": f"{position}.png", "media_type": "image",
                    "mime_type": "image/png", "size_bytes": 128,
                })
                attachments.append({
                    "quiz_id": quiz_id, "question_id": question_id,
                    "media_id": media_id, "role": "image",
                })
        session.execute(insert(QuizQuestionModel), questions)
        if options:
            session.execute(insert(QuestionOptionModel), options)
        if pairs:
            session.execute(insert(MatchingPairModel), pairs)
        if variants:
            session.execute(insert(ShortAnswerVariantModel), variants)
        if media:
            session.execute(insert(MediaModel), media)
            session.execute(insert(QuestionMediaModel), attachments)
    return user_id, quiz_id


def _cleanup(session_factory, prefix: str):
    with session_factory.begin() as session:
        session.execute(delete(QuizMetadataModel).where(
            QuizMetadataModel.source_path.like(f"benchmark://quiz-body/{prefix}%")
        ))
        session.execute(delete(MediaModel).where(
            MediaModel.storage_key.like(f"benchmark://quiz-body/{prefix}/%")
        ))
        session.execute(delete(UserModel).where(UserModel.id.like(f"{prefix}-%")))


def _measure(client, token, quiz_id, timer, questions, repetitions):
    db_values, api_values, client_values, total_values = [], [], [], []
    statements, sizes = [], []
    for _ in range(repetitions):
        timer.reset()
        started = time.perf_counter()
        response = client.get(
            f"/api/v1/content/bodies/quiz/{quiz_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        api_finished = time.perf_counter()
        response.raise_for_status()
        body = response.json()
        finished = time.perf_counter()
        assert len(body["questions"]) == questions
        db_values.append(timer.elapsed * 1_000)
        api_values.append((api_finished - started) * 1_000)
        client_values.append((finished - api_finished) * 1_000)
        total_values.append((finished - started) * 1_000)
        statements.append(timer.statements)
        sizes.append(len(response.content))
    return Measurement(
        questions=questions, repetitions=repetitions, http_requests=1,
        sql_statements=round(statistics.median(statements)),
        db_ms=round(statistics.median(db_values), 2),
        api_ms=round(statistics.median(api_values), 2),
        client_ms=round(statistics.median(client_values), 2),
        total_ms=round(statistics.median(total_values), 2),
        response_bytes=round(statistics.median(sizes)),
    )


def _explain(session_factory, quiz_id):
    statements = {
        "questions": (
            "SELECT question_id, question_text, question_type, position, correct_answer "
            "FROM quiz_questions WHERE quiz_id = :quiz_id ORDER BY position"
        ),
        "options": (
            "SELECT question_id, position, option_text, is_correct FROM question_options "
            "WHERE quiz_id = :quiz_id ORDER BY question_id, position"
        ),
        "pairs": (
            "SELECT question_id, position, prompt, answer FROM matching_pairs "
            "WHERE quiz_id = :quiz_id ORDER BY question_id, position"
        ),
        "variants": (
            "SELECT question_id, position, answer_text FROM short_answer_variants "
            "WHERE quiz_id = :quiz_id ORDER BY question_id, position"
        ),
        "media": (
            "SELECT qm.question_id, m.storage_key FROM question_media qm "
            "JOIN media m ON m.id = qm.media_id "
            "WHERE qm.quiz_id = :quiz_id AND qm.role = 'image' "
            "ORDER BY qm.question_id, qm.media_id"
        ),
    }
    results = []
    with session_factory() as session:
        for name, statement in statements.items():
            payload = session.execute(text(
                "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + statement
            ), {"quiz_id": quiz_id}).scalar_one()
            report = payload[0]
            plan = report["Plan"]
            results.append((
                name, plan["Node Type"], plan.get("Actual Rows", 0),
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
    run_prefix = f"quiz-body-bench-{uuid.uuid4().hex[:12]}"
    results = []
    plans = []
    try:
        for count in args.sizes:
            prefix = f"{run_prefix}-{count}"
            user_id, quiz_id = _seed(session_factory, prefix, count)
            try:
                token, _ = sessions.create(user_id)
                with TestClient(app) as client:
                    results.append(_measure(
                        client, token, quiz_id, timer, count, args.repetitions,
                    ))
                if args.explain and count == max(args.sizes):
                    plans = _explain(session_factory, quiz_id)
            finally:
                _cleanup(session_factory, prefix)
    finally:
        for count in args.sizes:
            _cleanup(session_factory, f"{run_prefix}-{count}")
        engine.dispose()

    print("questions http sql db_ms api_ms client_ms total_ms response_bytes")
    for row in results:
        print(
            f"{row.questions:>9} {row.http_requests:>4} {row.sql_statements:>3} "
            f"{row.db_ms:>8.2f} {row.api_ms:>8.2f} {row.client_ms:>9.2f} "
            f"{row.total_ms:>8.2f} {row.response_bytes:>14}"
        )
    if plans:
        print("\ncategory node rows execution_ms shared_hits")
        for name, node, rows, execution_ms, shared_hits in plans:
            print(
                f"{name:>10} {node:>20} {rows:>6} {execution_ms:>12.3f} "
                f"{shared_hits:>11}"
            )


if __name__ == "__main__":
    main()
