"""Add server-authoritative content revisions."""

from alembic import op
import sqlalchemy as sa


revision = "20260824_0008"
down_revision = "20260823_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("quizzes", "flashcard_decks"):
        op.add_column(
            table,
            sa.Column("content_version", sa.Integer(), nullable=False, server_default="1"),
        )


def downgrade() -> None:
    for table in ("flashcard_decks", "quizzes"):
        op.drop_column(table, "content_version")
