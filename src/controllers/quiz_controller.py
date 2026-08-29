# src/controllers/quiz_controller.py

import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from src.logic.question_types import MATCH_ANSWER_KEY, MATCH_PROMPT_KEY
from src.logic.translator import get_translator
from src.logic.quiz_logic import Quiz
from src.utils.paths import resolve_stored_path
from src.config import MASTERY_REQUIRED_SCORE, MASTERY_WRONG_PENALTY
from src.storage.repository_factory import (
    create_class_repository, create_moderation_repository, create_quiz_repository,
)
from src.storage.downloaded_content_service import DownloadedContentService

logger = logging.getLogger(__name__)


class QuizController:
    def __init__(
        self, user_id="guest", repo=None, role="student",
        user_repository=None, class_repository=None,
    ):
        self.translator = get_translator()
        self.user_repository = user_repository
        self.repo = repo or create_quiz_repository(user_repository)
        self.invites = class_repository or create_class_repository(user_repository)
        self.moderation = create_moderation_repository(user_repository, quizzes=self.repo)
        self.user_id = user_id or "guest"
        self.role = role
        self.quiz = None
        self.user_answers = {}
        self.current_quiz_info = None
        self.current_quiz_path = ""
        self.quiz_progress = {}
        self.session_mode = "practice"
        self.test_started_at = None
        self.saved_test_attempt = None
        self.active_test_attempt = None
        self.test_deadline = None
        self.question_started_at = None
        self.remote_assessment = False
        self.remote_position_by_question = {}
        self.remote_submit_failed = False
        self._policy_cache = {}
        self._prepared_quiz_start = None
        self.downloaded_content = None

    def configure_downloaded_content(self, library, base_repository=None):
        """Attach the lifecycle service before the read-through repository is installed."""
        base = base_repository or self.repo
        metadata = getattr(base, "metadata", None)
        bodies = getattr(base, "bodies", None)
        if metadata is not None and bodies is not None:
            self.downloaded_content = DownloadedContentService(library, metadata, bodies)
        return self.downloaded_content

    def check_downloaded_content(self, content_id):
        return self.downloaded_content.check("quiz", content_id, self.user_id) if self.downloaded_content else None

    def update_downloaded_content(self, content_id):
        return self.downloaded_content.update("quiz", content_id, self.user_id) if self.downloaded_content else None

    def get_cached_content_state(self, content_id):
        return (self.downloaded_content.get_cached_state("quiz", content_id, self.user_id)
                if self.downloaded_content else None)

    def get_available_quizzes(self):
        """Returns list of names for the UI list widget."""
        return [q["name"] for q in self._visible_quizzes()]

    def get_quiz_summaries(self):
        summaries = []
        for quiz in self._visible_quizzes():
            latest = next((
                attempt for attempt in self.repo.get_test_attempts(quiz["file"], self.user_id)
                if attempt.get("status") in {"submitted", "timed_out", "marked_zero"}
            ), None)
            summaries.append({
                **quiz,
                **self.repo.get_quiz_progress_summary(quiz["file"], self.user_id),
                "latest_test_percentage": latest.get("percentage") if latest else None,
            })
        return summaries

    def get_quiz_list_items(self):
        """Return metadata-only rows for the quiz selector."""
        return [
            {**quiz, "mastered": 0, "total": 0, "latest_test_percentage": None}
            for quiz in self._visible_quizzes()
        ]

    def get_quiz_summary(self, name):
        return next((quiz for quiz in self.get_quiz_summaries() if quiz["name"] == name), None)

    def is_quiz_complete(self, name):
        prepared = self._prepare_quiz_start(name)
        self._prepared_quiz_start = prepared
        if not prepared:
            return False
        questions = prepared["questions"]
        progress = prepared["progress"]
        return bool(
            questions
            and all(progress.get(question.get("id"), {}).get("mastered", False)
                    for question in questions)
        )

    def get_test_policy(self, name):
        metadata = next(
            (quiz for quiz in self._visible_quizzes() if quiz["name"] == name),
            None,
        )
        if not metadata:
            return None
        return self.get_test_policy_for_summary(metadata)

    def get_test_policy_for_summary(self, summary):
        settings = summary.get("test_settings", {}) if summary.get("visibility") == "class_only" else {}
        cache_key = (str(summary.get("file")), repr(settings))
        cache_enabled = hasattr(self.repo, "user_repository")
        if cache_enabled and cache_key in self._policy_cache:
            return dict(self._policy_cache[cache_key])
        class_only = summary.get("visibility") == "class_only"
        attempts = self.repo.get_test_attempts(summary["file"], self.user_id) if class_only else []
        charged_attempts = [
            attempt for attempt in attempts
            if attempt.get("counts_toward_limit", attempt.get("status") != "refunded")
            and attempt.get("status") not in {"in_progress", "abandoned"}
        ]
        unresolved = next((
            attempt for attempt in attempts
            if attempt.get("status") in {"in_progress", "abandoned"}
        ), None)
        attempt_limit = int(settings.get("attempt_limit", 1) or 0) if class_only else 0
        due_at = settings.get("due_at") if class_only else None
        due_datetime = self._parse_due_at(due_at)
        due_expired = bool(due_datetime and datetime.now(timezone.utc) > due_datetime)
        attempt_limit_reached = class_only and attempt_limit > 0 and len(charged_attempts) >= attempt_limit
        policy = {
            "class_only": class_only,
            "single_attempt": class_only and attempt_limit == 1,
            "completed": attempt_limit_reached,
            "due_expired": due_expired,
            "can_start": not attempt_limit_reached and not due_expired and unresolved is None,
            "attempt_limit": attempt_limit,
            "attempts_used": len(charged_attempts),
            "attempts_remaining": None if attempt_limit == 0 else max(0, attempt_limit - len(charged_attempts)),
            "unresolved_attempt": unresolved,
            "passing_grade_percent": (
                int(settings.get("passing_grade_percent", 80)) if class_only else None
            ),
            "due_at": due_at,
            "time_limit_minutes": int(settings.get("time_limit_minutes", 0) or 0),
            "answer_review_policy": settings.get("answer_review_policy", "immediate"),
        }
        if cache_enabled:
            self._policy_cache = {cache_key: policy}
        return dict(policy)

    def invalidate_policy_cache(self):
        self._policy_cache = {}

    def can_start_test(self, name):
        policy = self.get_test_policy(name)
        return bool(policy and policy["can_start"])

    def reset_quiz_progress(self, name):
        self.invalidate_policy_cache()
        self._prepared_quiz_start = None
        quiz = next((item for item in self._visible_quizzes() if item["name"] == name), None)
        if not quiz:
            logger.warning("Cannot reset progress: quiz '%s' was not found", name)
            return False
        reset = self.repo.reset_quiz_progress(quiz["file"], self.user_id)
        logger.info("Quiz progress reset requested for '%s' by user '%s': %s", name, self.user_id, reset)
        return reset

    def clear_all_progress(self):
        self._prepared_quiz_start = None
        removed = self.repo.clear_user_progress(self.user_id)
        logger.info("All quiz progress cleared for user '%s' (%d quizzes)", self.user_id, removed)
        return removed

    def join_with_code(self, code):
        if self.user_id == "guest":
            return False, "Sign in to join a class with an invitation code."
        return self.invites.enroll_with_code(code, self.user_id)

    def load_quiz_by_name(self, name, mode="practice"):
        """Initializes a new quiz session."""
        # A new non-remote session must never inherit server assessment state.
        # This is deliberately before content selection so mode transitions are clean.
        self.remote_assessment = False
        self.remote_position_by_question = {}
        self.saved_test_attempt = None
        self.active_test_attempt = None
        prepared = self._prepared_quiz_start if mode == "practice" else None
        self._prepared_quiz_start = None
        if prepared and prepared["name"] == name:
            meta = prepared["meta"]
        else:
            prepared = None
            quizzes = self._visible_quizzes()
            meta = next((q for q in quizzes if q["name"] == name), None)

        if meta:
            if meta.get("moderation_status") == "banned":
                logger.warning("Blocked attempt to study banned quiz '%s'", name)
                return None
            if mode == "test" and meta.get("source") == "downloaded":
                logger.warning("Blocked assessment attempt for cached quiz package '%s'", name)
                return None
            if mode == "test" and meta.get("visibility") == "class_only":
                start_assessment = getattr(self.repo, "start_assessment", None)
                if callable(start_assessment):
                    assessment = start_assessment(meta.get("id") or meta.get("file"))
                    if not isinstance(assessment, dict) or not assessment.get("id"):
                        return None
                    server_questions = list(assessment.get("questions") or [])
                    if not server_questions:
                        return None
                    normalized = []
                    for row in server_questions:
                        question = dict(row)
                        question.pop("answer", None)
                        question.pop("grading_key_json", None)
                        if question.get("type") == "matching":
                            question["pairs"] = [{"prompt": p.get("prompt", ""), "answer": ""} for p in question.get("pairs", [])]
                        normalized.append(question)
                    self.current_quiz_info = meta
                    self.current_quiz_path = meta["file"]
                    self.session_mode = "test"
                    self.remote_assessment = True
                    self.remote_submit_failed = False
                    self.active_test_attempt = assessment
                    self.remote_position_by_question = {
                        str(q.get("id")): int(q.get("position")) for q in server_questions
                    }
                    self.quiz = Quiz(normalized, shuffle=False, max_questions=None, preserve_presentation=True)
                    self.user_answers = {}
                    self.test_started_at = datetime.now(timezone.utc)
                    self.question_started_at = self.test_started_at
                    self.test_deadline = None
                    return self._get_current_card_data()
                policy = self.get_test_policy(name)
                if policy and not policy["can_start"]:
                    logger.warning("Blocked unavailable class-only test '%s' for '%s'", name, self.user_id)
                    return None
            self.current_quiz_info = meta
            self.current_quiz_path = meta["file"]
            questions = (
                prepared["questions"] if prepared is not None
                else self.repo.load_quiz_questions(meta["file"])
            )

            if not questions:
                logger.error(f"No questions loaded for quiz: {name}")
                return None

            self.quiz_progress = (
                prepared["progress"] if prepared is not None
                else self.repo.get_quiz_progress(self.current_quiz_path, self.user_id)
            )
            self.session_mode = "test" if mode == "test" else "practice"
            session_questions = questions if self.session_mode == "test" else [
                question for question in questions
                if not self.quiz_progress.get(question.get("id"), {}).get("mastered", False)
            ]
            self.quiz = Quiz(
                session_questions,
                shuffle=True,
                max_questions=None if self.session_mode == "test" else 20,
            )
            self.user_answers = {}
            self.test_started_at = datetime.now(timezone.utc) if self.session_mode == "test" else None
            self.question_started_at = self.test_started_at
            limit = int(meta.get("test_settings", {}).get("time_limit_minutes", 0) or 0)
            self.test_deadline = (
                self.test_started_at + timedelta(minutes=limit)
                if self.session_mode == "test" and meta.get("visibility") == "class_only" and limit > 0
                else None
            )
            self.saved_test_attempt = None
            self.active_test_attempt = None
            if self.session_mode == "test":
                previous_attempts = self.repo.get_test_attempts(self.current_quiz_path, self.user_id)
                charged = [
                    attempt for attempt in previous_attempts
                    if attempt.get("counts_toward_limit", attempt.get("status") != "refunded")
                    and attempt.get("status") not in {"in_progress", "abandoned"}
                ]
                passing_grade = (
                    int(meta.get("test_settings", {}).get("passing_grade_percent", 80))
                    if meta.get("visibility") == "class_only" else None
                )
                self.active_test_attempt = self.repo.save_test_attempt(self.current_quiz_path, {
                    "quiz_id": meta.get("id"),
                    "quiz_name": meta.get("name"),
                    "user_id": str(self.user_id),
                    "mode": "test",
                    "started_at": self.test_started_at.isoformat(),
                    "last_activity_at": self.test_started_at.isoformat(),
                    "score": 0,
                    "total": len(self.quiz.cards),
                    "percentage": 0.0,
                    "passing_grade_percent": passing_grade,
                    "passed": None,
                    "attempt_number": len(charged) + 1,
                    "status": "in_progress",
                    "counts_toward_limit": False,
                    "current_question": 1,
                    "answers": [],
                })

            logger.info(
                "Loaded quiz '%s' for user '%s': %d total, %d learning questions",
                name, self.user_id, len(questions), len(session_questions),
            )
            return self._get_current_card_data()

        logger.error(f"Quiz not found: {name}")
        return None

    def submit_answer(self, user_input):
        """Grades and saves the answer, then determines next step."""
        if not self.quiz or not self.quiz.get_current():
            logger.warning("Ignoring answer submission without an active quiz question")
            return {"type": "standard", "next_card": None}
        current_card = self.quiz.get_current()
        current_id = current_card.id
        current_q = current_card.question

        if self.remote_assessment:
            position = self.remote_position_by_question.get(str(current_id))
            if position is None or user_input is None or (isinstance(user_input, str) and not user_input.strip()):
                return {"type": "standard", "next_card": self._get_current_card_data()}
            wire_answer = user_input
            if current_card.type == "matching" and isinstance(user_input, list):
                wire_answer = {
                    str(pair.get(MATCH_PROMPT_KEY, "")): pair.get(MATCH_ANSWER_KEY, "")
                    for pair in user_input if isinstance(pair, dict)
                }
            checkpoint = self.repo.checkpoint_assessment(self.current_quiz_info.get("id"), self.active_test_attempt.get("id"), position, wire_answer)
            if not checkpoint:
                return {"type": "standard", "next_card": self._get_current_card_data()}
            self.user_answers[current_id] = {"question_id": current_id, "question": current_q, "type": current_card.type, "user_answer": user_input, "is_correct": None}
            if self.quiz.index >= len(self.quiz.cards) - 1:
                return {"type": "review", "next_card": None}
            self.quiz.next()
            self.question_started_at = datetime.now(timezone.utc)
            return {"type": "standard", "next_card": self._get_current_card_data()}

        # Block empty saves
        if user_input is None or (isinstance(user_input, str) and not user_input.strip()):
            logger.debug("Controller: Ignoring empty/None input.")
            return {"type": "standard", "next_card": self._get_current_card_data()}

        # Get correct answer based on new structure
        if current_card.type == "matching":
            correct = current_card.pairs
        else:
            # All other types now use 'answer' attribute
            correct = current_card.answer

        # Save to dictionary (Automatically overwrites if question exists)
        self.user_answers[current_id] = {
            "question_id": current_id,
            "question": current_q,
            "type": current_card.type,
            "user_answer": user_input,
            "correct_answer": correct,
            "is_correct": None,
            "answered_at": datetime.now(timezone.utc).isoformat(),
            "response_seconds": max(
                0, int((datetime.now(timezone.utc) - self.question_started_at).total_seconds())
            ) if self.question_started_at else None,
        }

        is_correct = self._check_logic(self.user_answers[current_id])
        self.user_answers[current_id]["is_correct"] = is_correct
        self._checkpoint_test_attempt()
        if self.session_mode == "practice":
            self._record_attempt(current_id, is_correct)

        logger.info(
            "Recorded %s attempt for quiz question '%s' (session answers: %d)",
            "correct" if is_correct else "wrong", current_id, len(self.user_answers),
        )

        # Determine navigation
        if self.quiz.index >= len(self.quiz.cards) - 1:
            return {"type": "review", "next_card": None}

        self.quiz.next()
        self.question_started_at = datetime.now(timezone.utc)
        return {"type": "standard", "next_card": self._get_current_card_data()}

    def get_progress_text(self):
        if not self.quiz:
            return ""
        from src.logic.translator import get_translator
        t = get_translator()
        progress = t.t(
            "quiz_view.progress_text",
            current=self.quiz.index + 1,
            total=len(self.quiz.cards),
        )
        mode_label = "Test" if self.is_test_mode else "Practice"
        return f"{mode_label} • {progress}"

    def get_navigation_status(self):
        """Tells the UI which buttons to show/hide."""
        if not self.quiz or not self.quiz.cards:
            return {
                "show_submit": False,
                "show_skip": False,
                "show_preview": False,
                "show_finish": False,
            }
        is_last = (self.quiz.index == len(self.quiz.cards) - 1)
        return {
            "show_submit": not is_last,
            "show_skip": not is_last,
            "show_preview": is_last,
            "show_finish": is_last
        }

    def _format_val(self, val):
        """Helper to turn lists/dicts into clean strings for the report."""
        if isinstance(val, list):
            if len(val) > 0 and isinstance(val[0], dict):  # Matching
                return ", ".join(
                    f"{item.get(MATCH_PROMPT_KEY)} -> {item.get(MATCH_ANSWER_KEY)}"
                    for item in val
                )
            return ", ".join([str(x) for x in val])  # Ordering/Multiple Choice
        return str(val)

    def get_final_results(self):
        """Returns score stats and raw answer data for the UI to render."""
        if self.remote_assessment:
            if self.saved_test_attempt:
                return self.saved_test_attempt
            pending = dict(self.active_test_attempt or {})
            pending.setdefault("status", "in_progress")
            pending.setdefault("score", 0)
            pending.setdefault("total", len(self.quiz.cards) if self.quiz else 0)
            pending.setdefault("percentage", 0.0)
            pending.setdefault("results", [])
            return pending
        correct_count = 0
        results = []

        for data in self.user_answers.values():
            is_correct = self._check_logic(data)
            if is_correct:
                correct_count += 1

            results.append({
                "question_id": data["question_id"],
                "question": data["question"],
                "user_answer": self._format_val(data["user_answer"]),
                "correct_answer": self._format_val(data["correct_answer"]),
                "is_correct": is_correct,
                "mastered": self.is_question_mastered(data["question_id"]),
                "can_master": self.is_eligible_for_mastery(data["question_id"]),
                "stats": self.get_question_progress(data["question_id"]),
                "answered_at": data.get("answered_at"),
                "response_seconds": data.get("response_seconds"),
            })

        total = len(self.quiz.cards) if self.quiz else 0
        percent = (correct_count / total) * 100 if total > 0 else 0
        return {
            "score": correct_count,
            "total": total,
            "percent": round(percent, 1),
            "results": results
        }

    def finalize_test_attempt(self, status="submitted"):
        """Record one completed Test Mode result without changing mastery."""
        if self.session_mode != "test" or not self.current_quiz_path:
            return None
        if self.saved_test_attempt is not None:
            return self.saved_test_attempt
        if self.remote_assessment and self.active_test_attempt:
            result = self.repo.submit_assessment(self.current_quiz_info.get("id"), self.active_test_attempt.get("id"))
            if result:
                self.saved_test_attempt = result
                self.active_test_attempt = None
                self.invalidate_policy_cache()
                self.remote_submit_failed = False
            else:
                self.remote_submit_failed = True
            # A failed remote submit is not permission to fall back to local grading.
            return None
        stats = self.get_final_results()
        submitted_at = datetime.now(timezone.utc)
        started_at = self.test_started_at or submitted_at
        settings = self.current_quiz_info.get("test_settings", {})
        class_only = self.current_quiz_info.get("visibility") == "class_only"
        passing_grade = int(settings.get("passing_grade_percent", 80)) if class_only else None
        previous_attempts = self.repo.get_test_attempts(self.current_quiz_path, self.user_id)
        attempt_number = (
            self.active_test_attempt.get("attempt_number") if self.active_test_attempt
            else len(previous_attempts) + 1
        )
        attempt = {
            "quiz_id": self.current_quiz_info.get("id"),
            "quiz_name": self.current_quiz_info.get("name"),
            "user_id": str(self.user_id),
            "mode": "test",
            "started_at": started_at.isoformat(),
            "submitted_at": submitted_at.isoformat(),
            "duration_seconds": max(0, int((submitted_at - started_at).total_seconds())),
            "score": stats["score"],
            "total": stats["total"],
            "percentage": stats["percent"],
            "passing_grade_percent": passing_grade,
            "passed": stats["percent"] >= passing_grade if passing_grade is not None else None,
            "attempt_number": attempt_number,
            "status": status,
            "counts_toward_limit": True,
            "answers": stats["results"],
        }
        if self.active_test_attempt:
            self.saved_test_attempt = self.repo.update_test_attempt(
                self.current_quiz_path, self.active_test_attempt["id"], attempt
            )
        else:
            self.saved_test_attempt = self.repo.save_test_attempt(self.current_quiz_path, attempt)
        self.active_test_attempt = None
        self.invalidate_policy_cache()
        return self.saved_test_attempt

    def abandon_test_attempt(self):
        """Checkpoint and mark an unfinished Test Mode session as abandoned."""
        if self.session_mode != "test" or not self.active_test_attempt or self.saved_test_attempt:
            return None
        if self.remote_assessment:
            # There is deliberately no remote abandonment endpoint. Leave the
            # server attempt resumable when the desktop session closes.
            return self.active_test_attempt
        self._checkpoint_test_attempt()
        now = datetime.now(timezone.utc)
        result = self.repo.update_test_attempt(self.current_quiz_path, self.active_test_attempt["id"], {
            "status": "abandoned",
            "interrupted_at": now.isoformat(),
            "last_question": (self.quiz.index + 1) if self.quiz else 0,
            "counts_toward_limit": False,
        })
        self.active_test_attempt = None
        self.invalidate_policy_cache()
        return result

    def _checkpoint_test_attempt(self):
        if self.session_mode != "test" or not self.active_test_attempt:
            return
        now = datetime.now(timezone.utc)
        updates = {
            "last_activity_at": now.isoformat(),
            "current_question": (self.quiz.index + 1) if self.quiz else 0,
            "answered_count": len(self.user_answers),
            "answers": [dict(value) for value in self.user_answers.values()],
        }
        updated = self.repo.update_test_attempt(
            self.current_quiz_path, self.active_test_attempt["id"], updates
        )
        if updated:
            self.active_test_attempt = updated

    def can_show_correct_answers(self):
        """Apply the teacher's answer-review policy to a completed Class-Only test."""
        if not self.current_quiz_info or self.current_quiz_info.get("visibility") != "class_only":
            return True
        if self.remote_assessment and self.saved_test_attempt is not None:
            return bool(self.saved_test_attempt.get("answers"))
        settings = self.current_quiz_info.get("test_settings", {})
        policy = settings.get("answer_review_policy", "immediate")
        if policy == "immediate":
            return True
        if policy == "never":
            return False
        due = self._parse_due_at(settings.get("due_at"))
        return bool(due and datetime.now(timezone.utc) >= due)

    def get_remaining_test_seconds(self):
        if not self.test_deadline:
            return None
        return max(0, int((self.test_deadline - datetime.now(timezone.utc)).total_seconds()))

    @staticmethod
    def _parse_due_at(value):
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            logger.warning("Ignoring invalid quiz due date: %r", value)
            return None

    @property
    def is_test_mode(self):
        return self.session_mode == "test"

    def is_question_mastered(self, question_id):
        return self.quiz_progress.get(question_id, {}).get("mastered", False)

    def get_question_progress(self, question_id):
        """Return normalized learning progress for one quiz question."""
        progress = self.quiz_progress.get(question_id, {})
        return {
            "correct": progress.get("correct", 0),
            "wrong": progress.get("wrong", 0),
            "mastered": progress.get("mastered", False),
        }

    def is_eligible_for_mastery(self, question_id):
        progress = self.get_question_progress(question_id)
        return (
            progress["correct"] - progress["wrong"] * MASTERY_WRONG_PENALTY
            >= MASTERY_REQUIRED_SCORE
        )

    def toggle_question_mastery(self, question_id):
        if not self.current_quiz_path:
            logger.warning("Cannot change mastery for '%s': no quiz is active", question_id)
            return None
        progress = self.quiz_progress.setdefault(question_id, {})
        if not progress.get("mastered", False) and not self.is_eligible_for_mastery(question_id):
            stats = self.get_question_progress(question_id)
            logger.info(
                "Mastery denied for question '%s': correct=%d wrong=%d",
                question_id, stats["correct"], stats["wrong"],
            )
            return False
        new_state = not progress.get("mastered", False)
        progress["mastered"] = new_state
        self.repo.save_quiz_progress(self.current_quiz_path, self.quiz_progress, self.user_id)
        logger.info("Question '%s' mastery changed to %s", question_id, new_state)
        return new_state

    def _record_attempt(self, question_id, is_correct):
        """Persist one learning attempt as soon as the answer is submitted."""
        progress = self.quiz_progress.setdefault(question_id, {})
        progress.setdefault("correct", 0)
        progress.setdefault("wrong", 0)
        progress.setdefault("mastered", False)
        progress["correct" if is_correct else "wrong"] += 1
        self.repo.save_quiz_progress(self.current_quiz_path, self.quiz_progress, self.user_id)
        logger.debug(
            "Updated attempts for question '%s': correct=%d wrong=%d",
            question_id, progress["correct"], progress["wrong"],
        )

    # --- Private Helpers ---
    def _visible_quizzes(self):
        """Apply lifecycle/visibility rules before displaying study content."""
        content = {
            item["file"]: item
            for item in self.moderation.get_content_for_selector(
                self.user_id, self.role, kind="quiz"
            )
            if item["kind"] == "quiz"
        }
        return [
            {
                **quiz,
                "moderation_status": content[quiz["file"]]["status"],
                "visibility": content[quiz["file"]].get("visibility", "public"),
                "test_settings": content[quiz["file"]].get("test_settings", {}),
                "moderation_reason": content[quiz["file"]].get("review_note", ""),
                "is_owner": str(content[quiz["file"]].get("owner_id")) == str(self.user_id),
                "can_view_moderation_reason": (
                    str(content[quiz["file"]].get("owner_id")) == str(self.user_id)
                    or self.role == "admin"
                ),
            }
            for quiz in self.repo.get_all_quizzes()
            if quiz["file"] in content
        ]

    def _prepare_quiz_start(self, name):
        """Load the selected practice package once for completion and session start."""
        meta = next((item for item in self._visible_quizzes() if item["name"] == name), None)
        if not meta or meta.get("moderation_status") == "banned":
            return None
        questions = self.repo.load_quiz_questions(meta["file"])
        progress = self.repo.get_quiz_progress(meta["file"], self.user_id)
        return {
            "name": name, "meta": meta, "questions": questions, "progress": progress,
        }

    def _get_current_card_data(self):
        """Extract card data for UI rendering."""
        card = self.quiz.get_current()
        t = self.translator

        if not card:
            return None

        data = {
            "id": card.id,
            "question": card.question,
            "type": card.type,
            "image_path": getattr(card, "image_path", None),
        }

        # Handle different question types based on new structure
        if card.type in ("single_choice", "multiple_choice"):
            # ChoiceQuestion has shuffled_options
            data["options"] = getattr(card, "shuffled_options", [])

        elif card.type == "matching":
            # MatchingQuestion for matching
            data["prompts"] = [pair[MATCH_PROMPT_KEY] for pair in card.pairs]
            data["dropdown_options"] = card.shuffled_options

        elif card.type == "ordering":
            # MatchingQuestion for ordering
            # card.answer is the correct order
            # card.shuffled_options is the shuffled version
            data["prompts"] = [t.t("quiz_view.step_label", number=i+1) for i in range(len(card.shuffled_options))]
            data["dropdown_options"] = card.shuffled_options

        return data

    def _get_correct_val(self, card):
        """ Get correct answer value."""
        if card.type == "matching":
            return card.pairs
        else:
            # All other types now use 'answer' attribute
            return card.answer

    def _check_logic(self, data):
        user_ans = data.get("user_answer")
        correct_ans = data.get("correct_answer")
        q_type = data.get("type")

        if not user_ans:
            return False

        if q_type == "true_false":
            return user_ans == correct_ans

        elif q_type in ("short_answer", "open", "text", "single_choice"):
            return str(user_ans).lower().strip() == str(correct_ans).lower().strip()

        elif q_type == "multiple_choice":
            if not isinstance(user_ans, list) or not isinstance(correct_ans, list):
                return False
            return sorted([str(x).lower() for x in user_ans]) == sorted([str(x).lower() for x in correct_ans])

        elif q_type == "matching":
            if not isinstance(user_ans, list) or not isinstance(correct_ans, list):
                return False
            if len(user_ans) != len(correct_ans):
                return False
            for u_pair in user_ans:
                found = False
                for c_pair in correct_ans:
                    if (
                        u_pair.get(MATCH_PROMPT_KEY) == c_pair.get(MATCH_PROMPT_KEY)
                        and u_pair.get(MATCH_ANSWER_KEY) == c_pair.get(MATCH_ANSWER_KEY)
                    ):
                        found = True
                        break
                if not found:
                    return False
            return True

        elif q_type == "ordering":
            if not isinstance(user_ans, list) or not isinstance(correct_ans, list):
                return False
            return user_ans == correct_ans

        return False

    def skip_question(self):
        """Moves to next index without saving and returns new card data."""
        if self.quiz.index < len(self.quiz.cards) - 1:
            self.quiz.next()
            self.question_started_at = datetime.now(timezone.utc)
            return self._get_current_card_data()
        return None

    def jump_to(self, index):
        """Used by the Review panel to edit a specific question."""
        if 0 <= index < len(self.quiz.cards):
            self.quiz.index = index
            self.question_started_at = datetime.now(timezone.utc)
            return self._get_current_card_data()
        return None

    def get_review_summary(self):
        """Correctly checks dictionary keys to see if answered."""
        summary = []
        for card in self.quiz.cards:
            summary.append({
                "question": card.question,
                "answered": card.id in self.user_answers
            })
        return summary

    def has_unanswered(self):
        """Checks if any questions were skipped."""
        return len(self.user_answers) < len(self.quiz.cards)

    def get_current_card_type(self):
        """Helper for the UI to know how to parse inputs."""
        if self.quiz:
            return self.quiz.get_current().type
        return None

    def get_current_matching_keys(self):
        """Helper for matching questions."""
        if not self.quiz or not self.quiz.get_current():
            return []
        card = self.quiz.get_current()
        if card.type == "matching":
            return [pair[MATCH_PROMPT_KEY] for pair in card.pairs]
        return []

    def get_absolute_image_path(self, stored_path: str) -> Path:
        """Helper for the UI to resolve project-relative paths."""
        return resolve_stored_path(stored_path)

    def get_current_card(self):
        """Returns the current card data for UI rendering."""
        return self._get_current_card_data()
