"""Shared PostgreSQL content revision primitives."""
from sqlalchemy import select


def lock_metadata(session, model, content_id):
    """Load and lock one metadata row for an atomic envelope mutation."""
    return session.scalar(select(model).where(model.id == str(content_id)).with_for_update())


def advance_revision(metadata):
    metadata.content_version = int(metadata.content_version or 0) + 1
    return metadata.content_version
