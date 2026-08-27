"""Controller-compatible HTTP repositories for authenticated desktop sessions."""

import base64
import copy
import uuid
from datetime import datetime, timezone
from pathlib import Path

from src.logic.test_settings import normalize_test_settings
from src.storage.http_content_body_repository import HttpContentBodyRepository
from src.storage.http_content_history_repository import HttpContentHistoryRepository
from src.storage.http_content_metadata_repository import HttpContentMetadataRepository
from src.storage.http_learning_repository import HttpLearningRepository


def _content_id(value) -> str:
    text = str(value or "").replace("\\", "/").rstrip("/")
    if text.endswith("/quiz.json") or text.endswith("/deck.json"):
        return text.split("/")[-2]
    return text


class _HttpContentRepositoryBase:
    kind = ""
    filename = ""
    supports_offline_download = True
    supports_deferred_editor_metadata = True

    def __init__(self, user_repository):
        self.user_repository = user_repository
        self.metadata = HttpContentMetadataRepository(user_repository)
        self.bodies = HttpContentBodyRepository(user_repository)
        self.learning = HttpLearningRepository(user_repository)
        self.histories = HttpContentHistoryRepository(user_repository)

    def _metadata_rows(self, scope=None):
        role = str((self.user_repository._current_user or {}).get("role", "student"))
        selected_scope = scope or ("all" if role == "admin" else "available")
        return self.metadata.get_all(self.kind, selected_scope)

    def get_owned_content(self):
        return self.metadata.get_all(self.kind, "owned")

    @staticmethod
    def resolve_path(_value):
        return None

    _resolve_path = resolve_path

    @staticmethod
    def _entry(item):
        return {"id": item["id"], "name": item["name"], "file": item["id"],
                "content_version": item.get("content_version"),
                "updated_at": item.get("updated_at")}

    def get_content_items(self):
        return self._content_items(self._metadata_rows())

    def get_owned_content_items(self):
        """Return the editor's owned rows from one actor-scoped metadata request."""
        return self._content_items(self.get_owned_content())

    def _content_items(self, metadata_rows):
        items = []
        for metadata in metadata_rows:
            items.append({
                "id": metadata["id"],
                "kind": self.kind,
                "name": metadata["name"],
                "file": metadata["id"],
                "path": None,
                "owner_id": metadata.get("owner_id") or metadata.get("source_owner_id"),
                "status": metadata.get("status", "draft"),
                "visibility": metadata.get("visibility", "private"),
                "allowed_user_ids": [],
                # The API has already enforced public/class enrollment scope.
                "server_authorized": True,
                "reviewed_by": None,
                "reviewed_at": None,
                "review_note": "",
                "source_path": metadata.get("source_path", ""),
                "updated_at": metadata.get("updated_at"),
                "test_settings": normalize_test_settings(metadata.get("test_settings")),
                "content_version": metadata.get("content_version"),
            })
        return items

    def update_moderation(self, item, status, visibility=None, note=""):
        metadata = item if item.get("source_path") else self.metadata.get_by_id(
            self.kind, _content_id(item["file"])
        )
        if metadata is None:
            return False
        payload = {
            "id": metadata["id"], "name": metadata["name"],
            "status": status,
            "visibility": visibility or metadata["visibility"],
            "source_path": metadata["source_path"],
            "test_settings": metadata.get("test_settings"),
            "review_note": str(note or ""),
        }
        return self.metadata.save(self.kind, payload) is not None

    def get_preview(self, item, limit=None):
        body = self._body(_content_id(item["file"])) or {}
        values = body.get("questions" if self.kind == "quiz" else "cards", [])
        return (values if limit is None else values[:limit], len(values))

    def get_edit_history(self, value):
        return self.histories.get_history(self.kind, _content_id(value))["edits"]

    def import_media(self, content_value, source_path):
        source = Path(source_path)
        if not source.exists():
            return str(source_path)
        status, body = self.user_repository._request(
            "POST", f"/api/v1/content/media/{self.kind}/{_content_id(content_value)}",
            {
                "filename": source.name,
                "content_base64": base64.b64encode(source.read_bytes()).decode("ascii"),
            },
            authenticated=True,
        )
        return str(body.get("stored_path")) if status == 200 and isinstance(body, dict) else str(source_path)


class HttpQuizRepository(_HttpContentRepositoryBase):
    kind = "quiz"
    filename = "quiz.json"

    def get_all_quizzes(self):
        return [self._entry(item) for item in self._metadata_rows()]

    def get_owned_quizzes(self):
        return [self._entry(item) for item in self.get_owned_content()]

    def load_quiz_questions(self, value):
        body = self._body(_content_id(value)) or {}
        return list(body.get("questions") or [])

    def get_quiz_body(self, value):
        return self._body(_content_id(value))

    def start_assessment(self, quiz_id):
        status, body = self.user_repository._request(
            "POST", f"/api/v1/quizzes/{_content_id(quiz_id)}/assessments",
            {}, authenticated=True,
        )
        return dict(body) if status == 200 and isinstance(body, dict) else None

    def get_assessment(self, quiz_id, attempt_id):
        status, body = self.user_repository._request(
            "GET", f"/api/v1/quizzes/{_content_id(quiz_id)}/assessments/{attempt_id}",
            authenticated=True,
        )
        return dict(body) if status == 200 and isinstance(body, dict) else None

    def checkpoint_assessment(self, quiz_id, attempt_id, position, answer):
        status, body = self.user_repository._request(
            "PUT", f"/api/v1/quizzes/{_content_id(quiz_id)}/assessments/{attempt_id}/responses/{int(position)}",
            {"user_answer": answer}, authenticated=True,
        )
        return dict(body) if status == 200 and isinstance(body, dict) else None

    def submit_assessment(self, quiz_id, attempt_id):
        status, body = self.user_repository._request(
            "POST", f"/api/v1/quizzes/{_content_id(quiz_id)}/assessments/{attempt_id}/submit",
            {}, authenticated=True,
        )
        return dict(body) if status == 200 and isinstance(body, dict) else None

    def _body(self, content_id):
        return self.bodies.get_quiz(content_id)

    def save_quiz_content(self, value, questions, test_settings=None, **_actor):
        content_id = _content_id(value)
        metadata = self.metadata.get_by_id("quiz", content_id)
        if metadata is None:
            return False
        saved = self.bodies.save_quiz({
            "id": content_id, "name": metadata["name"], "questions": questions,
        })
        if saved is None:
            return False
        if _actor.get("defer_metadata"):
            return True
        if test_settings is not None:
            payload = {
                "id": content_id, "name": metadata["name"],
                "status": metadata["status"], "visibility": metadata["visibility"],
                "source_path": metadata["source_path"],
                "test_settings": normalize_test_settings(test_settings),
            }
            return self.metadata.save("quiz", payload) is not None
        return True

    def create_quiz(self, name, questions=None, owner_id=None, test_settings=None, **_actor):
        content_id = str(uuid.uuid4())
        payload = {
            "id": content_id, "name": str(name), "status": "draft",
            "visibility": "private", "source_path": f"data/quizzes/{content_id}/quiz.json",
            "test_settings": normalize_test_settings(test_settings),
        }
        if self.metadata.save("quiz", payload) is None:
            return False
        if self.bodies.save_quiz({
            "id": content_id, "name": str(name), "questions": list(questions or []),
        }) is None:
            self.metadata.delete("quiz", content_id)
            return False
        return True

    def copy_quiz(self, original_name, new_name, owner_id=None, **actor):
        original = next((row for row in self.get_all_quizzes() if row["name"] == original_name), None)
        if original is None:
            return False
        questions = copy.deepcopy(self.load_quiz_questions(original["file"]))
        for question in questions:
            question["id"] = str(uuid.uuid4())
        return self.create_quiz(
            new_name, questions, owner_id, self.get_test_settings(original["file"]), **actor
        )

    def copy_quiz_item(self, original, new_name, owner_id=None, **actor):
        questions = copy.deepcopy(self.load_quiz_questions(original["file"]))
        for question in questions:
            question["id"] = str(uuid.uuid4())
        return self.create_quiz(
            new_name, questions, owner_id,
            normalize_test_settings(original.get("test_settings")), **actor,
        )

    def delete_quiz(self, name):
        return self.delete_quiz_result(name)["status"] == "deleted"

    def delete_quiz_result(self, name):
        item = next((row for row in self.get_all_quizzes() if row["name"] == name), None)
        if item is None:
            return {"status": "not_found", "status_code": None}
        return self.metadata.delete_result("quiz", item["id"])

    def delete_quiz_item_result(self, item):
        return self.metadata.delete_result("quiz", _content_id(item["file"]))

    def get_test_settings(self, value):
        item = self.metadata.get_by_id("quiz", _content_id(value))
        return normalize_test_settings(item.get("test_settings") if item else None)

    def get_quiz_progress(self, value, user_id="guest"):
        return self.learning.get_progress("quiz", _content_id(value))

    def get_quiz_progress_items(self, value, user_id="guest"):
        return self.learning.get_progress_items("quiz", _content_id(value))

    def get_progress_summary(self, *, refresh=False):
        return self.learning.get_progress_summary(refresh=refresh)

    def save_quiz_progress(self, value, progress_data, user_id="guest"):
        return self.learning.save_progress("quiz", _content_id(value), progress_data)

    def get_quiz_progress_summary(self, value, user_id="guest"):
        questions = self.load_quiz_questions(value)
        progress = self.get_quiz_progress(value, user_id)
        mastered = sum(1 for row in questions if progress.get(row.get("id"), {}).get("mastered"))
        total = len(questions)
        return {"mastered": mastered, "total": total,
                "percent": round(mastered / total * 100) if total else 0,
                "has_progress": bool(progress)}

    def reset_quiz_progress(self, value, user_id="guest"):
        return self.learning.reset_progress("quiz", _content_id(value))

    def clear_user_progress(self, user_id="guest"):
        return self.learning.clear_progress("quiz")

    def save_test_attempt(self, value, attempt):
        payload = dict(attempt)
        payload.setdefault("id", str(uuid.uuid4()))
        payload.setdefault("quiz_id", _content_id(value))
        payload.setdefault("started_at", datetime.now(timezone.utc).isoformat())
        return payload if self.learning.save_quiz_attempt(payload) else None

    def update_test_attempt(self, value, attempt_id, changes):
        return self.learning.update_quiz_attempt(_content_id(value), attempt_id, changes)

    def get_test_attempt(self, value, attempt_id):
        return next((row for row in self.get_test_attempts(value) if row.get("id") == attempt_id), None)

    def get_test_attempts(self, value, user_id=None):
        attempts = self.learning.get_quiz_attempts(_content_id(value))
        return sorted(
            attempts,
            key=lambda item: str(item.get("submitted_at") or item.get("started_at") or ""),
            reverse=True,
        )

    def get_latest_test_attempt(self, value, user_id):
        attempts = self.get_test_attempts(value, user_id)
        return attempts[0] if attempts else None

    def resolve_test_attempt(self, value, attempt_id, action, actor_id):
        # The server derives the acting user from the bearer token.  Keep the
        # desktop repository contract (resolved attempt or ``None``) while
        # routing through the class moderation endpoint used by API mode.
        del actor_id
        status, body = self.user_repository._request(
            "POST",
            f"/api/v1/classes/quiz/{_content_id(value)}/attempts/{attempt_id}/resolve",
            {"action": action},
            authenticated=True,
        )
        return dict(body) if status == 200 and isinstance(body, dict) else None

    def prune_progress(self, value, valid_ids):
        progress = self.get_quiz_progress(value)
        cleaned = {key: data for key, data in progress.items() if key in set(valid_ids)}
        if cleaned != progress:
            self.save_quiz_progress(value, cleaned)


class HttpFlashcardRepository(_HttpContentRepositoryBase):
    kind = "flashcard"
    filename = "deck.json"

    def get_all_decks(self):
        return [self._entry(item) for item in self._metadata_rows()]

    def get_owned_decks(self):
        return [self._entry(item) for item in self.get_owned_content()]

    def load_deck_cards(self, value):
        body = self._body(_content_id(value)) or {}
        return list(body.get("cards") or [])

    def get_deck_body(self, value):
        return self._body(_content_id(value))

    def _body(self, content_id):
        return self.bodies.get_flashcard_deck(content_id)

    def save_deck_content(self, value, cards, **_actor):
        content_id = _content_id(value)
        metadata = self.metadata.get_by_id("flashcard", content_id)
        return bool(metadata and self.bodies.save_flashcard_deck({
            "id": content_id, "name": metadata["name"], "cards": cards,
        }) is not None)

    def create_deck(self, name, cards=None, owner_id=None, **_actor):
        content_id = str(uuid.uuid4())
        payload = {
            "id": content_id, "name": str(name), "status": "draft",
            "visibility": "private",
            "source_path": f"data/flashcards/{content_id}/deck.json",
        }
        if self.metadata.save("flashcard", payload) is None:
            return False
        if self.bodies.save_flashcard_deck({
            "id": content_id, "name": str(name), "cards": list(cards or []),
        }) is None:
            self.metadata.delete("flashcard", content_id)
            return False
        return True

    def copy_deck(self, original_name, new_name, owner_id=None, **actor):
        original = next((row for row in self.get_all_decks() if row["name"] == original_name), None)
        if original is None:
            return False
        cards = copy.deepcopy(self.load_deck_cards(original["file"]))
        for card in cards:
            card["id"] = str(uuid.uuid4())
        return self.create_deck(new_name, cards, owner_id, **actor)

    def copy_deck_item(self, original, new_name, owner_id=None, **actor):
        cards = copy.deepcopy(self.load_deck_cards(original["file"]))
        for card in cards:
            card["id"] = str(uuid.uuid4())
        return self.create_deck(new_name, cards, owner_id, **actor)

    def delete_deck_permanently(self, name):
        return self.delete_deck_result(name)["status"] == "deleted"

    def delete_deck_result(self, name):
        item = next((row for row in self.get_all_decks() if row["name"] == name), None)
        if item is None:
            return {"status": "not_found", "status_code": None}
        return self.metadata.delete_result("flashcard", item["id"])

    def delete_deck_item_result(self, item):
        return self.metadata.delete_result("flashcard", _content_id(item["file"]))

    def get_progress(self, value, user_id="guest"):
        return self.learning.get_progress("flashcard", _content_id(value))

    def get_progress_items(self, value, user_id="guest"):
        return self.learning.get_progress_items("flashcard", _content_id(value))

    def get_progress_summary(self, *, refresh=False):
        return self.learning.get_progress_summary(refresh=refresh)

    def save_deck_progress(self, value, progress_data, user_id="guest"):
        return self.learning.save_progress("flashcard", _content_id(value), progress_data)

    def get_deck_progress_summary(self, value, user_id="guest"):
        cards = self.load_deck_cards(value)
        progress = self.get_progress(value, user_id)
        mastered = sum(1 for row in cards if progress.get(row.get("id"), {}).get("mastered"))
        total = len(cards)
        return {"mastered": mastered, "total": total,
                "percent": round(mastered / total * 100) if total else 0,
                "has_progress": bool(progress)}

    def reset_deck_progress(self, value, user_id="guest"):
        return self.learning.reset_progress("flashcard", _content_id(value))

    def clear_user_progress(self, user_id="guest"):
        return self.learning.clear_progress("flashcard")

    def prune_progress(self, value, valid_ids):
        progress = self.get_progress(value)
        cleaned = {key: data for key, data in progress.items() if key in set(valid_ids)}
        if cleaned != progress:
            self.save_deck_progress(value, cleaned)
