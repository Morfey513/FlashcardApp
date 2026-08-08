# src/controllers/quiz_controller.py

import logging
from pathlib import Path
from src.logic.question_types import MATCH_ANSWER_KEY, MATCH_PROMPT_KEY
from src.logic.translator import get_translator
from src.storage.quiz_repository import QuizRepository
from src.logic.quiz_logic import Quiz
from src.utils.paths import resolve_stored_path
from src.config import MASTERY_REQUIRED_SCORE, MASTERY_WRONG_PENALTY

logger = logging.getLogger(__name__)


class QuizController:
    def __init__(self, user_id="guest", repo=None, role="student"):
        self.translator = get_translator()
        self.repo = repo or QuizRepository()
        self.user_id = user_id or "guest"
        self.role = role
        self.quiz = None
        self.user_answers = {}
        self.current_quiz_info = None
        self.current_quiz_path = ""
        self.quiz_progress = {}

    def get_available_quizzes(self):
        """Returns list of names for the UI list widget."""
        return [q["name"] for q in self._visible_quizzes()]

    def get_quiz_summaries(self):
        return [
            {
                **quiz,
                **self.repo.get_quiz_progress_summary(quiz["file"], self.user_id),
            }
            for quiz in self._visible_quizzes()
        ]

    def get_quiz_summary(self, name):
        return next((quiz for quiz in self.get_quiz_summaries() if quiz["name"] == name), None)

    def is_quiz_complete(self, name):
        summary = self.get_quiz_summary(name)
        return bool(summary and summary["total"] > 0 and summary["mastered"] == summary["total"])

    def reset_quiz_progress(self, name):
        quiz = next((item for item in self._visible_quizzes() if item["name"] == name), None)
        if not quiz:
            logger.warning("Cannot reset progress: quiz '%s' was not found", name)
            return False
        reset = self.repo.reset_quiz_progress(quiz["file"], self.user_id)
        logger.info("Quiz progress reset requested for '%s' by user '%s': %s", name, self.user_id, reset)
        return reset

    def clear_all_progress(self):
        removed = self.repo.clear_user_progress(self.user_id)
        logger.info("All quiz progress cleared for user '%s' (%d quizzes)", self.user_id, removed)
        return removed

    def load_quiz_by_name(self, name):
        """Initializes a new quiz session."""
        quizzes = self._visible_quizzes()
        meta = next((q for q in quizzes if q["name"] == name), None)

        if meta:
            if meta.get("moderation_status") == "banned":
                logger.warning("Blocked attempt to study banned quiz '%s'", name)
                return None
            self.current_quiz_info = meta
            self.current_quiz_path = meta["file"]
            questions = self.repo.load_quiz_questions(meta["file"])

            if not questions:
                logger.error(f"No questions loaded for quiz: {name}")
                return None

            self.quiz_progress = self.repo.get_quiz_progress(self.current_quiz_path, self.user_id)
            learning_questions = [
                question
                for question in questions
                if not self.quiz_progress.get(question.get("id"), {}).get("mastered", False)
            ]
            self.quiz = Quiz(learning_questions, shuffle=True)
            self.user_answers = {}

            logger.info(
                "Loaded quiz '%s' for user '%s': %d total, %d learning questions",
                name, self.user_id, len(questions), len(learning_questions),
            )
            return self._get_current_card_data()

        logger.error(f"Quiz not found: {name}")
        return None

    def submit_answer(self, user_input):
        """Grades and saves the answer, then determines next step."""
        current_card = self.quiz.get_current()
        current_id = current_card.id
        current_q = current_card.question

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
            "correct_answer": correct
        }

        is_correct = self._check_logic(self.user_answers[current_id])
        self._record_attempt(current_id, is_correct)

        logger.info(
            "Recorded %s attempt for quiz question '%s' (session answers: %d)",
            "correct" if is_correct else "wrong", current_id, len(self.user_answers),
        )

        # Determine navigation
        if self.quiz.index >= len(self.quiz.cards) - 1:
            return {"type": "review", "next_card": None}

        self.quiz.next()
        return {"type": "standard", "next_card": self._get_current_card_data()}

    def get_progress_text(self):
        if not self.quiz:
            return ""
        from src.logic.translator import get_translator
        t = get_translator()
        return t.t("quiz_view.progress_text",
                   current=self.quiz.index + 1,
                   total=len(self.quiz.cards))

    def get_navigation_status(self):
        """Tells the UI which buttons to show/hide."""
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
            })

        total = len(self.quiz.cards)
        percent = (correct_count / total) * 100 if total > 0 else 0
        return {
            "score": correct_count,
            "total": total,
            "percent": round(percent, 1),
            "results": results
        }

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
        from src.storage.moderation_repository import ModerationRepository
        content = {
            item["file"]: item
            for item in ModerationRepository(quizzes=self.repo).get_content_for_selector(
                self.user_id, self.role
            )
            if item["kind"] == "quiz"
        }
        return [
            {
                **quiz,
                "moderation_status": content[quiz["file"]]["status"],
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
            data["prompts"] = [t.t("quiz_view.step_label", number=i+1) for i in range(len(card.answer))]
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
            return self._get_current_card_data()
        return None

    def jump_to(self, index):
        """Used by the Review panel to edit a specific question."""
        if 0 <= index < len(self.quiz.cards):
            self.quiz.index = index
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
