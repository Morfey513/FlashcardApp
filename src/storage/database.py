"""Database engine/session helpers for the PostgreSQL storage backend."""

import os
from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.runtime_config import load_runtime_environment


DATABASE_URL_ENV = "STUDY_BUDDY_DATABASE_URL"
load_runtime_environment()


def get_database_url() -> str:
    """Return the configured URL without providing an unsafe default password."""
    url = os.getenv(DATABASE_URL_ENV, "").strip()
    if not url:
        raise RuntimeError(
            f"{DATABASE_URL_ENV} is required when PostgreSQL storage is enabled"
        )
    return url


@lru_cache(maxsize=4)
def create_session_factory(database_url: str | None = None):
    """Create a reusable SQLAlchemy session factory for one database URL."""
    url = database_url or get_database_url()
    engine = create_engine(url, pool_pre_ping=True)
    return sessionmaker(bind=engine, expire_on_commit=False)
