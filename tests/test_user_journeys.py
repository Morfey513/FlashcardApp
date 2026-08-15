from src.controllers.quiz_controller import QuizController
from src.storage.flashcard_repository import FlashcardRepository
from src.storage.invitation_repository import InvitationRepository
from src.storage.moderation_repository import ModerationRepository
from src.storage.quiz_repository import QuizRepository


def make_stack(tmp_path):
    quizzes = QuizRepository(tmp_path / "quizzes", tmp_path / "quizzes.json")
    flashcards = FlashcardRepository(tmp_path / "flashcards", tmp_path / "decks.json")
    moderation = ModerationRepository(flashcards=flashcards, quizzes=quizzes)
    invitations = InvitationRepository(moderation)
    return quizzes, moderation, invitations


def test_teacher_publishes_student_joins_takes_test_and_roster_receives_grade(tmp_path):
    quizzes, moderation, invitations = make_stack(tmp_path)
    assert quizzes.create_quiz(
        "Class assessment",
        [
            {"id": "q1", "type": "short_answer", "question": "2 + 2?", "answer": "4"},
            {"id": "q2", "type": "short_answer", "question": "3 + 3?", "answer": "6"},
        ],
        owner_id="teacher-1",
        test_settings={"attempt_limit": 1, "passing_grade_percent": 75},
    )
    item = moderation.get_all_content()[0]
    assert moderation.update_status(
        item, "pending_review", "teacher-1", visibility="class_only",
        actor_role="teacher",
    )
    item = moderation.get_all_content()[0]
    assert moderation.update_status(
        item, "published", "admin", visibility="class_only", actor_role="admin"
    )
    success, code = invitations.generate_or_rotate_code(item["file"], "quiz", "teacher-1")
    assert success is True
    assert invitations.enroll_with_code(code, "student-1")[0] is True

    student = QuizController("student-1", quizzes, role="student")
    assert student.get_available_quizzes() == ["Class assessment"]
    assert student.load_quiz_by_name("Class assessment", mode="test")
    while True:
        answer = student.quiz.get_current().answer
        if student.submit_answer(answer)["type"] == "review":
            break
    attempt = student.finalize_test_attempt()
    assert attempt["percentage"] == 100.0
    assert attempt["passed"] is True

    roster = invitations.get_owned_classes("teacher-1")[0]["roster"]
    assert roster[0]["user_id"] == "student-1"
    assert roster[0]["best_grade"] == 100.0
    assert roster[0]["assessment_status"] == "Finished"


def test_public_practice_updates_progress_while_ban_immediately_removes_access(tmp_path):
    quizzes, moderation, _invitations = make_stack(tmp_path)
    assert quizzes.create_quiz(
        "Public practice",
        [{"id": "q1", "type": "short_answer", "question": "Capital?", "answer": "Ottawa"}],
        owner_id="teacher-1",
    )
    item = moderation.get_all_content()[0]
    assert moderation.update_status(
        item, "published", "admin", visibility="public", actor_role="admin"
    )
    student = QuizController("student-1", quizzes, role="student")
    assert student.load_quiz_by_name("Public practice", mode="practice")
    student.submit_answer("Ottawa")
    quiz_file = quizzes.get_all_quizzes()[0]["file"]
    assert quizzes.get_quiz_progress(quiz_file, "student-1")["q1"]["correct"] == 1

    item = moderation.get_all_content()[0]
    assert moderation.update_status(
        item, "banned", "admin", note="Policy violation", actor_role="admin"
    )
    assert student.get_available_quizzes() == []
    assert student.load_quiz_by_name("Public practice") is None
