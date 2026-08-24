"""Add frozen assessment foundation storage."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260823_0007"
down_revision = "20260817_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "quiz_attempts",
        sa.Column(
            "assessment_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.create_table(
        "quiz_attempt_questions",
        sa.Column("attempt_id", sa.String(64), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("question_id", sa.String(64), nullable=False),
        sa.Column(
            "presentation_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "grading_key_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["attempt_id"], ["quiz_attempts.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("attempt_id", "position"),
        sa.UniqueConstraint(
            "attempt_id", "question_id", name="uq_quiz_attempt_questions_question"
        ),
    )
    op.create_index(
        "uq_quiz_attempts_active_assessment",
        "quiz_attempts",
        ["user_id", "quiz_id"],
        unique=True,
        postgresql_where=sa.text(
            "assessment_snapshot IS NOT NULL AND status IN ('in_progress', 'abandoned')"
        ),
    )


def downgrade() -> None:
    op.drop_index("uq_quiz_attempts_active_assessment", table_name="quiz_attempts")
    op.drop_table("quiz_attempt_questions")
    op.drop_column("quiz_attempts", "assessment_snapshot")
