import hashlib
import hmac
import json
import logging
import secrets
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict

from src.config import USERS_FILE

logger = logging.getLogger(__name__)


class UserRepository:
    """Manages local user accounts without storing plaintext passwords."""

    HASH_NAME = "pbkdf2_sha256"
    HASH_ITERATIONS = 210_000

    def __init__(self, users_file: Path = USERS_FILE):
        self.users_file = users_file
        self._ensure_users_file()

    def _ensure_users_file(self):
        """Create default users or safely migrate legacy plaintext passwords."""
        self.users_file.parent.mkdir(parents=True, exist_ok=True)
        if not self.users_file.exists():
            data = {
                "users": [
                    {"id": "1", "role": "teacher", "login": "admin", "password": "admin123", "name": "Admin User"},
                    {"id": "2", "role": "student", "login": "student", "password": "student123", "name": "Student User"},
                ]
            }
            self._migrate_plaintext_passwords(data)
            self._write_users(data)
            logger.info("Created default users file with password hashes")
            return

        try:
            data = self._read_users()
            if self._migrate_plaintext_passwords(data) or self._normalize_accounts(data):
                self._write_users(data)
                logger.info("Migrated legacy plaintext passwords to PBKDF2 hashes")
        except (OSError, json.JSONDecodeError) as exc:
            logger.error("Unable to prepare users file: %s", exc)

    def authenticate(self, login: str, password: str) -> Optional[Dict]:
        """Authenticate a user and return only non-sensitive account metadata."""
        try:
            for user in self._read_users().get("users", []):
                if user.get("login") != login:
                    continue
                if user.get("status", "active") != "active":
                    logger.warning("Blocked login attempt for disabled account: %s", login)
                    return None
                if self._verify_password(password, user.get("password", "")):
                    logger.info("User authenticated: %s (role: %s)", login, user.get("role"))
                    return {key: value for key, value in user.items() if key != "password"}

            logger.warning("Authentication failed for login: %s", login)
            return None
        except (OSError, json.JSONDecodeError) as exc:
            logger.error("Authentication error: %s", exc)
            return None

    def get_all_users(self):
        """Return user metadata without password hashes."""
        try:
            return [
                {key: value for key, value in user.items() if key != "password"}
                for user in self._read_users().get("users", [])
            ]
        except (OSError, json.JSONDecodeError) as exc:
            logger.error("Error loading users: %s", exc)
            return []

    def register(self, name: str, login: str, password: str) -> tuple[bool, str, Optional[Dict]]:
        """Create a local student account with its own default preferences."""
        name, login = name.strip(), login.strip()
        if not name or not login or not password:
            return False, "Name, login, and password are required", None
        if len(password) < 8:
            return False, "Password must contain at least 8 characters", None
        try:
            data = self._read_users()
            if any(user.get("login", "").casefold() == login.casefold() for user in data.get("users", [])):
                return False, "That login is already in use", None
            user = {
                "id": str(uuid.uuid4()),
                "role": "student",
                "status": "active",
                "login": login,
                "password": self._hash_password(password),
                "name": name,
                "preferences": {"theme": "dark", "language": "en"},
            }
            data.setdefault("users", []).append(user)
            self._write_users(data)
            logger.info("Registered local student account: %s", login)
            return True, "Account created", {key: value for key, value in user.items() if key != "password"}
        except (OSError, json.JSONDecodeError) as exc:
            logger.error("Registration failed: %s", exc)
            return False, "Unable to create account", None

    def save_preferences(self, user_id: str, preferences: Dict) -> bool:
        """Persist non-sensitive UI preferences for one authenticated user."""
        try:
            data = self._read_users()
            for user in data.get("users", []):
                if str(user.get("id")) == str(user_id):
                    user["preferences"] = {
                        "theme": preferences.get("theme", "dark"),
                        "language": preferences.get("language", "en"),
                    }
                    self._write_users(data)
                    return True
        except (OSError, json.JSONDecodeError) as exc:
            logger.error("Could not save preferences for user '%s': %s", user_id, exc)
        return False

    def update_display_name(self, user_id: str, name: str) -> bool:
        name = name.strip()
        if not name:
            return False
        try:
            data = self._read_users()
            for user in data.get("users", []):
                if str(user.get("id")) == str(user_id):
                    user["name"] = name
                    self._write_users(data)
                    return True
        except (OSError, json.JSONDecodeError) as exc:
            logger.error("Could not update display name for user '%s': %s", user_id, exc)
        return False

    def change_password(self, user_id: str, current_password: str, new_password: str) -> tuple[bool, str]:
        if len(new_password) < 8:
            return False, "Password must contain at least 8 characters"
        try:
            data = self._read_users()
            for user in data.get("users", []):
                if str(user.get("id")) == str(user_id):
                    if not self._verify_password(current_password, user.get("password", "")):
                        return False, "Current password is incorrect"
                    user["password"] = self._hash_password(new_password)
                    self._write_users(data)
                    logger.info("Password changed for user '%s'", user_id)
                    return True, "Password changed"
        except (OSError, json.JSONDecodeError) as exc:
            logger.error("Could not change password for user '%s': %s", user_id, exc)
        return False, "Unable to change password"

    def update_role(self, user_id: str, role: str) -> bool:
        if role not in {"student", "teacher", "admin"}:
            return False
        return self._update_account_field(user_id, "role", role)

    def update_status(self, user_id: str, status: str, reason: str = "") -> bool:
        if status not in {"active", "banned"}:
            return False
        try:
            data = self._read_users()
            for user in data.get("users", []):
                if str(user.get("id")) != str(user_id):
                    continue
                user["status"] = status
                if status == "banned":
                    user["ban_reason"] = reason.strip() or "No reason was provided."
                    user["banned_at"] = datetime.now(timezone.utc).isoformat()
                else:
                    user["ban_reason"] = ""
                    user["banned_at"] = None
                self._write_users(data)
                return True
        except (OSError, json.JSONDecodeError) as exc:
            logger.error("Could not update account status for '%s': %s", user_id, exc)
        return False

    def get_ban_message(self, login: str) -> Optional[str]:
        """Return the current suspension reason for a local account, if any."""
        try:
            user = next(
                (entry for entry in self._read_users().get("users", []) if entry.get("login") == login),
                None,
            )
            if user and user.get("status") == "banned":
                reason = user.get("ban_reason") or "No reason was provided."
                return f"Account suspended. Reason: {reason}"
        except (OSError, json.JSONDecodeError) as exc:
            logger.error("Could not read account status for '%s': %s", login, exc)
        return None

    def _update_account_field(self, user_id, field, value):
        try:
            data = self._read_users()
            for user in data.get("users", []):
                if str(user.get("id")) == str(user_id):
                    user[field] = value
                    self._write_users(data)
                    return True
        except (OSError, json.JSONDecodeError) as exc:
            logger.error("Could not update account '%s': %s", user_id, exc)
        return False

    def _read_users(self):
        return json.loads(self.users_file.read_text(encoding="utf-8"))

    def _write_users(self, data):
        self.users_file.write_text(json.dumps(data, indent=4), encoding="utf-8")

    def _migrate_plaintext_passwords(self, data):
        changed = False
        for user in data.get("users", []):
            password = user.get("password", "")
            if password and not password.startswith(f"{self.HASH_NAME}$"):
                user["password"] = self._hash_password(password)
                changed = True
        return changed

    @staticmethod
    def _normalize_accounts(data):
        changed = False
        for user in data.get("users", []):
            if user.get("login") == "admin" and user.get("role") == "teacher":
                user["role"] = "admin"
                changed = True
            if "status" not in user:
                user["status"] = "active"
                changed = True
            if "ban_reason" not in user:
                user["ban_reason"] = ""
                changed = True
            if "banned_at" not in user:
                user["banned_at"] = None
                changed = True
            user.setdefault("preferences", {"theme": "dark", "language": "en"})
        return changed

    def _hash_password(self, password: str) -> str:
        salt = secrets.token_hex(16)
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt.encode("ascii"), self.HASH_ITERATIONS
        ).hex()
        return f"{self.HASH_NAME}${self.HASH_ITERATIONS}${salt}${digest}"

    def _verify_password(self, password: str, stored_value: str) -> bool:
        try:
            algorithm, iterations, salt, expected = stored_value.split("$", 3)
            if algorithm != self.HASH_NAME:
                return False
            actual = hashlib.pbkdf2_hmac(
                "sha256", password.encode("utf-8"), salt.encode("ascii"), int(iterations)
            ).hex()
            return hmac.compare_digest(actual, expected)
        except (TypeError, ValueError):
            return False
