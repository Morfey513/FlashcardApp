from src.controllers.profile_statistics_controller import ProfileStatisticsController
from src.storage.flashcard_repository import FlashcardRepository
from src.storage.quiz_repository import QuizRepository


def test_profile_statistics_reads_flashcard_and_quiz_progress(tmp_path):
    flashcards = FlashcardRepository(tmp_path / "flashcards", tmp_path / "decks.json")
    quizzes = QuizRepository(tmp_path / "quizzes", tmp_path / "quizzes.json")
    flashcards.create_deck("Deck", [{"id": "card", "front": "Prompt", "back": "Answer"}])
    quizzes.create_quiz("Quiz", [{"id": "question", "type": "short_answer", "question": "Question", "answer": "Answer"}])
    deck = flashcards.get_all_decks()[0]
    quiz = quizzes.get_all_quizzes()[0]
    flashcards.save_deck_progress(deck["file"], {"card": {"mastered": True, "correct": 6, "wrong": 1}}, "user-1")
    quizzes.save_quiz_progress(quiz["file"], {"question": {"mastered": False, "correct": 2, "wrong": 3}}, "user-1")

    controller = ProfileStatisticsController("user-1", flashcards, quizzes)
    flashcard_row = controller.get_flashcard_stats()["collections"][0]["rows"][0]
    quiz_row = controller.get_quiz_stats()["collections"][0]["rows"][0]

    assert flashcard_row == {"text": "Prompt", "mastered": True, "correct": 6, "wrong": 1}
    assert quiz_row == {"text": "Question", "mastered": False, "correct": 2, "wrong": 3}


def test_profile_statistics_resets_named_collections_and_all_progress(tmp_path):
    flashcards = FlashcardRepository(tmp_path / "flashcards", tmp_path / "decks.json")
    quizzes = QuizRepository(tmp_path / "quizzes", tmp_path / "quizzes.json")
    flashcards.create_deck("Deck", [{"id": "card", "front": "Prompt", "back": "Answer"}])
    quizzes.create_quiz("Quiz", [{"id": "question", "type": "short_answer", "question": "Q", "answer": "A"}])
    deck = flashcards.get_all_decks()[0]
    quiz = quizzes.get_all_quizzes()[0]
    controller = ProfileStatisticsController("user-1", flashcards, quizzes)

    flashcards.save_deck_progress(deck["file"], {"card": {"mastered": True}}, "user-1")
    quizzes.save_quiz_progress(quiz["file"], {"question": {"mastered": True}}, "user-1")
    assert controller.reset_collection("flashcards", "Missing") is False
    assert controller.reset_collection("flashcards", "Deck") is True
    assert controller.reset_collection("quizzes", "Quiz") is True

    flashcards.save_deck_progress(deck["file"], {"card": {"mastered": True}}, "user-1")
    quizzes.save_quiz_progress(quiz["file"], {"question": {"mastered": True}}, "user-1")
    assert controller.reset_all("flashcards") == 1
    assert quizzes.get_quiz_progress(quiz["file"], "user-1") != {}
    assert controller.reset_all() == 1
    assert quizzes.get_quiz_progress(quiz["file"], "user-1") == {}
