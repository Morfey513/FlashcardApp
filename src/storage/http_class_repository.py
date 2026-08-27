"""Authenticated HTTP adapter for class invitations and membership."""

from urllib.parse import urlencode

from src.storage.http_content_body_repository import HttpContentBodyRepository
from src.storage.http_content_metadata_repository import HttpContentMetadataRepository


class HttpClassRepository:
    def __init__(self, user_repository):
        self.user_repository = user_repository

    def enroll_with_code(self, code, _user_id=None):
        status, body = self.user_repository._request(
            "POST", "/api/v1/classes/join", {"code": code}, authenticated=True
        )
        if status == 200:
            return True, body.get("message", "Enrollment completed.")
        detail = body.get("detail", "Enrollment failed.") if isinstance(body, dict) else "Enrollment failed."
        return False, str(detail)

    def get_owned_classes(self, _owner_id=None, kind="all"):
        key = str(kind)
        cache = getattr(self.user_repository, "_owned_classes_cache", {})
        if key in cache:
            return [dict(item) for item in cache[key]]
        query = "" if kind == "all" else f"?{urlencode({'kind': kind})}"
        status, body = self.user_repository._request(
            "GET", f"/api/v1/classes/owned{query}", authenticated=True
        )
        result = [dict(item) for item in body] if status == 200 and isinstance(body, list) else []
        if status == 200 and isinstance(body, list):
            cache[key] = [dict(item) for item in result]
            self.user_repository._owned_classes_cache = cache
        return result

    def get_invitation(self, relative_path, kind):
        content_id = self._content_id(relative_path)
        status, body = self.user_repository._request(
            "GET", f"/api/v1/classes/{kind}/{content_id}/invitation",
            authenticated=True,
        )
        if status == 200 and isinstance(body, dict):
            return {"code": str(body.get("code", ""))}
        return {}

    def generate_or_rotate_code(self, relative_path, kind, _owner_id=None):
        # The API identifies content by stable ID. The transitional caller may
        # pass either that ID directly or a local JSON path containing it.
        content_id = self._content_id(relative_path)
        status, body = self.user_repository._request(
            "POST", f"/api/v1/classes/{kind}/{content_id}/invitation/rotate",
            authenticated=True,
        )
        if status == 200:
            return True, body.get("code", "")
        detail = body.get("detail", "Code rotation failed.") if isinstance(body, dict) else "Code rotation failed."
        return False, str(detail)

    def remove_enrollment(self, relative_path, kind, _owner_id, student_id):
        content_id = self._content_id(relative_path)
        status, body = self.user_repository._request(
            "DELETE", f"/api/v1/classes/{kind}/{content_id}/members/{student_id}",
            authenticated=True,
        )
        if status == 200:
            return True, body.get("message", "Student access removed.")
        detail = body.get("detail", "Access removal failed.") if isinstance(body, dict) else "Access removal failed."
        return False, str(detail)

    def get_student_attempts(self, relative_path, _owner_id, student_id):
        content_id = self._content_id(relative_path)
        status, body = self.user_repository._request(
            "GET", f"/api/v1/classes/quiz/{content_id}/students/{student_id}/attempts",
            authenticated=True,
        )
        return [dict(item) for item in body] if status == 200 and isinstance(body, list) else []

    def resolve_attempt(self, relative_path, _owner_id, attempt_id, action):
        content_id = self._content_id(relative_path)
        status, body = self.user_repository._request(
            "POST", f"/api/v1/classes/quiz/{content_id}/attempts/{attempt_id}/resolve",
            {"action": action}, authenticated=True,
        )
        if status == 200:
            return True, "Attempt resolved."
        detail = body.get("detail", "Attempt could not be resolved.") if isinstance(body, dict) else "Attempt could not be resolved."
        return False, str(detail)

    def update_answer_review_policy(self, relative_path, _owner_id, policy):
        if policy not in {"immediate", "after_due_date", "never"}:
            return False
        content_id = self._content_id(relative_path)
        metadata_repo = HttpContentMetadataRepository(self.user_repository)
        metadata = metadata_repo.get_by_id("quiz", content_id)
        if metadata is None:
            return False
        settings = dict(metadata.get("test_settings") or {})
        settings["answer_review_policy"] = policy
        payload = {
            "id": content_id, "name": metadata["name"],
            "status": metadata["status"], "visibility": metadata["visibility"],
            "source_path": metadata["source_path"], "test_settings": settings,
        }
        return metadata_repo.save("quiz", payload) is not None

    def get_quiz_analytics(self, relative_path, owner_id):
        content_id = self._content_id(relative_path)
        body = HttpContentBodyRepository(self.user_repository).get_quiz(content_id) or {}
        classes = self.get_owned_classes(owner_id, "quiz")
        classroom = next((row for row in classes if row.get("content_id") == content_id), {})
        attempts = [
            attempt
            for student in classroom.get("roster", [])
            for attempt in self.get_student_attempts(content_id, owner_id, student["user_id"])
            if attempt.get("status") in {"submitted", "timed_out", "marked_zero"}
        ]
        rows = []
        for question in body.get("questions", []):
            answers = [
                answer for attempt in attempts for answer in attempt.get("answers", [])
                if answer.get("question_id") == question.get("id")
                and isinstance(answer.get("is_correct"), bool)
            ]
            correct = sum(1 for answer in answers if answer.get("is_correct") is True)
            rate = round(correct / len(answers) * 100, 1) if answers else None
            timings = [
                answer["response_seconds"] for answer in answers
                if isinstance(answer.get("response_seconds"), (int, float))
            ]
            rows.append({
                "question_id": question.get("id"),
                "question": question.get("question", "Untitled question"),
                "correct": correct, "responses": len(answers), "correct_rate": rate,
                "average_seconds": round(sum(timings) / len(timings), 1) if timings else None,
                "difficulty": "Not rated" if rate is None else "Easy" if rate >= 75 else "Medium" if rate >= 50 else "Hard",
            })
        return rows

    @staticmethod
    def _content_id(value):
        text = str(value).replace("\\", "/").rstrip("/")
        if text.endswith("/quiz.json") or text.endswith("/deck.json"):
            return text.split("/")[-2]
        return text
