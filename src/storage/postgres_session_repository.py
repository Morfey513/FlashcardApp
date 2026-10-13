"""Server-session persistence for the local identity API."""

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError

from src.storage.database import create_session_factory
from src.storage.postgres_models import UserSessionModel
from src.storage.errors import RepositoryUnavailable


class PostgresSessionRepository:
    """Issue opaque tokens while storing only their SHA-256 hashes."""

    def __init__(self, session_factory=None, lifetime: timedelta | None = None):
        self.session_factory = session_factory or create_session_factory()
        self.lifetime = lifetime or timedelta(hours=24)

    @staticmethod
    def _token_hash(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    activity_throttle = timedelta(minutes=5)

    def create(
        self,
        user_id: str,
        *,
        ip_address: str | None = None,
        client_label: str | None = None,
        device_fingerprint: str | None = None,
    ) -> tuple[str, int]:
        token = secrets.token_urlsafe(32)
        now = datetime.now(timezone.utc)
        expires_at = now + self.lifetime
        try:
            with self.session_factory.begin() as session:
                session.add(
                    UserSessionModel(
                        id=str(uuid.uuid4()),
                        user_id=str(user_id),
                        session_token_hash=self._token_hash(token),
                        expires_at=expires_at,
                        ip_address=ip_address,
                        client_label=client_label,
                        device_fingerprint=device_fingerprint,
                        last_activity_at=now,
                    )
                )
        except SQLAlchemyError as exc:
            raise RepositoryUnavailable("Session storage is unavailable") from exc
        return token, max(0, int(self.lifetime.total_seconds()))

    def is_ready(self) -> bool:
        """Return whether the configured database accepts a simple query."""
        try:
            with self.session_factory() as session:
                return session.scalar(text("SELECT 1")) == 1
        except SQLAlchemyError:
            return False

    def resolve(self, token: str) -> str | None:
        if not token:
            return None
        try:
            with self.session_factory.begin() as session:
                stored = session.scalar(
                    select(UserSessionModel).where(
                        UserSessionModel.session_token_hash == self._token_hash(token)
                    )
                )
                if stored is None or stored.revoked_at is not None:
                    return None
                if self._as_utc(stored.expires_at) <= datetime.now(timezone.utc):
                    return None
                now = datetime.now(timezone.utc)
                last_activity = stored.last_activity_at
                if (
                    last_activity is None
                    or self._as_utc(last_activity) <= now - self.activity_throttle
                ):
                    stored.last_activity_at = now
                return stored.user_id
        except SQLAlchemyError as exc:
            raise RepositoryUnavailable("Session storage is unavailable") from exc

    def revoke(self, token: str) -> bool:
        if not token:
            return False
        try:
            with self.session_factory.begin() as session:
                stored = session.scalar(
                    select(UserSessionModel).where(
                        UserSessionModel.session_token_hash == self._token_hash(token)
                    )
                )
                if stored is None:
                    return False
                if stored.revoked_at is None:
                    stored.revoked_at = datetime.now(timezone.utc)
                return True
        except SQLAlchemyError:
            return False

    @staticmethod
    def _session_data(stored: UserSessionModel, current_session_id: str | None, *, include_fingerprint: bool) -> dict:
        result = {
            "id": stored.id,
            "created_at": stored.created_at,
            "last_activity_at": stored.last_activity_at,
            "ip_address": stored.ip_address,
            "client_label": stored.client_label,
            "is_current": stored.id == current_session_id,
        }
        if include_fingerprint:
            result["device_fingerprint"] = stored.device_fingerprint
        return result

    def _current_session_id(self, session, token: str) -> str | None:
        return session.scalar(select(UserSessionModel.id).where(
            UserSessionModel.session_token_hash == self._token_hash(token)
        ))

    def list_active(self, user_id: str, token: str, *, include_fingerprint: bool = False) -> tuple[list[dict], datetime | None]:
        """Return only unrevoked, unexpired sessions for one account."""
        try:
            with self.session_factory() as session:
                current_id = self._current_session_id(session, token)
                now = datetime.now(timezone.utc)
                sessions = session.scalars(select(UserSessionModel).where(
                    UserSessionModel.user_id == str(user_id),
                    UserSessionModel.revoked_at.is_(None),
                    UserSessionModel.expires_at > now,
                ).order_by(UserSessionModel.created_at.desc())).all()
                # Login history is intentionally derived from all of the
                # account's prior sessions, even after one has expired or was
                # revoked; the visible active-session list remains filtered.
                last_other_login = session.scalar(
                    select(UserSessionModel.created_at).where(
                        UserSessionModel.user_id == str(user_id),
                        UserSessionModel.id != current_id,
                    ).order_by(UserSessionModel.created_at.desc()).limit(1)
                )
                return (
                    [self._session_data(item, current_id, include_fingerprint=include_fingerprint) for item in sessions],
                    last_other_login,
                )
        except SQLAlchemyError as exc:
            raise RepositoryUnavailable("Session storage is unavailable") from exc

    def revoke_owned(self, user_id: str, session_id: str) -> bool:
        try:
            with self.session_factory.begin() as session:
                stored = session.get(UserSessionModel, str(session_id))
                if stored is None or stored.user_id != str(user_id):
                    return False
                if stored.revoked_at is None:
                    stored.revoked_at = datetime.now(timezone.utc)
                return True
        except SQLAlchemyError as exc:
            raise RepositoryUnavailable("Session storage is unavailable") from exc

    def revoke_others(self, user_id: str, token: str) -> int:
        try:
            with self.session_factory.begin() as session:
                current_id = self._current_session_id(session, token)
                if current_id is None:
                    return 0
                now = datetime.now(timezone.utc)
                sessions = session.scalars(select(UserSessionModel).where(
                    UserSessionModel.user_id == str(user_id),
                    UserSessionModel.id != current_id,
                    UserSessionModel.revoked_at.is_(None),
                    UserSessionModel.expires_at > now,
                )).all()
                for stored in sessions:
                    stored.revoked_at = now
                return len(sessions)
        except SQLAlchemyError as exc:
            raise RepositoryUnavailable("Session storage is unavailable") from exc
