"""Canonical roles, content lifecycle, visibility, and account-state rules."""

ROLES = ("student", "teacher", "admin")
ACCOUNT_STATUSES = ("active", "banned")
CONTENT_STATUSES = ("draft", "pending_review", "published", "rejected", "banned")
VISIBILITIES = ("private", "class_only", "public")

ROLE_LABELS = {
    "student": "Student",
    "teacher": "Teacher",
    "admin": "Admin",
}
CONTENT_STATUS_LABELS = {
    "draft": "Draft",
    "pending_review": "Pending Review",
    "published": "Published",
    "rejected": "Rejected",
    "banned": "Banned",
}
VISIBILITY_LABELS = {
    "private": "Draft (Private)",
    "class_only": "Class-Only (Invite Code)",
    "public": "Public (Submit for Review)",
}

# These are domain transitions. The UI may expose a smaller role-specific subset.
ALLOWED_CONTENT_TRANSITIONS = {
    "draft": {"pending_review"},
    "pending_review": {"published", "rejected", "banned"},
    "published": {"draft", "banned"},
    "rejected": {"draft", "banned"},
    "banned": {"draft"},
}


def is_role(value: str) -> bool:
    return value in ROLES


def is_account_status(value: str) -> bool:
    return value in ACCOUNT_STATUSES


def is_content_status(value: str) -> bool:
    return value in CONTENT_STATUSES


def is_visibility(value: str) -> bool:
    return value in VISIBILITIES


def visibility_submission_status(visibility: str) -> str:
    """Private work is draft; class-only/public work enters moderation."""
    return "draft" if visibility == "private" else "pending_review"


def default_visibility_for_status(status: str) -> str:
    return "private" if status == "draft" else "public"


def can_create_content(role: str) -> bool:
    """Return whether a role may create quizzes or flashcard decks."""
    return role in {"teacher", "admin"}


def can_edit_content(role: str, owns_content: bool) -> bool:
    """Admins may edit all content; teachers are limited to their own."""
    return role == "admin" or (role == "teacher" and owns_content)


def can_manage_class(role: str, owns_content: bool) -> bool:
    """Class rosters belong to the teacher who owns the content."""
    return role == "teacher" and owns_content


def can_moderate_content(role: str) -> bool:
    return role == "admin"


def can_ban_accounts(role: str) -> bool:
    return role == "admin"
