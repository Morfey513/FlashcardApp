"""HTTP adapter implementing the desktop user-repository contract."""

import json
import logging
import os
from typing import Dict, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


logger = logging.getLogger(__name__)
API_URL_ENV = "STUDY_BUDDY_API_URL"


class HttpUserRepository:
    """Translate the synchronous desktop contract into local API requests."""

    def __init__(self, base_url: str | None = None, requester=None, timeout: float = 2.0):
        self.base_url = (
            base_url or os.getenv(API_URL_ENV, "http://127.0.0.1:8000")
        ).rstrip("/")
        self._requester = requester or self._urllib_request
        self.timeout = float(timeout)
        self._token: str | None = None
        self._current_user: Dict | None = None
        self._ban_messages: dict[str, str] = {}

    def _headers(self, authenticated: bool) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if authenticated and self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    def _request(self, method: str, path: str, payload=None, authenticated=False):
        return self._requester(method, path, payload, self._headers(authenticated))

    def _urllib_request(self, method: str, path: str, payload, headers):
        body = None
        request_headers = dict(headers)
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            request_headers["Content-Type"] = "application/json"
        request = Request(
            f"{self.base_url}{path}", data=body, headers=request_headers, method=method
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                raw = response.read()
                return response.status, json.loads(raw) if raw else None
        except HTTPError as exc:
            raw = exc.read()
            try:
                detail = json.loads(raw) if raw else None
            except json.JSONDecodeError:
                detail = {"detail": "The server returned an invalid response"}
            return exc.code, detail
        except (URLError, TimeoutError, OSError) as exc:
            logger.error("Study Buddy API request failed: %s", exc)
            return 0, {"detail": "Study Buddy API is unavailable"}

    @staticmethod
    def _detail(body, default: str) -> str:
        return str(body.get("detail", default)) if isinstance(body, dict) else default

    def _accept_session(self, body: dict) -> Dict:
        self._token = str(body["access_token"])
        self._current_user = dict(body["user"])
        return dict(self._current_user)

    def authenticate(self, login: str, password: str) -> Optional[Dict]:
        self._ban_messages.pop(login.casefold(), None)
        code, body = self._request(
            "POST", "/api/v1/auth/login", {"login": login, "password": password}
        )
        if code == 200 and isinstance(body, dict):
            return self._accept_session(body)
        if code == 403:
            self._ban_messages[login.casefold()] = self._detail(body, "Account suspended")
        self._token = None
        self._current_user = None
        return None

    def register(
        self, name: str, login: str, password: str
    ) -> tuple[bool, str, Optional[Dict]]:
        code, body = self._request(
            "POST",
            "/api/v1/auth/register",
            {"name": name, "login": login, "password": password},
        )
        if code == 201 and isinstance(body, dict):
            return True, "Account created", self._accept_session(body)
        return False, self._detail(body, "Unable to create account"), None

    def get_all_users(self) -> list[Dict]:
        code, body = self._request("GET", "/api/v1/admin/users", authenticated=True)
        return [dict(user) for user in body] if code == 200 and isinstance(body, list) else []

    def get_public_users_by_ids(self, user_ids) -> list[Dict]:
        """Resolve roster-safe display identities without administrator access."""
        normalized = [str(user_id) for user_id in user_ids if str(user_id)]
        if not normalized or not self._token:
            return []
        code, body = self._request(
            "POST", "/api/v1/users/profiles", {"user_ids": normalized}, authenticated=True
        )
        return [dict(user) for user in body] if code == 200 and isinstance(body, list) else []

    def get_user_by_id(self, user_id: str) -> Optional[Dict]:
        if self._current_user and str(self._current_user.get("id")) == str(user_id):
            code, body = self._request("GET", "/api/v1/users/me", authenticated=True)
            if code == 200 and isinstance(body, dict):
                self._current_user = dict(body)
                return dict(body)
            return None
        known = next(
            (user for user in self.get_all_users() if str(user.get("id")) == str(user_id)),
            None,
        )
        if known is not None:
            return known
        profiles = self.get_public_users_by_ids([user_id])
        return profiles[0] if profiles else None

    def save_preferences(self, user_id: str, preferences: Dict) -> bool:
        if not self._owns_current_account(user_id):
            return False
        code, body = self._request(
            "PUT",
            "/api/v1/users/me/preferences",
            {"preferences": preferences},
            authenticated=True,
        )
        return self._update_current_user(code, body)

    def update_display_name(self, user_id: str, name: str) -> bool:
        if not self._owns_current_account(user_id):
            return False
        code, body = self._request(
            "PATCH",
            "/api/v1/users/me/display-name",
            {"name": name},
            authenticated=True,
        )
        return self._update_current_user(code, body)

    def change_password(
        self, user_id: str, current_password: str, new_password: str
    ) -> tuple[bool, str]:
        if not self._owns_current_account(user_id):
            return False, "Unable to change password"
        code, body = self._request(
            "POST",
            "/api/v1/users/me/change-password",
            {"current_password": current_password, "new_password": new_password},
            authenticated=True,
        )
        if code == 204:
            return True, "Password changed"
        return False, self._detail(body, "Unable to change password")

    def update_role(self, user_id: str, role: str) -> bool:
        code, _body = self._request(
            "PATCH",
            f"/api/v1/admin/users/{user_id}/role",
            {"role": role},
            authenticated=True,
        )
        return code == 200

    def update_status(self, user_id: str, status: str, reason: str = "") -> bool:
        code, _body = self._request(
            "PATCH",
            f"/api/v1/admin/users/{user_id}/status",
            {"status": status, "reason": reason},
            authenticated=True,
        )
        return code == 200

    def set_account_status(
        self,
        actor_role: str,
        user_id: str,
        status: str,
        reason: str = "",
        actor_id: str | None = None,
    ) -> bool:
        # The API derives the actor from the token instead of trusting these
        # compatibility arguments supplied by the desktop contract.
        return self.update_status(user_id, status, reason)

    def get_ban_message(self, login: str) -> Optional[str]:
        return self._ban_messages.get(login.casefold())

    def is_online(self) -> bool:
        """Return true only when the API and its PostgreSQL dependency are ready."""
        code, body = self._request("GET", "/ready")
        return code == 200 and isinstance(body, dict) and body.get("status") == "ready"

    def logout(self) -> bool:
        if not self._token:
            self._current_user = None
            return True
        code, _body = self._request("POST", "/api/v1/auth/logout", authenticated=True)
        self._token = None
        self._current_user = None
        return code == 204

    def _owns_current_account(self, user_id: str) -> bool:
        return bool(
            self._current_user
            and str(self._current_user.get("id")) == str(user_id)
            and self._token
        )

    def _update_current_user(self, code: int, body) -> bool:
        if code != 200 or not isinstance(body, dict):
            return False
        self._current_user = dict(body)
        return True
