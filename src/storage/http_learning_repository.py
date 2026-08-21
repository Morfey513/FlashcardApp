"""Authenticated desktop adapter for server-owned learning state."""


class HttpLearningRepository:
    def __init__(self, user_repository):
        self.user_repository = user_repository

    def get_progress(self, kind, content_id):
        status, body = self.user_repository._request(
            "GET", f"/api/v1/progress/{kind}/{content_id}", authenticated=True
        )
        if status == 200 and isinstance(body, dict):
            return dict(body.get("progress") or {})
        return {}

    def save_progress(self, kind, content_id, progress):
        status, _body = self.user_repository._request(
            "PUT", f"/api/v1/progress/{kind}/{content_id}",
            {"progress": progress}, authenticated=True,
        )
        return status == 200

    def reset_progress(self, kind, content_id):
        status, body = self.user_repository._request(
            "DELETE", f"/api/v1/progress/{kind}/{content_id}", authenticated=True
        )
        return bool(status == 200 and isinstance(body, dict) and body.get("removed"))

    def clear_progress(self, kind):
        status, body = self.user_repository._request(
            "DELETE", f"/api/v1/progress/{kind}", authenticated=True
        )
        return int(body.get("removed", 0)) if status == 200 and isinstance(body, dict) else 0

    def get_quiz_attempts(self, quiz_id):
        status, body = self.user_repository._request(
            "GET", f"/api/v1/quizzes/{quiz_id}/attempts", authenticated=True
        )
        return [dict(item) for item in body] if status == 200 and isinstance(body, list) else []

    def save_quiz_attempt(self, source):
        quiz_id = str(source.get("quiz_id", ""))
        attempt_id = str(source.get("id", ""))
        if not quiz_id or not attempt_id:
            return False
        allowed = {
            "id", "quiz_id", "mode", "status", "started_at", "submitted_at",
            "score", "total", "percentage", "passed", "answers",
            "counts_toward_limit", "last_activity_at", "attempt_number",
            "interrupted_at", "passing_grade_percent", "duration_seconds",
            "current_question", "answered_count", "resolved_by", "resolved_at", "resolution",
        }
        payload = {key: value for key, value in dict(source).items() if key in allowed}
        status, _body = self.user_repository._request(
            "PUT", f"/api/v1/quizzes/{quiz_id}/attempts/{attempt_id}",
            payload, authenticated=True,
        )
        return status == 200

    def update_quiz_attempt(self, quiz_id, attempt_id, changes):
        current = next(
            (item for item in self.get_quiz_attempts(quiz_id) if item.get("id") == attempt_id),
            None,
        )
        if current is None:
            return None
        current.update(dict(changes))
        return current if self.save_quiz_attempt(current) else None
