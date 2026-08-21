"""Authenticated desktop adapter for relational question/card bodies."""


class HttpContentBodyRepository:
    def __init__(self, user_repository):
        self.user_repository = user_repository

    def get_quiz(self, quiz_id):
        return self._get("quiz", quiz_id)

    def get_flashcard_deck(self, deck_id):
        return self._get("flashcard", deck_id)

    def save_quiz(self, source):
        return self._save("quiz", source)

    def save_flashcard_deck(self, source):
        return self._save("flashcard", source)

    def _get(self, kind, content_id):
        status, body = self.user_repository._request(
            "GET", f"/api/v1/content/bodies/{kind}/{content_id}", authenticated=True
        )
        return dict(body) if status == 200 and isinstance(body, dict) else None

    def _save(self, kind, source):
        content_id = str(source.get("id", ""))
        status, body = self.user_repository._request(
            "PUT", f"/api/v1/content/bodies/{kind}/{content_id}",
            source, authenticated=True,
        )
        return dict(body) if status == 200 and isinstance(body, dict) else None
