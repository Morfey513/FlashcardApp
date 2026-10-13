"""Disposable copy of the desktop runtime used by visible GUI tests."""
from __future__ import annotations

import shutil
import tempfile
import json
from pathlib import Path


class RuntimeCopy:
    def __init__(self, source_root: Path, run_id: str, keep: bool = False, *, preview_only: bool = False):
        self.source_root = source_root
        self.run_id = run_id
        self.keep = keep
        self.path = Path(tempfile.mkdtemp(prefix=f"study-buddy-{run_id}-"))
        self.guest_quiz_name = f"GUI Runtime Quiz {run_id}"
        self.guest_deck_name = f"GUI Runtime Deck {run_id}"
        self.preview_only = preview_only

    def prepare(self) -> Path:
        ignored = shutil.ignore_patterns(".git", ".venv", ".pytest-*", "__pycache__", "cache", "logs", "artifacts")
        for name in ("src", "styles", "data", "requirements.txt"):
            source = self.source_root / name
            target = self.path / name
            if source.is_dir():
                shutil.copytree(source, target, ignore=ignored)
            elif source.exists():
                shutil.copy2(source, target)
        (self.path / "logs").mkdir(exist_ok=True)
        # Guest sessions intentionally use the local repository. Replace only
        # the copied bundled indexes with one known fixture per kind, so list
        # selection is deterministic without altering application behavior or
        # the developer's source data.
        self._write_visible_fixtures()
        return self.path

    def _write_visible_fixtures(self) -> None:
        fixture_id = f"gui-runtime-{self.run_id}"
        quiz_name = self.guest_quiz_name
        deck_name = self.guest_deck_name
        quiz_relative = Path("data") / "quizzes" / fixture_id / "quiz.json"
        deck_relative = Path("data") / "flashcards" / fixture_id / "deck.json"
        quiz_path = self.path / quiz_relative
        deck_path = self.path / deck_relative
        quiz_path.parent.mkdir(parents=True, exist_ok=True)
        deck_path.parent.mkdir(parents=True, exist_ok=True)
        quiz_questions = (
            [{"id": "preview-boolean", "question": "GUI preview true false", "type": "true_false", "answer": True}]
            if self.preview_only else [
                {"id": "single", "question": "GUI fixture single choice", "type": "single_choice", "choices": ["one", "two"], "answer": "one"},
                {"id": "multiple", "question": "GUI fixture multiple choice", "type": "multiple_choice", "choices": ["one", "two"], "answer": ["one"]},
                {"id": "boolean", "question": "GUI fixture true false", "type": "true_false", "answer": True},
                {"id": "short", "question": "GUI fixture short answer", "type": "short_answer", "answer": "one"},
                {"id": "matching", "question": "GUI fixture matching", "type": "matching", "pairs": [{"prompt": "one", "answer": "1"}, {"prompt": "two", "answer": "2"}]},
                {"id": "ordering", "question": "GUI fixture ordering", "type": "ordering", "items": ["one", "two"], "answer": ["one", "two"]},
            ]
        )
        quiz_path.write_text(json.dumps({"id": fixture_id, "name": quiz_name, "questions": quiz_questions}, indent=2), encoding="utf-8")
        deck_path.write_text(json.dumps({"id": fixture_id, "name": deck_name, "cards": [
            {"id": "card-one", "front": "GUI fixture front", "back": "GUI fixture back"},
            {"id": "card-two", "front": "GUI fixture front two", "back": "GUI fixture back two"},
        ]}, indent=2), encoding="utf-8")
        (self.path / "data" / "quizzes.json").write_text(json.dumps([
            {"id": fixture_id, "name": quiz_name, "file": str(quiz_relative).replace("\\", "/")}
        ], indent=2), encoding="utf-8")
        (self.path / "data" / "flashcard_decks.json").write_text(json.dumps([
            {"id": fixture_id, "name": deck_name, "file": str(deck_relative).replace("\\", "/")}
        ], indent=2), encoding="utf-8")

    def cleanup(self) -> None:
        if not self.keep:
            shutil.rmtree(self.path, ignore_errors=True)
