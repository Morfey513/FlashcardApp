"""PostgreSQL persistence for authenticated learning progress and quiz attempts."""

import logging
from datetime import datetime, timezone
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import delete, select
from sqlalchemy.exc import SQLAlchemyError

from src.storage.database import create_session_factory
from src.storage.postgres_models import (
    FlashcardDeckMetadataModel,
    FlashcardProgressModel,
    QuizAttemptAnswerModel,
    QuizAttemptModel,
    QuizMetadataModel,
    QuizQuestionProgressModel,
    UserModel,
)

logger = logging.getLogger(__name__)


class PostgresLearningRepository:
    """Stores server-owned learning state; guest state intentionally remains local."""

    def __init__(self, session_factory=None):
        self.session_factory = session_factory or create_session_factory()

    def import_flashcard_progress(self, deck_id: str, user_id: str, progress: dict) -> bool:
        return self._replace_progress(
            FlashcardProgressModel, FlashcardDeckMetadataModel,
            "deck_id", str(deck_id), str(user_id), progress, "card_id",
        )

    def import_quiz_progress(self, quiz_id: str, user_id: str, progress: dict) -> bool:
        return self._replace_progress(
            QuizQuestionProgressModel, QuizMetadataModel,
            "quiz_id", str(quiz_id), str(user_id), progress, "question_id",
        )

    def get_flashcard_progress(self, deck_id: str, user_id: str) -> dict:
        return self._get_progress(
            FlashcardProgressModel, "deck_id", str(deck_id), str(user_id), "card_id"
        )

    def get_quiz_progress(self, quiz_id: str, user_id: str) -> dict:
        return self._get_progress(
            QuizQuestionProgressModel, "quiz_id", str(quiz_id), str(user_id), "question_id"
        )

    def import_quiz_attempt(self, source: dict) -> bool:
        attempt_id = str(source.get("id", "")).strip()
        user_id = str(source.get("user_id", "")).strip()
        quiz_id = str(source.get("quiz_id", "")).strip()
        if not attempt_id or not quiz_id or not self._authenticated_user(user_id):
            return False
        try:
            with self.session_factory.begin() as session:
                if session.get(UserModel, user_id) is None or session.get(QuizMetadataModel, quiz_id) is None:
                    return False
                attempt = session.get(QuizAttemptModel, attempt_id)
                if attempt is None:
                    attempt = QuizAttemptModel(id=attempt_id, user_id=user_id, quiz_id=quiz_id)
                    session.add(attempt)
                attempt.user_id = user_id
                attempt.quiz_id = quiz_id
                attempt.mode = str(source.get("mode") or "test")
                attempt.status = self._attempt_status(source)
                attempt.started_at = self._datetime(source.get("started_at"), required=True)
                attempt.last_activity_at = self._datetime(source.get("last_activity_at"))
                attempt.submitted_at = self._datetime(source.get("submitted_at"))
                attempt.interrupted_at = self._datetime(source.get("interrupted_at"))
                attempt.score = self._integer(source.get("score"))
                attempt.total = self._integer(source.get("total"))
                attempt.percentage = float(source.get("percentage") or 0.0)
                attempt.passing_grade_percent = self._optional_integer(source.get("passing_grade_percent"))
                attempt.passed = source.get("passed") if isinstance(source.get("passed"), bool) else None
                attempt.attempt_number = max(1, self._integer(source.get("attempt_number"), 1))
                attempt.counts_toward_limit = bool(source.get("counts_toward_limit", True))
                attempt.duration_seconds = self._optional_integer(source.get("duration_seconds"))
                attempt.current_question = self._optional_integer(source.get("current_question"))
                attempt.answered_count = self._optional_integer(source.get("answered_count"))
                resolved_by = str(source.get("resolved_by") or "").strip() or None
                attempt.resolved_by = resolved_by if resolved_by and session.get(UserModel, resolved_by) else None
                attempt.resolved_at = self._datetime(source.get("resolved_at"))
                attempt.resolution = str(source.get("resolution") or "").strip() or None

                session.execute(delete(QuizAttemptAnswerModel).where(
                    QuizAttemptAnswerModel.attempt_id == attempt_id
                ))
                for position, answer in enumerate(source.get("answers") or []):
                    if not isinstance(answer, dict):
                        continue
                    session.add(QuizAttemptAnswerModel(
                        id=str(uuid5(NAMESPACE_URL, f"study-buddy:{attempt_id}:{position}")),
                        attempt_id=attempt_id,
                        question_id=str(answer.get("question_id") or f"position-{position}"),
                        position=position,
                        question_text=str(answer.get("question") or ""),
                        question_type=str(answer.get("type") or ""),
                        user_answer=answer.get("user_answer"),
                        correct_answer=answer.get("correct_answer"),
                        is_correct=answer.get("is_correct") if isinstance(answer.get("is_correct"), bool) else None,
                        response_seconds=self._optional_float(answer.get("response_seconds")),
                    ))
                return True
        except (SQLAlchemyError, ValueError, TypeError) as exc:
            logger.error("Could not import quiz attempt '%s': %s", attempt_id, exc)
            return False

    def get_quiz_attempts(self, quiz_id: str, user_id: str | None = None) -> list[dict]:
        try:
            with self.session_factory() as session:
                statement = select(QuizAttemptModel).where(QuizAttemptModel.quiz_id == str(quiz_id))
                if user_id is not None:
                    statement = statement.where(QuizAttemptModel.user_id == str(user_id))
                attempts = session.scalars(statement.order_by(QuizAttemptModel.started_at)).all()
                return [self._attempt_public(session, attempt) for attempt in attempts]
        except SQLAlchemyError as exc:
            logger.error("Could not load attempts for quiz '%s': %s", quiz_id, exc)
            return []

    def get_quiz_attempt(self, attempt_id: str) -> dict | None:
        """Load one attempt without applying a user filter for API ownership checks."""
        with self.session_factory() as session:
            attempt = session.get(QuizAttemptModel, str(attempt_id))
            return self._attempt_public(session, attempt) if attempt is not None else None

    def assessment_summary(self, quiz_id: str, user_id: str) -> dict:
        attempts = [
            attempt for attempt in self.get_quiz_attempts(quiz_id, user_id)
            if attempt["status"] in {"submitted", "timed_out", "marked_zero"}
            and attempt["counts_toward_limit"]
        ]
        percentages = [attempt["percentage"] for attempt in attempts]
        return {
            "attempts_used": len(attempts),
            "best_percentage": max(percentages) if percentages else None,
            "average_percentage": round(sum(percentages) / len(percentages), 1) if percentages else None,
            "latest_status": attempts[-1]["status"] if attempts else "not_started",
        }

    def delete_progress(self, kind: str, content_id: str, user_id: str) -> bool:
        model, field = self._progress_model(kind)
        try:
            with self.session_factory.begin() as session:
                result = session.execute(delete(model).where(
                    model.user_id == str(user_id),
                    getattr(model, field) == str(content_id),
                ))
                return bool(result.rowcount)
        except (SQLAlchemyError, ValueError) as exc:
            logger.error("Could not delete %s progress '%s': %s", kind, content_id, exc)
            return False

    def clear_user_progress(self, kind: str, user_id: str) -> int:
        model, _field = self._progress_model(kind)
        try:
            with self.session_factory.begin() as session:
                result = session.execute(delete(model).where(
                    model.user_id == str(user_id)
                ))
                return int(result.rowcount or 0)
        except (SQLAlchemyError, ValueError) as exc:
            logger.error("Could not clear %s progress for '%s': %s", kind, user_id, exc)
            return 0

    def resolve_attempt(self, quiz_id: str, attempt_id: str, action: str, actor_id: str):
        attempts = self.get_quiz_attempts(quiz_id)
        attempt = next((row for row in attempts if row["id"] == str(attempt_id)), None)
        if not attempt or attempt.get("status") not in {"in_progress", "abandoned"}:
            return None
        now = datetime.now(timezone.utc).isoformat()
        if action == "refund":
            attempt.update({
                "status": "refunded", "counts_toward_limit": False,
                "resolved_by": str(actor_id), "resolved_at": now,
                "resolution": action,
            })
        elif action in {"submit_current", "mark_zero"}:
            total = max(0, self._integer(attempt.get("total")))
            score = 0 if action == "mark_zero" else sum(
                1 for answer in attempt.get("answers", [])
                if answer.get("is_correct") is True
            )
            percentage = round((score / total) * 100, 1) if total else 0.0
            passing = attempt.get("passing_grade_percent")
            attempt.update({
                "status": "marked_zero" if action == "mark_zero" else "submitted",
                "submitted_at": now, "score": score, "percentage": percentage,
                "passed": percentage >= passing if passing is not None else None,
                "counts_toward_limit": True, "resolved_by": str(actor_id),
                "resolved_at": now, "resolution": action,
            })
        else:
            return None
        return attempt if self.import_quiz_attempt(attempt) else None

    def _replace_progress(self, model, content_model, content_field, content_id,
                          user_id, progress, item_field):
        if not self._authenticated_user(user_id) or not isinstance(progress, dict):
            return False
        try:
            with self.session_factory.begin() as session:
                if session.get(UserModel, user_id) is None or session.get(content_model, content_id) is None:
                    return False
                session.execute(delete(model).where(
                    model.user_id == user_id, getattr(model, content_field) == content_id
                ))
                for item_id, stats in progress.items():
                    if not isinstance(stats, dict):
                        continue
                    values = {
                        "user_id": user_id, content_field: content_id, item_field: str(item_id),
                        "correct_count": self._integer(stats.get("correct")),
                        "wrong_count": self._integer(stats.get("wrong")),
                        "mastered": bool(stats.get("mastered", False)),
                    }
                    session.add(model(**values))
                return True
        except (SQLAlchemyError, ValueError, TypeError) as exc:
            logger.error("Could not import progress for '%s': %s", content_id, exc)
            return False

    def _get_progress(self, model, content_field, content_id, user_id, item_field):
        if not self._authenticated_user(user_id):
            return {}
        try:
            with self.session_factory() as session:
                rows = session.scalars(select(model).where(
                    model.user_id == user_id, getattr(model, content_field) == content_id
                )).all()
                return {
                    str(getattr(row, item_field)): {
                        "correct": row.correct_count, "wrong": row.wrong_count,
                        "mastered": row.mastered,
                    }
                    for row in rows
                }
        except SQLAlchemyError as exc:
            logger.error("Could not load progress for '%s': %s", content_id, exc)
            return {}

    @staticmethod
    def _attempt_public(session, attempt):
        answers = session.scalars(select(QuizAttemptAnswerModel).where(
            QuizAttemptAnswerModel.attempt_id == attempt.id
        ).order_by(QuizAttemptAnswerModel.position)).all()
        return {
            "id": attempt.id, "quiz_id": attempt.quiz_id, "user_id": attempt.user_id,
            "mode": attempt.mode, "status": attempt.status,
            "started_at": attempt.started_at.isoformat(),
            "last_activity_at": attempt.last_activity_at.isoformat() if attempt.last_activity_at else None,
            "submitted_at": attempt.submitted_at.isoformat() if attempt.submitted_at else None,
            "interrupted_at": attempt.interrupted_at.isoformat() if attempt.interrupted_at else None,
            "score": attempt.score, "total": attempt.total,
            "percentage": attempt.percentage,
            "passing_grade_percent": attempt.passing_grade_percent,
            "passed": attempt.passed,
            "attempt_number": attempt.attempt_number,
            "counts_toward_limit": attempt.counts_toward_limit,
            "duration_seconds": attempt.duration_seconds,
            "current_question": attempt.current_question,
            "answered_count": attempt.answered_count,
            "resolved_by": attempt.resolved_by,
            "resolved_at": attempt.resolved_at.isoformat() if attempt.resolved_at else None,
            "resolution": attempt.resolution,
            "answers": [{
                "question_id": answer.question_id, "question": answer.question_text,
                "type": answer.question_type, "user_answer": answer.user_answer,
                "correct_answer": answer.correct_answer, "is_correct": answer.is_correct,
                "response_seconds": answer.response_seconds,
            } for answer in answers],
        }

    @staticmethod
    def _authenticated_user(user_id):
        return bool(user_id and user_id.casefold() != "guest")

    @staticmethod
    def _progress_model(kind):
        normalized = str(kind).casefold()
        if normalized == "quiz":
            return QuizQuestionProgressModel, "quiz_id"
        if normalized in {"flashcard", "deck", "flashcard_deck"}:
            return FlashcardProgressModel, "deck_id"
        raise ValueError(f"Unsupported learning kind: {kind!r}")

    @staticmethod
    def _attempt_status(source):
        status = str(source.get("status") or "").strip()
        if status:
            allowed = {
                "in_progress", "abandoned", "submitted", "timed_out",
                "marked_zero", "refunded",
            }
            if status not in allowed:
                raise ValueError(f"Unsupported attempt status: {status}")
            return status
        return "submitted" if source.get("submitted_at") else "in_progress"

    @staticmethod
    def _datetime(value, required=False):
        if isinstance(value, datetime):
            return value
        if value:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if required:
            return datetime.now(timezone.utc)
        return None

    @staticmethod
    def _integer(value, default=0):
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @classmethod
    def _optional_integer(cls, value):
        return None if value is None or value == "" else cls._integer(value)

    @staticmethod
    def _optional_float(value):
        try:
            return None if value is None or value == "" else float(value)
        except (TypeError, ValueError):
            return None
