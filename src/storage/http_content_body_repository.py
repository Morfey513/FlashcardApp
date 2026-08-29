"""Authenticated desktop adapter for relational question/card bodies."""


class HttpContentBodyRepository:
    def __init__(self, user_repository):
        self.user_repository = user_repository

    def get_quiz(self, quiz_id):
        return self._get("quiz", quiz_id)

    def get_quiz_result(self, quiz_id):
        return self._get_result("quiz", quiz_id)

    def get_flashcard_deck(self, deck_id):
        return self._get("flashcard", deck_id)

    def get_flashcard_deck_result(self, deck_id):
        return self._get_result("flashcard", deck_id)

    def get_practice_package(self, kind, content_id):
        status, body = self.get_practice_package_result(kind, content_id)
        return dict(body) if status == 200 and isinstance(body, dict) else None

    def get_practice_package_result(self, kind, content_id):
        return self.user_repository._request(
            "GET", f"/api/v1/content/practice-packages/{kind}/{content_id}",
            authenticated=True,
        )

    def get_media_manifest(self, kind, content_id):
        status, body = self.get_media_manifest_result(kind, content_id)
        return dict(body) if status == 200 and isinstance(body, dict) else None

    def get_media_manifest_result(self, kind, content_id):
        return self.user_repository._request(
            "GET", f"/api/v1/content/media-manifests/{kind}/{content_id}",
            authenticated=True,
        )

    def get_media_bytes_result(self, kind, content_id, media_id, content_version):
        return self.user_repository._request_bytes(
            "GET",
            f"/api/v1/content/media/{kind}/{content_id}/{media_id}"
            f"?expected_content_version={int(content_version)}",
            authenticated=True,
        )

    def save_quiz(self, source):
        return self._save("quiz", source)

    def save_flashcard_deck(self, source):
        return self._save("flashcard", source)

    def _get(self, kind, content_id):
        status, body = self._get_result(kind, content_id)
        return dict(body) if status == 200 and isinstance(body, dict) else None

    def _get_result(self, kind, content_id):
        status, body = self.user_repository._request(
            "GET", f"/api/v1/content/bodies/{kind}/{content_id}", authenticated=True
        )
        return status, body

    def _save(self, kind, source):
        content_id = str(source.get("id", ""))
        status, body = self.user_repository._request(
            "PUT", f"/api/v1/content/bodies/{kind}/{content_id}",
            source, authenticated=True,
        )
        if status == 200 and isinstance(body, dict):
            self.user_repository._content_metadata_cache = {}
            return dict(body)
        return None
