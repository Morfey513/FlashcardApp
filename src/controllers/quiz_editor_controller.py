# src/controllers/quiz_editor_controller.py

import logging
from pathlib import Path
import uuid

from src.storage.quiz_repository import QuizRepository
from src.utils.paths import resolve_stored_path, to_stored_path

logger = logging.getLogger(__name__)


class QuizEditorController:
    def __init__(self, owner_id="legacy", role="teacher"):

        self.repo = QuizRepository()
        self.owner_id = str(owner_id)
        self.role = role
        self.current_quiz_info = None
        self.current_questions = []
        self.has_unsaved_changes = False

    def get_quiz_names(self):
        """Get list of all quiz names."""
        return [q["name"] for q in self._editable_quizzes()]

    def get_quiz_entries(self):
        """Editable quiz rows with their lifecycle status for the editor menu."""
        from src.storage.moderation_repository import ModerationRepository
        metadata = {
            item["file"]: item for item in ModerationRepository(quizzes=self.repo).get_all_content()
        }
        return [
            {**quiz, "status": metadata[quiz["file"]]["status"]}
            for quiz in self._editable_quizzes()
        ]

    def get_current_moderation(self):
        """Return lifecycle details for the quiz currently open in the editor."""
        if not self.current_quiz_info:
            return {}
        for item in self._moderation_items():
            if item["file"] == self.current_quiz_info["file"]:
                return item
        return {}

    def process_image_path(self, absolute_path: str) -> str:
        """Convert absolute path to project-relative path."""
        if self.current_quiz_info:
            return self.repo.import_media(
                self.current_quiz_info["file"], absolute_path
            )
        return to_stored_path(absolute_path)

    def get_absolute_image_path(self, stored_path: str) -> Path:
        """Convert stored path to absolute Path object."""
        return resolve_stored_path(stored_path)

    def load_quiz(self, name):
        """Load a quiz by name."""
        quizzes = self._editable_quizzes()
        self.current_quiz_info = next((q for q in quizzes if q["name"] == name), None)

        if self.current_quiz_info:
            self.current_questions = self.repo.load_quiz_questions(
                self.current_quiz_info["file"]
            )
            self.has_unsaved_changes = False
            logger.info(f"Loaded quiz: {name} with {len(self.current_questions)} questions")
            return True

        logger.error(f"Quiz not found: {name}")
        return False

    def save_quiz(self, questions, valid_ids, submit_for_review=False):
        """Save a draft, or save and submit it to the moderation queue."""
        try:
            if not self.current_quiz_info:
                return False

            for q in questions:
                if 'id' not in q or not q['id']:
                    q['id'] = str(uuid.uuid4())

            self.repo.save_quiz_content(self.current_quiz_info["file"], questions)
            self.repo.prune_progress(self.current_quiz_info["file"], set(valid_ids))
            from src.storage.moderation_repository import ModerationRepository
            status = "pending_review" if submit_for_review else "draft"
            ModerationRepository(quizzes=self.repo).set_content_status(
                self.current_quiz_info["file"], "quiz", status, self.owner_id
            )
            self.has_unsaved_changes = False
            return True
        except Exception as e:
            logger.error(f"Quiz save failed: {e}")
            return False

    def duplicate_question(self, index):
        """Handles the logic of copying a question and assigning a new ID."""
        if 0 <= index < len(self.current_questions):
            q_copy = self.current_questions[index].copy()
            q_copy["id"] = str(uuid.uuid4())
            q_copy["question"] += " (Copy)"
            self.current_questions.append(q_copy)
            self.has_unsaved_changes = True
            return True
        return False

    def delete_question(self, index):
        """Centralized question deletion logic."""
        if 0 <= index < len(self.current_questions):
            del self.current_questions[index]
            self.has_unsaved_changes = True
            return True
        return False

# Standardizing repo wrappers
    def create_new_quiz(self, name):
        return self.repo.create_quiz(name, owner_id=self.owner_id)

    def copy_quiz(self, original_name, new_name):
        return self.repo.copy_quiz(original_name, new_name, self.owner_id)

    def _editable_quizzes(self):
        items = self._moderation_items()
        allowed = {
            item["file"] for item in items
            if item["kind"] == "quiz"
            and (self.role == "admin" or str(item["owner_id"]) == self.owner_id)
        }
        return [quiz for quiz in self.repo.get_all_quizzes() if quiz["file"] in allowed]

    def _moderation_items(self):
        from src.storage.moderation_repository import ModerationRepository
        return ModerationRepository(quizzes=self.repo).get_all_content()

    def delete_quiz(self, name):
        return self.repo.delete_quiz(name)
