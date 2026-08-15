from src.controllers.main_controller import MainController
from src.logic.app_settings import AppSettings
from src.logic.user_session import UserSession
from src.storage.user_repository import UserRepository


class RecordingTranslator:
    def __init__(self):
        self.languages = []

    def set_language(self, language, persist=False):
        self.languages.append((language, persist))


def make_controller(tmp_path):
    controller = object.__new__(MainController)
    controller.user_repo = UserRepository(tmp_path / "users.json")
    controller.session = UserSession()
    controller.settings = object.__new__(AppSettings)
    controller.settings.settings_file = tmp_path / "settings.json"
    controller.settings.settings = {"theme": "dark", "language": "en"}
    controller.translator = RecordingTranslator()
    return controller


def test_main_controller_authentication_and_session_transitions(tmp_path):
    controller = make_controller(tmp_path)
    created, _message, user = controller.user_repo.register(
        "Learner", "learner", "password1"
    )
    assert created

    assert controller.attempt_login("", "password1") == (
        False,
        "Please enter both login and password",
    )
    assert controller.attempt_login("learner", "wrong") == (
        False,
        "Invalid login or password",
    )

    success, message = controller.attempt_login("learner", "password1")
    assert success is True
    assert message == "Welcome, Learner!"
    assert controller.get_current_user_id() == user["id"]
    assert controller.get_current_user_name() == "Learner"
    assert controller.get_current_role() == "student"
    assert controller.can_access_editor() is False
    assert controller.translator.languages[-1] == ("en", False)

    controller.logout()
    assert controller.get_current_user_id() == "guest"
    assert controller.get_current_user_name() == "Guest"
    controller.continue_as_guest()
    assert controller.session.is_guest is True


def test_main_controller_registration_name_and_password_orchestration(tmp_path):
    controller = make_controller(tmp_path)

    success, message = controller.register("New User", "new.user", "password1")
    assert success is True
    assert "created" in message.lower()
    assert controller.session.is_authenticated()

    assert controller.update_display_name("Updated User") is True
    assert controller.get_current_user_name() == "Updated User"
    assert controller.change_password("wrong", "newpassword")[0] is False
    assert controller.change_password("password1", "newpassword")[0] is True

    controller.logout()
    assert controller.update_display_name("Ignored") is False
    assert controller.change_password("newpassword", "anotherpass") == (
        False,
        "You must be signed in",
    )
    assert controller.attempt_login("new.user", "newpassword")[0] is True


def test_main_controller_returns_repository_ban_message(tmp_path):
    controller = make_controller(tmp_path)
    controller.user_repo.authenticate = lambda _login, _password: None
    controller.user_repo.get_ban_message = lambda _login: "Account suspended: policy violation"

    assert controller.attempt_login("blocked", "password1") == (
        False,
        "Account suspended: policy violation",
    )


def test_main_controller_keeps_guest_and_user_preferences_separate(tmp_path, monkeypatch):
    controller = make_controller(tmp_path)

    assert controller.get_theme() == "dark"
    assert controller.toggle_theme() == "light"
    assert controller.settings.get_theme() == "light"

    loaded = []
    monkeypatch.setattr("src.main.load_qt_translations", lambda app, code: loaded.append((app, code)))
    controller.set_language("fr")
    assert controller.get_language() == "fr"
    assert loaded[-1][1] == "fr"

    created, _message, _user = controller.user_repo.register(
        "Personalized", "personalized", "password1"
    )
    assert created
    assert controller.attempt_login("personalized", "password1")[0] is True
    controller.set_theme("dark")
    controller.set_language("en")

    saved = next(
        user for user in controller.user_repo.get_all_users()
        if user["id"] == controller.get_current_user_id()
    )
    assert saved["preferences"]["theme"] == "dark"
    assert saved["preferences"]["language"] == "en"
    assert controller.settings.get_theme() == "light"
    assert controller.settings.get_language() == "fr"


def test_main_controller_validates_and_isolates_saved_geometry(tmp_path):
    controller = make_controller(tmp_path)

    assert controller.get_launcher_size() == (700, 580)
    assert controller.get_window_size("quiz_editor") == (900, 650)
    assert controller.get_window_size("unknown") == (800, 650)
    controller.set_launcher_size(0, 600)
    controller.set_window_size("quiz_editor", -1, 600)
    assert controller.settings.get_launcher_size() is None
    assert controller.settings.get_window_size("quiz_editor") is None

    controller.set_launcher_size(720, 680)
    controller.set_window_size("quiz_editor", 880, 620)
    assert controller.get_launcher_size() == (720, 680)
    assert controller.get_window_size("quiz_editor") == (880, 620)

    created, _message, _user = controller.user_repo.register(
        "Teacher", "teacher.geometry", "password1"
    )
    assert created
    authenticated = controller.user_repo.authenticate("teacher.geometry", "password1")
    authenticated["role"] = "teacher"
    controller.session.login(authenticated)
    assert controller.get_launcher_size() == (760, 840)
    controller.set_launcher_size(940, 760)
    controller.set_window_size("flashcard_editor", 920, 670)
    assert controller.get_launcher_size() == (940, 760)
    assert controller.get_window_size("flashcard_editor") == (920, 670)
    assert controller.settings.get_launcher_size() == [720, 680]
