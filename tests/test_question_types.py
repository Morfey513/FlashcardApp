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
