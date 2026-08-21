from src.controllers.flashcard_editor_controller import FlashcardEditorController
from src.controllers.quiz_editor_controller import QuizEditorController
from src.storage.flashcard_repository import FlashcardRepository
from src.storage.quiz_repository import QuizRepository


def make_flashcard_controller(repo, owner_id="teacher-1", role="teacher"):
    return FlashcardEditorController(owner_id, role, repo=repo)


def make_quiz_controller(repo, owner_id="teacher-1", role="teacher"):
    return QuizEditorController(owner_id, role, repo=repo)


def test_flashcard_editor_enforces_ownership_and_manages_cards(tmp_path):
    repo = FlashcardRepository(tmp_path / "flashcards", tmp_path / "decks.json")
    repo.create_deck("Owned", [{"id": "c1", "front": "One", "back": "1"}], owner_id="teacher-1")
    repo.create_deck("Other", [{"id": "c2", "front": "Two", "back": "2"}], owner_id="teacher-2")
    controller = make_flashcard_controller(repo)

    assert controller.get_deck_names() == ["Owned"]
    assert controller.load_deck("Other") is False
    assert controller.load_deck("Owned") is True
    assert controller.get_current_moderation()["owner_id"] == "teacher-1"

    assert controller.add_card({"front": "Added", "back": "A"}) is True
    added_id = controller.current_cards[-1]["id"]
    assert added_id
    assert controller.update_card(1, {"front": "Updated", "back": "U"}) is True
    assert controller.current_cards[1]["id"] == added_id
    assert controller.update_card(20, {}) is False
    assert controller.duplicate_card(0) is True
    assert controller.current_cards[-1]["id"] != "c1"
    assert controller.current_cards[-1]["front"].endswith("(Copy)")
    assert controller.duplicate_card(20) is False
    assert controller.remove_card(1) is True
    assert controller.remove_card(20) is False
    assert controller.has_unsaved_changes is True

    admin = make_flashcard_controller(repo, owner_id="admin-1", role="admin")
    assert set(admin.get_deck_names()) == {"Owned", "Other"}


def test_flashcard_editor_saves_visibility_ids_and_prunes_progress(tmp_path, monkeypatch):
    repo = FlashcardRepository(tmp_path / "flashcards", tmp_path / "decks.json")
    repo.create_deck("Owned", [{"id": "old", "front": "Old", "back": "A"}], owner_id="teacher-1")
    deck = repo.get_all_decks()[0]
    repo.save_deck_progress(deck["file"], {"old": {"mastered": True}}, "student-1")
    controller = make_flashcard_controller(repo)

    assert controller.save_deck([], "private") is False
    assert controller.load_deck("Owned") is True
    assert controller.save_deck([], "unsupported") is False
    cards = [{"front": "New", "back": "Answer"}]
    assert controller.save_deck(cards, "class_only") is True
    assert cards[0]["id"]
    assert repo.get_progress(deck["file"], "student-1") == {}
    assert repo.load_deck_cards(deck["file"])[0]["front"] == "New"
    moderation = controller.get_current_moderation()
    assert moderation["status"] == "pending_review"
    assert moderation["visibility"] == "class_only"
    assert controller.has_unsaved_changes is False

    monkeypatch.setattr(
        repo,
        "save_deck_content",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("disk full")),
    )
    assert controller.save_deck(cards, "private") is False


def test_quiz_editor_enforces_ownership_and_manages_questions(tmp_path):
    repo = QuizRepository(tmp_path / "quizzes", tmp_path / "quizzes.json")
    question = {"id": "q1", "type": "short_answer", "question": "One?", "answer": "1"}
    repo.create_quiz("Owned", [question], owner_id="teacher-1")
    repo.create_quiz("Other", [question], owner_id="teacher-2")
    controller = make_quiz_controller(repo)

    assert controller.get_quiz_names() == ["Owned"]
    assert controller.load_quiz("Other") is False
    assert controller.load_quiz("Owned") is True
    assert controller.get_current_moderation()["owner_id"] == "teacher-1"
    assert controller.duplicate_question(0) is True
    assert controller.current_questions[-1]["id"] != "q1"
    assert controller.current_questions[-1]["question"].endswith("(Copy)")
    assert controller.duplicate_question(20) is False
    assert controller.delete_question(1) is True
    assert controller.delete_question(20) is False
    assert controller.has_unsaved_changes is True

    admin = make_quiz_controller(repo, owner_id="admin-1", role="admin")
    assert set(admin.get_quiz_names()) == {"Owned", "Other"}


def test_quiz_editor_saves_assessment_settings_and_handles_repo_failure(tmp_path, monkeypatch):
    repo = QuizRepository(tmp_path / "quizzes", tmp_path / "quizzes.json")
    repo.create_quiz(
        "Owned",
        [{"id": "old", "type": "short_answer", "question": "Old?", "answer": "A"}],
        owner_id="teacher-1",
    )
    quiz = repo.get_all_quizzes()[0]
    repo.save_quiz_progress(quiz["file"], {"old": {"mastered": True}}, "student-1")
    controller = make_quiz_controller(repo)

    assert controller.save_quiz([], [], "private") is False
    assert controller.load_quiz("Owned") is True
    assert controller.save_quiz([], [], "unsupported") is False
    questions = [{"type": "short_answer", "question": "New?", "answer": "B"}]
    assert controller.save_quiz(
        questions,
        [],
        "class_only",
        {"time_limit_minutes": 15, "passing_grade_percent": 75, "attempt_limit": 2},
    ) is True
    assert questions[0]["id"]
    assert repo.get_quiz_progress(quiz["file"], "student-1") == {}
    assert repo.get_test_settings(quiz["file"])["time_limit_minutes"] == 15
    moderation = controller.get_current_moderation()
    assert moderation["status"] == "pending_review"
    assert moderation["visibility"] == "class_only"

    monkeypatch.setattr(repo, "save_quiz_content", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("disk full")))
    assert controller.save_quiz(questions, [questions[0]["id"]], "private") is False


def test_editor_wrappers_enforce_roles_and_ownership(tmp_path):
    flashcards = FlashcardRepository(tmp_path / "flashcards", tmp_path / "decks.json")
    quizzes = QuizRepository(tmp_path / "quizzes", tmp_path / "quizzes.json")
    assert flashcards.create_deck("Teacher deck", owner_id="teacher-1")
    assert flashcards.create_deck("Other deck", owner_id="teacher-2")
    assert quizzes.create_quiz("Teacher quiz", owner_id="teacher-1")
    assert quizzes.create_quiz("Other quiz", owner_id="teacher-2")

    student_decks = make_flashcard_controller(flashcards, "student-1", "student")
    student_quizzes = make_quiz_controller(quizzes, "student-1", "student")
    assert student_decks.get_deck_names() == []
    assert student_decks.create_deck("Blocked") is False
    assert student_decks.copy_deck("Teacher deck", "Blocked copy") is False
    assert student_decks.delete_deck("Teacher deck") is False
    assert student_quizzes.get_quiz_names() == []
    assert student_quizzes.create_new_quiz("Blocked") is False
    assert student_quizzes.copy_quiz("Teacher quiz", "Blocked copy") is False
    assert student_quizzes.delete_quiz("Teacher quiz") is False

    teacher_decks = make_flashcard_controller(flashcards)
    teacher_quizzes = make_quiz_controller(quizzes)
    assert teacher_decks.copy_deck("Other deck", "Stolen deck") is False
    assert teacher_decks.delete_deck("Other deck") is False
    assert teacher_quizzes.copy_quiz("Other quiz", "Stolen quiz") is False
    assert teacher_quizzes.delete_quiz("Other quiz") is False
    assert teacher_decks.copy_deck("Teacher deck", "Teacher deck copy") is True
    assert teacher_quizzes.copy_quiz("Teacher quiz", "Teacher quiz copy") is True
    assert teacher_decks.delete_deck("Teacher deck") is True
    assert teacher_quizzes.delete_quiz("Teacher quiz") is True

    admin_decks = make_flashcard_controller(flashcards, "admin-1", "admin")
    admin_quizzes = make_quiz_controller(quizzes, "admin-1", "admin")
    assert admin_decks.copy_deck("Other deck", "Admin deck copy") is True
    assert admin_quizzes.copy_quiz("Other quiz", "Admin quiz copy") is True
    assert admin_decks.delete_deck("Other deck") is True
    assert admin_quizzes.delete_quiz("Other quiz") is True


def test_editor_media_and_invitation_delegation(monkeypatch):
    class RepoStub:
        def import_media(self, relative_path, absolute_path):
            return f"imported:{relative_path}:{absolute_path}"

    class InvitationStub:
        calls = []

        def generate_or_rotate_code(self, relative_path, kind, owner_id):
            self.calls.append((relative_path, kind, owner_id))
            return True, "CODE-2345"

        def get_invitation(self, _relative_path, _kind):
            return {"code": "CODE-2345"}

    import src.controllers.flashcard_editor_controller as flash_module
    import src.controllers.quiz_editor_controller as quiz_module

    flash = FlashcardEditorController(
        "teacher-1", "teacher", repo=RepoStub(), class_repository=InvitationStub()
    )
    quiz = QuizEditorController(
        "teacher-1", "teacher", repo=RepoStub(), class_repository=InvitationStub()
    )
    assert flash.generate_or_rotate_invite_code()[0] is False
    assert quiz.generate_or_rotate_invite_code()[0] is False

    flash.current_deck_info = {"file": "deck.json"}
    quiz.current_quiz_info = {"file": "quiz.json"}
    assert flash.process_image_path("front.png") == "imported:deck.json:front.png"
    assert flash.process_audio_path("front.mp3") == "imported:deck.json:front.mp3"
    assert quiz.process_image_path("question.png") == "imported:quiz.json:question.png"
    assert flash.generate_or_rotate_invite_code() == (True, "CODE-2345")
    assert quiz.generate_or_rotate_invite_code() == (True, "CODE-2345")
    assert InvitationStub.calls == [
        ("deck.json", "flashcard", "teacher-1"),
        ("quiz.json", "quiz", "teacher-1"),
    ]
