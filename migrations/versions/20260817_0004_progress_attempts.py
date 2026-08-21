"""Create authenticated learning progress and test-attempt tables."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260817_0004"
down_revision = "20260817_0003"
branch_labels = None
depends_on = None


def _progress_table(name, content_column, content_table, item_column):
    op.create_table(
        name,
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column(content_column, sa.String(length=64), nullable=False),
        sa.Column(item_column, sa.String(length=64), nullable=False),
        sa.Column("correct_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("wrong_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("mastered", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint([content_column], [f"{content_table}.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", content_column, item_column),
    )


def upgrade() -> None:
    _progress_table("flashcard_progress", "deck_id", "flashcard_decks", "card_id")
    _progress_table("quiz_question_progress", "quiz_id", "quizzes", "question_id")
    op.create_table(
        "quiz_attempts",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("quiz_id", sa.String(length=64), nullable=False),
        sa.Column("mode", sa.String(length=20), server_default="test", nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("interrupted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("score", sa.Integer(), server_default="0", nullable=False),
        sa.Column("total", sa.Integer(), server_default="0", nullable=False),
        sa.Column("percentage", sa.Float(), server_default="0", nullable=False),
        sa.Column("passing_grade_percent", sa.Integer(), nullable=True),
        sa.Column("passed", sa.Boolean(), nullable=True),
        sa.Column("attempt_number", sa.Integer(), server_default="1", nullable=False),
        sa.Column("counts_toward_limit", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("current_question", sa.Integer(), nullable=True),
        sa.Column("answered_count", sa.Integer(), nullable=True),
        sa.Column("resolved_by", sa.String(length=64), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution", sa.String(length=30), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "status IN ('in_progress', 'abandoned', 'submitted', 'timed_out', 'marked_zero', 'refunded')",
            name="ck_quiz_attempts_status",
        ),
        sa.ForeignKeyConstraint(["quiz_id"], ["quizzes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["resolved_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_quiz_attempts_user_id", "quiz_attempts", ["user_id"])
    op.create_index("ix_quiz_attempts_quiz_id", "quiz_attempts", ["quiz_id"])
    op.create_table(
        "quiz_attempt_answers",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("attempt_id", sa.String(length=64), nullable=False),
        sa.Column("question_id", sa.String(length=64), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("question_text", sa.Text(), server_default="", nullable=False),
        sa.Column("question_type", sa.String(length=40), server_default="", nullable=False),
        sa.Column("user_answer", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("correct_answer", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("is_correct", sa.Boolean(), nullable=True),
        sa.Column("response_seconds", sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(["attempt_id"], ["quiz_attempts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("attempt_id", "position", name="uq_quiz_attempt_answers_position"),
    )
    op.create_index("ix_quiz_attempt_answers_attempt_id", "quiz_attempt_answers", ["attempt_id"])


def downgrade() -> None:
    op.drop_table("quiz_attempt_answers")
    op.drop_table("quiz_attempts")
    op.drop_table("quiz_question_progress")
    op.drop_table("flashcard_progress")
