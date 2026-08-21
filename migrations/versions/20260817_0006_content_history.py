"""Create attributed edit and moderation history tables."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260817_0006"
down_revision = "20260817_0005"
branch_labels = None
depends_on = None


def _edit_table(name, content_column, content_table):
    op.create_table(
        name,
        sa.Column("id", sa.String(64), nullable=False),
        sa.Column(content_column, sa.String(64), nullable=False),
        sa.Column("changed_by", sa.String(64), nullable=True),
        sa.Column("source_actor_id", sa.String(64), nullable=False),
        sa.Column("actor_role", sa.String(30), nullable=False),
        sa.Column("action", sa.String(40), nullable=False),
        sa.Column("change_summary", sa.Text(), nullable=False),
        sa.Column("changed_fields", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint([content_column], [f"{content_table}.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["changed_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(f"ix_{name}_{content_column}", name, [content_column])


def _moderation_table(name, content_column, content_table):
    op.create_table(
        name,
        sa.Column("id", sa.String(64), nullable=False),
        sa.Column(content_column, sa.String(64), nullable=False),
        sa.Column("moderator_id", sa.String(64), nullable=True),
        sa.Column("source_actor_id", sa.String(64), nullable=False),
        sa.Column("action", sa.String(40), nullable=False),
        sa.Column("note", sa.Text(), server_default="", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint([content_column], [f"{content_table}.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["moderator_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(f"ix_{name}_{content_column}", name, [content_column])


def upgrade() -> None:
    _edit_table("quiz_edit_history", "quiz_id", "quizzes")
    _edit_table("flashcard_edit_history", "deck_id", "flashcard_decks")
    _moderation_table("quiz_moderation_history", "quiz_id", "quizzes")
    _moderation_table("flashcard_moderation_history", "deck_id", "flashcard_decks")


def downgrade() -> None:
    op.drop_table("flashcard_moderation_history")
    op.drop_table("quiz_moderation_history")
    op.drop_table("flashcard_edit_history")
    op.drop_table("quiz_edit_history")
