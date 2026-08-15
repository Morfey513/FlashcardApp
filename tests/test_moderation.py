import json

from src.storage.flashcard_repository import FlashcardRepository
from src.storage.moderation_repository import ModerationRepository
from src.storage.quiz_repository import QuizRepository
from src.storage.user_repository import UserRepository


def test_moderation_status_is_preserved_when_content_is_saved(tmp_path):
    flashcards = FlashcardRepository(tmp_path / "flashcards", tmp_path / "decks.json")
    quizzes = QuizRepository(tmp_path / "quizzes", tmp_path / "quizzes.json")
    assert flashcards.create_deck("Private draft", owner_id="teacher-1")

    moderation = ModerationRepository(flashcards, quizzes)
    item = moderation.get_all_content()[0]
    assert item["status"] == "draft"
    assert item["visibility"] == "private"
    assert moderation.update_status(
        item, "pending_review", "teacher-1", "Ready to review",
        visibility="class_only", actor_role="teacher",
    )

    flashcards.save_deck_content(item["file"], [{"id": "card-1", "front": "Q", "back": "A"}])
    deck_data = json.loads(item["path"].read_text(encoding="utf-8"))
    history = json.loads((item["path"].parent / "moderation_history.json").read_text(encoding="utf-8"))
    assert deck_data["moderation"]["status"] == "pending_review"
    assert deck_data["moderation"]["visibility"] == "class_only"
    assert history[-1]["action"] == "pending_review"


def test_lifecycle_visibility_and_account_bans(tmp_path):
    flashcards = FlashcardRepository(tmp_path / "flashcards", tmp_path / "decks.json")
    quizzes = QuizRepository(tmp_path / "quizzes", tmp_path / "quizzes.json")
    assert flashcards.create_deck("Teacher draft", owner_id="teacher-1")
    moderation = ModerationRepository(flashcards, quizzes)

    assert moderation.get_content_for_user("student-1", "student") == []
    assert len(moderation.get_content_for_user("teacher-1", "teacher")) == 1

    item = moderation.get_all_content()[0]
    assert moderation.update_status(
        item, "pending_review", "teacher-2", actor_role="teacher"
    ) is False
    assert moderation.update_status(
        item, "published", "teacher-1", actor_role="teacher"
    ) is False
    assert moderation.update_status(
        item, "pending_review", "student-1", actor_role="student"
    ) is False
    assert moderation.update_status(
        item, "published", "admin", visibility="public", actor_role="admin"
    )
    assert len(moderation.get_content_for_user("student-1", "student")) == 1
    assert moderation.update_status(item, "banned", "admin", actor_role="admin")
    assert moderation.get_content_for_user("teacher-1", "teacher") == []
    assert len(moderation.get_content_for_selector("teacher-1", "teacher")) == 1
    assert moderation.get_content_for_selector("admin", "admin") == []

    users = UserRepository(tmp_path / "users.json")
    admin = users.authenticate("admin", "admin123")
    assert users.set_account_status(
        "teacher", admin["id"], "banned", "Not authorized"
    ) is False
    assert users.set_account_status(
        "admin", admin["id"], "banned", "Repeated guideline violations"
    )
    assert users.authenticate("admin", "admin123") is None
    assert "Repeated guideline violations" in users.get_ban_message("admin")
