"""Create quiz questions, flashcards, and media metadata tables."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260817_0005"
down_revision = "20260817_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "quiz_questions",
        sa.Column("quiz_id", sa.String(64), nullable=False),
        sa.Column("question_id", sa.String(64), nullable=False),
        sa.Column("question_text", sa.Text(), nullable=False),
        sa.Column("question_type", sa.String(40), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("correct_answer", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.CheckConstraint(
            "question_type IN ('single_choice', 'multiple_choice', 'true_false', "
            "'short_answer', 'matching', 'ordering')",
            name="ck_quiz_questions_type",
        ),
        sa.ForeignKeyConstraint(["quiz_id"], ["quizzes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("quiz_id", "question_id"),
        sa.UniqueConstraint("quiz_id", "position", name="uq_quiz_questions_position"),
    )
    op.create_table(
        "question_options",
        sa.Column("quiz_id", sa.String(64), nullable=False),
        sa.Column("question_id", sa.String(64), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("option_text", sa.Text(), nullable=False),
        sa.Column("is_correct", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.ForeignKeyConstraint(
            ["quiz_id", "question_id"],
            ["quiz_questions.quiz_id", "quiz_questions.question_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("quiz_id", "question_id", "position"),
    )
    op.create_table(
        "matching_pairs",
        sa.Column("quiz_id", sa.String(64), nullable=False),
        sa.Column("question_id", sa.String(64), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["quiz_id", "question_id"],
            ["quiz_questions.quiz_id", "quiz_questions.question_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("quiz_id", "question_id", "position"),
    )
    op.create_table(
        "short_answer_variants",
        sa.Column("quiz_id", sa.String(64), nullable=False),
        sa.Column("question_id", sa.String(64), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("answer_text", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["quiz_id", "question_id"],
            ["quiz_questions.quiz_id", "quiz_questions.question_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("quiz_id", "question_id", "position"),
    )
    op.create_table(
        "flashcards",
        sa.Column("deck_id", sa.String(64), nullable=False),
        sa.Column("card_id", sa.String(64), nullable=False),
        sa.Column("front_text", sa.Text(), nullable=False),
        sa.Column("back_text", sa.Text(), nullable=False),
        sa.Column("hint_text", sa.Text(), server_default="", nullable=False),
        sa.Column("description_text", sa.Text(), server_default="", nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["deck_id"], ["flashcard_decks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("deck_id", "card_id"),
        sa.UniqueConstraint("deck_id", "position", name="uq_flashcards_position"),
    )
    op.create_table(
        "media",
        sa.Column("id", sa.String(64), nullable=False),
        sa.Column("owner_id", sa.String(64), nullable=True),
        sa.Column("storage_key", sa.Text(), nullable=False),
        sa.Column("original_filename", sa.Text(), nullable=False),
        sa.Column("media_type", sa.String(20), nullable=False),
        sa.Column("mime_type", sa.String(255), server_default="", nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("checksum_sha256", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("storage_key"),
    )
    op.create_index("ix_media_owner_id", "media", ["owner_id"])
    op.create_table(
        "question_media",
        sa.Column("quiz_id", sa.String(64), nullable=False),
        sa.Column("question_id", sa.String(64), nullable=False),
        sa.Column("media_id", sa.String(64), nullable=False),
        sa.Column("role", sa.String(30), nullable=False),
        sa.ForeignKeyConstraint(
            ["quiz_id", "question_id"],
            ["quiz_questions.quiz_id", "quiz_questions.question_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["media_id"], ["media.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("quiz_id", "question_id", "media_id", "role"),
    )
    op.create_table(
        "flashcard_media",
        sa.Column("deck_id", sa.String(64), nullable=False),
        sa.Column("card_id", sa.String(64), nullable=False),
        sa.Column("media_id", sa.String(64), nullable=False),
        sa.Column("role", sa.String(30), nullable=False),
        sa.ForeignKeyConstraint(
            ["deck_id", "card_id"],
            ["flashcards.deck_id", "flashcards.card_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["media_id"], ["media.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("deck_id", "card_id", "media_id", "role"),
    )


def downgrade() -> None:
    op.drop_table("flashcard_media")
    op.drop_table("question_media")
    op.drop_table("media")
    op.drop_table("flashcards")
    op.drop_table("short_answer_variants")
    op.drop_table("matching_pairs")
    op.drop_table("question_options")
    op.drop_table("quiz_questions")
