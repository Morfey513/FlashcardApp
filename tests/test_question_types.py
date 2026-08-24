import pytest

from src.logic.question_types import QuestionFactory, normalize_matching_pairs


def test_legacy_matching_pairs_are_normalized():
    pairs, changed = normalize_matching_pairs([{"1": "France", "2": "Paris"}])
    assert changed
    assert pairs == [{"prompt": "France", "answer": "Paris"}]


def test_invalid_matching_pair_has_clear_error():
    with pytest.raises(ValueError, match="must contain 'prompt' and 'answer'"):
        normalize_matching_pairs([{"prompt": "France"}])


def test_choice_options_are_shuffled_without_losing_values():
    question = QuestionFactory.from_dict({
        "type": "single_choice",
        "question": "Pick",
        "choices": ["A", "B", "C"],
        "answer": "A",
    })
    question.shuffle()
    assert sorted(question.shuffled_options) == ["A", "B", "C"]


def test_quiz_preserve_presentation_does_not_shuffle_safe_options():
    from src.logic.quiz_logic import Quiz

    quiz = Quiz([{
        "id": "q1", "type": "single_choice", "question": "Pick",
        "choices": ["B", "A"],
    }], shuffle=True, preserve_presentation=True, max_questions=None)
    assert [card.id for card in quiz.cards] == ["q1"]
    assert quiz.cards[0].shuffled_options == ["B", "A"]


def test_quiz_preserve_presentation_keeps_matching_and_ordering_items():
    from src.logic.quiz_logic import Quiz

    quiz = Quiz([
        {"id": "m", "type": "matching", "question": "Match",
         "pairs": [{"prompt": "A", "answer": ""}], "right_options": ["one"]},
        {"id": "o", "type": "ordering", "question": "Order", "items": ["second", "first"]},
    ], preserve_presentation=True, max_questions=None)
    assert quiz.cards[0].shuffled_options == ["one"]
    assert quiz.cards[1].shuffled_options == ["second", "first"]
