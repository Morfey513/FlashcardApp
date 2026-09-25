import json
from pathlib import Path

from src.logic.flashcard_logic import FlashcardSession
from src.logic.quiz_logic import Quiz


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_canonical_quiz_demo_covers_every_question_type():
    rows = _load(PROJECT_ROOT / "data" / "quizzes.json")
    assert len(rows) == 1

    quiz = _load(PROJECT_ROOT / rows[0]["file"])
    assert quiz["name"] == "Question Types Demo Quiz"
    assert len(quiz["questions"]) == 6
    assert {question["type"] for question in quiz["questions"]} == {
        "short_answer",
        "single_choice",
        "multiple_choice",
        "true_false",
        "matching",
        "ordering",
    }
    assert len(Quiz(quiz["questions"], shuffle=False).cards) == 6


def test_canonical_flashcard_demo_has_two_cards_and_valid_media():
    rows = _load(PROJECT_ROOT / "data" / "flashcard_decks.json")
    assert len(rows) == 1

    deck = _load(PROJECT_ROOT / rows[0]["file"])
    assert deck["name"] == "Media Demo Flashcards"
    assert deck["moderation"]["status"] == "published"
    assert len(deck["cards"]) == 2
    assert all(card["front"] and card["back"] for card in deck["cards"])

    media_card = deck["cards"][0]
    media_paths = [media_card["image"], *media_card["audio"].values()]
    assert media_card["hint"] and media_card["description"]
    assert all((PROJECT_ROOT / path).is_file() for path in media_paths)
    assert len(FlashcardSession(deck["cards"], {}).study_cards) == 2
