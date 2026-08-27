"""PostgreSQL persistence for authenticated learning progress and quiz attempts."""

import logging
import random
from datetime import datetime, timezone
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import and_, delete, func, literal, or_, select, union_all
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from src.storage.database import create_session_factory
from src.storage.postgres_models import (
    FlashcardDeckMetadataModel,
    FlashcardModel,
    FlashcardProgressModel,
    ClassFlashcardDeckModel,
    ClassMemberModel,
    ClassQuizModel,
    QuizAttemptAnswerModel,
    QuizAttemptModel,
    QuizAttemptQuestionModel,
    QuizMetadataModel,
    QuizQuestionModel,
    QuizQuestionProgressModel,
    UserModel,
)

logger = logging.getLogger(__name__)


class PostgresLearningRepository:
    """Stores server-owned learning state; guest state intentionally remains local."""

    def __init__(self, session_factory=None):
        self.session_factory = session_factory or create_session_factory()

    def start_assessment(self, user_id, quiz, settings, questions):
        """Create or resume one frozen, server-authoritative assessment."""
        import uuid
        from sqlalchemy import and_
        user_id, quiz_id = str(user_id), str(quiz.get("id"))
        now = datetime.now(timezone.utc)
        deadline = None
        if settings.get("time_limit_minutes"):
            from datetime import timedelta
            deadline = (now + timedelta(minutes=settings["time_limit_minutes"])).isoformat()
        snapshot = {"version": 1, **settings, "question_count": len(questions), "started_at": now.isoformat(), "deadline_at": deadline}
        try:
            with self.session_factory.begin() as session:
                existing = session.scalars(select(QuizAttemptModel).where(
                    QuizAttemptModel.user_id == user_id,
                    QuizAttemptModel.quiz_id == quiz_id,
                    QuizAttemptModel.assessment_snapshot.is_not(None),
                    QuizAttemptModel.status.in_(["in_progress", "abandoned"]),
                ).order_by(QuizAttemptModel.started_at.desc())).first()
                if existing:
                    return self._assessment_public(session, existing)
                completed = session.scalars(select(QuizAttemptModel).where(
                    QuizAttemptModel.user_id == user_id, QuizAttemptModel.quiz_id == quiz_id,
                    QuizAttemptModel.assessment_snapshot.is_not(None),
                    QuizAttemptModel.status.in_(["submitted", "timed_out", "marked_zero"]),
                    QuizAttemptModel.counts_toward_limit.is_(True),
                )).all()
                if settings.get("attempt_limit", 0) and len(completed) >= settings["attempt_limit"]:
                    return None
                attempt = QuizAttemptModel(id=str(uuid.uuid4()), user_id=user_id, quiz_id=quiz_id,
                    mode="assessment", status="in_progress", started_at=now,
                    last_activity_at=now, total=len(questions), attempt_number=1,
                    passing_grade_percent=settings.get("passing_grade_percent"), assessment_snapshot=snapshot)
                session.add(attempt)
                session.flush()
                # The presentation is randomized exactly once, before it is
                # persisted. Resume reads these rows and never reruns this.
                frozen_questions = list(questions)
                random.shuffle(frozen_questions)
                for position, question in enumerate(frozen_questions):
                    answer = question.get("answer")
                    if question.get("type") == "matching":
                        answer = {str(pair.get("prompt")): pair.get("answer") for pair in question.get("pairs", [])}
                    presentation = {k: question.get(k) for k in ("id", "question", "type", "choices", "has_image", "image_path", "media") if k in question}
                    if isinstance(presentation.get("choices"), list):
                        presentation["choices"] = list(presentation["choices"])
                        random.shuffle(presentation["choices"])
                    if question.get("type") == "matching":
                        pairs = question.get("pairs") or []
                        presentation["pairs"] = [{"prompt": pair.get("prompt"), "answer": None} for pair in pairs]
                        presentation["right_options"] = list(question.get("right_options") or [pair.get("answer") for pair in pairs])
                        random.shuffle(presentation["right_options"])
                    if question.get("type") == "ordering":
                        # Ordering bodies persist their canonical order under
                        # ``answer`` (choices are derived from it by the
                        # content repository).  Freeze the complete set of
                        # selectable items at attempt creation time; never
                        # reconstruct it from live question rows on resume.
                        presentation["items"] = list(
                            question.get("items")
                            or question.get("choices")
                            or question.get("answer")
                            or []
                        )
                        random.shuffle(presentation["items"])
                    if question.get("type") == "true_false":
                        presentation["choices"] = list(question.get("choices") or [True, False])
                    grading = {"type": question.get("type"), "answer": answer}
                    session.add(QuizAttemptQuestionModel(attempt_id=attempt.id, position=position,
                        question_id=str(question.get("id")), presentation_json=presentation, grading_key_json=grading))
                return self._assessment_public(session, attempt)
        except SQLAlchemyError as exc:
            logger.error("Could not start assessment: %s", exc)
            if isinstance(exc, IntegrityError):
                with self.session_factory() as session:
                    existing = session.scalars(select(QuizAttemptModel).where(
                        QuizAttemptModel.user_id == user_id, QuizAttemptModel.quiz_id == quiz_id,
                        QuizAttemptModel.assessment_snapshot.is_not(None),
                        QuizAttemptModel.status.in_(["in_progress", "abandoned"]),
                    ).order_by(QuizAttemptModel.started_at.desc())).first()
                    if existing:
                        return self._assessment_public(session, existing)
            return None

    def get_assessment(self, user_id, attempt_id):
        with self.session_factory() as session:
            attempt = session.get(QuizAttemptModel, str(attempt_id))
            if not attempt or attempt.user_id != str(user_id) or attempt.assessment_snapshot is None:
                return None
            if attempt.status in {"submitted", "timed_out", "marked_zero"}:
                return self._assessment_result(session, attempt)
            return self._assessment_public(session, attempt)

    def checkpoint_assessment(self, user_id, attempt_id, position, response):
        try:
            with self.session_factory.begin() as session:
                attempt = session.scalar(select(QuizAttemptModel).where(
                    QuizAttemptModel.id == str(attempt_id),
                    QuizAttemptModel.user_id == str(user_id),
                ).with_for_update())
                if not attempt or attempt.assessment_snapshot is None or attempt.status != "in_progress":
                    return None
                deadline = (attempt.assessment_snapshot or {}).get("deadline_at")
                if deadline:
                    try:
                        expires = datetime.fromisoformat(str(deadline).replace("Z", "+00:00"))
                        if expires.tzinfo is None: expires = expires.replace(tzinfo=timezone.utc)
                        if datetime.now(timezone.utc) >= expires:
                            return self._finalize_assessment(session, attempt, timed_out=True)
                    except ValueError:
                        pass
                frozen = session.scalar(select(QuizAttemptQuestionModel).where(
                    QuizAttemptQuestionModel.attempt_id == attempt.id, QuizAttemptQuestionModel.position == int(position)))
                if frozen is None:
                    return None
                answer_id = str(uuid5(NAMESPACE_URL, f"study-buddy:{attempt.id}:{position}"))
                current = session.get(QuizAttemptAnswerModel, answer_id)
                if current is None:
                    current = QuizAttemptAnswerModel(id=answer_id, attempt_id=attempt.id, question_id=frozen.question_id, position=position, question_text=(frozen.presentation_json or {}).get("question", ""), question_type=(frozen.grading_key_json or {}).get("type", ""))
                    session.add(current)
                current.user_answer = response
                attempt.last_activity_at = datetime.now(timezone.utc)
                return {"attempt_id": attempt.id, "position": int(position), "saved": True}
        except (SQLAlchemyError, ValueError, TypeError):
            return None

    def submit_assessment(self, user_id, attempt_id, responses=None, timed_out=False):
        try:
            with self.session_factory.begin() as session:
                attempt = session.scalar(select(QuizAttemptModel).where(
                    QuizAttemptModel.id == str(attempt_id),
                    QuizAttemptModel.user_id == str(user_id),
                ).with_for_update())
                if not attempt or attempt.assessment_snapshot is None or attempt.status != "in_progress":
                    return None
                deadline = (attempt.assessment_snapshot or {}).get("deadline_at")
                if deadline:
                    try:
                        expires = datetime.fromisoformat(str(deadline).replace("Z", "+00:00"))
                        if expires.tzinfo is None:
                            expires = expires.replace(tzinfo=timezone.utc)
                        timed_out = timed_out or datetime.now(timezone.utc) >= expires
                    except ValueError:
                        pass
                return self._finalize_assessment(session, attempt, responses=responses, timed_out=timed_out)
        except (SQLAlchemyError, ValueError, TypeError) as exc:
            logger.error("Could not submit assessment: %s", exc); return None

    def _finalize_assessment(self, session, attempt, responses=None, timed_out=False):
        """Grade an assessment from its frozen keys and transition it terminally.

        ``responses`` is deliberately ignored for timeout finalization: only
        answers checkpointed before the deadline are eligible for grading.
        """
        from src.logic.assessment_grading import grade_assessment

        rows = session.scalars(select(QuizAttemptQuestionModel).where(
            QuizAttemptQuestionModel.attempt_id == attempt.id
        ).order_by(QuizAttemptQuestionModel.position)).all()
        stored = {str(a.position): a.user_answer for a in session.scalars(
            select(QuizAttemptAnswerModel).where(QuizAttemptAnswerModel.attempt_id == attempt.id)
        ).all()}
        if not timed_out:
            stored.update(responses or {})
        data = [{"position": row.position, "question_id": row.question_id,
                 "grading_key_json": row.grading_key_json} for row in rows]
        results, score, percentage = grade_assessment(data, stored)
        for result in results:
            answer = session.scalar(select(QuizAttemptAnswerModel).where(
                QuizAttemptAnswerModel.attempt_id == attempt.id,
                QuizAttemptAnswerModel.position == result["position"],
            ))
            if answer is None:
                grading = data[result["position"]]["grading_key_json"] or {}
                answer = QuizAttemptAnswerModel(
                    id=str(uuid5(NAMESPACE_URL, f"study-buddy:{attempt.id}:{result['position']}")),
                    attempt_id=attempt.id, question_id=result["question_id"],
                    position=result["position"], question_type=grading.get("type", ""),
                )
                session.add(answer)
            answer.user_answer, answer.is_correct = result["user_answer"], result["is_correct"]
        attempt.status = "timed_out" if timed_out else "submitted"
        attempt.submitted_at = datetime.now(timezone.utc)
        attempt.score = score
        attempt.total = len(rows)
        attempt.percentage = percentage
        attempt.passed = percentage >= (attempt.passing_grade_percent or 0)
        attempt.counts_toward_limit = True
        return self._assessment_result(session, attempt)

    @staticmethod
    def _assessment_public(session, attempt):
        rows = session.scalars(select(QuizAttemptQuestionModel).where(QuizAttemptQuestionModel.attempt_id == attempt.id).order_by(QuizAttemptQuestionModel.position)).all()
        return {"id": attempt.id, "quiz_id": attempt.quiz_id, "status": attempt.status, "started_at": attempt.started_at.isoformat(), "total": attempt.total, "questions": [{"position": r.position, **(r.presentation_json or {})} for r in rows]}

    @staticmethod
    def _assessment_result(session, attempt):
        result = {"id": attempt.id, "quiz_id": attempt.quiz_id, "status": attempt.status, "score": attempt.score, "total": attempt.total, "percentage": attempt.percentage, "passed": attempt.passed}
        snapshot = attempt.assessment_snapshot or {}
        policy = snapshot.get("answer_review_policy", "immediate")
        due = snapshot.get("due_at")
        reveal = policy == "immediate"
        if policy == "after_due_date" and due:
            try:
                deadline = datetime.fromisoformat(str(due).replace("Z", "+00:00"))
                if deadline.tzinfo is None: deadline = deadline.replace(tzinfo=timezone.utc)
                reveal = datetime.now(timezone.utc) >= deadline
            except ValueError:
                reveal = False
        if reveal:
            answers = session.scalars(select(QuizAttemptAnswerModel).where(QuizAttemptAnswerModel.attempt_id == attempt.id).order_by(QuizAttemptAnswerModel.position)).all()
            result["answers"] = [{"position": a.position, "question_id": a.question_id, "user_answer": a.user_answer, "is_correct": a.is_correct} for a in answers]
        else:
            result["answers"] = []
        return result

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

    def get_progress_summary(
        self, user_id: str, actor_role: str = "student", *, include_items: bool = True,
    ) -> dict:
        """Return every currently available quiz/deck progress row in one query."""
        user_id = str(user_id)
        if not self._authenticated_user(user_id):
            return self._empty_progress_summary()

        def available(metadata, class_link, content_column):
            if str(actor_role).casefold() == "admin":
                return literal(True)
            enrolled_content = select(content_column).select_from(class_link).join(
                ClassMemberModel,
                ClassMemberModel.class_id == class_link.class_id,
            ).where(
                ClassMemberModel.user_id == user_id,
                ClassMemberModel.status == "active",
            )
            return or_(
                metadata.owner_id == user_id,
                and_(
                    metadata.lifecycle == "published",
                    or_(metadata.visibility == "public", metadata.id.in_(enrolled_content)),
                ),
            )

        quiz_rows = select(
            literal("quiz").label("kind"), QuizMetadataModel.id.label("content_id"),
            QuizMetadataModel.name.label("content_name"),
            QuizQuestionModel.question_id.label("item_id"),
            QuizQuestionModel.question_text.label("item_text"),
            QuizQuestionModel.position.label("position"),
            func.coalesce(QuizQuestionProgressModel.correct_count, 0).label("correct"),
            func.coalesce(QuizQuestionProgressModel.wrong_count, 0).label("wrong"),
            func.coalesce(QuizQuestionProgressModel.mastered, False).label("mastered"),
            QuizQuestionProgressModel.user_id.is_not(None).label("has_progress"),
        ).select_from(QuizMetadataModel).outerjoin(
            QuizQuestionModel, QuizQuestionModel.quiz_id == QuizMetadataModel.id,
        ).outerjoin(
            QuizQuestionProgressModel,
            and_(
                QuizQuestionProgressModel.quiz_id == QuizMetadataModel.id,
                QuizQuestionProgressModel.question_id == QuizQuestionModel.question_id,
                QuizQuestionProgressModel.user_id == user_id,
            ),
        ).where(available(QuizMetadataModel, ClassQuizModel, ClassQuizModel.quiz_id))

        deck_rows = select(
            literal("flashcard").label("kind"),
            FlashcardDeckMetadataModel.id.label("content_id"),
            FlashcardDeckMetadataModel.name.label("content_name"),
            FlashcardModel.card_id.label("item_id"),
            FlashcardModel.front_text.label("item_text"),
            FlashcardModel.position.label("position"),
            func.coalesce(FlashcardProgressModel.correct_count, 0).label("correct"),
            func.coalesce(FlashcardProgressModel.wrong_count, 0).label("wrong"),
            func.coalesce(FlashcardProgressModel.mastered, False).label("mastered"),
            FlashcardProgressModel.user_id.is_not(None).label("has_progress"),
        ).select_from(FlashcardDeckMetadataModel).outerjoin(
            FlashcardModel, FlashcardModel.deck_id == FlashcardDeckMetadataModel.id,
        ).outerjoin(
            FlashcardProgressModel,
            and_(
                FlashcardProgressModel.deck_id == FlashcardDeckMetadataModel.id,
                FlashcardProgressModel.card_id == FlashcardModel.card_id,
                FlashcardProgressModel.user_id == user_id,
            ),
        ).where(available(
            FlashcardDeckMetadataModel,
            ClassFlashcardDeckModel,
            ClassFlashcardDeckModel.deck_id,
        ))

        statement = select(union_all(quiz_rows, deck_rows).subquery()).order_by(
            "kind", "content_name", "content_id", "position"
        )
        try:
            with self.session_factory() as session:
                rows = session.execute(statement).mappings().all()
        except SQLAlchemyError as exc:
            logger.error("Could not load PostgreSQL progress summary: %s", exc)
            return self._empty_progress_summary()

        collections = []
        by_key = {}
        for row in rows:
            key = (row["kind"], row["content_id"])
            collection = by_key.get(key)
            if collection is None:
                collection = {
                    "kind": row["kind"], "id": row["content_id"],
                    "name": row["content_name"], "items": [],
                    "summary": {"mastered": 0, "total": 0, "percent": 0,
                                "has_progress": False},
                }
                by_key[key] = collection
                collections.append(collection)
            if row["item_id"] is None:
                continue
            item = {
                "id": row["item_id"], "text": str(row["item_text"] or "Untitled"),
                "mastered": bool(row["mastered"]), "correct": int(row["correct"]),
                "wrong": int(row["wrong"]),
            }
            if include_items:
                collection["items"].append(item)
            summary = collection["summary"]
            summary["total"] += 1
            summary["mastered"] += int(item["mastered"])
            summary["has_progress"] = summary["has_progress"] or bool(row["has_progress"])

        totals = {
            "flashcards": {"mastered": 0, "total": 0},
            "quizzes": {"mastered": 0, "total": 0},
        }
        for collection in collections:
            summary = collection["summary"]
            summary["percent"] = (
                round(summary["mastered"] / summary["total"] * 100)
                if summary["total"] else 0
            )
            bucket = totals["quizzes" if collection["kind"] == "quiz" else "flashcards"]
            bucket["mastered"] += summary["mastered"]
            bucket["total"] += summary["total"]
        return {"collections": collections, "summary": totals}

    @staticmethod
    def _empty_progress_summary():
        return {
            "collections": [],
            "summary": {
                "flashcards": {"mastered": 0, "total": 0},
                "quizzes": {"mastered": 0, "total": 0},
            },
        }

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
        # Snapshot-backed assessments must be resolved from their private frozen keys.
        with self.session_factory.begin() as session:
            frozen_attempt = session.scalar(select(QuizAttemptModel).where(
                QuizAttemptModel.id == str(attempt_id),
            ).with_for_update())
            if frozen_attempt and frozen_attempt.quiz_id == str(quiz_id) and frozen_attempt.assessment_snapshot is not None:
                if frozen_attempt.status not in {"in_progress", "abandoned"}:
                    return None
                now = datetime.now(timezone.utc)
                if action == "refund":
                    frozen_attempt.status, frozen_attempt.counts_toward_limit = "refunded", False
                elif action in {"submit_current", "mark_zero"}:
                    if action == "mark_zero":
                        score = 0
                    else:
                        from src.logic.assessment_grading import grade_assessment
                        rows = session.scalars(select(QuizAttemptQuestionModel).where(QuizAttemptQuestionModel.attempt_id == frozen_attempt.id).order_by(QuizAttemptQuestionModel.position)).all()
                        answers = session.scalars(select(QuizAttemptAnswerModel).where(QuizAttemptAnswerModel.attempt_id == frozen_attempt.id)).all()
                        stored = {str(a.position): a.user_answer for a in answers}
                        data = [{"position": r.position, "question_id": r.question_id, "grading_key_json": r.grading_key_json} for r in rows]
                        _results, score, _percentage = grade_assessment(data, stored)
                        frozen_attempt.total = len(rows)
                    percentage = round(score / frozen_attempt.total * 100, 1) if frozen_attempt.total else 0.0
                    frozen_attempt.status = "marked_zero" if action == "mark_zero" else "submitted"
                    frozen_attempt.score, frozen_attempt.percentage = score, percentage
                    frozen_attempt.passed = percentage >= (frozen_attempt.passing_grade_percent or 0)
                    frozen_attempt.counts_toward_limit = True
                    frozen_attempt.submitted_at = now
                else:
                    return None
                frozen_attempt.resolved_by, frozen_attempt.resolved_at, frozen_attempt.resolution = str(actor_id), now, action
                session.flush()
                return self._attempt_public(session, frozen_attempt)
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
            "assessment_snapshot": attempt.assessment_snapshot,
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
