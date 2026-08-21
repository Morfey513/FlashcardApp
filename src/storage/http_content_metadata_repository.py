"""Authenticated desktop adapter for server-owned content metadata."""

from urllib.parse import urlencode


class HttpContentMetadataRepository:
    def __init__(self, user_repository):
        self.user_repository = user_repository

    def get_all(self, kind=None, scope="available"):
        query = {"scope": scope}
        if kind:
            query["kind"] = kind
        code, body = self.user_repository._request(
            "GET", f"/api/v1/content/metadata?{urlencode(query)}",
            authenticated=True,
        )
        return [dict(item) for item in body] if code == 200 and isinstance(body, list) else []

    def get_by_id(self, kind, content_id):
        code, body = self.user_repository._request(
            "GET", f"/api/v1/content/metadata/{kind}/{content_id}",
            authenticated=True,
        )
        return dict(body) if code == 200 and isinstance(body, dict) else None

    def save(self, kind, payload):
        content_id = str(payload.get("id", ""))
        code, body = self.user_repository._request(
            "PUT", f"/api/v1/content/metadata/{kind}/{content_id}",
            payload, authenticated=True,
        )
        return dict(body) if code == 200 and isinstance(body, dict) else None

    def delete(self, kind, content_id):
        code, _body = self.user_repository._request(
            "DELETE", f"/api/v1/content/metadata/{kind}/{content_id}",
            authenticated=True,
        )
        return code == 200
