import json

from src.storage.flashcard_repository import FlashcardRepository
from src.storage.invitation_repository import InvitationRepository
from src.storage.moderation_repository import ModerationRepository
from src.storage.quiz_repository import QuizRepository
from src.controllers.quiz_controller import QuizController


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

    assert moderation.update_status(
        item, "published", "admin", visibility="class_only", actor_role="admin"
    )
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


def test_owner_roster_removal_and_progress_summary(tmp_path):
    flashcards = FlashcardRepository(tmp_path / "flashcards", tmp_path / "decks.json")
    quizzes = QuizRepository(tmp_path / "quizzes", tmp_path / "quizzes.json")
    flashcards.create_deck("Teacher Class", owner_id="teacher-1")
    moderation = ModerationRepository(flashcards, quizzes)
    invites = InvitationRepository(moderation)
    item = moderation.get_all_content()[0]
    flashcards.save_deck_content(item["file"], [{"id": "card-1", "front": "Q", "back": "A"}])
    moderation.update_status(
        item, "published", "admin", visibility="class_only", actor_role="admin"
    )
    _, code = invites.generate_or_rotate_code(item["file"], "flashcard", "teacher-1")
    assert invites.enroll_with_code(code, "student-1")[0]
    flashcards.save_deck_progress(item["file"], {"card-1": {"mastered": True}}, "student-1")
    assert len(moderation.get_content_for_selector("student-1", "student")) == 1

    roster = invites.get_owned_classes("teacher-1")
    assert len(roster) == 1
    assert roster[0]["roster"][0]["mastered"] == 1
    assert invites.get_owned_classes("teacher-2") == []
    assert invites.remove_enrollment(item["file"], "flashcard", "teacher-2", "student-1")[0] is False
    assert invites.remove_enrollment(item["file"], "flashcard", "teacher-1", "student-1")[0]
    assert invites.get_owned_classes("teacher-1")[0]["roster"] == []
    assert moderation.get_content_for_selector("student-1", "student") == []


def test_invalid_and_unavailable_codes_cannot_enroll_or_appear_in_roster(tmp_path):
    flashcards = FlashcardRepository(tmp_path / "flashcards", tmp_path / "decks.json")
    quizzes = QuizRepository(tmp_path / "quizzes", tmp_path / "quizzes.json")
    flashcards.create_deck("Restricted", owner_id="teacher-1")
    moderation = ModerationRepository(flashcards, quizzes)
    invites = InvitationRepository(moderation)
    item = moderation.get_all_content()[0]
    _, code = invites.generate_or_rotate_code(item["file"], "flashcard", "teacher-1")

    assert not invites.enroll_with_code("NOT-A-CODE", "student-1")[0]
    assert not invites.enroll_with_code(code, "student-1")[0]  # still a draft
    assert invites.get_owned_classes("teacher-1") == []

    moderation.update_status(
        item, "published", "admin", visibility="class_only", actor_role="admin"
    )
    assert invites.enroll_with_code(code, "student-1")[0]
    moderation.update_status(item, "banned", "admin", actor_role="admin")
    assert not invites.enroll_with_code(code, "student-2")[0]
    assert invites.get_owned_classes("teacher-1") == []


def test_quiz_roster_reports_grades_attempts_and_question_analytics(tmp_path):
    flashcards = FlashcardRepository(tmp_path / "flashcards", tmp_path / "decks.json")
    quizzes = QuizRepository(tmp_path / "quizzes", tmp_path / "quizzes.json")
    quizzes.create_quiz(
        "Assessment", [
            {"id": "q1", "type": "short_answer", "question": "Capital?", "answer": "Ottawa"},
            {"id": "q2", "type": "short_answer", "question": "Organ?", "answer": "Heart"},
        ], owner_id="teacher-1", test_settings={"attempt_limit": 3},
    )
    moderation = ModerationRepository(flashcards, quizzes)
    invites = InvitationRepository(moderation)
    item = moderation.get_all_content()[0]
    moderation.update_status(
        item, "published", "admin", visibility="class_only", actor_role="admin"
    )
    _, code = invites.generate_or_rotate_code(item["file"], "quiz", "teacher-1")
    assert invites.enroll_with_code(code, "student-1")[0]

    controller = QuizController("student-1", quizzes, role="student")
    controller.load_quiz_by_name("Assessment", mode="test")
    while controller.quiz.current_card is not None:
        answer = controller.quiz.current_card.answer
        if controller.submit_answer(answer)["type"] == "review":
            break
    controller.finalize_test_attempt()

    roster = invites.get_owned_classes("teacher-1")[0]
    student = roster["roster"][0]
    assert student["best_grade"] == 100.0
    assert student["average_grade"] == 100.0
    assert student["attempts_used"] == 1
    assert student["assessment_status"] == "Finished"
    assert roster["class_average"] == 100.0
    analytics = invites.get_quiz_analytics(item["file"], "teacher-1")
    assert [row["correct_rate"] for row in analytics] == [100.0, 100.0]


def test_teacher_controls_answer_review_policy(tmp_path):
    flashcards = FlashcardRepository(tmp_path / "flashcards", tmp_path / "decks.json")
    quizzes = QuizRepository(tmp_path / "quizzes", tmp_path / "quizzes.json")
    quizzes.create_quiz("Review Rules", owner_id="teacher-1")
    moderation = ModerationRepository(flashcards, quizzes)
    invites = InvitationRepository(moderation)
    item = moderation.get_all_content()[0]
    assert invites.update_answer_review_policy(
        item["file"], "teacher-1", "after_due_date"
    )
    assert quizzes.get_test_settings(item["file"])["answer_review_policy"] == "after_due_date"
    assert not invites.update_answer_review_policy(item["file"], "teacher-2", "never")
    assert not invites.update_answer_review_policy(item["file"], "teacher-1", "invalid")
