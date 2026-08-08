import random

from src.logic.flashcard_logic import FlashcardSession


def test_mastery_eligibility_uses_the_weighted_wrong_answer_penalty():
    cards = [{"id": "card-1", "front": "Q", "back": "A"}]
    session = FlashcardSession(cards, {"card-1": {"correct": 5, "wrong": 0}})
    assert session.is_eligible_for_mastery("card-1")
    session.progress["card-1"] = {"correct": 6, "wrong": 1}
    assert not session.is_eligible_for_mastery("card-1")
    session.progress["card-1"] = {"correct": 8, "wrong": 2}
    assert session.is_eligible_for_mastery("card-1")


def test_mastered_cards_are_excluded_from_new_session():
    cards = [
        {"id": "ready", "front": "Q1", "back": "A1"},
        {"id": "todo", "front": "Q2", "back": "A2"},
    ]
    session = FlashcardSession(cards, {
        "ready": {"correct": 5, "wrong": 0, "mastered": True}
    })
    assert [card["id"] for card in session.study_cards] == ["todo"]


def test_mark_answer_updates_persistent_and_session_counts():
    cards = [{"id": "card-1", "front": "Q", "back": "A"}]
    session = FlashcardSession(cards, {})
    session.mark_answer(True)
    assert session.progress["card-1"]["correct"] == 1
    assert session.session_stats["known"] == 1


def test_session_is_limited_to_twenty_unique_shuffled_cards():
    cards = [{"id": str(index), "front": str(index), "back": str(index)} for index in range(25)]
    session = FlashcardSession(cards, {}, rng=random.Random(7))

    assert len(session.study_cards) == 20
    assert len({card["id"] for card in session.study_cards}) == 20
    assert [card["id"] for card in session.study_cards] != [str(index) for index in range(20)]


def test_cards_with_more_mistakes_have_a_higher_selection_weight():
    cards = [
        {"id": "strong", "front": "Q", "back": "A"},
        {"id": "weak", "front": "Q", "back": "A"},
    ]
    session = FlashcardSession(cards, {
        "strong": {"correct": 8, "wrong": 0},
        "weak": {"correct": 1, "wrong": 4},
    })

    assert session._selection_weight(cards[1]) > session._selection_weight(cards[0])


def test_wrong_answer_adds_one_delayed_retry_to_the_learning_queue():
    cards = [
        {"id": "one", "front": "1", "back": "1"},
        {"id": "two", "front": "2", "back": "2"},
        {"id": "three", "front": "3", "back": "3"},
    ]
    session = FlashcardSession(cards, {}, rng=random.Random(1))
    current_id = session.get_current_card()["id"]

    session.mark_answer(False)
    assert [card["id"] for card in session.study_cards].count(current_id) == 2

    session.current_index = next(
        index
        for index, card in enumerate(session.study_cards)
        if index > 0 and card["id"] == current_id
    )
    session.mark_answer(False)
    assert [card["id"] for card in session.study_cards].count(current_id) == 2
