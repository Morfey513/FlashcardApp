from src.logic.user_session import UserSession
from src.storage.user_repository import UserRepository


def test_two_students_have_distinct_progress_owner_ids():
    first = UserSession()
    second = UserSession()
    first.login({"id": "2", "role": "student", "name": "Student User"})
    second.login({"id": "3", "role": "student", "name": "Student Two"})
    assert first.current_user["id"] != second.current_user["id"]
    assert not first.can_edit()
    assert not second.can_edit()


def test_user_repository_hashes_passwords_and_keeps_them_out_of_sessions(tmp_path):
    repo = UserRepository(tmp_path / "users.json")
    raw = (tmp_path / "users.json").read_text(encoding="utf-8")

    user = repo.authenticate("admin", "admin123")

    assert "admin123" not in raw
    assert user["login"] == "admin"
    assert "password" not in user
    assert repo.authenticate("admin", "wrong-password") is None


def test_registration_creates_student_with_isolated_preferences(tmp_path):
    repo = UserRepository(tmp_path / "users.json")
    created, _message, user = repo.register("New Student", "new.student", "password1")

    assert created is True
    assert user["role"] == "student"
    assert user["preferences"] == {"theme": "dark", "language": "en"}
    assert repo.authenticate("new.student", "password1")["id"] == user["id"]

    assert repo.save_preferences(user["id"], {"theme": "light", "language": "fr"})
    saved = next(item for item in repo.get_all_users() if item["id"] == user["id"])
    assert saved["preferences"] == {"theme": "light", "language": "fr"}


def test_user_can_change_display_name_and_password_with_current_password(tmp_path):
    repo = UserRepository(tmp_path / "users.json")
    created, _message, user = repo.register("Old Name", "renamed", "password1")
    assert created

    assert repo.update_display_name(user["id"], "New Name")
    assert repo.change_password(user["id"], "wrong", "newpassword")[0] is False
    assert repo.change_password(user["id"], "password1", "newpassword")[0] is True
    assert repo.authenticate("renamed", "password1") is None
    assert repo.authenticate("renamed", "newpassword")["name"] == "New Name"
