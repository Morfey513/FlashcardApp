from src.controllers.quiz_controller import QuizController
from src.logic.quiz_logic import Quiz
from src.storage.quiz_repository import QuizRepository


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
