import pytest

from src.controllers.quiz_controller import QuizController


@pytest.mark.parametrize(
    ("question_type", "user_answer", "correct_answer", "expected"),
    [
        ("true_false", True, True, True),
        ("short_answer", " Paris ", "paris", True),
        ("single_choice", "A", "A", True),
        ("multiple_choice", ["B", "A"], ["A", "B"], True),
        (
            "matching",
            [{"prompt": "France", "answer": "Paris"}],
            [{"prompt": "France", "answer": "Paris"}],
            True,
        ),
        ("ordering", ["first", "second"], ["first", "second"], True),
        ("ordering", ["second", "first"], ["first", "second"], False),
    ],
)
def test_question_grading(
    question_type, user_answer, correct_answer, expected
):
    controller = object.__new__(QuizController)
    assert controller._check_logic({
        "type": question_type,
        "user_answer": user_answer,
        "correct_answer": correct_answer,
    }) is expected
