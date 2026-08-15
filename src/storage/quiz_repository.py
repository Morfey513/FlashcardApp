import json
import logging
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

from src.config import QUIZ_DIR, QUIZ_INDEX
from src.logic.question_types import normalize_matching_pairs
from src.logic.test_settings import normalize_test_settings
from src.utils.paths import resolve_stored_path, to_stored_path

logger = logging.getLogger(__name__)

QUIZ_FILENAME = "quiz.json"
MEDIA_FOLDER = "media"
PROGRESS_FOLDER = "progress"
ATTEMPTS_FOLDER = "attempts"


class QuizRepository:
    """Owns all filesystem details for quizzes."""

    def __init__(self, quiz_dir: Path = QUIZ_DIR, index_path: Path = QUIZ_INDEX):
        self.quiz_data_folder = Path(quiz_dir)
        self.index_path = Path(index_path)
        self.quiz_data_folder.mkdir(parents=True, exist_ok=True)
        self.index_path.parent.mkdir(parents=True, exist_ok=True)

    def get_all_quizzes(self):
        if not self.index_path.exists():
            return self._rebuild_index_from_disk()
        try:
            quizzes = self._read_json(self.index_path)
            cleaned = [
                quiz for quiz in quizzes
                if self._resolve_path(quiz.get("file")).exists()
            ]
            if cleaned != quizzes:
                self._save_index(cleaned)
            return cleaned
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            logger.error("Failed to load quiz index: %s", exc)
            return self._rebuild_index_from_disk()

    def _rebuild_index_from_disk(self):
        quizzes = []
        for file in self.quiz_data_folder.glob(f"*/{QUIZ_FILENAME}"):
            try:
                data = self._read_json(file)
                quizzes.append({
                    "id": data.get("id", file.parent.name),
                    "name": data.get("name", file.parent.name),
                    "file": to_stored_path(file),
                })
            except (OSError, json.JSONDecodeError, TypeError) as exc:
                logger.warning("Skipping invalid quiz %s: %s", file, exc)
        self._save_index(quizzes)
        return quizzes

    def load_quiz_questions(self, relative_path: str):
        file = self._resolve_path(relative_path)
        if not file or not file.exists():
            return []
        try:
            data = self._read_json(file)
            questions = data.get("questions", []) if isinstance(data, dict) else data
            changed = self._normalize_questions(questions)
            if changed:
                self.save_quiz_content(relative_path, questions)
            return questions
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            logger.error("Failed to load quiz %s: %s", relative_path, exc)
            return []

    def save_quiz_content(self, relative_path: str, questions: list, test_settings=None):
        file = self._resolve_path(relative_path)
        metadata = self._read_json(file) if file.exists() else {}
        self._normalize_questions(questions)
        self._write_quiz(
            file,
            metadata.get("id", file.parent.name),
            metadata.get("name", file.parent.name),
            questions,
            metadata.get("moderation"),
            normalize_test_settings(
                metadata.get("test_settings") if test_settings is None else test_settings
            ),
        )

    def create_quiz(self, name, questions=None, owner_id=None, test_settings=None):
        if any(quiz["name"] == name for quiz in self.get_all_quizzes()):
            return False
        quiz_id = str(uuid.uuid4())
        quiz_dir = self.quiz_data_folder / quiz_id
        quiz_dir.mkdir(parents=True)
        (quiz_dir / MEDIA_FOLDER).mkdir()
        file = quiz_dir / QUIZ_FILENAME
        questions = questions or []
        self._normalize_questions(questions)
        moderation = None
        if owner_id is not None:
            moderation = {
                "owner_id": str(owner_id), "status": "draft", "visibility": "private",
                "allowed_user_ids": [], "reviewed_by": None, "reviewed_at": None,
                "review_note": "",
            }
        self._write_quiz(
            file, quiz_id, name, questions, moderation,
            normalize_test_settings(test_settings),
        )
        quizzes = self.get_all_quizzes()
        quizzes.append({"id": quiz_id, "name": name, "file": to_stored_path(file)})
        self._save_index(quizzes)
        return True

    def copy_quiz(self, original_name, new_name, owner_id=None):
        original = self._find_by_name(original_name)
        if not original:
            return False
        copied = []
        for question in self.load_quiz_questions(original["file"]):
            item = question.copy()
            item["id"] = str(uuid.uuid4())
            copied.append(item)
        return self.create_quiz(
            new_name, copied, owner_id,
            test_settings=self.get_test_settings(original["file"]),
        )

    def get_test_settings(self, quiz_relative_path):
        file = self._resolve_path(quiz_relative_path)
        if not file or not file.exists():
            return normalize_test_settings()
        try:
            return normalize_test_settings(self._read_json(file).get("test_settings"))
        except (OSError, json.JSONDecodeError, TypeError):
            return normalize_test_settings()

    def delete_quiz(self, name: str):
        quiz = self._find_by_name(name)
        if not quiz:
            return False
        file = self._resolve_path(quiz["file"])
        if file.parent.parent == self.quiz_data_folder and file.parent.exists():
            shutil.rmtree(file.parent)
        self._save_index([
            item for item in self.get_all_quizzes() if item["name"] != name
        ])
        return True

    def import_media(self, quiz_relative_path: str, source_path: str) -> str:
        source = Path(source_path)
        if not source.exists():
            return str(source_path)
        media_dir = self._resolve_path(quiz_relative_path).parent / MEDIA_FOLDER
        media_dir.mkdir(parents=True, exist_ok=True)
        target = media_dir / source.name
        counter = 2
        while target.exists() and source.resolve() != target.resolve():
            target = media_dir / f"{source.stem}_{counter}{source.suffix}"
            counter += 1
        if not target.exists():
            shutil.copy2(source, target)
        return to_stored_path(target)

    def get_quiz_progress(self, quiz_relative_path, user_id="guest"):
        file = self._progress_file(quiz_relative_path, user_id)
        if not file.exists():
            logger.debug("No saved quiz progress for user '%s' at %s", user_id, file)
            return {}
        try:
            progress = self._read_json(file)
            logger.debug(
                "Loaded progress for user '%s' from %s (%d question records)",
                user_id, file, len(progress),
            )
            return progress
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            logger.error("Failed to load quiz progress %s: %s", file, exc)
            return {}

    def save_quiz_progress(self, quiz_relative_path, progress_data, user_id="guest"):
        file = self._progress_file(quiz_relative_path, user_id)
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(json.dumps(progress_data, indent=4), encoding="utf-8")
        logger.debug(
            "Saved progress for user '%s' to %s (%d question records)",
            user_id, file, len(progress_data),
        )

    def get_quiz_progress_summary(self, quiz_relative_path, user_id="guest"):
        questions = self.load_quiz_questions(quiz_relative_path)
        progress = self.get_quiz_progress(quiz_relative_path, user_id)
        total = len(questions)
        mastered = sum(
            1
            for question in questions
            if progress.get(question.get("id"), {}).get("mastered", False)
        )
        return {
            "mastered": mastered,
            "total": total,
            "percent": round((mastered / total) * 100) if total else 0,
            "has_progress": bool(progress),
        }

    def reset_quiz_progress(self, quiz_relative_path, user_id="guest"):
        file = self._progress_file(quiz_relative_path, user_id)
        if not file.exists():
            logger.info("No quiz progress to reset for user '%s' at %s", user_id, file)
            return False
        file.unlink()
        logger.info("Reset quiz progress for user '%s' at %s", user_id, file)
        return True

    def clear_user_progress(self, user_id="guest"):
        removed = 0
        for quiz in self.get_all_quizzes():
            if self.reset_quiz_progress(quiz["file"], user_id):
                removed += 1
        logger.info("Cleared progress for user '%s' from %d quizzes", user_id, removed)
        return removed

    def save_test_attempt(self, quiz_relative_path, attempt):
        """Persist a new test-attempt record inside its quiz folder."""
        quiz_file = self._resolve_path(quiz_relative_path)
        folder = quiz_file.parent / ATTEMPTS_FOLDER
        folder.mkdir(parents=True, exist_ok=True)
        payload = dict(attempt)
        payload.setdefault("id", str(uuid.uuid4()))
        payload.setdefault("created_at", datetime.now(timezone.utc).isoformat())
        if payload.get("status") not in {"in_progress", "abandoned"}:
            payload.setdefault("submitted_at", datetime.now(timezone.utc).isoformat())
        (folder / f"{payload['id']}.json").write_text(
            json.dumps(payload, indent=4), encoding="utf-8"
        )
        return payload

    def update_test_attempt(self, quiz_relative_path, attempt_id, changes):
        """Update one attempt as it moves through its explicit lifecycle."""
        quiz_file = self._resolve_path(quiz_relative_path)
        file = quiz_file.parent / ATTEMPTS_FOLDER / f"{attempt_id}.json"
        if not file.exists():
            return None
        try:
            payload = self._read_json(file)
            payload.update(dict(changes))
            file.write_text(json.dumps(payload, indent=4), encoding="utf-8")
            return payload
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            logger.error("Failed to update test attempt %s: %s", attempt_id, exc)
            return None

    def get_test_attempt(self, quiz_relative_path, attempt_id):
        quiz_file = self._resolve_path(quiz_relative_path)
        file = quiz_file.parent / ATTEMPTS_FOLDER / f"{attempt_id}.json"
        if not file.exists():
            return None
        try:
            return self._read_json(file)
        except (OSError, json.JSONDecodeError, TypeError):
            return None

    def resolve_test_attempt(self, quiz_relative_path, attempt_id, action, actor_id):
        """Resolve an interrupted attempt by grading, refunding, or assigning zero."""
        attempt = self.get_test_attempt(quiz_relative_path, attempt_id)
        if not attempt or attempt.get("status") not in {"in_progress", "abandoned"}:
            return None
        now = datetime.now(timezone.utc).isoformat()
        resolution = {
            "resolved_at": now,
            "resolved_by": str(actor_id),
            "resolution": action,
        }
        if action == "refund":
            resolution.update({"status": "refunded", "counts_toward_limit": False})
        elif action in {"submit_current", "mark_zero"}:
            total = max(0, int(attempt.get("total", 0) or 0))
            answers = attempt.get("answers", []) if isinstance(attempt.get("answers"), list) else []
            score = 0 if action == "mark_zero" else sum(
                1 for answer in answers if answer.get("is_correct") is True
            )
            percentage = round((score / total) * 100, 1) if total else 0.0
            passing = attempt.get("passing_grade_percent")
            resolution.update({
                "status": "marked_zero" if action == "mark_zero" else "submitted",
                "submitted_at": now,
                "score": score,
                "percentage": percentage,
                "passed": percentage >= passing if passing is not None else None,
                "counts_toward_limit": True,
            })
        else:
            return None
        return self.update_test_attempt(quiz_relative_path, attempt_id, resolution)

    def get_test_attempts(self, quiz_relative_path, user_id=None):
        folder = self._resolve_path(quiz_relative_path).parent / ATTEMPTS_FOLDER
        if not folder.exists():
            return []
        attempts = []
        for file in folder.glob("*.json"):
            try:
                attempt = self._read_json(file)
                if user_id is None or str(attempt.get("user_id")) == str(user_id):
                    attempts.append(attempt)
            except (OSError, json.JSONDecodeError, TypeError) as exc:
                logger.warning("Skipping invalid test attempt %s: %s", file, exc)
        return sorted(attempts, key=lambda item: item.get("submitted_at", ""), reverse=True)

    def get_latest_test_attempt(self, quiz_relative_path, user_id):
        attempts = self.get_test_attempts(quiz_relative_path, user_id)
        return attempts[0] if attempts else None

    def prune_progress(self, quiz_relative_path, valid_ids):
        quiz_file = self._resolve_path(quiz_relative_path)
        progress_dir = quiz_file.parent / PROGRESS_FOLDER
        if not progress_dir.exists():
            return
        for file in progress_dir.glob("*.json"):
            progress = self._read_json(file)
            cleaned = {key: value for key, value in progress.items() if key in valid_ids}
            file.write_text(json.dumps(cleaned, indent=4), encoding="utf-8")

    def _normalize_questions(self, questions):
        changed = False
        for question in questions:
            if not question.get("id"):
                question["id"] = str(uuid.uuid4())
                changed = True
            legacy_image = question.pop("image", None)
            if legacy_image is not None:
                if not question.get("image_path"):
                    question["image_path"] = legacy_image
                changed = True
            if question.get("type") == "matching":
                pairs, pairs_changed = normalize_matching_pairs(question.get("pairs", []))
                question["pairs"] = pairs
                changed = changed or pairs_changed
        return changed

    def _find_by_name(self, name):
        return next((item for item in self.get_all_quizzes() if item["name"] == name), None)

    def _progress_file(self, quiz_relative_path, user_id):
        safe_id = "".join(
            char if char.isalnum() or char in "_-" else "_"
            for char in str(user_id or "guest")
        )
        return (
            self._resolve_path(quiz_relative_path).parent
            / PROGRESS_FOLDER
            / f"{safe_id}.json"
        )

    @staticmethod
    def _read_json(file):
        return json.loads(file.read_text(encoding="utf-8"))

    @staticmethod
    def _write_quiz(file, quiz_id, name, questions, moderation=None, test_settings=None):
        file.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "id": quiz_id,
            "name": name,
            "questions": questions,
            "test_settings": normalize_test_settings(test_settings),
        }
        if moderation is not None:
            data["moderation"] = moderation
        file.write_text(json.dumps(data, indent=4), encoding="utf-8")

    def _resolve_path(self, path_value):
        if not path_value:
            return None
        path = Path(path_value)
        return path if path.is_absolute() else resolve_stored_path(path)

    def _save_index(self, quizzes):
        self.index_path.write_text(json.dumps(quizzes, indent=4), encoding="utf-8")
