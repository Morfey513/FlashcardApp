"""Persistence-backend selection for repositories."""

import os

from src.runtime_config import load_runtime_environment
from src.storage.user_repository import JsonUserRepository
from src.storage.user_repository_contract import UserRepositoryContract


STORAGE_BACKEND_ENV = "STUDY_BUDDY_STORAGE"
load_runtime_environment()


def configured_storage_backend() -> str:
    """Return the normalized backend selected by process or local config."""
    return os.getenv(STORAGE_BACKEND_ENV, "json").strip().casefold()


def create_user_repository() -> UserRepositoryContract:
    """Create the configured repository; JSON remains the safe default."""
    backend = configured_storage_backend()
    if backend == "json":
        return JsonUserRepository()
    if backend in {"postgres", "postgresql"}:
        from src.storage.postgres_user_repository import PostgresUserRepository

        return PostgresUserRepository()
    if backend in {"api", "http"}:
        from src.storage.http_user_repository import HttpUserRepository

        return HttpUserRepository()
    raise ValueError(
        f"Unsupported {STORAGE_BACKEND_ENV} value: {backend!r}; "
        "expected 'json', 'postgresql', or 'api'"
    )


def _authenticated_api(user_repository) -> bool:
    return bool(
        configured_storage_backend() in {"api", "http"}
        and user_repository is not None
        and getattr(user_repository, "_token", None)
    )


def create_quiz_repository(user_repository=None):
    if _authenticated_api(user_repository):
        from src.storage.http_domain_repositories import HttpQuizRepository
        return HttpQuizRepository(user_repository)
    from src.storage.quiz_repository import QuizRepository
    return QuizRepository()


def create_flashcard_repository(user_repository=None):
    if _authenticated_api(user_repository):
        from src.storage.http_domain_repositories import HttpFlashcardRepository
        return HttpFlashcardRepository(user_repository)
    from src.storage.flashcard_repository import FlashcardRepository
    return FlashcardRepository()


def create_moderation_repository(user_repository=None, *, flashcards=None, quizzes=None):
    from src.storage.moderation_repository import ModerationRepository
    return ModerationRepository(
        flashcards=flashcards or create_flashcard_repository(user_repository),
        quizzes=quizzes or create_quiz_repository(user_repository),
    )


def create_class_repository(user_repository=None, moderation=None):
    if _authenticated_api(user_repository):
        from src.storage.http_class_repository import HttpClassRepository
        return HttpClassRepository(user_repository)
    from src.storage.invitation_repository import InvitationRepository
    return InvitationRepository(moderation)


def create_content_library(*, quiz_repository=None, flashcard_repository=None, cache_root=None):
    """Create the additive local library facade without changing content repositories."""
    from src.storage.content_library import ContentLibrary

    return ContentLibrary(
        quiz_repository=quiz_repository,
        flashcard_repository=flashcard_repository,
        cache_root=cache_root,
    )
