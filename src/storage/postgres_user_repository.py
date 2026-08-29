"""PostgreSQL implementation of the user-repository contract."""

import logging
import uuid
from datetime import datetime, timezone
from typing import Dict, Optional

from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError, OperationalError, SQLAlchemyError
from sqlalchemy.orm import selectinload

from src.logic.access_control import can_ban_accounts, is_account_status, is_role
from src.logic.passwords import PasswordHasher
from src.storage.database import create_session_factory
from src.storage.postgres_models import (
    AccountModerationHistoryModel,
    UserModel,
    UserSettingsModel,
)
from src.storage.errors import RepositoryUnavailable

logger = logging.getLogger(__name__)


class PostgresUserRepository:
    """Persist users and preferences through SQLAlchemy/PostgreSQL."""

    def __init__(self, session_factory=None):
        self.session_factory = session_factory or create_session_factory()

    @staticmethod
    def _preferences_from_settings(settings: UserSettingsModel | None) -> Dict:
        if settings is None:
            return {"theme": "dark", "language": "en"}
        preferences = dict(settings.extra_preferences or {})
        preferences["theme"] = settings.theme
        preferences["language"] = settings.language_code
        if settings.launcher_width and settings.launcher_height:
            preferences["launcher_size"] = [
                settings.launcher_width,
                settings.launcher_height,
            ]
        if settings.window_sizes:
            preferences["window_sizes"] = dict(settings.window_sizes)
        return preferences

    @classmethod
    def _public_user(cls, user: UserModel) -> Dict:
        return {
            "id": user.id,
            "login": user.username,
            "name": user.display_name,
            "role": user.role,
            "status": user.status,
            "ban_reason": user.ban_reason or "",
            "banned_at": user.banned_at.isoformat() if user.banned_at else None,
            "preferences": cls._preferences_from_settings(user.settings),
            **({"email": user.email} if user.email else {}),
        }

    @staticmethod
    def _apply_preferences(settings: UserSettingsModel, preferences: Dict):
        values = dict(preferences or {})
        settings.theme = str(values.pop("theme", "dark"))
        settings.language_code = str(values.pop("language", "en"))
        launcher_size = values.pop("launcher_size", None)
        if (
            isinstance(launcher_size, (list, tuple))
            and len(launcher_size) == 2
            and all(isinstance(item, int) and item > 0 for item in launcher_size)
        ):
            settings.launcher_width = int(launcher_size[0])
            settings.launcher_height = int(launcher_size[1])
        else:
            settings.launcher_width = None
            settings.launcher_height = None
        window_sizes = values.pop("window_sizes", {})
        settings.window_sizes = dict(window_sizes) if isinstance(window_sizes, dict) else {}
        settings.extra_preferences = values

    def authenticate(self, login: str, password: str) -> Optional[Dict]:
        try:
            with self.session_factory() as session:
                user = session.scalar(
                    select(UserModel)
                    .options(selectinload(UserModel.settings))
                    .where(func.lower(UserModel.username) == login.casefold())
                )
                if user is None:
                    logger.warning("Authentication failed for login: %s", login)
                    return None
                if user.status != "active":
                    logger.warning("Blocked login attempt for disabled account: %s", login)
                    return None
                if not PasswordHasher.verify(password, user.password_hash):
                    logger.warning("Authentication failed for login: %s", login)
                    return None
                logger.info("User authenticated: %s (role: %s)", login, user.role)
                return self._public_user(user)
        except SQLAlchemyError as exc:
            logger.error("PostgreSQL authentication error: %s", exc)
            raise RepositoryUnavailable("User storage is unavailable") from exc

    def get_all_users(self) -> list[Dict]:
        try:
            with self.session_factory() as session:
                users = session.scalars(
                    select(UserModel)
                    .options(selectinload(UserModel.settings))
                    .order_by(func.lower(UserModel.username))
                ).all()
                return [self._public_user(user) for user in users]
        except SQLAlchemyError as exc:
            logger.error("Error loading PostgreSQL users: %s", exc)
            return []

    def get_user_by_id(self, user_id: str) -> Optional[Dict]:
        try:
            with self.session_factory() as session:
                user = session.scalar(
                    select(UserModel)
                    .options(selectinload(UserModel.settings))
                    .where(UserModel.id == str(user_id))
                )
                return self._public_user(user) if user is not None else None
        except SQLAlchemyError as exc:
            logger.error("Could not load PostgreSQL user '%s': %s", user_id, exc)
            raise RepositoryUnavailable("User storage is unavailable") from exc

    def register(
        self, name: str, login: str, password: str
    ) -> tuple[bool, str, Optional[Dict]]:
        name, login = name.strip(), login.strip()
        if not name or not login or not password:
            return False, "Name, login, and password are required", None
        if len(password) < 8:
            return False, "Password must contain at least 8 characters", None
        try:
            with self.session_factory.begin() as session:
                exists = session.scalar(
                    select(UserModel.id).where(
                        func.lower(UserModel.username) == login.casefold()
                    )
                )
                if exists:
                    return False, "That login is already in use", None
                user = UserModel(
                    id=str(uuid.uuid4()),
                    username=login,
                    password_hash=PasswordHasher.hash(password),
                    display_name=name,
                    role="student",
                    status="active",
                    ban_reason="",
                )
                user.settings = UserSettingsModel(theme="dark", language_code="en")
                session.add(user)
                session.flush()
                result = self._public_user(user)
            logger.info("Registered PostgreSQL student account: %s", login)
            return True, "Account created", result
        except IntegrityError:
            return False, "That login is already in use", None
        except OperationalError as exc:
            raise RepositoryUnavailable("User storage is unavailable") from exc
        except SQLAlchemyError as exc:
            logger.error("PostgreSQL registration failed: %s", exc)
            return False, "Unable to create account", None

    def save_preferences(self, user_id: str, preferences: Dict) -> bool:
        try:
            with self.session_factory.begin() as session:
                user = session.get(UserModel, str(user_id))
                if user is None:
                    return False
                if user.settings is None:
                    user.settings = UserSettingsModel(user_id=user.id)
                self._apply_preferences(user.settings, preferences)
                return True
        except SQLAlchemyError as exc:
            logger.error("Could not save PostgreSQL preferences for '%s': %s", user_id, exc)
            return False

    def update_display_name(self, user_id: str, name: str) -> bool:
        name = name.strip()
        if not name:
            return False
        return self._update_account_field(user_id, "display_name", name)

    def change_password(
        self, user_id: str, current_password: str, new_password: str
    ) -> tuple[bool, str]:
        if len(new_password) < 8:
            return False, "Password must contain at least 8 characters"
        try:
            with self.session_factory.begin() as session:
                user = session.get(UserModel, str(user_id))
                if user is None:
                    return False, "Unable to change password"
                if not PasswordHasher.verify(current_password, user.password_hash):
                    return False, "Current password is incorrect"
                user.password_hash = PasswordHasher.hash(new_password)
                return True, "Password changed"
        except SQLAlchemyError as exc:
            logger.error("Could not change PostgreSQL password for '%s': %s", user_id, exc)
            return False, "Unable to change password"

    def update_role(self, user_id: str, role: str) -> bool:
        if not is_role(role):
            return False
        return self._update_account_field(user_id, "role", role)

    def update_status(
        self, user_id: str, status: str, reason: str = "",
        moderator_id: str | None = None,
    ) -> bool:
        if not is_account_status(status):
            return False
        try:
            with self.session_factory.begin() as session:
                user = session.get(UserModel, str(user_id))
                if user is None:
                    return False
                previous = user.status
                user.status = status
                if status == "banned":
                    user.ban_reason = reason.strip() or "No reason was provided."
                    user.banned_at = datetime.now(timezone.utc)
                else:
                    user.ban_reason = ""
                    user.banned_at = None
                session.add(
                    AccountModerationHistoryModel(
                        id=str(uuid.uuid4()),
                        target_user_id=user.id,
                        moderator_id=moderator_id,
                        previous_status=previous,
                        new_status=status,
                        reason=user.ban_reason,
                    )
                )
                return True
        except SQLAlchemyError as exc:
            logger.error("Could not update PostgreSQL account '%s': %s", user_id, exc)
            return False

    def set_account_status(
        self, actor_role: str, user_id: str, status: str, reason: str = "",
        actor_id: str | None = None,
    ) -> bool:
        if not can_ban_accounts(actor_role):
            return False
        return self.update_status(user_id, status, reason, actor_id)

    def get_ban_message(self, login: str) -> Optional[str]:
        try:
            with self.session_factory() as session:
                user = session.scalar(
                    select(UserModel).where(
                        func.lower(UserModel.username) == login.casefold()
                    )
                )
                if user and user.status == "banned":
                    return (
                        "Account suspended. Reason: "
                        f"{user.ban_reason or 'No reason was provided.'}"
                    )
        except SQLAlchemyError as exc:
            logger.error("Could not read PostgreSQL account status for '%s': %s", login, exc)
        return None

    def logout(self) -> bool:
        """Direct database mode has no client session token to revoke."""
        return True

    def is_online(self) -> bool:
        """Check that the configured PostgreSQL database accepts a query."""
        try:
            with self.session_factory() as session:
                session.execute(text("SELECT 1"))
            return True
        except SQLAlchemyError as exc:
            logger.warning("PostgreSQL readiness check failed: %s", exc)
            return False

    def _update_account_field(self, user_id: str, field: str, value) -> bool:
        try:
            with self.session_factory.begin() as session:
                user = session.get(UserModel, str(user_id))
                if user is None:
                    return False
                setattr(user, field, value)
                return True
        except SQLAlchemyError as exc:
            logger.error("Could not update PostgreSQL account '%s': %s", user_id, exc)
            return False

    def import_json_user(self, source: Dict) -> bool:
        """Upsert one legacy JSON account while preserving its external ID/hash."""
        user_id = str(source.get("id", "")).strip()
        username = str(source.get("login", "")).strip()
        password_hash = str(source.get("password", ""))
        if not user_id or not username or not password_hash:
            return False
        try:
            with self.session_factory.begin() as session:
                user = session.get(UserModel, user_id)
                if user is None:
                    user = UserModel(id=user_id)
                    session.add(user)
                user.username = username
                user.email = source.get("email") or None
                user.password_hash = password_hash
                user.display_name = str(source.get("name") or username)
                user.role = str(source.get("role") or "student")
                user.status = str(source.get("status") or "active")
                user.ban_reason = str(source.get("ban_reason") or "")
                banned_at = source.get("banned_at")
                user.banned_at = (
                    datetime.fromisoformat(banned_at) if isinstance(banned_at, str) else None
                )
                if user.settings is None:
                    user.settings = UserSettingsModel(user_id=user_id)
                self._apply_preferences(user.settings, source.get("preferences", {}))
                return True
        except (SQLAlchemyError, ValueError) as exc:
            logger.error("Could not import JSON user '%s': %s", user_id, exc)
            return False
