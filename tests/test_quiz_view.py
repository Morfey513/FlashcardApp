import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QPushButton

from src.ui.quiz_view import QuizListRow, QuizViewer
from src.ui.flashcard_viewer import DeckListRow


def test_quiz_list_row_tracks_custom_selected_state():
    app = QApplication.instance() or QApplication([])
    quiz = {
        "name": "Selection test",
        "total": 6,
        "mastered": 0,
        "moderation_status": "published",
    }
    row = QuizListRow(quiz, "0 of 6 mastered")

    assert row.property("selected") is False

    row.set_selected(True)
    assert row.property("selected") is True

    row.set_selected(False)
    assert row.property("selected") is False
    assert app is not None


def test_true_false_ui_returns_boolean_value():
    app = QApplication.instance() or QApplication([])

    class ControllerStub:
        user_id = "student"
        role = "student"

        def get_quiz_summaries(self):
            return []

        def get_current_card_type(self):
            return "true_false"

    viewer = QuizViewer(ControllerStub())
    viewer.render_answer_widget({"type": "true_false"})
    viewer.answer_group[0].setChecked(True)

    assert viewer.get_user_input() is True
    assert app is not None


def test_active_content_rows_show_visibility_instead_of_published_status():
    app = QApplication.instance() or QApplication([])
    quiz = {
        "name": "Public quiz", "total": 1, "mastered": 0,
        "moderation_status": "published", "visibility": "public",
    }
    deck = {
        "name": "Class deck", "total": 1, "mastered": 0,
        "moderation_status": "published", "visibility": "class_only",
    }

    quiz_row = QuizListRow(quiz, "0 of 1")
    deck_row = DeckListRow(deck, "0 of 1")
    quiz_chip = quiz_row.findChild(QPushButton, "content_status_chip")
    deck_chip = deck_row.findChild(QPushButton, "content_status_chip")

    assert quiz_chip.text() == "Public"
    assert deck_chip.text() == "Class-Only"
    assert app is not None


def test_completed_class_test_is_disabled_from_selection():
    app = QApplication.instance() or QApplication([])

    class ControllerStub:
        user_id = "student"
        role = "student"

        def get_quiz_summaries(self):
            return [{
                "name": "One attempt test",
                "total": 1,
                "mastered": 0,
                "moderation_status": "published",
                "visibility": "class_only",
                "latest_test_score": 75,
            }]

        def can_start_test(self, _name):
            return False

        def get_test_policy(self, _name):
            return {"completed": True, "due_expired": False}

        def get_current_card(self):
            return None

        def abandon_test_attempt(self):
            pass

    viewer = QuizViewer(ControllerStub())
    viewer.update_quiz_selection(viewer.quiz_list.currentItem(), None)

    assert viewer.take_test_btn.isEnabled() is False
    assert "attempt limit" in viewer.take_test_btn.toolTip().lower()
    viewer.close()
    assert app is not None
