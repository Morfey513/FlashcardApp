"""Authenticated desktop adapter for server-owned content metadata."""

from urllib.parse import urlencode


class HttpContentMetadataRepository:
    def __init__(self, user_repository):
        self.user_repository = user_repository

    def _cache(self):
        return getattr(self.user_repository, "_content_metadata_cache", {})

    def invalidate(self):
        self.user_repository._content_metadata_cache = {}

    def get_all(self, kind=None, scope="available", *, refresh=False):
        key = (str(kind or ""), str(scope))
        cache = self._cache()
        if not refresh and key in cache:
            return [dict(item) for item in cache[key]]
        query = {"scope": scope}
        if kind:
            query["kind"] = kind
        code, body = self.user_repository._request(
            "GET", f"/api/v1/content/metadata?{urlencode(query)}",
            authenticated=True,
        )
        result = [dict(item) for item in body] if code == 200 and isinstance(body, list) else []
        if code == 200 and isinstance(body, list):
            cache[key] = [dict(item) for item in result]
            self.user_repository._content_metadata_cache = cache
        return result

    def refresh(self, kind=None, scope="available"):
        return self.get_all(kind, scope, refresh=True)

    def get_by_id(self, kind, content_id):
        result = self.get_by_id_result(kind, content_id)
        return result[1] if result[0] == 200 else None

    def get_by_id_result(self, kind, content_id):
        code, body = self.user_repository._request(
            "GET", f"/api/v1/content/metadata/{kind}/{content_id}",
            authenticated=True,
        )
        return code, dict(body) if code == 200 and isinstance(body, dict) else body

    def save(self, kind, payload):
        payload = dict(payload)
        payload.pop("offline_download_allowed", None)
        payload.pop("package_projection", None)
        content_id = str(payload.get("id", ""))
        code, body = self.user_repository._request(
            "PUT", f"/api/v1/content/metadata/{kind}/{content_id}",
            payload, authenticated=True,
        )
        if code == 200 and isinstance(body, dict):
            self.invalidate()
            return dict(body)
        return None

    def delete(self, kind, content_id):
        return self.delete_result(kind, content_id)["status"] == "deleted"

    def delete_result(self, kind, content_id):
        code, _body = self.user_repository._request(
            "DELETE", f"/api/v1/content/metadata/{kind}/{content_id}",
            authenticated=True,
        )
        if 200 <= code < 300:
            self.invalidate()
            return {"status": "deleted", "status_code": code}
        if code == 404:
            self.invalidate()
            return {"status": "not_found", "status_code": code}
        if code in {401, 403}:
            return {"status": "forbidden", "status_code": code}
        return {"status": "failed", "status_code": code}
