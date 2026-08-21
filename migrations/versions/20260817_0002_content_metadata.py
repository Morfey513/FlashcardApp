"""Create quiz and flashcard-deck metadata/ownership tables."""

from alembic import op
import sqlalchemy as sa


revision = "20260817_0002"
down_revision = "20260816_0001"
branch_labels = None
depends_on = None


LIFECYCLE_CHECK = "lifecycle IN ('draft', 'pending_review', 'published', 'rejected', 'banned')"
VISIBILITY_CHECK = "visibility IN ('private', 'class_only', 'public')"


def upgrade() -> None:
    op.create_table(
        "quizzes",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("owner_id", sa.String(length=64), nullable=True),
        sa.Column("source_owner_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("lifecycle", sa.String(length=30), nullable=False),
        sa.Column("visibility", sa.String(length=30), nullable=False),
        sa.Column("source_path", sa.Text(), nullable=False),
        sa.Column("time_limit_minutes", sa.Integer(), server_default="0", nullable=False),
        sa.Column("passing_grade_percent", sa.Integer(), server_default="80", nullable=False),
        sa.Column("attempt_limit", sa.Integer(), server_default="1", nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("answer_review_policy", sa.String(length=30), server_default="immediate", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(LIFECYCLE_CHECK, name="ck_quizzes_lifecycle"),
        sa.CheckConstraint(VISIBILITY_CHECK, name="ck_quizzes_visibility"),
        sa.CheckConstraint(
            "answer_review_policy IN ('immediate', 'after_due_date', 'never')",
            name="ck_quizzes_answer_review_policy",
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_path", name="uq_quizzes_source_path"),
    )
    op.create_index("ix_quizzes_owner_id", "quizzes", ["owner_id"])

    op.create_table(
        "flashcard_decks",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("owner_id", sa.String(length=64), nullable=True),
        sa.Column("source_owner_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("lifecycle", sa.String(length=30), nullable=False),
        sa.Column("visibility", sa.String(length=30), nullable=False),
        sa.Column("source_path", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(LIFECYCLE_CHECK, name="ck_flashcard_decks_lifecycle"),
        sa.CheckConstraint(VISIBILITY_CHECK, name="ck_flashcard_decks_visibility"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_path", name="uq_flashcard_decks_source_path"),
    )
    op.create_index("ix_flashcard_decks_owner_id", "flashcard_decks", ["owner_id"])


def downgrade() -> None:
    op.drop_table("flashcard_decks")
    op.drop_table("quizzes")
