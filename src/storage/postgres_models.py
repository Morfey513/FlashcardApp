"""SQLAlchemy models for the first PostgreSQL migration slice."""

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


JSON_VALUE = JSON().with_variant(JSONB, "postgresql")


class Base(DeclarativeBase):
    pass


class UserModel(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("role IN ('student', 'teacher', 'admin')", name="ck_users_role"),
        CheckConstraint("status IN ('active', 'banned')", name="ck_users_status"),
    )

    # TEXT keeps legacy IDs such as "1" valid during the hybrid JSON/SQL phase.
    # Newly registered accounts still receive UUID strings.
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    username: Mapped[str] = mapped_column(String(50), nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), unique=True)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    ban_reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    banned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    settings: Mapped["UserSettingsModel"] = relationship(
        back_populates="user", cascade="all, delete-orphan", uselist=False
    )


class UserSettingsModel(Base):
    __tablename__ = "user_settings"
    __table_args__ = (
        CheckConstraint("theme IN ('light', 'dark')", name="ck_user_settings_theme"),
    )

    user_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    language_code: Mapped[str] = mapped_column(String(10), nullable=False, default="en")
    theme: Mapped[str] = mapped_column(String(20), nullable=False, default="dark")
    launcher_width: Mapped[int | None] = mapped_column(Integer)
    launcher_height: Mapped[int | None] = mapped_column(Integer)
    window_sizes: Mapped[dict] = mapped_column(JSON_VALUE, nullable=False, default=dict)
    extra_preferences: Mapped[dict] = mapped_column(JSON_VALUE, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    user: Mapped[UserModel] = relationship(back_populates="settings")


class UserSessionModel(Base):
    __tablename__ = "user_sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    session_token_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AccountModerationHistoryModel(Base):
    __tablename__ = "account_moderation_history"
    __table_args__ = (
        CheckConstraint(
            "previous_status IN ('active', 'banned')", name="ck_account_history_previous"
        ),
        CheckConstraint(
            "new_status IN ('active', 'banned')", name="ck_account_history_new"
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    target_user_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    moderator_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    previous_status: Mapped[str] = mapped_column(String(20), nullable=False)
    new_status: Mapped[str] = mapped_column(String(20), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


Index("uq_users_username_lower", func.lower(UserModel.username), unique=True)


class QuizMetadataModel(Base):
    """Server-owned quiz envelope while question bodies remain in JSON."""

    __tablename__ = "quizzes"
    __table_args__ = (
        CheckConstraint(
            "lifecycle IN ('draft', 'pending_review', 'published', 'rejected', 'banned')",
            name="ck_quizzes_lifecycle",
        ),
        CheckConstraint(
            "visibility IN ('private', 'class_only', 'public')",
            name="ck_quizzes_visibility",
        ),
        CheckConstraint(
            "answer_review_policy IN ('immediate', 'after_due_date', 'never')",
            name="ck_quizzes_answer_review_policy",
        ),
        UniqueConstraint("source_path", name="uq_quizzes_source_path"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    source_owner_id: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    lifecycle: Mapped[str] = mapped_column(String(30), nullable=False)
    visibility: Mapped[str] = mapped_column(String(30), nullable=False)
    source_path: Mapped[str] = mapped_column(Text, nullable=False)
    content_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    time_limit_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    passing_grade_percent: Mapped[int] = mapped_column(Integer, nullable=False, default=80)
    attempt_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    answer_review_policy: Mapped[str] = mapped_column(
        String(30), nullable=False, default="immediate"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class FlashcardDeckMetadataModel(Base):
    """Server-owned deck envelope while card bodies remain in JSON."""

    __tablename__ = "flashcard_decks"
    __table_args__ = (
        CheckConstraint(
            "lifecycle IN ('draft', 'pending_review', 'published', 'rejected', 'banned')",
            name="ck_flashcard_decks_lifecycle",
        ),
        CheckConstraint(
            "visibility IN ('private', 'class_only', 'public')",
            name="ck_flashcard_decks_visibility",
        ),
        UniqueConstraint("source_path", name="uq_flashcard_decks_source_path"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    source_owner_id: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    lifecycle: Mapped[str] = mapped_column(String(30), nullable=False)
    visibility: Mapped[str] = mapped_column(String(30), nullable=False)
    source_path: Mapped[str] = mapped_column(Text, nullable=False)
    content_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ClassModel(Base):
    __tablename__ = "classes"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'archived')", name="ck_classes_status"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ClassQuizModel(Base):
    __tablename__ = "class_quizzes"
    class_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("classes.id", ondelete="CASCADE"), primary_key=True
    )
    quiz_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("quizzes.id", ondelete="CASCADE"), primary_key=True
    )


class ClassFlashcardDeckModel(Base):
    __tablename__ = "class_flashcard_decks"
    class_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("classes.id", ondelete="CASCADE"), primary_key=True
    )
    deck_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("flashcard_decks.id", ondelete="CASCADE"), primary_key=True
    )


class ClassMemberModel(Base):
    __tablename__ = "class_members"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'removed')", name="ck_class_members_status"
        ),
    )
    class_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("classes.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ClassInvitationModel(Base):
    __tablename__ = "class_invitations"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'revoked')", name="ck_class_invitations_status"
        ),
        UniqueConstraint("normalized_code", name="uq_class_invitations_code"),
    )
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    class_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("classes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_by: Mapped[str] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    display_code: Mapped[str] = mapped_column(String(32), nullable=False)
    normalized_code: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class FlashcardProgressModel(Base):
    __tablename__ = "flashcard_progress"
    user_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    deck_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("flashcard_decks.id", ondelete="CASCADE"), primary_key=True
    )
    card_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    correct_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    wrong_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    mastered: Mapped[bool] = mapped_column(nullable=False, default=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class QuizQuestionProgressModel(Base):
    __tablename__ = "quiz_question_progress"
    user_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    quiz_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("quizzes.id", ondelete="CASCADE"), primary_key=True
    )
    question_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    correct_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    wrong_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    mastered: Mapped[bool] = mapped_column(nullable=False, default=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class QuizAttemptModel(Base):
    __tablename__ = "quiz_attempts"
    __table_args__ = (
        CheckConstraint(
            "status IN ('in_progress', 'abandoned', 'submitted', 'timed_out', "
            "'marked_zero', 'refunded')",
            name="ck_quiz_attempts_status",
        ),
        Index(
            "uq_quiz_attempts_active_assessment",
            "user_id",
            "quiz_id",
            unique=True,
            postgresql_where=text(
                "assessment_snapshot IS NOT NULL AND status IN ('in_progress', 'abandoned')"
            ),
        ),
    )
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    quiz_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("quizzes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    mode: Mapped[str] = mapped_column(String(20), nullable=False, default="test")
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_activity_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    interrupted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    percentage: Mapped[float] = mapped_column(nullable=False, default=0.0)
    passing_grade_percent: Mapped[int | None] = mapped_column(Integer)
    passed: Mapped[bool | None] = mapped_column()
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    counts_toward_limit: Mapped[bool] = mapped_column(nullable=False, default=True)
    assessment_snapshot: Mapped[object | None] = mapped_column(JSON_VALUE)
    duration_seconds: Mapped[int | None] = mapped_column(Integer)
    current_question: Mapped[int | None] = mapped_column(Integer)
    answered_count: Mapped[int | None] = mapped_column(Integer)
    resolved_by: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="SET NULL")
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolution: Mapped[str | None] = mapped_column(String(30))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class QuizAttemptQuestionModel(Base):
    """Immutable question presentation/grading material for server assessments."""

    __tablename__ = "quiz_attempt_questions"
    __table_args__ = (
        UniqueConstraint(
            "attempt_id", "question_id", name="uq_quiz_attempt_questions_question"
        ),
    )

    attempt_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("quiz_attempts.id", ondelete="CASCADE"), primary_key=True
    )
    position: Mapped[int] = mapped_column(Integer, primary_key=True)
    question_id: Mapped[str] = mapped_column(String(64), nullable=False)
    presentation_json: Mapped[object] = mapped_column(JSON_VALUE, nullable=False)
    grading_key_json: Mapped[object] = mapped_column(JSON_VALUE, nullable=False)


class QuizAttemptAnswerModel(Base):
    __tablename__ = "quiz_attempt_answers"
    __table_args__ = (
        UniqueConstraint(
            "attempt_id", "position", name="uq_quiz_attempt_answers_position"
        ),
    )
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    attempt_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("quiz_attempts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    question_id: Mapped[str] = mapped_column(String(64), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    question_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    question_type: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    user_answer: Mapped[object] = mapped_column(JSON_VALUE)
    correct_answer: Mapped[object] = mapped_column(JSON_VALUE)
    is_correct: Mapped[bool | None] = mapped_column()
    response_seconds: Mapped[float | None] = mapped_column()


class QuizQuestionModel(Base):
    __tablename__ = "quiz_questions"
    __table_args__ = (
        CheckConstraint(
            "question_type IN ('single_choice', 'multiple_choice', 'true_false', "
            "'short_answer', 'matching', 'ordering')",
            name="ck_quiz_questions_type",
        ),
        UniqueConstraint("quiz_id", "position", name="uq_quiz_questions_position"),
    )
    quiz_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("quizzes.id", ondelete="CASCADE"), primary_key=True
    )
    question_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    question_type: Mapped[str] = mapped_column(String(40), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    correct_answer: Mapped[object] = mapped_column(JSON_VALUE)


class QuestionOptionModel(Base):
    __tablename__ = "question_options"
    quiz_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    question_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    position: Mapped[int] = mapped_column(Integer, primary_key=True)
    option_text: Mapped[str] = mapped_column(Text, nullable=False)
    is_correct: Mapped[bool] = mapped_column(nullable=False, default=False)
    __table_args__ = (
        ForeignKeyConstraint(
            ["quiz_id", "question_id"],
            ["quiz_questions.quiz_id", "quiz_questions.question_id"],
            ondelete="CASCADE",
        ),
    )


class MatchingPairModel(Base):
    __tablename__ = "matching_pairs"
    quiz_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    question_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    position: Mapped[int] = mapped_column(Integer, primary_key=True)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    __table_args__ = (
        ForeignKeyConstraint(
            ["quiz_id", "question_id"],
            ["quiz_questions.quiz_id", "quiz_questions.question_id"],
            ondelete="CASCADE",
        ),
    )


class ShortAnswerVariantModel(Base):
    __tablename__ = "short_answer_variants"
    quiz_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    question_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    position: Mapped[int] = mapped_column(Integer, primary_key=True)
    answer_text: Mapped[str] = mapped_column(Text, nullable=False)
    __table_args__ = (
        ForeignKeyConstraint(
            ["quiz_id", "question_id"],
            ["quiz_questions.quiz_id", "quiz_questions.question_id"],
            ondelete="CASCADE",
        ),
    )


class FlashcardModel(Base):
    __tablename__ = "flashcards"
    __table_args__ = (
        UniqueConstraint("deck_id", "position", name="uq_flashcards_position"),
    )
    deck_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("flashcard_decks.id", ondelete="CASCADE"), primary_key=True
    )
    card_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    front_text: Mapped[str] = mapped_column(Text, nullable=False)
    back_text: Mapped[str] = mapped_column(Text, nullable=False)
    hint_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    description_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    position: Mapped[int] = mapped_column(Integer, nullable=False)


class MediaModel(Base):
    __tablename__ = "media"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    storage_key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    original_filename: Mapped[str] = mapped_column(Text, nullable=False)
    media_type: Mapped[str] = mapped_column(String(20), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    checksum_sha256: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class QuestionMediaModel(Base):
    __tablename__ = "question_media"
    quiz_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    question_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    media_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("media.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[str] = mapped_column(String(30), primary_key=True)
    __table_args__ = (
        ForeignKeyConstraint(
            ["quiz_id", "question_id"],
            ["quiz_questions.quiz_id", "quiz_questions.question_id"],
            ondelete="CASCADE",
        ),
    )


class FlashcardMediaModel(Base):
    __tablename__ = "flashcard_media"
    deck_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    card_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    media_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("media.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[str] = mapped_column(String(30), primary_key=True)
    __table_args__ = (
        ForeignKeyConstraint(
            ["deck_id", "card_id"],
            ["flashcards.deck_id", "flashcards.card_id"],
            ondelete="CASCADE",
        ),
    )


class QuizEditHistoryModel(Base):
    __tablename__ = "quiz_edit_history"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    quiz_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("quizzes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    changed_by: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="SET NULL")
    )
    source_actor_id: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_role: Mapped[str] = mapped_column(String(30), nullable=False)
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    change_summary: Mapped[str] = mapped_column(Text, nullable=False)
    changed_fields: Mapped[object] = mapped_column(JSON_VALUE, nullable=False)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class FlashcardEditHistoryModel(Base):
    __tablename__ = "flashcard_edit_history"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    deck_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("flashcard_decks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    changed_by: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="SET NULL")
    )
    source_actor_id: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_role: Mapped[str] = mapped_column(String(30), nullable=False)
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    change_summary: Mapped[str] = mapped_column(Text, nullable=False)
    changed_fields: Mapped[object] = mapped_column(JSON_VALUE, nullable=False)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class QuizModerationHistoryModel(Base):
    __tablename__ = "quiz_moderation_history"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    quiz_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("quizzes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    moderator_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="SET NULL")
    )
    source_actor_id: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class FlashcardModerationHistoryModel(Base):
    __tablename__ = "flashcard_moderation_history"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    deck_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("flashcard_decks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    moderator_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="SET NULL")
    )
    source_actor_id: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
