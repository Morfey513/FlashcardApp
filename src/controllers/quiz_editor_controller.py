# src/controllers/quiz_editor_controller.py

import logging
from pathlib import Path
import uuid

from src.utils.paths import resolve_stored_path, to_stored_path
from src.logic.access_control import (
    can_create_content,
    can_edit_content,
    is_visibility,
    visibility_submission_status,
)
from src.logic.test_settings import normalize_test_settings
from src.storage.repository_factory import (
    create_class_repository,
    create_moderation_repository,
    create_quiz_repository,
)

logger = logging.getLogger(__name__)


class QuizEditorController:
    def __init__(
        self, owner_id="legacy", role="teacher", user_repository=None,
        repo=None, moderation=None, class_repository=None,
    ):
        self.repo = repo or create_quiz_repository(user_repository)
        self.moderation = moderation or create_moderation_repository(
            user_repository, quizzes=self.repo
        )
        self.invitations = class_repository or create_class_repository(
            user_repository, self.moderation
        )
        self.owner_id = str(owner_id)
        self.role = role
        self.current_quiz_info = None
        self.current_questions = []
        self.has_unsaved_changes = False
        self._editable_by_name = {}

    def get_quiz_names(self):
        """Get list of all quiz names."""
        return [q["name"] for q in self._editable_quizzes()]

    def get_quiz_entries(self):
        """Editable quiz rows with their lifecycle status for the editor menu."""
        metadata = {
            item["file"]: item for item in self._moderation_items()
        }
        rows = [
            {**quiz, "status": metadata[quiz["file"]]["status"],
             "visibility": metadata[quiz["file"]].get("visibility", "private"),
             "moderation_reason": metadata[quiz["file"]].get("review_note", "")}
            for quiz in self._editable_quizzes()
        ]
        self._editable_by_name = {row["name"]: row for row in rows}
        return rows

    def get_current_moderation(self):
        """Return lifecycle details for the quiz currently open in the editor."""
        if not self.current_quiz_info:
            return {}
        for item in self._moderation_items():
            if item["file"] == self.current_quiz_info["file"]:
                return item
        return {}

    def get_current_invite_code(self):
        if not self.current_quiz_info:
            return ""
        return self.invitations.get_invitation(
            self.current_quiz_info["file"], "quiz"
        ).get("code", "")

    def get_current_test_settings(self):
        if not self.current_quiz_info:
            return normalize_test_settings()
        metadata = self.get_current_moderation()
        if metadata:
            return normalize_test_settings(metadata.get("test_settings"))
        return self.repo.get_test_settings(self.current_quiz_info["file"])

    def generate_or_rotate_invite_code(self):
        if not self.current_quiz_info:
            return False, "Open a quiz before generating an invitation code."
        return self.invitations.generate_or_rotate_code(
            self.current_quiz_info["file"], "quiz", self.owner_id
        )

    def get_invite_code(self, name):
        quiz = next((item for item in self._editable_quizzes() if item["name"] == name), None)
        return self.invitations.get_invitation(quiz["file"], "quiz").get("code", "") if quiz else ""

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
        self.current_quiz_info = self._editable_by_name.get(name)
        if self.current_quiz_info is None:
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

    def save_quiz(self, questions, valid_ids, visibility="private", test_settings=None):
        """Save private work or submit public/class-only work for review."""
        try:
            if not self.current_quiz_info:
                return False
            if not is_visibility(visibility):
                return False

            for q in questions:
                if 'id' not in q or not q['id']:
                    q['id'] = str(uuid.uuid4())

            save_actor = {"actor_id": self.owner_id, "actor_role": self.role}
            if getattr(self.repo, "supports_deferred_editor_metadata", False):
                save_actor["defer_metadata"] = bool(
                    self.current_quiz_info.get("source_path")
                )
            saved = self.repo.save_quiz_content(
                self.current_quiz_info["file"], questions,
                normalize_test_settings(test_settings),
                **save_actor,
            )
            # Legacy JSON repositories return None after a successful write;
            # HTTP repositories return an explicit boolean.
            if saved is False:
                return False
            self.repo.prune_progress(self.current_quiz_info["file"], set(valid_ids))
            status = visibility_submission_status(visibility)
            current = self.current_quiz_info
            if current.get("source_path"):
                current["test_settings"] = normalize_test_settings(test_settings)
                moderated = self.moderation.update_status(
                    current, status, self.owner_id, visibility=visibility,
                    actor_role=self.role,
                )
            else:
                moderated = self.moderation.set_content_status(
                    current["file"], "quiz", status, self.owner_id,
                    visibility=visibility, actor_role=self.role,
                )
            if not moderated:
                return False
            current.update({"status": status, "visibility": visibility})
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
        if not can_create_content(self.role):
            return False
        return self.repo.create_quiz(
            name, owner_id=self.owner_id, actor_role=self.role
        )

    def copy_quiz(self, original_name, new_name):
        original = self._editable_by_name.get(original_name)
        if original is None:
            original = next(
                (quiz for quiz in self._editable_quizzes() if quiz["name"] == original_name),
                None,
            )
        if not original or not can_edit_content(
            self.role,
            str(self.get_current_owner(original)) == self.owner_id,
        ):
            return False
        copy_item = getattr(self.repo, "copy_quiz_item", None)
        if callable(copy_item):
            return copy_item(
                original, new_name, self.owner_id, actor_role=self.role
            )
        return self.repo.copy_quiz(
            original_name, new_name, self.owner_id, actor_role=self.role
        )

    def get_current_edit_history(self):
        if not self.current_quiz_info:
            return []
        return self.repo.get_edit_history(self.current_quiz_info["file"])

    def get_current_owner(self, quiz):
        if quiz.get("owner_id") is not None:
            return str(quiz["owner_id"])
        item = next(
            (entry for entry in self._moderation_items() if entry["file"] == quiz["file"]),
            {},
        )
        return str(item.get("owner_id", ""))

    def _editable_quizzes(self):
        if self.role not in {"teacher", "admin"}:
            return []
        items = self._moderation_items()
        allowed = {
            item["file"] for item in items
            if item["kind"] == "quiz"
            and (self.role == "admin" or str(item["owner_id"]) == self.owner_id)
        }
        owned_items = getattr(self.repo, "get_owned_content_items", None)
        if self.role == "teacher" and callable(owned_items):
            rows = [{**item, "file": item["file"]} for item in items]
        else:
            rows = (self.repo.get_owned_quizzes()
                    if hasattr(self.repo, "get_owned_quizzes")
                    else self.repo.get_all_quizzes())
        return [quiz for quiz in rows if quiz["file"] in allowed]

    def _moderation_items(self):
        owned_items = getattr(self.repo, "get_owned_content_items", None)
        if self.role == "teacher" and callable(owned_items):
            return owned_items()
        return self.moderation.get_all_content(kind="quiz")

    def delete_quiz(self, name):
        return self.delete_quiz_result(name)["status"] == "deleted"

    def delete_quiz_result(self, name):
        quiz = self._editable_by_name.get(name)
        if quiz is None:
            quiz = next((item for item in self._editable_quizzes() if item["name"] == name), None)
        if not quiz or not can_edit_content(
            self.role,
            self.get_current_owner(quiz) == self.owner_id,
        ):
            return {"status": "forbidden", "status_code": None}
        delete_item = getattr(self.repo, "delete_quiz_item_result", None)
        if callable(delete_item):
            return delete_item(quiz)
        delete_result = getattr(self.repo, "delete_quiz_result", None)
        if callable(delete_result):
            return delete_result(name)
        return {
            "status": "deleted" if self.repo.delete_quiz(name) else "failed",
            "status_code": None,
        }
