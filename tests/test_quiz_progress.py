from datetime import datetime, timedelta, timezone

from src.controllers.quiz_controller import QuizController
from src.logic.quiz_logic import Quiz
from src.storage.quiz_repository import QuizRepository
from src.storage.moderation_repository import ModerationRepository
from src.storage.flashcard_repository import FlashcardRepository


def test_quiz_question_ids_survive_conversion_to_runtime_questions():
    quiz = Quiz([
        {"id": "stable-id", "type": "short_answer", "question": "Q", "answer": "A"}
    ])
    assert quiz.cards[0].id == "stable-id"


def test_quiz_mastery_progress_is_isolated_per_user_and_resettable(tmp_path):
    repo = QuizRepository(tmp_path / "quizzes", tmp_path / "quizzes.json")
    repo.create_quiz("Science", [
        {"id": "q1", "type": "short_answer", "question": "One", "answer": "1"},
        {"id": "q2", "type": "short_answer", "question": "Two", "answer": "2"},
    ])

    first = QuizController("student-1", repo)
    second = QuizController("student-2", repo)
    quiz_file = repo.get_all_quizzes()[0]["file"]
    repo.save_quiz_progress(quiz_file, {"q1": {"correct": 5, "wrong": 0}}, "student-1")
    assert first.load_quiz_by_name("Science") is not None
    assert first.toggle_question_mastery("q1") is True

    assert first.get_quiz_summary("Science")["mastered"] == 1
    assert second.get_quiz_summary("Science")["mastered"] == 0
    assert first.reset_quiz_progress("Science") is True
    assert first.get_quiz_summary("Science")["mastered"] == 0


def test_completed_quiz_can_be_reset_and_started_again(tmp_path):
    repo = QuizRepository(tmp_path / "quizzes", tmp_path / "quizzes.json")
    repo.create_quiz("Single", [
        {"id": "q1", "type": "short_answer", "question": "One", "answer": "1"}
    ])
    controller = QuizController("guest", repo)
    quiz_file = repo.get_all_quizzes()[0]["file"]
    repo.save_quiz_progress(quiz_file, {"q1": {"correct": 5, "wrong": 0}}, "guest")
    assert controller.load_quiz_by_name("Single") is not None
    assert controller.toggle_question_mastery("q1") is True

    assert controller.is_quiz_complete("Single") is True
    assert controller.reset_quiz_progress("Single") is True
    assert controller.load_quiz_by_name("Single")["id"] == "q1"


def test_quiz_attempts_use_flashcard_mastery_threshold(tmp_path):
    repo = QuizRepository(tmp_path / "quizzes", tmp_path / "quizzes.json")
    repo.create_quiz("Single", [
        {"id": "q1", "type": "short_answer", "question": "One", "answer": "1"}
    ])
    controller = QuizController("guest", repo)
    assert controller.load_quiz_by_name("Single") is not None

    for _ in range(5):
        controller.submit_answer("1")
    assert controller.get_question_progress("q1") == {
        "correct": 5, "wrong": 0, "mastered": False
    }
    assert controller.is_eligible_for_mastery("q1") is True
    assert controller.toggle_question_mastery("q1") is True

    controller.toggle_question_mastery("q1")
    controller.submit_answer("wrong")
    assert controller.is_eligible_for_mastery("q1") is False
    assert controller.toggle_question_mastery("q1") is False


def test_test_mode_uses_every_question_and_saves_result_without_progress(tmp_path):
    repo = QuizRepository(tmp_path / "quizzes", tmp_path / "quizzes.json")
    questions = [
        {"id": f"q{i}", "type": "short_answer", "question": f"Q{i}", "answer": str(i)}
        for i in range(25)
    ]
    repo.create_quiz("Exam", questions)
    controller = QuizController("student-1", repo)

    assert controller.load_quiz_by_name("Exam", mode="test") is not None
    assert controller.is_test_mode is True
    assert len(controller.quiz.cards) == 25

    while controller.quiz.current_card is not None:
        expected = controller.quiz.current_card.answer
        result = controller.submit_answer(expected)
        if result["type"] == "review":
            break

    attempt = controller.finalize_test_attempt()
    quiz_file = repo.get_all_quizzes()[0]["file"]
    assert attempt["score"] == 25
    assert attempt["percentage"] == 100.0
    assert repo.get_quiz_progress(quiz_file, "student-1") == {}
    assert repo.get_latest_test_attempt(quiz_file, "student-1")["id"] == attempt["id"]
    assert controller.finalize_test_attempt()["id"] == attempt["id"]


def test_class_only_test_allows_one_completed_attempt_but_public_is_unlimited(tmp_path):
    repo = QuizRepository(tmp_path / "quizzes", tmp_path / "quizzes.json")
    question = [{"id": "q1", "type": "short_answer", "question": "Q", "answer": "A"}]
    repo.create_quiz("Class Test", question, owner_id="teacher-1")
    repo.create_quiz("Public Test", question, owner_id="teacher-1")
    flashcards = FlashcardRepository(tmp_path / "flashcards", tmp_path / "decks.json")
    moderation = ModerationRepository(flashcards=flashcards, quizzes=repo)
    for item in moderation.get_all_content():
        visibility = "class_only" if item["name"] == "Class Test" else "public"
        assert moderation.update_status(
            item, "published", "admin", visibility=visibility, actor_role="admin"
        )

    controller = QuizController("teacher-1", repo, role="teacher")
    assert controller.get_test_policy("Class Test")["single_attempt"] is True
    assert controller.load_quiz_by_name("Class Test", mode="test") is not None
    controller.submit_answer("A")
    controller.finalize_test_attempt()
    assert controller.can_start_test("Class Test") is False
    assert controller.load_quiz_by_name("Class Test", mode="test") is None

    assert controller.get_test_policy("Public Test")["single_attempt"] is False
    assert controller.load_quiz_by_name("Public Test", mode="test") is not None
    controller.submit_answer("A")
    assert controller.finalize_test_attempt()["passed"] is None
    assert controller.can_start_test("Public Test") is True
    assert controller.load_quiz_by_name("Public Test", mode="test") is not None


def test_class_only_custom_test_rules_are_persisted_and_enforced(tmp_path):
    repo = QuizRepository(tmp_path / "quizzes", tmp_path / "quizzes.json")
    questions = [
        {"id": "q1", "type": "short_answer", "question": "Q1", "answer": "A"},
        {"id": "q2", "type": "short_answer", "question": "Q2", "answer": "B"},
    ]
    settings = {
        "time_limit_minutes": 15,
        "passing_grade_percent": 75,
        "attempt_limit": 2,
    }
    repo.create_quiz("Configured Test", questions, owner_id="teacher-1", test_settings=settings)
    flashcards = FlashcardRepository(tmp_path / "flashcards", tmp_path / "decks.json")
    moderation = ModerationRepository(flashcards=flashcards, quizzes=repo)
    item = moderation.get_all_content()[0]
    assert moderation.update_status(
        item, "published", "admin", visibility="class_only", actor_role="admin"
    )

    controller = QuizController("teacher-1", repo, role="teacher")
    policy = controller.get_test_policy("Configured Test")
    assert policy["attempt_limit"] == 2
    assert policy["attempts_remaining"] == 2
    assert policy["passing_grade_percent"] == 75
    assert policy["time_limit_minutes"] == 15

    assert controller.load_quiz_by_name("Configured Test", mode="test") is not None
    assert 0 < controller.get_remaining_test_seconds() <= 15 * 60
    controller.submit_answer(controller.quiz.current_card.answer)
    controller.submit_answer("wrong")
    first = controller.finalize_test_attempt()
    assert first["attempt_number"] == 1
    assert first["percentage"] == 50.0
    assert first["passed"] is False
    assert first["passing_grade_percent"] == 75

    assert controller.load_quiz_by_name("Configured Test", mode="test") is not None
    while controller.quiz.current_card is not None:
        answer = controller.quiz.current_card.answer
        if controller.submit_answer(answer)["type"] == "review":
            break
    second = controller.finalize_test_attempt()
    assert second["attempt_number"] == 2
    assert second["passed"] is True
    assert controller.can_start_test("Configured Test") is False
    assert controller.load_quiz_by_name("Configured Test", mode="test") is None


def test_zero_attempt_limit_allows_unlimited_class_test_attempts(tmp_path):
    repo = QuizRepository(tmp_path / "quizzes", tmp_path / "quizzes.json")
    question = [{"id": "q1", "type": "short_answer", "question": "Q", "answer": "A"}]
    repo.create_quiz(
        "Unlimited Test", question, owner_id="teacher-1",
        test_settings={"attempt_limit": 0, "passing_grade_percent": 60},
    )
    flashcards = FlashcardRepository(tmp_path / "flashcards", tmp_path / "decks.json")
    moderation = ModerationRepository(flashcards=flashcards, quizzes=repo)
    assert moderation.update_status(
        moderation.get_all_content()[0], "published", "admin",
        visibility="class_only", actor_role="admin"
    )

    controller = QuizController("teacher-1", repo, role="teacher")
    for _ in range(3):
        assert controller.load_quiz_by_name("Unlimited Test", mode="test") is not None
        controller.submit_answer("A")
        controller.finalize_test_attempt()
        assert controller.can_start_test("Unlimited Test") is True

    policy = controller.get_test_policy("Unlimited Test")
    assert policy["attempt_limit"] == 0
    assert policy["attempts_remaining"] is None


def test_expired_class_only_due_date_blocks_new_test_attempts(tmp_path):
    repo = QuizRepository(tmp_path / "quizzes", tmp_path / "quizzes.json")
    question = [{"id": "q1", "type": "short_answer", "question": "Q", "answer": "A"}]
    expired = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    repo.create_quiz(
        "Expired Test", question, owner_id="teacher-1",
        test_settings={"attempt_limit": 0, "due_at": expired},
    )
    flashcards = FlashcardRepository(tmp_path / "flashcards", tmp_path / "decks.json")
    moderation = ModerationRepository(flashcards=flashcards, quizzes=repo)
    assert moderation.update_status(
        moderation.get_all_content()[0], "published", "admin",
        visibility="class_only", actor_role="admin"
    )

    controller = QuizController("teacher-1", repo, role="teacher")
    policy = controller.get_test_policy("Expired Test")
    assert policy["due_expired"] is True
    assert policy["can_start"] is False
    assert controller.can_start_test("Expired Test") is False
    assert controller.load_quiz_by_name("Expired Test", mode="test") is None


def test_interrupted_attempt_is_checkpointed_and_refund_allows_retake(tmp_path):
    repo = QuizRepository(tmp_path / "quizzes", tmp_path / "quizzes.json")
    repo.create_quiz(
        "Interrupted", [
            {"id": "q1", "type": "short_answer", "question": "Q1", "answer": "A"},
            {"id": "q2", "type": "short_answer", "question": "Q2", "answer": "B"},
        ], owner_id="teacher-1", test_settings={"attempt_limit": 1},
    )
    moderation = ModerationRepository(
        flashcards=FlashcardRepository(tmp_path / "flashcards", tmp_path / "decks.json"),
        quizzes=repo,
    )
    assert moderation.update_status(
        moderation.get_all_content()[0], "published", "admin",
        visibility="class_only", actor_role="admin"
    )
    controller = QuizController("teacher-1", repo, role="teacher")
    assert controller.load_quiz_by_name("Interrupted", mode="test")
    controller.submit_answer(controller.quiz.cards[0].answer)
    abandoned = controller.abandon_test_attempt()
    assert abandoned["status"] == "abandoned"
    assert abandoned["answered_count"] == 1
    assert controller.get_test_policy("Interrupted")["can_start"] is False

    refunded = repo.resolve_test_attempt(
        repo.get_all_quizzes()[0]["file"], abandoned["id"], "refund", "teacher-1"
    )
    assert refunded["status"] == "refunded"
    assert refunded["counts_toward_limit"] is False
    assert controller.get_test_policy("Interrupted")["can_start"] is True


def test_teacher_can_autograde_answered_part_of_abandoned_attempt(tmp_path):
    repo = QuizRepository(tmp_path / "quizzes", tmp_path / "quizzes.json")
    repo.create_quiz(
        "Partial", [
            {"id": "q1", "type": "short_answer", "question": "Q1", "answer": "A"},
            {"id": "q2", "type": "short_answer", "question": "Q2", "answer": "B"},
        ], owner_id="teacher-1", test_settings={"passing_grade_percent": 50},
    )
    moderation = ModerationRepository(
        flashcards=FlashcardRepository(tmp_path / "flashcards", tmp_path / "decks.json"),
        quizzes=repo,
    )
    moderation.update_status(
        moderation.get_all_content()[0], "published", "admin",
        visibility="class_only", actor_role="admin"
    )
    controller = QuizController("teacher-1", repo, role="teacher")
    controller.load_quiz_by_name("Partial", mode="test")
    controller.submit_answer(controller.quiz.cards[0].answer)
    abandoned = controller.abandon_test_attempt()
    graded = repo.resolve_test_attempt(
        repo.get_all_quizzes()[0]["file"], abandoned["id"], "submit_current", "teacher-1"
    )
    assert graded["status"] == "submitted"
    assert graded["score"] == 1
    assert graded["percentage"] == 50.0
    assert graded["passed"] is True
