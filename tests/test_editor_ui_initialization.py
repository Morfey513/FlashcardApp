import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtWidgets import QApplication, QInputDialog, QMessageBox, QPushButton, QWidget

import src.ui.editor.flashcard_editor as flashcard_editor_module
import src.ui.editor.quiz_editor as quiz_editor_module
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


@pytest.mark.parametrize("editor_type", ["quiz", "flashcard"])
def test_editor_status_column_stays_aligned_when_invite_action_is_present(editor_type):
    app = QApplication.instance() or QApplication([])
    previous_stylesheet = app.styleSheet()
    app.setStyleSheet(Path("styles/style.qss").read_text(encoding="utf-8"))
    if editor_type == "quiz":
        controller = QuizEditorControllerStub()
        controller.get_quiz_entries = lambda: [
            {"name": "Class Quiz", "status": "draft", "visibility": "class_only"},
            {"name": "Public Quiz", "status": "draft", "visibility": "public"},
        ]
        editor = QuizEditor(controller)
        list_widget = editor.editor_quiz_list
    else:
        controller = FlashcardEditorControllerStub()
        controller.get_deck_entries = lambda: [
            {"name": "Class Deck", "status": "draft", "visibility": "class_only"},
            {"name": "Public Deck", "status": "draft", "visibility": "public"},
        ]
        editor = FlashcardEditor(controller)
        list_widget = editor.deck_list

    try:
        editor.show()
        app.processEvents()
        status_x = [
            list_widget.itemWidget(list_widget.item(index))
            .findChild(QWidget, "content_status_slot").geometry().x()
            for index in range(2)
        ]
        assert status_x[0] == status_x[1]
        chip_centers = [
            (lambda row, chip: chip.mapTo(row, chip.rect().center()).x())(
                list_widget.itemWidget(list_widget.item(index)),
                list_widget.itemWidget(list_widget.item(index))
                .findChild(QPushButton, "content_status_chip"),
            )
            for index in range(2)
        ]
        assert chip_centers[0] == chip_centers[1]
    finally:
        editor.close()
        app.setStyleSheet(previous_stylesheet)


def test_class_only_editor_row_keeps_key_and_trash_emoji_actions():
    app = QApplication.instance() or QApplication([])
    editor = QuizEditor(QuizEditorControllerStub())
    editor._add_quiz_row("Class Quiz", "draft", "class_only")
    row = editor.editor_quiz_list.itemWidget(editor.editor_quiz_list.item(1))
    buttons = row.findChildren(QPushButton, "inline_action")

    assert "🔑️" in [button.text() for button in buttons]
    assert "🗑️" in [button.text() for button in buttons]
    editor.close()
    assert app is not None


def test_editor_row_title_retains_text_for_custom_painting():
    app = QApplication.instance() or QApplication([])
    editor = QuizEditor(QuizEditorControllerStub())
    row = editor.editor_quiz_list.itemWidget(editor.editor_quiz_list.item(0))
    title = row.findChild(QWidget, "editor_row_label")

    assert title._full_text == "Existing Quiz"
    assert title.text() == "Existing Quiz"
    editor.close()
    assert app is not None


@pytest.mark.parametrize("editor_type", ["quiz", "flashcard"])
def test_editor_rejected_status_badge_opens_moderation_reason(monkeypatch, editor_type):
    app = QApplication.instance() or QApplication([])
    received = []
    if editor_type == "quiz":
        monkeypatch.setattr(
            quiz_editor_module, "show_moderation_reason",
            lambda _parent, status, reason: received.append((status, reason)),
        )
        editor = QuizEditor(QuizEditorControllerStub())
        editor._add_quiz_row("Rejected Quiz", "rejected", "public", "Needs citations")
        list_widget = editor.editor_quiz_list
    else:
        monkeypatch.setattr(
            flashcard_editor_module, "show_moderation_reason",
            lambda _parent, status, reason: received.append((status, reason)),
        )
        editor = FlashcardEditor(FlashcardEditorControllerStub())
        editor._add_deck_row("Rejected Deck", "rejected", "public", "Needs citations")
        list_widget = editor.deck_list

    row = list_widget.itemWidget(list_widget.item(list_widget.count() - 1))
    chip = row.findChild(QPushButton, "content_status_chip")
    assert chip.text() == "⚠️ Rejected (info)"
    assert chip.property("content_status") == "rejected"
    assert chip.property("interactive") is True
    chip.click()
    assert received == [("rejected", "Needs citations")]
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
