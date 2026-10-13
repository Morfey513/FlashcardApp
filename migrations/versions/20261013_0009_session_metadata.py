"""Add optional metadata for user-managed active sessions."""

from alembic import op
import sqlalchemy as sa


revision = "20261013_0009"
down_revision = "20260824_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("user_sessions", sa.Column("ip_address", sa.Text(), nullable=True))
    op.add_column("user_sessions", sa.Column("client_label", sa.Text(), nullable=True))
    op.add_column("user_sessions", sa.Column("device_fingerprint", sa.Text(), nullable=True))
    op.add_column("user_sessions", sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("user_sessions", "last_activity_at")
    op.drop_column("user_sessions", "device_fingerprint")
    op.drop_column("user_sessions", "client_label")
    op.drop_column("user_sessions", "ip_address")
