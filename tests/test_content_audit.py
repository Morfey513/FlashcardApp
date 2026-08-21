import json

from src.controllers.flashcard_editor_controller import FlashcardEditorController
from src.controllers.quiz_editor_controller import QuizEditorController
from src.storage.flashcard_repository import FlashcardRepository
from src.storage.quiz_repository import QuizRepository


def _flashcard_controller(repo, actor_id, role):
    return FlashcardEditorController(actor_id, role, repo=repo)


def _quiz_controller(repo, actor_id, role):
    return QuizEditorController(actor_id, role, repo=repo)


def test_admin_flashcard_edit_is_attributed_without_changing_owner(tmp_path):
    repo = FlashcardRepository(tmp_path / "flashcards", tmp_path / "decks.json")
    assert repo.create_deck(
        "Teacher deck", [{"id": "c1", "front": "Old", "back": "A"}],
        owner_id="teacher-1", actor_role="teacher",
    )
    controller = _flashcard_controller(repo, "admin-1", "admin")

    assert controller.load_deck("Teacher deck")
    assert controller.save_deck(
        [{"id": "c1", "front": "Edited by admin", "back": "A"}], "private"
    )

    moderation = controller.get_current_moderation()
    assert moderation["owner_id"] == "teacher-1"
    history = controller.get_current_edit_history()
    assert history[-1]["changed_by"] == "admin-1"
    assert history[-1]["role"] == "admin"
    assert history[-1]["action"] == "updated"
    assert history[-1]["changed_fields"] == ["cards"]
    assert "edited cards" in history[-1]["change_summary"]
    assert history[-1]["timestamp"]


def test_admin_quiz_edit_records_questions_and_assessment_settings(tmp_path):
    repo = QuizRepository(tmp_path / "quizzes", tmp_path / "quizzes.json")
    assert repo.create_quiz(
        "Teacher quiz",
        [{"id": "q1", "type": "short_answer", "question": "Old?", "answer": "A"}],
        owner_id="teacher-1", actor_role="teacher",
    )
    controller = _quiz_controller(repo, "admin-1", "admin")

    assert controller.load_quiz("Teacher quiz")
    questions = [
        {"id": "q1", "type": "short_answer", "question": "Edited?", "answer": "B"},
        {"id": "q2", "type": "short_answer", "question": "Added?", "answer": "C"},
    ]
    assert controller.save_quiz(
        questions, {"q1", "q2"}, "class_only",
        {"time_limit_minutes": 10, "passing_grade_percent": 80},
    )

    assert controller.get_current_moderation()["owner_id"] == "teacher-1"
    history = controller.get_current_edit_history()
    assert history[-1]["changed_by"] == "admin-1"
    assert history[-1]["role"] == "admin"
    assert history[-1]["changed_fields"] == ["questions", "test_settings"]
    assert "questions 1 → 2" in history[-1]["change_summary"]
    assert "assessment settings changed" in history[-1]["change_summary"]


def test_noop_save_does_not_add_audit_noise(tmp_path):
    repo = FlashcardRepository(tmp_path / "flashcards", tmp_path / "decks.json")
    cards = [{"id": "c1", "front": "Q", "back": "A"}]
    assert repo.create_deck(
        "Stable", cards, owner_id="teacher-1", actor_role="teacher"
    )
    deck = repo.get_all_decks()[0]
    before = repo.get_edit_history(deck["file"])

    repo.save_deck_content(
        deck["file"], cards, actor_id="teacher-1", actor_role="teacher"
    )

    assert repo.get_edit_history(deck["file"]) == before


def test_edit_history_json_uses_requested_actor_fields(tmp_path):
    repo = QuizRepository(tmp_path / "quizzes", tmp_path / "quizzes.json")
    assert repo.create_quiz("Audit", owner_id="teacher-1", actor_role="teacher")
    quiz = repo.get_all_quizzes()[0]
    history_file = repo._resolve_path(quiz["file"]).parent / "edit_history.json"

    entry = json.loads(history_file.read_text(encoding="utf-8"))[0]
    assert {"changed_by", "role", "timestamp", "change_summary"} <= set(entry)
    assert entry["changed_by"] == "teacher-1"
    assert entry["role"] == "teacher"


def test_invalid_existing_audit_history_is_not_overwritten(tmp_path):
    repo = FlashcardRepository(tmp_path / "flashcards", tmp_path / "decks.json")
    assert repo.create_deck("Audit", owner_id="teacher-1", actor_role="teacher")
    deck = repo.get_all_decks()[0]
    history_file = repo.resolve_path(deck["file"]).parent / "edit_history.json"
    history_file.write_text("not valid json", encoding="utf-8")

    repo.save_deck_content(
        deck["file"], [{"id": "c1", "front": "Q", "back": "A"}],
        actor_id="teacher-1", actor_role="teacher",
    )

    assert history_file.read_text(encoding="utf-8") == "not valid json"
