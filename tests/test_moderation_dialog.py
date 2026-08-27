import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QDialog, QDialogButtonBox, QRadioButton

from src.storage.http_user_repository import HttpUserRepository
from src.ui.moderation_dialog import InterruptedAttemptDialog, ModerationDialog


class DialogRecordingUserRepository(HttpUserRepository):
    def __init__(self, role):
        super().__init__(requester=self._record_request)
        self._token = "token"
        self._current_user = {"id": f"{role}-1", "role": role}
        self._content_metadata_cache = {}
        self._owned_classes_cache = {}
        self.calls = []

    def _record_request(self, method, path, payload, headers):
        self.calls.append((method, path, "Authorization" in headers))
        if path == "/api/v1/admin/users":
            if self._current_user["role"] != "admin":
                return 403, {"detail": "Administrator role required"}
            return 200, [{
                "id": "admin-1", "login": "admin", "name": "Administrator",
                "role": "admin", "status": "active",
            }]
        if path == "/api/v1/classes/owned":
            return 200, [{
                "kind": "flashcard", "file": "deck-1", "name": "Class Deck",
                "roster": [{"user_id": "student-1", "mastered": 0, "total": 1,
                            "percent": 0}],
                "invite_code": "CODE", "test_settings": {},
            }]
        if path == "/api/v1/users/profiles":
            return 200, [{
                "id": "student-1", "login": "student", "name": "Student",
                "role": "student", "status": "active",
            }]
        if path.startswith("/api/v1/content/metadata?"):
            return 200, []
        return 404, {}


def test_interrupted_attempt_apply_accepts_selected_resolution():
    app = QApplication.instance() or QApplication([])
    dialog = InterruptedAttemptDialog(
        "student32",
        {
            "started_at": "2026-08-14T19:44:43",
            "last_question": 1,
            "total": 1,
        },
    )

    mark_zero = next(
        radio
        for radio in dialog.findChildren(QRadioButton)
        if radio.property("value") == "mark_zero"
    )
    mark_zero.setChecked(True)
    apply_button = dialog.findChild(QDialogButtonBox).button(
        QDialogButtonBox.StandardButton.Apply
    )
    apply_button.click()

    assert dialog.selected_action() == "mark_zero"
    assert dialog.result() == QDialog.DialogCode.Accepted
    dialog.close()
    assert app is not None


def test_teacher_roster_skips_admin_users_and_loads_owned_classes(monkeypatch):
    monkeypatch.setenv("STUDY_BUDDY_STORAGE", "api")
    app = QApplication.instance() or QApplication([])
    user = DialogRecordingUserRepository("teacher")

    dialog = ModerationDialog("teacher-1", role="teacher", user_repository=user)

    paths = [path for _method, path, _authenticated in user.calls]
    assert "/api/v1/admin/users" not in paths
    assert paths.count("/api/v1/classes/owned") == 1
    assert "/api/v1/users/profiles" in paths
    assert "Active Class-Only items: 1" in dialog.class_summary_label.text()
    assert dialog.users_by_id["student-1"]["name"] == "Student"
    dialog.close()
    assert app is not None


def test_admin_moderation_still_loads_admin_users(monkeypatch):
    monkeypatch.setenv("STUDY_BUDDY_STORAGE", "api")
    app = QApplication.instance() or QApplication([])
    user = DialogRecordingUserRepository("admin")

    dialog = ModerationDialog("admin-1", role="admin", user_repository=user)

    paths = [path for _method, path, _authenticated in user.calls]
    assert paths.count("/api/v1/admin/users") == 1
    assert paths.count("/api/v1/content/metadata?scope=all&kind=flashcard") == 1
    assert paths.count("/api/v1/content/metadata?scope=all&kind=quiz") == 1
    assert len(paths) == 3
    assert dialog.users_by_id["admin-1"]["role"] == "admin"
    dialog.close()
    assert app is not None
