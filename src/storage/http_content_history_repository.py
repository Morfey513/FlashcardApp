"""Authenticated HTTP adapter for content audit/moderation history."""


class HttpContentHistoryRepository:
    def __init__(self, user_repository):
        self.user_repository = user_repository

    def get_history(self, kind, content_id):
        status, body = self.user_repository._request(
            "GET", f"/api/v1/content/history/{kind}/{content_id}", authenticated=True
        )
        if status == 200 and isinstance(body, dict):
            return {
                "edits": list(body.get("edits") or []),
                "moderation": list(body.get("moderation") or []),
            }
        return {"edits": [], "moderation": []}
