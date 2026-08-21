"""Server-session persistence for the local identity API."""

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError

from src.storage.database import create_session_factory
from src.storage.postgres_models import UserSessionModel


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

    def create(self, user_id: str) -> tuple[str, int]:
        token = secrets.token_urlsafe(32)
        now = datetime.now(timezone.utc)
        expires_at = now + self.lifetime
        with self.session_factory.begin() as session:
            session.add(
                UserSessionModel(
                    id=str(uuid.uuid4()),
                    user_id=str(user_id),
                    session_token_hash=self._token_hash(token),
                    expires_at=expires_at,
                )
            )
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
            with self.session_factory() as session:
                stored = session.scalar(
                    select(UserSessionModel).where(
                        UserSessionModel.session_token_hash == self._token_hash(token)
                    )
                )
                if stored is None or stored.revoked_at is not None:
                    return None
                if self._as_utc(stored.expires_at) <= datetime.now(timezone.utc):
                    return None
                return stored.user_id
        except SQLAlchemyError:
            return None

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
