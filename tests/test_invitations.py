import json

from src.storage.flashcard_repository import FlashcardRepository
from src.storage.invitation_repository import InvitationRepository
from src.storage.moderation_repository import ModerationRepository
from src.storage.quiz_repository import QuizRepository


def test_class_only_invitation_enrols_student_and_rotation_revokes_old_code(tmp_path):
    flashcards = FlashcardRepository(tmp_path / "flashcards", tmp_path / "decks.json")
    quizzes = QuizRepository(tmp_path / "quizzes", tmp_path / "quizzes.json")
    assert flashcards.create_deck("Math Basics", owner_id="teacher-1")
    moderation = ModerationRepository(flashcards, quizzes)
    invites = InvitationRepository(moderation)
    item = moderation.get_all_content()[0]

    success, code = invites.generate_or_rotate_code(item["file"], "flashcard", "teacher-1")
    assert success
    assert "-" in code
    assert not invites.enroll_with_code(code, "student-1")[0]

    assert moderation.update_status(item, "published", "admin", visibility="class_only")
    success, message = invites.enroll_with_code(code, "student-1")
    assert success and "Math Basics" in message

    data = json.loads(item["path"].read_text(encoding="utf-8"))
    metadata = data["moderation"]
    assert "student-1" in metadata["enrollments"]
    assert "student-1" in metadata["allowed_user_ids"]

    success, rotated = invites.generate_or_rotate_code(item["file"], "flashcard", "teacher-1")
    assert success and rotated != code
    assert not invites.enroll_with_code(code, "student-2")[0]
    assert invites.enroll_with_code(rotated, "student-2")[0]


def test_only_owner_can_manage_an_invitation_code(tmp_path):
    flashcards = FlashcardRepository(tmp_path / "flashcards", tmp_path / "decks.json")
    quizzes = QuizRepository(tmp_path / "quizzes", tmp_path / "quizzes.json")
    flashcards.create_deck("Private Deck", owner_id="teacher-1")
    moderation = ModerationRepository(flashcards, quizzes)
    item = moderation.get_all_content()[0]
    assert InvitationRepository(moderation).generate_or_rotate_code(
        item["file"], "flashcard", "teacher-2"
    )[0] is False
