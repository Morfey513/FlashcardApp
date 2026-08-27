"""Benchmark Quiz/Flashcard Editor HTTP paths in disposable PostgreSQL only."""

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
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.api.main import create_app
from src.controllers.flashcard_editor_controller import FlashcardEditorController
from src.controllers.quiz_editor_controller import QuizEditorController
from src.logic.test_settings import normalize_test_settings
from src.storage.http_user_repository import HttpUserRepository
from src.storage.postgres_class_repository import PostgresClassRepository
from src.storage.postgres_content_body_repository import PostgresContentBodyRepository
from src.storage.postgres_content_history_repository import PostgresContentHistoryRepository
from src.storage.postgres_content_metadata_repository import PostgresContentMetadataRepository
from src.storage.postgres_learning_repository import PostgresLearningRepository
from src.storage.postgres_models import (
    ClassFlashcardDeckModel, ClassInvitationModel, ClassModel, ClassQuizModel,
    FlashcardDeckMetadataModel, FlashcardModel, QuizMetadataModel,
    QuizQuestionModel, UserModel,
)
from src.storage.postgres_session_repository import PostgresSessionRepository
from src.storage.postgres_user_repository import PostgresUserRepository

TEST_DATABASE_NAME = "study_buddy_test"
DEFAULT_SIZES = (10, 100, 1_000)


@dataclass
class Measurement:
    kind: str
    count: int
    operation: str
    http: int
    sql: int
    db_ms: float
    api_ms: float
    client_ms: float
    total_ms: float
    response_bytes: int


class Recorder:
    def __init__(self, engine):
        self.engine = engine
        self.active = False
        event.listen(engine, "before_cursor_execute", self._before)
        event.listen(engine, "after_cursor_execute", self._after)
        self.reset()

    def reset(self):
        self.sql = 0
        self.db_seconds = 0.0
        self.http = 0
        self.api_seconds = 0.0
        self.response_bytes = 0
        self.requests = []

    def _before(self, _conn, _cursor, _statement, _params, context, _many):
        if self.active:
            context._editor_benchmark_started = time.perf_counter()

    def _after(self, _conn, _cursor, _statement, _params, context, _many):
        if self.active:
            self.sql += 1
            self.db_seconds += time.perf_counter() - context._editor_benchmark_started

    def requester(self, client):
        def request(method, path, payload, headers):
            started = time.perf_counter()
            response = client.request(method, path, json=payload, headers=headers)
            elapsed = time.perf_counter() - started
            if self.active:
                self.http += 1
                self.api_seconds += elapsed
                self.response_bytes += len(response.content)
                self.requests.append((method, path, response.status_code))
            body = response.json() if response.content else None
            return response.status_code, body
        return request

    def measure(self, kind, count, operation, work):
        self.reset()
        self.active = True
        started = time.perf_counter()
        try:
            result = work()
        finally:
            finished = time.perf_counter()
            self.active = False
        if result is False or result is None:
            raise RuntimeError(f"{kind} {operation} failed: {self.requests}")
        total = finished - started
        return Measurement(
            kind, count, operation, self.http, self.sql,
            round(self.db_seconds * 1_000, 2), round(self.api_seconds * 1_000, 2),
            round(max(0.0, total - self.api_seconds) * 1_000, 2),
            round(total * 1_000, 2), self.response_bytes,
        )


def _database_url():
    value = os.getenv("STUDY_BUDDY_TEST_DATABASE_URL", "").strip()
    parsed = make_url(value) if value else None
    if parsed is None or parsed.get_backend_name() != "postgresql" or parsed.database != TEST_DATABASE_NAME:
        raise RuntimeError(f"Test URL must point to PostgreSQL {TEST_DATABASE_NAME!r}")
    return value


def _seed(session_factory, prefix, count):
    owner_id = f"{prefix}-owner"
    quiz_ids = [f"{prefix}-q-{index}" for index in range(count)]
    deck_ids = [f"{prefix}-d-{index}" for index in range(count)]
    with session_factory.begin() as session:
        session.execute(insert(UserModel), [{
            "id": owner_id, "username": f"editor_{prefix[-12:]}",
            "email": f"{prefix}@benchmark.invalid", "password_hash": "benchmark-only",
            "display_name": "Editor benchmark", "role": "teacher", "status": "active",
            "ban_reason": "",
        }])
        session.execute(insert(QuizMetadataModel), [{
            "id": value, "owner_id": owner_id, "source_owner_id": owner_id,
            "name": f"Quiz {index:05d}", "lifecycle": "published" if index == 0 else "draft",
            "visibility": "class_only" if index == 0 else "private",
            "source_path": f"benchmark://editor/{prefix}/quiz/{index}",
            "content_version": 1, "time_limit_minutes": 0,
            "passing_grade_percent": 80, "attempt_limit": 0,
            "answer_review_policy": "immediate",
        } for index, value in enumerate(quiz_ids)])
        session.execute(insert(FlashcardDeckMetadataModel), [{
            "id": value, "owner_id": owner_id, "source_owner_id": owner_id,
            "name": f"Deck {index:05d}", "lifecycle": "published" if index == 0 else "draft",
            "visibility": "class_only" if index == 0 else "private",
            "source_path": f"benchmark://editor/{prefix}/deck/{index}",
            "content_version": 1,
        } for index, value in enumerate(deck_ids)])
        session.execute(insert(QuizQuestionModel), [{
            "quiz_id": quiz_ids[0], "question_id": "question-1",
            "question_text": "Question", "question_type": "short_answer",
            "position": 0, "correct_answer": "Answer",
        }])
        session.execute(insert(FlashcardModel), [{
            "deck_id": deck_ids[0], "card_id": "card-1", "front_text": "Front",
            "back_text": "Back", "hint_text": "Hint", "description_text": "Description",
            "position": 0,
        }])
        class_rows, quiz_links, deck_links, invitation_rows = [], [], [], []
        for label, content_ids, links, field in (
            ("q", quiz_ids, quiz_links, "quiz_id"),
            ("d", deck_ids, deck_links, "deck_id"),
        ):
            for index, content_id in enumerate(content_ids):
                class_id = f"{prefix}-c-{label}-{index}"
                class_rows.append({
                    "id": class_id, "owner_id": owner_id,
                    "name": f"Editor {label} {index:05d}", "status": "active",
                })
                links.append({"class_id": class_id, field: content_id})
                code = uuid.uuid5(uuid.NAMESPACE_URL, class_id).hex[:12].upper()
                invitation_rows.append({
                    "id": str(uuid.uuid4()), "class_id": class_id,
                    "created_by": owner_id, "display_code": code,
                    "normalized_code": code, "status": "active",
                })
        session.execute(insert(ClassModel), class_rows)
        session.execute(insert(ClassQuizModel), quiz_links)
        session.execute(insert(ClassFlashcardDeckModel), deck_links)
        session.execute(insert(ClassInvitationModel), invitation_rows)
    return owner_id


def _cleanup(session_factory, prefix):
    with session_factory.begin() as session:
        session.execute(delete(QuizMetadataModel).where(
            QuizMetadataModel.source_path.like(f"benchmark://editor/{prefix}%")
        ))
        session.execute(delete(FlashcardDeckMetadataModel).where(
            FlashcardDeckMetadataModel.source_path.like(f"benchmark://editor/{prefix}%")
        ))
        session.execute(delete(ClassModel).where(ClassModel.id.like(f"{prefix}-c-%")))
        session.execute(delete(UserModel).where(UserModel.id == f"{prefix}-owner"))


def _run_kind(kind, count, client, token, user_data, recorder):
    user = HttpUserRepository(
        base_url="http://testserver", requester=recorder.requester(client),
    )
    user._token = token
    user._current_user = dict(user_data)
    user._content_metadata_cache = {}
    user._owned_classes_cache = {}
    controller = (
        QuizEditorController(user_data["id"], "teacher", user_repository=user)
        if kind == "quiz" else
        FlashcardEditorController(user_data["id"], "teacher", user_repository=user)
    )
    entries = controller.get_quiz_entries if kind == "quiz" else controller.get_deck_entries
    load = controller.load_quiz if kind == "quiz" else controller.load_deck
    name = "Quiz 00000" if kind == "quiz" else "Deck 00000"
    work_name = "Quiz 00001" if kind == "quiz" else "Deck 00001"
    results = [recorder.measure(kind, count, "open_list", entries)]

    def open_item():
        if not load(name):
            return False
        moderation = controller.get_current_moderation()
        if kind == "quiz":
            controller.get_current_test_settings()
        code = controller.get_current_invite_code()
        return bool(moderation and code)
    results.append(recorder.measure(kind, count, "open_item", open_item))

    # Save/copy a private draft. Published teacher-owned Quiz metadata cannot
    # currently be re-saved before its lifecycle transition; that behavior is
    # audited separately rather than contaminating the performance baseline.
    if not load(work_name):
        raise RuntimeError(f"Could not prepare {kind} draft for save")

    if kind == "quiz":
        save = lambda: controller.save_quiz(
            controller.current_questions,
            {row["id"] for row in controller.current_questions},
            "class_only", normalize_test_settings(),
        )
        copy_work = lambda: controller.copy_quiz(work_name, f"{work_name} Copy")
        delete_work = lambda: controller.delete_quiz_result(f"{work_name} Copy")["status"] == "deleted"
    else:
        save = lambda: controller.save_deck(controller.current_cards, "class_only")
        copy_work = lambda: controller.copy_deck(work_name, f"{work_name} Copy")
        delete_work = lambda: controller.delete_deck_result(f"{work_name} Copy")["status"] == "deleted"
    results.append(recorder.measure(kind, count, "save", save))
    results.append(recorder.measure(kind, count, "copy", copy_work))
    results.append(recorder.measure(kind, count + 1, "delete_copy", delete_work))
    if not load(name):
        raise RuntimeError(f"Could not restore {kind} class content")
    results.append(recorder.measure(
        kind, count, "rotate_invite", controller.generate_or_rotate_invite_code,
    ))
    return results


def _explain(session_factory, owner_id, kind):
    table = "quizzes" if kind == "quiz" else "flashcard_decks"
    link_table = "class_quizzes" if kind == "quiz" else "class_flashcard_decks"
    link_field = "quiz_id" if kind == "quiz" else "deck_id"
    content_id = f"{owner_id.removesuffix('-owner')}-{'q' if kind == 'quiz' else 'd'}-0"
    class_id = f"{owner_id.removesuffix('-owner')}-c-{'q' if kind == 'quiz' else 'd'}-0"
    statements = {
        "metadata_catalog": (
            f"SELECT * FROM {table} ORDER BY name, id", {}
        ),
        "class_link": (
            f"SELECT * FROM {link_table} WHERE {link_field} = :content_id",
            {"content_id": content_id},
        ),
        "invitation": (
            "SELECT * FROM class_invitations WHERE class_id = :class_id "
            "AND status = 'active'", {"class_id": class_id},
        ),
    }
    results = []
    with session_factory() as session:
        for category, (statement, params) in statements.items():
            payload = session.execute(text(
                "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + statement
            ), params).scalar_one()[0]
            plan = payload["Plan"]
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
                kind, category, " > ".join(nodes),
                plan.get("Actual Rows", 0), payload["Execution Time"],
            ))
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sizes", type=int, nargs="+", default=list(DEFAULT_SIZES))
    parser.add_argument("--explain", action="store_true")
    args = parser.parse_args()
    os.environ["STUDY_BUDDY_STORAGE"] = "api"
    engine = create_engine(_database_url(), pool_pre_ping=True)
    sessions_factory = sessionmaker(bind=engine, expire_on_commit=False)
    recorder = Recorder(engine)
    users = PostgresUserRepository(sessions_factory)
    session_repo = PostgresSessionRepository(sessions_factory)
    app = create_app(
        user_repository=users, session_repository=session_repo,
        content_repository=PostgresContentMetadataRepository(sessions_factory),
        class_repository=PostgresClassRepository(sessions_factory),
        learning_repository=PostgresLearningRepository(sessions_factory),
        content_body_repository=PostgresContentBodyRepository(sessions_factory),
        content_history_repository=PostgresContentHistoryRepository(sessions_factory),
    )
    run_prefix = f"editor-bench-{uuid.uuid4().hex[:10]}"
    results, plans = [], []
    try:
        for count in args.sizes:
            prefix = f"{run_prefix}-{count}"
            owner_id = _seed(sessions_factory, prefix, count)
            try:
                token, _ = session_repo.create(owner_id)
                user_data = users.get_user_by_id(owner_id)
                with TestClient(app) as client:
                    for kind in ("quiz", "flashcard"):
                        results.extend(_run_kind(
                            kind, count, client, token, user_data, recorder,
                        ))
                if args.explain and count == max(args.sizes):
                    for kind in ("quiz", "flashcard"):
                        plans.extend(_explain(sessions_factory, owner_id, kind))
            finally:
                _cleanup(sessions_factory, prefix)
    finally:
        _cleanup(sessions_factory, run_prefix)
        with sessions_factory() as session:
            remaining = session.execute(text(
                "SELECT (SELECT count(*) FROM quizzes WHERE source_path LIKE :value) + "
                "(SELECT count(*) FROM flashcard_decks WHERE source_path LIKE :value)"
            ), {"value": f"benchmark://editor/{run_prefix}%"}).scalar_one()
        engine.dispose()
    if remaining:
        raise RuntimeError(f"Synthetic cleanup failed: content={remaining}")

    print("kind dataset operation http sql db_ms api_ms client_ms total_ms response_bytes")
    for row in results:
        print(f"{row.kind:>9} {row.count:>7} {row.operation:>13} {row.http:>4} {row.sql:>4} "
              f"{row.db_ms:>8.2f} {row.api_ms:>8.2f} {row.client_ms:>9.2f} "
              f"{row.total_ms:>8.2f} {row.response_bytes:>14}")
    for kind, category, node, rows, execution in plans:
        print(f"plan {kind}.{category}: {node}; rows={rows}; execution_ms={execution:.3f}")
    print("synthetic_cleanup_verified=true")


if __name__ == "__main__":
    main()
