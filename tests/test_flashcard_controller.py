from src.controllers.flashcard_controller import FlashcardController
from src.storage.flashcard_repository import FlashcardRepository


def test_controller_exposes_current_user_progress_and_guest_clear(tmp_path):
    repo = FlashcardRepository(tmp_path / "flashcards", tmp_path / "decks.json")
    repo.create_deck("Science", [{"id": "c1", "front": "Question", "back": "Answer"}])
    deck = repo.get_all_decks()[0]
    repo.save_deck_progress(deck["file"], {"c1": {"mastered": True}}, "guest")
    repo.save_deck_progress(deck["file"], {"c1": {"mastered": True}}, "student-2")

    guest = FlashcardController("guest", repo)
    assert guest.get_deck_summaries()[0]["mastered"] == 1
    assert guest.clear_guest_progress() == 1
    assert repo.get_progress(deck["file"], "guest") == {}
    assert repo.get_progress(deck["file"], "student-2") != {}

    student = FlashcardController("student-2", repo)
    assert student.clear_guest_progress() == 0
    assert student.reset_deck_progress("Science") is True
    assert repo.get_progress(deck["file"], "student-2") == {}


def test_mastering_a_card_returns_the_next_card(tmp_path):
    repo = FlashcardRepository(tmp_path / "flashcards", tmp_path / "decks.json")
    repo.create_deck("Science", [
        {"id": "first", "front": "One", "back": "1"},
        {"id": "second", "front": "Two", "back": "2"},
    ])
    deck = repo.get_all_decks()[0]
    repo.save_deck_progress(deck["file"], {
        "first": {"correct": 5, "wrong": 0},
        "second": {"correct": 5, "wrong": 0},
    }, "guest")
    controller = FlashcardController("guest", repo)

    first_card = controller.start_deck("Science")
    assert first_card["id"] in {"first", "second"}
    mastered, next_card = controller.toggle_current_card_mastery()

    assert mastered is True
    assert next_card["id"] in {"first", "second"}
    assert next_card["id"] != first_card["id"]
    assert repo.get_progress(deck["file"], "guest")[first_card["id"]]["mastered"] is True


def test_completed_deck_can_be_reset_and_started_again(tmp_path):
    repo = FlashcardRepository(tmp_path / "flashcards", tmp_path / "decks.json")
    repo.create_deck("Complete", [{"id": "only", "front": "Q", "back": "A"}])
    deck = repo.get_all_decks()[0]
    repo.save_deck_progress(deck["file"], {"only": {"mastered": True}}, "student-2")
    controller = FlashcardController("student-2", repo)

    assert controller.is_deck_complete("Complete") is True
    assert controller.start_deck("Complete") is None
    assert controller.reset_deck_progress("Complete") is True
    assert controller.is_deck_complete("Complete") is False
    assert controller.start_deck("Complete")["id"] == "only"
