import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from src.controllers.quiz_controller import QuizController
from src.storage.pending_quiz_attempt_store import PendingQuizAttemptStore
from src.ui.quiz_view import QuizViewer


class FailingThenSavingQuizRepository:
    persists_test_attempts_remotely = True
    supports_offline_download = False

    def __init__(self, failures=1):
        self.failures = failures
        self.calls = []

    def get_all_quizzes(self):
        return []

    def _resolve_path(self, _value):
        return None

    def get_content_items(self):
        return []

    def get_test_attempts(self, _quiz_path, _user_id):
        return []

    def save_test_attempt(self, quiz_path, attempt):
        self.calls.append(("save", quiz_path, dict(attempt)))
        if self.failures:
            self.failures -= 1
            return None
        return dict(attempt)

    def update_test_attempt(self, quiz_path, attempt_id, attempt):
        self.calls.append(("update", quiz_path, attempt_id, dict(attempt)))
        if self.failures:
            self.failures -= 1
            return None
        return dict(attempt)


class UnwritablePendingStore(PendingQuizAttemptStore):
    def save(self, _quiz_path, _attempt, _operation):
        raise OSError("simulated local write failure")


def completed_controller(repo, store, *, active=None, quiz_id="quiz-1"):
    controller = QuizController("student-1", repo=repo, pending_attempt_store=store)
    controller.session_mode = "test"
    controller.current_quiz_path = quiz_id
    controller.current_quiz_info = {
        "id": quiz_id, "name": f"Sample {quiz_id}", "visibility": "public",
    }
    controller.active_test_attempt = active
    controller.get_final_results = lambda: {
        "score": 1, "total": 1, "percent": 100.0,
        "results": [{"question_id": "q1", "user_answer": "A", "is_correct": True}],
    }
    return controller


def test_failed_final_save_creates_complete_pending_record_and_flag(tmp_path):
    store = PendingQuizAttemptStore(tmp_path / "pending")
    repo = FailingThenSavingQuizRepository()
    controller = completed_controller(repo, store)

    assert controller.finalize_test_attempt() is None
    assert controller.final_save_pending is True
    assert controller.saved_test_attempt is None
    records = store.list_for_user("student-1")
    assert len(records) == 1
    assert records[0]["operation"] == "save"
    assert records[0]["attempt"] == repo.calls[0][2]
    assert records[0]["attempt"]["id"]
    assert records[0]["attempt"]["answers"][0]["question_id"] == "q1"
    assert controller.finalize_test_attempt() is None
    assert len(repo.calls) == 1


def test_no_active_test_does_not_set_pending_flag(tmp_path):
    controller = QuizController(
        "student-1", repo=FailingThenSavingQuizRepository(),
        pending_attempt_store=PendingQuizAttemptStore(tmp_path / "pending"),
    )
    assert controller.finalize_test_attempt() is None
    assert controller.final_save_pending is False


def test_offline_download_capability_does_not_imply_remote_attempt_save(tmp_path):
    class OfflineCapableLocalRepository(FailingThenSavingQuizRepository):
        supports_offline_download = True
        persists_test_attempts_remotely = False

    store = PendingQuizAttemptStore(tmp_path / "pending")
    controller = completed_controller(OfflineCapableLocalRepository(), store)
    assert controller.finalize_test_attempt() is None
    assert controller.final_save_pending is False
    assert store.list_for_user("student-1") == []


def test_successful_retry_reads_pending_file_and_clears_flag(tmp_path):
    store = PendingQuizAttemptStore(tmp_path / "pending")
    repo = FailingThenSavingQuizRepository()
    controller = completed_controller(repo, store)
    controller.finalize_test_attempt()
    expected = store.list_for_user("student-1")[0]["attempt"]
    controller.current_quiz_path = "different-quiz"
    controller.user_answers = {}

    saved = controller.retry_final_test_attempt()

    assert saved == expected
    assert repo.calls[1][1] == "quiz-1"
    assert repo.calls[1][2] == expected
    assert store.list_for_user("student-1") == []
    assert controller.saved_test_attempt == expected
    assert controller.final_save_pending is False


def test_second_failed_retry_keeps_one_pending_file(tmp_path):
    store = PendingQuizAttemptStore(tmp_path / "pending")
    repo = FailingThenSavingQuizRepository(failures=2)
    controller = completed_controller(repo, store)
    controller.finalize_test_attempt()
    before = list(store.root.glob("*.json"))

    assert controller.retry_final_test_attempt() is None

    assert controller.final_save_pending is True
    assert list(store.root.glob("*.json")) == before
    assert repo.calls[0][2]["id"] == repo.calls[1][2]["id"]


def test_failed_pending_file_write_keeps_retryable_attempt_in_memory(tmp_path):
    store = UnwritablePendingStore(tmp_path / "pending")
    repo = FailingThenSavingQuizRepository(failures=2)
    controller = completed_controller(repo, store)

    assert controller.finalize_test_attempt() is None
    assert controller.final_save_pending is True
    assert controller.final_save_durable is False
    pending = controller.list_pending_test_attempts()
    assert len(pending) == 1
    assert pending[0]["in_memory_only"] is True
    assert pending[0]["attempt"] == repo.calls[0][2]
    assert not store.root.exists() or not list(store.root.glob("*.json"))

    assert controller.retry_final_test_attempt() is None
    assert len(controller.list_pending_test_attempts()) == 1
    assert repo.calls[1][2]["id"] == repo.calls[0][2]["id"]

    assert controller.retry_final_test_attempt()["id"] == repo.calls[0][2]["id"]
    assert controller.list_pending_test_attempts() == []
    assert controller.final_save_pending is False


def test_result_and_menu_keep_memory_only_retry_visible(tmp_path):
    app = QApplication.instance() or QApplication([])
    store = UnwritablePendingStore(tmp_path / "pending")
    repo = FailingThenSavingQuizRepository()
    controller = completed_controller(repo, store)
    viewer = QuizViewer(controller)

    viewer.show_results()
    assert viewer.result_retry_save_btn.isEnabled() is True
    assert "closing it will lose" in viewer.result_save_notice.text()
    viewer.return_to_menu()
    assert viewer.menu_retry_save_btn.isHidden() is False
    assert "lost if you close" in viewer.menu_pending_label.text()

    viewer.menu_retry_save_btn.click()
    assert controller.list_pending_test_attempts() == []
    assert viewer.menu_pending_label.isHidden() is True
    viewer.close()
    assert app is not None


def test_reopened_quiz_view_surfaces_and_retries_leftover_pending_save(tmp_path):
    app = QApplication.instance() or QApplication([])
    store = PendingQuizAttemptStore(tmp_path / "pending")
    repo = FailingThenSavingQuizRepository()
    completed_controller(repo, store).finalize_test_attempt()

    reopened = QuizController("student-1", repo=repo, pending_attempt_store=store)
    viewer = QuizViewer(reopened)

    assert len(reopened.list_pending_test_attempts()) == 1
    assert viewer.menu_pending_label.isHidden() is False
    assert "not yet saved" in viewer.menu_pending_label.text()
    assert viewer.menu_retry_save_btn.isHidden() is False

    viewer.menu_retry_save_btn.click()
    assert store.list_for_user("student-1") == []
    assert viewer.menu_pending_label.isHidden() is True
    viewer.close()
    assert app is not None


def test_menu_retries_every_pending_result_once_per_click(tmp_path):
    app = QApplication.instance() or QApplication([])
    store = PendingQuizAttemptStore(tmp_path / "pending")
    repo = FailingThenSavingQuizRepository(failures=2)
    completed_controller(repo, store, quiz_id="quiz-1").finalize_test_attempt()
    completed_controller(repo, store, quiz_id="quiz-2").finalize_test_attempt()
    viewer = QuizViewer(QuizController("student-1", repo=repo, pending_attempt_store=store))

    assert len(store.list_for_user("student-1")) == 2
    assert "2 Test Mode" in viewer.menu_pending_label.text()
    viewer.menu_retry_save_btn.click()

    assert len(repo.calls) == 4
    assert store.list_for_user("student-1") == []
    assert viewer.menu_pending_label.isHidden() is True
    viewer.close()
    assert app is not None


def test_menu_keeps_only_failed_result_after_retrying_all(tmp_path):
    app = QApplication.instance() or QApplication([])
    store = PendingQuizAttemptStore(tmp_path / "pending")
    repo = FailingThenSavingQuizRepository(failures=2)
    completed_controller(repo, store, quiz_id="quiz-1").finalize_test_attempt()
    completed_controller(repo, store, quiz_id="quiz-2").finalize_test_attempt()
    repo.failures = 1
    viewer = QuizViewer(QuizController("student-1", repo=repo, pending_attempt_store=store))

    viewer.menu_retry_save_btn.click()

    assert len(repo.calls) == 4
    assert len(store.list_for_user("student-1")) == 1
    assert "1 Test Mode" in viewer.menu_pending_label.text()
    viewer.close()
    assert app is not None


def test_result_panel_explains_unsaved_score_and_updates_after_retry(tmp_path):
    app = QApplication.instance() or QApplication([])
    store = PendingQuizAttemptStore(tmp_path / "pending")
    repo = FailingThenSavingQuizRepository()
    controller = completed_controller(repo, store)
    viewer = QuizViewer(controller)

    viewer.show_results()
    assert viewer.result_retry_save_btn.isHidden() is False
    assert "not been saved" in viewer.result_save_notice.text()
    assert "1/1" in viewer.result_label.text()

    viewer.result_retry_save_btn.click()
    assert "now saved" in viewer.result_save_notice.text()
    assert viewer.result_retry_save_btn.isHidden() is True
    assert store.list_for_user("student-1") == []
    viewer.close()
    assert app is not None


def test_existing_attempt_retries_as_update_with_original_id(tmp_path):
    store = PendingQuizAttemptStore(tmp_path / "pending")
    repo = FailingThenSavingQuizRepository()
    controller = completed_controller(repo, store, active={"id": "existing-attempt", "attempt_number": 2})

    assert controller.finalize_test_attempt() is None
    assert store.list_for_user("student-1")[0]["operation"] == "update"
    assert controller.retry_final_test_attempt()["id"] == "existing-attempt"
    assert [call[0] for call in repo.calls] == ["update", "update"]
    assert repo.calls[0][2] == repo.calls[1][2] == "existing-attempt"
