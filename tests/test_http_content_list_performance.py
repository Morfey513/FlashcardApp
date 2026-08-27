import pytest

from src.controllers.flashcard_controller import FlashcardController
from src.controllers.flashcard_editor_controller import FlashcardEditorController
from src.controllers.profile_statistics_controller import ProfileStatisticsController
from src.controllers.quiz_controller import QuizController
from src.controllers.quiz_editor_controller import QuizEditorController
from src.storage.flashcard_repository import FlashcardRepository
from src.storage.http_content_metadata_repository import HttpContentMetadataRepository
from src.storage.http_domain_repositories import HttpFlashcardRepository, HttpQuizRepository
from src.storage.http_class_repository import HttpClassRepository
from src.storage.quiz_repository import QuizRepository


class RecordingUserRepository:
    def __init__(self):
        self._token = "token-a"
        self._current_user = {"id": "user-a", "role": "teacher"}
        self.calls = []

    def _request(self, method, path, payload=None, authenticated=False):
        self.calls.append((method, path, authenticated))
        if path.startswith("/api/v1/content/metadata?"):
            return 200, [{
                "id": "quiz-1", "name": "Quiz", "owner_id": "user-a",
                "source_owner_id": "user-a", "status": "published",
                "visibility": "public", "content_version": 1,
                "source_path": "quiz.json", "created_at": None,
                "updated_at": None, "kind": "quiz", "test_settings": None,
            }]
        return 200, {"edits": [], "moderation": []}


class StudyRecordingUserRepository:
    def __init__(self, *, mastered=False, visibility="public"):
        self._token = "token-a"
        self._current_user = {"id": "student-a", "role": "student"}
        self._content_metadata_cache = {}
        self.calls = []
        self.mastered = mastered
        self.visibility = visibility
        self.cleared_progress = set()

    def _request(self, method, path, payload=None, authenticated=False):
        self.calls.append((method, path, authenticated))
        if path == "/api/v1/progress/summary?include_items=true":
            quiz_mastered = self.mastered and "quiz" not in self.cleared_progress
            deck_mastered = self.mastered and "flashcard" not in self.cleared_progress
            return 200, {
                "collections": [
                    {
                        "kind": "flashcard", "id": "deck-1", "name": "One Deck",
                        "items": [{"id": "c1", "text": "Q", "mastered": deck_mastered,
                                   "correct": 3 if deck_mastered else 0, "wrong": 0}],
                        "summary": {"mastered": int(deck_mastered), "total": 1,
                                    "percent": 100 if deck_mastered else 0,
                                    "has_progress": deck_mastered},
                    },
                    {
                        "kind": "quiz", "id": "quiz-1", "name": "One Quiz",
                        "items": [{"id": "q1", "text": "Q", "mastered": quiz_mastered,
                                   "correct": 2 if quiz_mastered else 0, "wrong": 0}],
                        "summary": {"mastered": int(quiz_mastered), "total": 1,
                                    "percent": 100 if quiz_mastered else 0,
                                    "has_progress": quiz_mastered},
                    },
                ],
                "summary": {
                    "flashcards": {"mastered": int(deck_mastered), "total": 1},
                    "quizzes": {"mastered": int(quiz_mastered), "total": 1},
                },
            }
        if path in {
            "/api/v1/content/metadata?scope=available&kind=quiz",
            "/api/v1/content/metadata?scope=owned&kind=quiz",
        }:
            return 200, [{
                "id": "quiz-1", "name": "One Quiz", "owner_id": "teacher-a",
                "source_owner_id": "teacher-a", "status": "published",
                "visibility": self.visibility, "content_version": 1,
                "source_path": "quiz.json", "created_at": None,
                "updated_at": None, "kind": "quiz",
                "test_settings": {"attempt_limit": 2, "passing_grade_percent": 75},
            }]
        if path in {
            "/api/v1/content/metadata?scope=available&kind=flashcard",
            "/api/v1/content/metadata?scope=owned&kind=flashcard",
        }:
            return 200, [{
                "id": "deck-1", "name": "One Deck", "owner_id": "teacher-a",
                "source_owner_id": "teacher-a", "status": "published",
                "visibility": self.visibility, "content_version": 1,
                "source_path": "deck.json", "created_at": None,
                "updated_at": None, "kind": "flashcard", "test_settings": None,
            }]
        if path == "/api/v1/content/bodies/quiz/quiz-1":
            return 200, {"id": "quiz-1", "name": "One Quiz", "content_version": 1,
                         "questions": [{"id": "q1", "type": "short_answer",
                                        "question": "Q", "answer": "A"}]}
        if path == "/api/v1/content/bodies/flashcard/deck-1":
            return 200, {"id": "deck-1", "name": "One Deck", "content_version": 1,
                         "cards": [{"id": "c1", "front": "Q", "back": "A"}]}
        if path in {
            "/api/v1/progress/quiz/quiz-1",
            "/api/v1/progress/quiz/quiz-1?include_items=true",
        }:
            mastered = self.mastered and "quiz" not in self.cleared_progress
            progress = {"q1": {"mastered": mastered, "correct": 2 if mastered else 0,
                                "wrong": 0}}
            body = {"progress": progress}
            if "include_items=true" in path:
                body.update({
                    "items": [{"id": "q1", "text": "Q", **progress["q1"]}],
                    "summary": {"mastered": int(mastered), "total": 1,
                                "percent": 100 if mastered else 0,
                                "has_progress": mastered},
                })
            return 200, body
        if path in {
            "/api/v1/progress/flashcard/deck-1",
            "/api/v1/progress/flashcard/deck-1?include_items=true",
        }:
            mastered = self.mastered and "flashcard" not in self.cleared_progress
            progress = {"c1": {"mastered": mastered, "correct": 3 if mastered else 0,
                                "wrong": 0}}
            body = {"progress": progress}
            if "include_items=true" in path:
                body.update({
                    "items": [{"id": "c1", "text": "Q", **progress["c1"]}],
                    "summary": {"mastered": int(mastered), "total": 1,
                                "percent": 100 if mastered else 0,
                                "has_progress": mastered},
                })
            return 200, body
        if method == "DELETE" and path == "/api/v1/progress/quiz":
            self.cleared_progress.add("quiz")
            return 200, {"removed": 1}
        if method == "DELETE" and path == "/api/v1/progress/flashcard":
            self.cleared_progress.add("flashcard")
            return 200, {"removed": 1}
        if path == "/api/v1/quizzes/quiz-1/attempts":
            return 200, []
        if method == "PUT" and path.startswith("/api/v1/quizzes/quiz-1/attempts/"):
            return 200, dict(payload or {})
        if method == "POST" and path == "/api/v1/quizzes/quiz-1/assessments":
            return 200, {
                "id": "assessment-1", "quiz_id": "quiz-1",
                "questions": [{"id": "q1", "position": 0, "type": "short_answer",
                               "question": "Q"}],
            }
        if path == "/api/v1/content/metadata/quiz/quiz-1":
            return 200, {
                "id": "quiz-1", "name": "One Quiz", "status": "published",
                "visibility": self.visibility, "source_path": "quiz.json",
                "test_settings": {"attempt_limit": 2, "passing_grade_percent": 75},
            }
        if path == "/api/v1/content/metadata/flashcard/deck-1":
            return 200, {
                "id": "deck-1", "name": "One Deck", "status": "published",
                "visibility": self.visibility, "source_path": "deck.json",
            }
        if path in {
            "/api/v1/classes/quiz/quiz-1/invitation",
            "/api/v1/classes/flashcard/deck-1/invitation",
        }:
            return 200, {"code": "CLASS-CODE"}
        if method == "PUT" and path.startswith("/api/v1/content/metadata/"):
            return 200, {
                **dict(payload or {}), "owner_id": "teacher-a",
                "source_owner_id": "teacher-a", "content_version": 1,
            }
        if method == "PUT" and path.startswith("/api/v1/content/bodies/"):
            return 200, dict(payload or {})
        return 404, {}


def test_metadata_is_cached_by_kind_and_scope_and_refresh_bypasses_cache():
    user = RecordingUserRepository()
    repo = HttpContentMetadataRepository(user)

    repo.get_all("quiz", "available")
    repo.get_all("quiz", "available")
    repo.get_all("flashcard", "available")
    repo.refresh("quiz", "available")

    paths = [path for _method, path, _auth in user.calls]
    assert paths.count("/api/v1/content/metadata?scope=available&kind=quiz") == 2
    assert paths.count("/api/v1/content/metadata?scope=available&kind=flashcard") == 1


def test_content_item_list_does_not_load_history_per_item():
    user = RecordingUserRepository()
    repo = HttpQuizRepository(user)

    items = repo.get_content_items()

    assert [item["file"] for item in items] == ["quiz-1"]
    assert [path for _method, path, _auth in user.calls] == [
        "/api/v1/content/metadata?scope=available&kind=quiz"
    ]


def test_owned_content_uses_owned_scope_without_exposing_other_content():
    user = RecordingUserRepository()
    repo = HttpQuizRepository(user)

    repo.get_owned_quizzes()

    assert user.calls[-1][1] == "/api/v1/content/metadata?scope=owned&kind=quiz"


def test_owned_classes_are_cached_for_repeated_roster_refreshes():
    user = RecordingUserRepository()
    user._current_user["role"] = "teacher"
    user._request = lambda method, path, payload=None, authenticated=False: (
        user.calls.append((method, path, authenticated)) or (200, [])
    )
    repo = HttpClassRepository(user)

    repo.get_owned_classes("user-a", "all")
    repo.get_owned_classes("user-a", "all")

    assert [path for _method, path, _auth in user.calls] == ["/api/v1/classes/owned"]


def test_http_quiz_completion_and_practice_start_reuse_selected_body_and_progress(monkeypatch):
    monkeypatch.setenv("STUDY_BUDDY_STORAGE", "api")
    user = StudyRecordingUserRepository()
    controller = QuizController(
        "student-a", repo=HttpQuizRepository(user), role="student", user_repository=user,
    )

    assert controller.is_quiz_complete("One Quiz") is False
    assert controller.load_quiz_by_name("One Quiz", mode="practice")["id"] == "q1"

    paths = [path for _method, path, _authenticated in user.calls]
    assert paths.count("/api/v1/content/bodies/quiz/quiz-1") == 1
    assert paths.count("/api/v1/progress/quiz/quiz-1") == 1
    assert "/api/v1/quizzes/quiz-1/attempts" not in paths
    assert not any("kind=flashcard" in path for path in paths)


def test_http_flashcard_completion_and_start_reuse_selected_body_and_progress(monkeypatch):
    monkeypatch.setenv("STUDY_BUDDY_STORAGE", "api")
    user = StudyRecordingUserRepository()
    controller = FlashcardController(
        "student-a", repo=HttpFlashcardRepository(user), role="student",
        user_repository=user,
    )

    assert controller.is_deck_complete("One Deck") is False
    assert controller.start_deck("One Deck")["id"] == "c1"

    paths = [path for _method, path, _authenticated in user.calls]
    assert paths.count("/api/v1/content/bodies/flashcard/deck-1") == 1
    assert paths.count("/api/v1/progress/flashcard/deck-1") == 1
    assert not any("kind=quiz" in path for path in paths)


@pytest.mark.parametrize("mastered", [False, True])
def test_http_test_policy_and_start_do_not_duplicate_selected_package(monkeypatch, mastered):
    monkeypatch.setenv("STUDY_BUDDY_STORAGE", "api")
    user = StudyRecordingUserRepository(mastered=mastered)
    controller = QuizController(
        "student-a", repo=HttpQuizRepository(user), role="student", user_repository=user,
    )

    policy = controller.get_test_policy("One Quiz")
    assert policy["can_start"] is True
    assert controller.load_quiz_by_name("One Quiz", mode="test")["id"] == "q1"

    paths = [path for _method, path, _authenticated in user.calls]
    assert paths.count("/api/v1/content/bodies/quiz/quiz-1") == 1
    assert paths.count("/api/v1/progress/quiz/quiz-1") == 1
    assert paths.count("/api/v1/quizzes/quiz-1/attempts") == 1
    assert not any("kind=flashcard" in path for path in paths)
    calls = [(method, path) for method, path, _auth in user.calls]
    assert calls[:4] == [
        ("GET", "/api/v1/content/metadata?scope=available&kind=quiz"),
        ("GET", "/api/v1/content/bodies/quiz/quiz-1"),
        ("GET", "/api/v1/progress/quiz/quiz-1"),
        ("GET", "/api/v1/quizzes/quiz-1/attempts"),
    ]
    assert len(calls) == 5
    assert calls[4][0] == "PUT"
    assert calls[4][1].startswith("/api/v1/quizzes/quiz-1/attempts/")


def test_http_class_test_uses_policy_attempts_then_server_assessment_only(monkeypatch):
    monkeypatch.setenv("STUDY_BUDDY_STORAGE", "api")
    user = StudyRecordingUserRepository(visibility="class_only")
    controller = QuizController(
        "student-a", repo=HttpQuizRepository(user), role="student", user_repository=user,
    )

    assert controller.get_test_policy("One Quiz")["can_start"] is True
    assert controller.load_quiz_by_name("One Quiz", mode="test")["id"] == "q1"

    calls = [(method, path) for method, path, _auth in user.calls]
    assert calls == [
        ("GET", "/api/v1/content/metadata?scope=available&kind=quiz"),
        ("GET", "/api/v1/quizzes/quiz-1/attempts"),
        ("POST", "/api/v1/quizzes/quiz-1/assessments"),
    ]
    assert not any("/content/bodies/" in path or "/progress/" in path for _, path in calls)


def test_http_completion_detection_still_recognizes_mastered_content(monkeypatch):
    monkeypatch.setenv("STUDY_BUDDY_STORAGE", "api")
    quiz_user = StudyRecordingUserRepository(mastered=True)
    deck_user = StudyRecordingUserRepository(mastered=True)

    assert QuizController(
        "student-a", repo=HttpQuizRepository(quiz_user), user_repository=quiz_user,
    ).is_quiz_complete("One Quiz") is True
    assert FlashcardController(
        "student-a", repo=HttpFlashcardRepository(deck_user), user_repository=deck_user,
    ).is_deck_complete("One Deck") is True


def test_local_completion_and_start_reuse_selected_body_and_progress(tmp_path, monkeypatch):
    quiz_repo = QuizRepository(tmp_path / "quizzes", tmp_path / "quizzes.json")
    deck_repo = FlashcardRepository(tmp_path / "decks", tmp_path / "decks.json")
    assert quiz_repo.create_quiz(
        "Local Quiz", [{"id": "q1", "type": "short_answer", "question": "Q", "answer": "A"}],
    )
    assert deck_repo.create_deck("Local Deck", [{"id": "c1", "front": "Q", "back": "A"}])
    quiz_calls = {"body": 0, "progress": 0}
    deck_calls = {"body": 0, "progress": 0}
    original_quiz_body = quiz_repo.load_quiz_questions
    original_quiz_progress = quiz_repo.get_quiz_progress
    original_deck_body = deck_repo.load_deck_cards
    original_deck_progress = deck_repo.get_progress

    def load_quiz(value):
        quiz_calls["body"] += 1
        return original_quiz_body(value)

    def load_quiz_progress(value, user_id="guest"):
        quiz_calls["progress"] += 1
        return original_quiz_progress(value, user_id)

    def load_deck(value):
        deck_calls["body"] += 1
        return original_deck_body(value)

    def load_deck_progress(value, user_id="guest"):
        deck_calls["progress"] += 1
        return original_deck_progress(value, user_id)

    monkeypatch.setattr(quiz_repo, "load_quiz_questions", load_quiz)
    monkeypatch.setattr(quiz_repo, "get_quiz_progress", load_quiz_progress)
    monkeypatch.setattr(deck_repo, "load_deck_cards", load_deck)
    monkeypatch.setattr(deck_repo, "get_progress", load_deck_progress)

    quiz_controller = QuizController("guest", quiz_repo)
    deck_controller = FlashcardController("guest", deck_repo)
    assert quiz_controller.is_quiz_complete("Local Quiz") is False
    assert quiz_controller.load_quiz_by_name("Local Quiz")
    assert deck_controller.is_deck_complete("Local Deck") is False
    assert deck_controller.start_deck("Local Deck")
    assert quiz_calls == {"body": 1, "progress": 1}
    assert deck_calls == {"body": 1, "progress": 1}


def test_http_profile_statistics_use_lightweight_progress_items_without_bodies(monkeypatch):
    monkeypatch.setenv("STUDY_BUDDY_STORAGE", "api")
    user = StudyRecordingUserRepository(mastered=True)
    controller = ProfileStatisticsController(
        "student-a", HttpFlashcardRepository(user), HttpQuizRepository(user),
        user_repository=user,
    )

    flashcards = controller.get_flashcard_stats()
    quizzes = controller.get_quiz_stats()

    assert flashcards["collections"][0]["rows"][0]["text"] == "Q"
    assert quizzes["collections"][0]["rows"][0]["text"] == "Q"
    assert flashcards["mastered"] == quizzes["mastered"] == 1
    paths = [path for _method, path, _authenticated in user.calls]
    assert paths.count("/api/v1/progress/summary?include_items=true") == 1
    assert not any(path.startswith("/api/v1/progress/flashcard/deck-") for path in paths)
    assert not any(path.startswith("/api/v1/progress/quiz/quiz-") for path in paths)
    assert not any("/content/bodies/" in path for path in paths)


@pytest.mark.parametrize("scope", [None, "flashcards", "quizzes"])
def test_http_profile_clear_refreshes_only_lightweight_affected_stats(monkeypatch, scope):
    monkeypatch.setenv("STUDY_BUDDY_STORAGE", "api")
    user = StudyRecordingUserRepository(mastered=True)
    controller = ProfileStatisticsController(
        "student-a", HttpFlashcardRepository(user), HttpQuizRepository(user),
        user_repository=user,
    )
    controller.get_flashcard_stats()
    controller.get_quiz_stats()
    user.calls.clear()

    assert controller.reset_all(scope) == (2 if scope is None else 1)
    flashcards = controller.get_flashcard_stats()
    quizzes = controller.get_quiz_stats()

    paths = [path for _method, path, _authenticated in user.calls]
    expected_deleted = (
        {"/api/v1/progress/flashcard", "/api/v1/progress/quiz"}
        if scope is None else {f"/api/v1/progress/{'flashcard' if scope == 'flashcards' else 'quiz'}"}
    )
    assert {path for method, path, _authenticated in user.calls if method == "DELETE"} == expected_deleted
    assert not any("/content/bodies/" in path for path in paths)
    assert flashcards["mastered"] == (1 if scope == "quizzes" else 0)
    assert quizzes["mastered"] == (1 if scope == "flashcards" else 0)


@pytest.mark.parametrize(
    ("controller_class", "list_method", "expected_kind", "unexpected_kind"),
    [(QuizEditorController, "get_quiz_entries", "quiz", "flashcard"),
     (FlashcardEditorController, "get_deck_entries", "flashcard", "quiz")],
)
def test_http_editor_list_discovery_is_scoped_to_its_content_kind(
    monkeypatch, controller_class, list_method, expected_kind, unexpected_kind,
):
    monkeypatch.setenv("STUDY_BUDDY_STORAGE", "api")
    user = StudyRecordingUserRepository()
    user._current_user = {"id": "teacher-a", "role": "teacher"}
    controller = controller_class(
        "teacher-a", "teacher", user_repository=user,
    )

    getattr(controller, list_method)()

    paths = [path for _method, path, _authenticated in user.calls]
    assert any(f"kind={expected_kind}" in path for path in paths)
    assert not any(f"kind={unexpected_kind}" in path for path in paths)


@pytest.mark.parametrize(
    ("controller_class", "list_method", "kind"),
    [(QuizEditorController, "get_quiz_entries", "quiz"),
     (FlashcardEditorController, "get_deck_entries", "flashcard")],
)
def test_http_teacher_editor_list_uses_one_owned_catalog_request(
    monkeypatch, controller_class, list_method, kind,
):
    monkeypatch.setenv("STUDY_BUDDY_STORAGE", "api")
    user = StudyRecordingUserRepository()
    user._current_user = {"id": "teacher-a", "role": "teacher"}
    controller = controller_class("teacher-a", "teacher", user_repository=user)

    assert getattr(controller, list_method)()

    metadata_paths = [
        path for _method, path, _authenticated in user.calls
        if path.startswith("/api/v1/content/metadata?")
    ]
    assert metadata_paths == [f"/api/v1/content/metadata?scope=owned&kind={kind}"]


@pytest.mark.parametrize(
    ("controller_class", "load_method", "save_method", "name", "kind"),
    [(QuizEditorController, "load_quiz", "save_quiz", "One Quiz", "quiz"),
     (FlashcardEditorController, "load_deck", "save_deck", "One Deck", "flashcard")],
)
def test_http_editor_save_reuses_selected_metadata_and_avoids_opposite_kind(
    monkeypatch, controller_class, load_method, save_method, name, kind,
):
    monkeypatch.setenv("STUDY_BUDDY_STORAGE", "api")
    user = StudyRecordingUserRepository()
    user._current_user = {"id": "teacher-a", "role": "teacher"}
    controller = controller_class("teacher-a", "teacher", user_repository=user)
    assert getattr(controller, load_method)(name)
    user.calls.clear()

    if kind == "quiz":
        saved = getattr(controller, save_method)(
            controller.current_questions,
            {row["id"] for row in controller.current_questions},
            "public", {"attempt_limit": 2},
        )
    else:
        saved = getattr(controller, save_method)(controller.current_cards, "public")

    assert saved is True
    paths = [path for _method, path, _authenticated in user.calls]
    assert not any("scope=available" in path or "scope=owned" in path for path in paths)
    opposite = "flashcard" if kind == "quiz" else "quiz"
    assert not any(f"kind={opposite}" in path for path in paths)
    metadata_path = (
        f"/api/v1/content/metadata/{kind}/"
        f"{'quiz-1' if kind == 'quiz' else 'deck-1'}"
    )
    assert sum(method == "GET" and path == metadata_path
               for method, path, _authenticated in user.calls) == 1
    assert sum(method == "PUT" and path == metadata_path
               for method, path, _authenticated in user.calls) == 1


def test_quiz_editor_open_reuses_list_metadata_for_settings(monkeypatch):
    monkeypatch.setenv("STUDY_BUDDY_STORAGE", "api")
    user = StudyRecordingUserRepository(visibility="class_only")
    user._current_user = {"id": "teacher-a", "role": "teacher"}
    controller = QuizEditorController("teacher-a", "teacher", user_repository=user)
    assert controller.get_quiz_entries()
    user.calls.clear()

    assert controller.load_quiz("One Quiz") is True
    moderation = controller.get_current_moderation()
    settings = controller.get_current_test_settings()
    invitation = controller.get_current_invite_code()

    paths = [path for _method, path, _authenticated in user.calls]
    assert moderation["visibility"] == "class_only"
    assert settings["attempt_limit"] == 2
    assert invitation == "CLASS-CODE"
    assert paths.count("/api/v1/content/bodies/quiz/quiz-1") == 1
    assert paths.count("/api/v1/classes/quiz/quiz-1/invitation") == 1
    assert "/api/v1/content/metadata/quiz/quiz-1" not in paths


def test_flashcard_editor_open_uses_body_and_class_invitation(monkeypatch):
    monkeypatch.setenv("STUDY_BUDDY_STORAGE", "api")
    user = StudyRecordingUserRepository(visibility="class_only")
    user._current_user = {"id": "teacher-a", "role": "teacher"}
    controller = FlashcardEditorController("teacher-a", "teacher", user_repository=user)
    assert controller.get_deck_entries()
    user.calls.clear()

    assert controller.load_deck("One Deck") is True
    moderation = controller.get_current_moderation()
    invitation = controller.get_current_invite_code()

    paths = [path for _method, path, _authenticated in user.calls]
    assert moderation["visibility"] == "class_only"
    assert invitation == "CLASS-CODE"
    assert paths.count("/api/v1/content/bodies/flashcard/deck-1") == 1
    assert paths.count("/api/v1/classes/flashcard/deck-1/invitation") == 1


@pytest.mark.parametrize(
    ("controller_class", "create_method", "entries_method", "kind", "other_kind"),
    [(QuizEditorController, "create_new_quiz", "get_quiz_entries", "quiz", "flashcard"),
     (FlashcardEditorController, "create_deck", "get_deck_entries", "flashcard", "quiz")],
)
def test_http_editor_creation_refreshes_only_its_own_kind(
    monkeypatch, controller_class, create_method, entries_method, kind, other_kind,
):
    monkeypatch.setenv("STUDY_BUDDY_STORAGE", "api")
    user = StudyRecordingUserRepository()
    user._current_user = {"id": "teacher-a", "role": "teacher"}
    controller = controller_class("teacher-a", "teacher", user_repository=user)

    assert getattr(controller, create_method)("Created Content") is True
    getattr(controller, entries_method)()

    calls = [(method, path) for method, path, _authenticated in user.calls]
    assert sum(method == "PUT" and "/content/metadata/" in path for method, path in calls) == 1
    assert sum(method == "PUT" and f"/content/bodies/{kind}/" in path for method, path in calls) == 1
    assert any(method == "GET" and f"kind={kind}" in path for method, path in calls)
    assert not any(method == "GET" and f"kind={other_kind}" in path for method, path in calls)


@pytest.mark.parametrize(
    ("controller_class", "load_method", "save_method", "name", "body_kind"),
    [(QuizEditorController, "load_quiz", "save_quiz", "One Quiz", "quiz"),
     (FlashcardEditorController, "load_deck", "save_deck", "One Deck", "flashcard")],
)
def test_http_editor_does_not_report_success_after_failed_body_put(
    monkeypatch, controller_class, load_method, save_method, name, body_kind,
):
    monkeypatch.setenv("STUDY_BUDDY_STORAGE", "api")
    user = StudyRecordingUserRepository()
    user._current_user = {"id": "teacher-a", "role": "teacher"}
    original_request = user._request

    def fail_body_put(method, path, payload=None, authenticated=False):
        if method == "PUT" and f"/content/bodies/{body_kind}/" in path:
            user.calls.append((method, path, authenticated))
            return 500, {"detail": "write failed"}
        return original_request(method, path, payload, authenticated)

    user._request = fail_body_put
    controller = controller_class("teacher-a", "teacher", user_repository=user)
    assert getattr(controller, load_method)(name) is True
    user.calls.clear()

    if body_kind == "quiz":
        result = getattr(controller, save_method)(
            controller.current_questions,
            {question["id"] for question in controller.current_questions},
            "private",
        )
    else:
        result = getattr(controller, save_method)(controller.current_cards, "private")

    assert result is False
    calls = [(method, path) for method, path, _auth in user.calls]
    assert sum(method == "PUT" and f"/content/bodies/{body_kind}/" in path
               for method, path in calls) == 1
    assert not any("/progress/" in path for _method, path in calls)
