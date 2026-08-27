import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtWidgets import QApplication, QInputDialog, QMessageBox

from src.ui.editor.flashcard_editor import FlashcardEditor
from src.ui.editor.quiz_editor import QuizEditor


class QuizEditorControllerStub:
    has_unsaved_changes = False

    def __init__(self):
        self.calls = 0

    def get_quiz_entries(self):
        self.calls += 1
        return [{"name": "Existing Quiz", "status": "draft", "visibility": "private"}]

    def delete_quiz_result(self, _name):
        return {"status": "deleted", "status_code": 200}

    def copy_quiz(self, _original, _new):
        return False


class FlashcardEditorControllerStub:
    has_unsaved_changes = False

    def __init__(self):
        self.calls = 0

    def get_deck_entries(self):
        self.calls += 1
        return [{"name": "Existing Deck", "status": "draft", "visibility": "private"}]

    def delete_deck_result(self, _name):
        return {"status": "deleted", "status_code": 200}


def test_quiz_editor_populates_existing_content_once_during_initialization():
    app = QApplication.instance() or QApplication([])
    controller = QuizEditorControllerStub()

    editor = QuizEditor(controller)

    assert controller.calls == 1
    assert editor.editor_quiz_list.count() == 1
    assert editor.editor_quiz_list.item(0).data(0x0100) == "Existing Quiz"
    editor.close()
    assert app is not None


def test_flashcard_editor_populates_existing_content_once_during_initialization():
    app = QApplication.instance() or QApplication([])
    controller = FlashcardEditorControllerStub()

    editor = FlashcardEditor(controller)

    assert controller.calls == 1
    assert editor.deck_list.count() == 1
    assert editor.deck_list.item(0).data(0x0100) == "Existing Deck"
    editor.close()
    assert app is not None


@pytest.mark.parametrize(
    ("outcome", "refreshes", "message_kind"),
    [("deleted", 1, None), ("not_found", 1, "information"),
     ("forbidden", 0, "warning"), ("failed", 0, "warning")],
)
def test_quiz_editor_delete_refreshes_only_for_deleted_or_missing(
    monkeypatch, outcome, refreshes, message_kind,
):
    app = QApplication.instance() or QApplication([])
    controller = QuizEditorControllerStub()
    controller.delete_quiz_result = lambda _name: {"status": outcome, "status_code": 403}
    editor = QuizEditor(controller)
    refresh_calls = []
    messages = []
    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(QMessageBox, "information", lambda *_args: messages.append("information"))
    monkeypatch.setattr(QMessageBox, "warning", lambda *_args: messages.append("warning"))
    monkeypatch.setattr(editor, "refresh_quiz_list", lambda: refresh_calls.append(True))

    editor.delete_quiz_by_name("Existing Quiz")

    assert len(refresh_calls) == refreshes
    assert messages == ([] if message_kind is None else [message_kind])
    editor.close()
    assert app is not None


def test_failed_quiz_copy_does_not_refresh_the_editor_list(monkeypatch):
    app = QApplication.instance() or QApplication([])
    editor = QuizEditor(QuizEditorControllerStub())
    refresh_calls = []
    monkeypatch.setattr(QInputDialog, "getText", lambda *_args, **_kwargs: ("Copy", True))
    monkeypatch.setattr(editor, "refresh_quiz_list", lambda: refresh_calls.append(True))

    editor.copy_quiz_by_name("Existing Quiz")

    assert refresh_calls == []
    editor.close()
    assert app is not None


@pytest.mark.parametrize(
    ("outcome", "refreshes", "message_kind"),
    [("deleted", 1, None), ("not_found", 1, "information"),
     ("forbidden", 0, "warning"), ("failed", 0, "warning")],
)
def test_flashcard_editor_delete_refreshes_only_for_deleted_or_missing(
    monkeypatch, outcome, refreshes, message_kind,
):
    app = QApplication.instance() or QApplication([])
    controller = FlashcardEditorControllerStub()
    controller.delete_deck_result = lambda _name: {"status": outcome, "status_code": 403}
    editor = FlashcardEditor(controller)
    refresh_calls = []
    messages = []
    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(QMessageBox, "information", lambda *_args: messages.append("information"))
    monkeypatch.setattr(QMessageBox, "warning", lambda *_args: messages.append("warning"))
    monkeypatch.setattr(editor, "refresh_deck_list", lambda: refresh_calls.append(True))

    editor.delete_deck_by_name("Existing Deck")

    assert len(refresh_calls) == refreshes
    assert messages == ([] if message_kind is None else [message_kind])
    editor.close()
    assert app is not None
