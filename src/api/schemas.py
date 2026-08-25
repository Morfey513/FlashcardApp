"""Validated request and response models for the identity API."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RegistrationRequest(StrictRequest):
    name: str = Field(min_length=1, max_length=100)
    login: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=8, max_length=1024)


class LoginRequest(StrictRequest):
    login: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=1, max_length=1024)


class PreferencesRequest(StrictRequest):
    preferences: dict[str, Any]


class DisplayNameRequest(StrictRequest):
    name: str = Field(min_length=1, max_length=100)


class PasswordChangeRequest(StrictRequest):
    current_password: str = Field(min_length=1, max_length=1024)
    new_password: str = Field(min_length=8, max_length=1024)


class RoleUpdateRequest(StrictRequest):
    role: Literal["student", "teacher", "admin"]


class AccountStatusRequest(StrictRequest):
    status: Literal["active", "banned"]
    reason: str = Field(default="", max_length=2000)


class PublicProfilesRequest(StrictRequest):
    user_ids: list[str] = Field(min_length=1, max_length=100)


class UserResponse(BaseModel):
    id: str
    login: str
    name: str
    role: str
    status: str
    preferences: dict[str, Any]
    email: str | None = None


class PublicUserResponse(BaseModel):
    """Minimal account identity safe to show in a teacher's class roster."""

    id: str
    login: str
    name: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserResponse


class ContentMetadataRequest(StrictRequest):
    id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=255)
    status: Literal["draft", "pending_review", "published", "rejected", "banned"]
    visibility: Literal["private", "class_only", "public"]
    source_path: str = Field(min_length=1, max_length=2000)
    test_settings: dict[str, Any] | None = None
    review_note: str = Field(default="", max_length=4000)


class ContentMetadataResponse(BaseModel):
    id: str
    kind: Literal["quiz", "flashcard"]
    name: str
    owner_id: str | None
    source_owner_id: str
    owner_resolved: bool
    status: str
    visibility: str
    source_path: str
    created_at: str | None
    updated_at: str | None
    content_version: int
    test_settings: dict[str, Any] | None = None


class JoinClassRequest(StrictRequest):
    code: str = Field(min_length=1, max_length=64)


class MessageResponse(BaseModel):
    message: str


class InvitationResponse(BaseModel):
    code: str


class ProgressEntry(StrictRequest):
    correct: int = Field(default=0, ge=0)
    wrong: int = Field(default=0, ge=0)
    mastered: bool = False


class LearningProgressRequest(StrictRequest):
    progress: dict[str, ProgressEntry]


class QuizAttemptRequest(StrictRequest):
    id: str = Field(min_length=1, max_length=64)
    quiz_id: str = Field(min_length=1, max_length=64)
    mode: str = "test"
    status: str | None = None
    started_at: str | None = None
    last_activity_at: str | None = None
    submitted_at: str | None = None
    interrupted_at: str | None = None
    score: int = 0
    total: int = 0
    percentage: float = 0.0
    passing_grade_percent: int | None = None
    passed: bool | None = None
    attempt_number: int = Field(default=1, ge=1)
    counts_toward_limit: bool = True
    duration_seconds: int | None = None
    current_question: int | None = None
    answered_count: int | None = None
    resolved_by: str | None = None
    resolved_at: str | None = None
    resolution: str | None = None
    answers: list[dict[str, Any]] = Field(default_factory=list)


class AssessmentResponseRequest(StrictRequest):
    user_answer: Any = None


class AssessmentSubmitRequest(StrictRequest):
    responses: dict[str, Any] = Field(default_factory=dict)


class ContentBodyRequest(StrictRequest):
    id: str = Field(min_length=1, max_length=64)
    name: str = Field(default="", max_length=255)
    questions: list[dict[str, Any]] | None = None
    cards: list[dict[str, Any]] | None = None


class MediaUploadRequest(StrictRequest):
    filename: str = Field(min_length=1, max_length=255)
    content_base64: str = Field(min_length=1)


class MediaUploadResponse(BaseModel):
    stored_path: str


class AttemptResolutionRequest(StrictRequest):
    action: Literal["submit_current", "refund", "mark_zero"]
