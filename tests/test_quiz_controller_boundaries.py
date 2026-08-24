from datetime import datetime, timedelta, timezone

from src.controllers.quiz_controller import QuizController
from src.storage.flashcard_repository import FlashcardRepository
from src.storage.moderation_repository import ModerationRepository
from src.storage.quiz_repository import QuizRepository
from src.logic.quiz_logic import Quiz


def make_repositories(tmp_path):
    quizzes = QuizRepository(tmp_path / "quizzes", tmp_path / "quizzes.json")
    flashcards = FlashcardRepository(tmp_path / "flashcards", tmp_path / "decks.json")
    return quizzes, ModerationRepository(flashcards=flashcards, quizzes=quizzes)


def publish(moderation, name, visibility="public", status="published"):
    item = next(item for item in moderation.get_all_content() if item["name"] == name)
    assert moderation.update_status(
        item, status, "admin", visibility=visibility, actor_role="admin"
    )
    return item


def test_missing_empty_and_inactive_quiz_states_are_safe(tmp_path):
    repo, moderation = make_repositories(tmp_path)
    controller = QuizController("student-1", repo)

    assert controller.get_test_policy("Missing") is None
    assert controller.can_start_test("Missing") is False
    assert controller.reset_quiz_progress("Missing") is False
    assert controller.load_quiz_by_name("Missing") is None
    assert controller.submit_answer("answer") == {"type": "standard", "next_card": None}
    assert controller.get_final_results() == {
        "score": 0, "total": 0, "percent": 0, "results": []
    }
    assert controller.get_navigation_status() == {
        "show_submit": False,
        "show_skip": False,
        "show_preview": False,
        "show_finish": False,
    }
    assert controller.get_current_matching_keys() == []

    assert repo.create_quiz("Empty", [], owner_id="teacher-1")
    publish(moderation, "Empty")
    assert controller.load_quiz_by_name("Empty") is None


def test_banned_owner_content_cannot_be_started(tmp_path):
    repo, moderation = make_repositories(tmp_path)
    assert repo.create_quiz(
        "Banned quiz",
        [{"id": "q1", "type": "short_answer", "question": "Q", "answer": "A"}],
        owner_id="teacher-1",
    )
    publish(moderation, "Banned quiz", status="banned")

    owner = QuizController("teacher-1", repo, role="teacher")
    assert owner.get_quiz_summary("Banned quiz")["moderation_status"] == "banned"
    assert owner.load_quiz_by_name("Banned quiz") is None


def test_navigation_boundaries_and_empty_answers_do_not_advance(tmp_path):
    repo, moderation = make_repositories(tmp_path)
    assert repo.create_quiz("Navigation", [
        {"id": "q1", "type": "short_answer", "question": "First", "answer": "A"},
        {"id": "q2", "type": "short_answer", "question": "Last", "answer": "B"},
    ], owner_id="teacher-1")
    publish(moderation, "Navigation")
    controller = QuizController("student-1", repo)
    assert controller.load_quiz_by_name("Navigation")

    current_id = controller.get_current_card()["id"]
    assert controller.submit_answer(" ")["next_card"]["id"] == current_id
    assert controller.user_answers == {}
    assert controller.jump_to(-1) is None
    assert controller.jump_to(20) is None
    assert controller.jump_to(0)
    assert controller.skip_question()
    assert controller.skip_question() is None
    assert controller.get_navigation_status() == {
        "show_submit": False,
        "show_skip": False,
        "show_preview": True,
        "show_finish": True,
    }
    assert controller.submit_answer(controller.quiz.get_current().answer)["type"] == "review"
    assert controller.has_unanswered() is True


def test_timer_and_answer_review_policy_boundaries():
    controller = QuizController("student-1", repo=object())
    assert controller.get_remaining_test_seconds() is None
    controller.test_deadline = datetime.now(timezone.utc) - timedelta(seconds=1)
    assert controller.get_remaining_test_seconds() == 0
    controller.test_deadline = datetime.now(timezone.utc) + timedelta(seconds=10)
    assert 0 <= controller.get_remaining_test_seconds() <= 10

    assert controller._parse_due_at(None) is None
    assert controller._parse_due_at("not-a-date") is None
    assert controller._parse_due_at("2030-01-01T00:00:00").tzinfo is not None

    controller.current_quiz_info = {"visibility": "public"}
    assert controller.can_show_correct_answers() is True
    controller.current_quiz_info = {
        "visibility": "class_only",
        "test_settings": {"answer_review_policy": "never"},
    }
    assert controller.can_show_correct_answers() is False
    controller.current_quiz_info["test_settings"] = {"answer_review_policy": "immediate"}
    assert controller.can_show_correct_answers() is True
    controller.current_quiz_info["test_settings"] = {
        "answer_review_policy": "after_due_date",
        "due_at": (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
    }
    assert controller.can_show_correct_answers() is True
    controller.current_quiz_info["test_settings"]["due_at"] = (
        datetime.now(timezone.utc) + timedelta(days=1)
    ).isoformat()
    assert controller.can_show_correct_answers() is False


def test_test_attempt_lifecycle_guards_are_idempotent(tmp_path):
    repo, moderation = make_repositories(tmp_path)
    assert repo.create_quiz("Lifecycle", [
        {"id": "q1", "type": "short_answer", "question": "Q", "answer": "A"}
    ], owner_id="teacher-1", test_settings={"attempt_limit": 2})
    publish(moderation, "Lifecycle", visibility="class_only")
    controller = QuizController("teacher-1", repo, role="teacher")

    assert controller.finalize_test_attempt() is None
    assert controller.abandon_test_attempt() is None
    assert controller.load_quiz_by_name("Lifecycle", mode="test")
    first_active_id = controller.active_test_attempt["id"]
    controller.submit_answer("A")
    saved = controller.finalize_test_attempt(status="timed_out")
    assert saved["status"] == "timed_out"
    assert saved["id"] == first_active_id
    assert controller.finalize_test_attempt()["id"] == saved["id"]
    assert controller.abandon_test_attempt() is None


def test_mastery_requires_active_quiz_and_normalizes_missing_progress(tmp_path):
    repo, moderation = make_repositories(tmp_path)
    controller = QuizController("student-1", repo)
    assert controller.toggle_question_mastery("q1") is None
    assert controller.get_question_progress("q1") == {
        "correct": 0, "wrong": 0, "mastered": False
    }

    assert repo.create_quiz("Mastery", [
        {"id": "q1", "type": "short_answer", "question": "Q", "answer": "A"}
    ], owner_id="teacher-1")
    publish(moderation, "Mastery")
    assert controller.load_quiz_by_name("Mastery")
    assert controller.toggle_question_mastery("q1") is False


def test_remote_matching_checkpoint_uses_server_mapping_and_never_grades_locally():
    class Remote:
        def __init__(self): self.payload = None
        def checkpoint_assessment(self, *args): self.payload = args[-1]; return {"saved": True}
        def submit_assessment(self, *args): return None

    repo = Remote()
    controller = QuizController("teacher", repo, role="teacher")
    controller.quiz = Quiz([{"id": "m", "type": "matching", "question": "M",
                             "pairs": [{"prompt": "A", "answer": "1"}, {"prompt": "B", "answer": "2"}]}],
                           preserve_presentation=True)
    controller.session_mode = "test"
    controller.remote_assessment = True
    controller.current_quiz_info = {"id": "quiz"}
    controller.active_test_attempt = {"id": "attempt"}
    controller.remote_position_by_question = {"m": 4}
    result = controller.submit_answer([{"prompt": "A", "answer": "1"}, {"prompt": "B", "answer": "2"}])
    assert repo.payload == {"A": "1", "B": "2"}
    assert result["type"] == "review"
    assert controller.user_answers["m"]["is_correct"] is None


def test_remote_submit_failure_never_falls_back_to_local_grading():
    class Remote:
        def submit_assessment(self, *args): return None
    controller = QuizController("student", Remote())
    controller.quiz = Quiz([{"id": "q", "type": "short_answer", "question": "Q", "answer": "secret"}], preserve_presentation=True)
    controller.session_mode = "test"
    controller.remote_assessment = True
    controller.current_quiz_path = "quiz"
    controller.current_quiz_info = {"id": "quiz"}
    controller.active_test_attempt = {"id": "attempt"}
    assert controller.finalize_test_attempt() is None
    assert controller.get_final_results()["status"] == "in_progress"


def test_ordering_remote_projection_renders_safe_item_count():
    controller = QuizController("student", object())
    controller.quiz = Quiz([{"id": "o", "type": "ordering", "question": "Order",
                             "items": ["A", "B", "C"]}], preserve_presentation=True)
    card = controller._get_current_card_data()
    assert len(card["prompts"]) == 3
    assert card["dropdown_options"] == ["A", "B", "C"]


def test_loading_legacy_session_clears_remote_assessment_state(tmp_path):
    repo, moderation = make_repositories(tmp_path)
    assert repo.create_quiz("Legacy", [{"id": "q", "type": "short_answer", "question": "Q", "answer": "A"}], owner_id="teacher")
    publish(moderation, "Legacy")
    controller = QuizController("student", repo)
    controller.remote_assessment = True
    controller.remote_position_by_question = {"old": 7}
    controller.active_test_attempt = {"id": "old-attempt"}
    controller.saved_test_attempt = {"id": "old-result"}
    assert controller.load_quiz_by_name("Legacy")
    assert controller.remote_assessment is False
    assert controller.remote_position_by_question == {}
    assert controller.active_test_attempt is None
    assert controller.saved_test_attempt is None


def test_remote_assessment_resume_precedes_generic_unresolved_preflight(tmp_path):
    repo, moderation = make_repositories(tmp_path)
    assert repo.create_quiz(
        "Remote resume",
        [{"id": "q1", "type": "short_answer", "question": "Q", "answer": "A"}],
        owner_id="teacher",
    )
    publish(moderation, "Remote resume", visibility="class_only")

    calls = []

    def resume_assessment(quiz_id):
        calls.append(quiz_id)
        return {
            "id": "existing-attempt",
            "status": "in_progress",
            "questions": [{"id": "q1", "position": 0, "type": "short_answer", "question": "Q"}],
        }

    repo.start_assessment = resume_assessment

    def unexpected_generic_preflight(*_args, **_kwargs):
        raise AssertionError("generic unresolved-attempt preflight must not run")

    repo.get_test_attempts = unexpected_generic_preflight
    controller = QuizController("teacher", repo, role="teacher")

    assert controller.load_quiz_by_name("Remote resume", mode="test")
    expected_quiz_id = next(q["id"] for q in repo.get_all_quizzes() if q["name"] == "Remote resume")
    assert calls == [expected_quiz_id]
    assert controller.remote_assessment is True
    assert controller.active_test_attempt["id"] == "existing-attempt"
