import json

from src.storage.flashcard_repository import FlashcardRepository
from src.storage.quiz_repository import QuizRepository


def test_flashcard_repository_uses_deck_folder_and_user_progress(tmp_path):
    repo = FlashcardRepository(
        tmp_path / "flashcards",
        tmp_path / "flashcard_decks.json",
    )
    assert repo.create_deck("Biology", [{"id": "c1", "front": "Cell", "back": "Unit"}])
    deck = repo.get_all_decks()[0]
    deck_file = repo.resolve_path(deck["file"])
    assert deck_file.name == "deck.json"
    assert deck_file.parent.name == deck["id"]

    repo.save_deck_progress(deck["file"], {"c1": {"correct": 1}}, "student-1")
    repo.save_deck_progress(deck["file"], {"c1": {"correct": 2}}, "student-2")
    assert repo.get_progress(deck["file"], "student-1")["c1"]["correct"] == 1
    assert repo.get_progress(deck["file"], "student-2")["c1"]["correct"] == 2


def test_flashcard_index_rebuilds_from_deck_metadata(tmp_path):
    index = tmp_path / "flashcard_decks.json"
    repo = FlashcardRepository(tmp_path / "flashcards", index)
    repo.create_deck("History")
    index.unlink()
    rebuilt = repo.get_all_decks()
    assert rebuilt[0]["name"] == "History"


def test_quiz_repository_uses_quiz_folder_and_normalizes_data(tmp_path):
    repo = QuizRepository(tmp_path / "quizzes", tmp_path / "quizzes.json")
    questions = [{
        "type": "matching",
        "question": "Capitals",
        "pairs": [{"1": "France", "2": "Paris"}],
        "image": "legacy.png",
    }]
    assert repo.create_quiz("Geography", questions)
    quiz = repo.get_all_quizzes()[0]
    quiz_file = repo._resolve_path(quiz["file"])
    assert quiz_file.name == "quiz.json"
    loaded = repo.load_quiz_questions(quiz["file"])
    assert loaded[0]["pairs"] == [{"prompt": "France", "answer": "Paris"}]
    assert loaded[0]["image_path"] == "legacy.png"
    assert "image" not in loaded[0]


def test_repository_index_is_json(tmp_path):
    index = tmp_path / "quizzes.json"
    repo = QuizRepository(tmp_path / "quizzes", index)
    repo.create_quiz("One")
    assert json.loads(index.read_text(encoding="utf-8"))[0]["name"] == "One"


def test_media_is_copied_into_owning_quiz_folder(tmp_path):
    repo = QuizRepository(tmp_path / "quizzes", tmp_path / "quizzes.json")
    repo.create_quiz("Media Quiz")
    quiz = repo.get_all_quizzes()[0]
    source = tmp_path / "picture.png"
    source.write_bytes(b"image")
    stored = repo.import_media(quiz["file"], str(source))
    imported = repo._resolve_path(stored)
    assert imported.read_bytes() == b"image"
    assert imported.parent.name == "media"
    assert imported.parent.parent.name == quiz["id"]


def test_flashcard_media_is_copied_and_saved_with_the_card(tmp_path):
    repo = FlashcardRepository(tmp_path / "flashcards", tmp_path / "decks.json")
    assert repo.create_deck("Media Deck")
    deck = repo.get_all_decks()[0]

    image_source = tmp_path / "picture.png"
    audio_source = tmp_path / "pronunciation.mp3"
    image_source.write_bytes(b"image")
    audio_source.write_bytes(b"audio")

    image_path = repo.import_media(deck["file"], str(image_source))
    audio_path = repo.import_media(deck["file"], str(audio_source))
    repo.save_deck_content(deck["file"], [{
        "id": "card-1",
        "front": "Question",
        "back": "Answer",
        "image": image_path,
        "audio": {"front": audio_path, "back": audio_path},
    }])

    saved_card = repo.load_deck_cards(deck["file"])[0]
    imported_image = repo.resolve_path(saved_card["image"])
    imported_audio = repo.resolve_path(saved_card["audio"]["front"])
    assert imported_image.read_bytes() == b"image"
    assert imported_audio.read_bytes() == b"audio"
    assert imported_image.parent == imported_audio.parent
    assert imported_image.parent.name == "media"
    assert imported_image.parent.parent.name == deck["id"]


def test_quiz_delete_removes_owned_folder(tmp_path):
    repo = QuizRepository(tmp_path / "quizzes", tmp_path / "quizzes.json")
    repo.create_quiz("Disposable")
    quiz = repo.get_all_quizzes()[0]
    folder = repo._resolve_path(quiz["file"]).parent
    assert repo.delete_quiz("Disposable")
    assert not folder.exists()
    assert repo.get_all_quizzes() == []


def test_corrupt_quiz_index_rebuilds_from_metadata(tmp_path):
    index = tmp_path / "quizzes.json"
    repo = QuizRepository(tmp_path / "quizzes", index)
    repo.create_quiz("Recoverable")
    index.write_text("{broken", encoding="utf-8")
    assert repo.get_all_quizzes()[0]["name"] == "Recoverable"


def test_flashcard_copy_assigns_new_card_ids_and_delete_removes_folder(tmp_path):
    repo = FlashcardRepository(tmp_path / "flashcards", tmp_path / "decks.json")
    assert repo.create_deck("Original", [{"id": "card-1", "front": "Q", "back": "A"}])
    assert repo.copy_deck("Original", "Copy")
    copied = next(deck for deck in repo.get_all_decks() if deck["name"] == "Copy")
    assert repo.load_deck_cards(copied["file"])[0]["id"] != "card-1"
    folder = repo.resolve_path(copied["file"]).parent
    assert repo.delete_deck_permanently("Copy")
    assert not folder.exists()


def test_prune_progress_removes_deleted_cards_for_every_user(tmp_path):
    repo = FlashcardRepository(tmp_path / "flashcards", tmp_path / "decks.json")
    repo.create_deck("Biology", [{"id": "keep", "front": "Q", "back": "A"}])
    deck = repo.get_all_decks()[0]
    repo.save_deck_progress(deck["file"], {"keep": {}, "drop": {}}, "student-1")
    repo.save_deck_progress(deck["file"], {"keep": {}, "drop": {}}, "student-2")
    repo.prune_progress(deck["file"], {"keep"})
    assert repo.get_progress(deck["file"], "student-1") == {"keep": {}}
    assert repo.get_progress(deck["file"], "student-2") == {"keep": {}}


def test_progress_summary_and_reset_only_affect_the_requested_user(tmp_path):
    repo = FlashcardRepository(tmp_path / "flashcards", tmp_path / "decks.json")
    repo.create_deck("Biology", [
        {"id": "mastered", "front": "Q1", "back": "A1"},
        {"id": "learning", "front": "Q2", "back": "A2"},
    ])
    deck = repo.get_all_decks()[0]
    repo.save_deck_progress(
        deck["file"], {"mastered": {"mastered": True}, "learning": {"correct": 3}}, "student-1"
    )
    repo.save_deck_progress(deck["file"], {"mastered": {"mastered": True}}, "student-2")

    assert repo.get_deck_progress_summary(deck["file"], "student-1") == {
        "mastered": 1, "total": 2, "percent": 50, "has_progress": True,
    }
    assert repo.reset_deck_progress(deck["file"], "student-1") is True
    assert repo.get_progress(deck["file"], "student-1") == {}
    assert repo.get_progress(deck["file"], "student-2")["mastered"]["mastered"] is True


def test_clear_user_progress_removes_only_that_users_files(tmp_path):
    repo = FlashcardRepository(tmp_path / "flashcards", tmp_path / "decks.json")
    repo.create_deck("One", [{"id": "c1", "front": "Q", "back": "A"}])
    repo.create_deck("Two", [{"id": "c2", "front": "Q", "back": "A"}])
    for deck in repo.get_all_decks():
        repo.save_deck_progress(deck["file"], {"card": {"mastered": True}}, "guest")
        repo.save_deck_progress(deck["file"], {"card": {"mastered": True}}, "student-2")

    assert repo.clear_user_progress("guest") == 2
    for deck in repo.get_all_decks():
        assert repo.get_progress(deck["file"], "guest") == {}
        assert repo.get_progress(deck["file"], "student-2") != {}
