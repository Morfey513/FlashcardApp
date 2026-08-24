from src.logic.assessment_grading import grade_assessment, grade_question


def test_grade_all_supported_question_types():
    assert grade_question("true_false", True, True)
    assert grade_question("single_choice", "b", "b")
    assert grade_question("multiple_choice", ["a", "c"], ["c", "a"])
    assert grade_question("short_answer", ["Paris", "paris"], "PARIS")
    assert grade_question("matching", {"one": "1"}, {"one": "1"})
    assert grade_question("ordering", ["a", "b"], ["a", "b"])


def test_grade_assessment_returns_score_and_does_not_use_client_score():
    rows = [
        {"position": 0, "question_id": "q1", "grading_key_json": {"type": "single_choice", "answer": "yes"}},
        {"position": 1, "question_id": "q2", "grading_key_json": {"type": "true_false", "answer": False}},
    ]
    results, score, percentage = grade_assessment(rows, {"0": "yes", "1": True, "client_score": 999})
    assert score == 1
    assert percentage == 50.0
    assert results[0]["is_correct"] is True
    assert results[1]["is_correct"] is False
