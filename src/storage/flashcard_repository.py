import json
import logging
import shutil
import uuid
from pathlib import Path

from src.config import FLASHCARD_DIR, FLASHCARD_INDEX
from src.utils.paths import resolve_stored_path, to_stored_path

logger = logging.getLogger(__name__)

DECK_FILENAME = "deck.json"
MEDIA_FOLDER = "media"
PROGRESS_FOLDER = "progress"


class FlashcardRepository:
    """Owns all filesystem details for flashcard decks."""

    def __init__(
        self,
        flashcard_dir: Path = FLASHCARD_DIR,
        index_path: Path = FLASHCARD_INDEX,
    ):
        self.flashcard_dir = Path(flashcard_dir)
        self.index_path = Path(index_path)
        self.flashcard_dir.mkdir(parents=True, exist_ok=True)
        self.index_path.parent.mkdir(parents=True, exist_ok=True)

    def get_all_decks(self):
        if not self.index_path.exists():
            return self._rebuild_index_from_disk()
        try:
            decks = self._read_json(self.index_path)
            cleaned = [
                deck for deck in decks
                if self.resolve_path(deck.get("file")).exists()
            ]
            if cleaned != decks:
                self._save_index(cleaned)
            return cleaned
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            logger.error("Failed to load deck index: %s", exc)
            return self._rebuild_index_from_disk()

    def _rebuild_index_from_disk(self):
        decks = []
        for file in self.flashcard_dir.glob(f"*/{DECK_FILENAME}"):
            try:
                data = self._read_json(file)
                decks.append({
                    "id": data.get("id", file.parent.name),
                    "name": data.get("name", file.parent.name),
                    "file": to_stored_path(file),
                })
            except (OSError, json.JSONDecodeError, TypeError) as exc:
                logger.warning("Skipping invalid deck %s: %s", file, exc)
        self._save_index(decks)
        return decks

    def create_deck(self, name: str, cards=None, owner_id=None):
        if any(deck["name"] == name for deck in self.get_all_decks()):
            return False
        deck_id = str(uuid.uuid4())
        deck_dir = self.flashcard_dir / deck_id
        deck_dir.mkdir(parents=True)
        (deck_dir / MEDIA_FOLDER).mkdir()
        (deck_dir / PROGRESS_FOLDER).mkdir()
        file = deck_dir / DECK_FILENAME
        moderation = None
        if owner_id is not None:
            moderation = {
                "owner_id": str(owner_id), "status": "draft", "visibility": "public",
                "allowed_user_ids": [], "reviewed_by": None, "reviewed_at": None,
                "review_note": "",
            }
        self._write_deck(file, deck_id, name, cards or [], moderation)
        decks = self.get_all_decks()
        decks.append({"id": deck_id, "name": name, "file": to_stored_path(file)})
        self._save_index(decks)
        return True

    def copy_deck(self, original_name: str, new_name: str, owner_id=None):
        original = self._find_by_name(original_name)
        if not original:
            return False
        cards = []
        for card in self.load_deck_cards(original["file"]):
            copied = card.copy()
            copied["id"] = str(uuid.uuid4())
            cards.append(copied)
        return self.create_deck(new_name, cards, owner_id)

    def save_deck_content(self, relative_path: str, cards: list):
        file = self.resolve_path(relative_path)
        metadata = self._read_json(file) if file.exists() else {}
        self._write_deck(
            file,
            metadata.get("id", file.parent.name),
            metadata.get("name", file.parent.name),
            cards,
            metadata.get("moderation"),
        )

    def create_empty_deck(self, name):
        if not self.create_deck(name, []):
            return False, "Deck already exists"
        deck = self._find_by_name(name)
        return True, str(self.resolve_path(deck["file"]))

    def delete_deck_files(self, relative_path):
        file = self.resolve_path(relative_path)
        if file and file.parent.parent == self.flashcard_dir and file.parent.exists():
            shutil.rmtree(file.parent)
        return True

    def delete_deck_permanently(self, deck_name: str):
        deck = self._find_by_name(deck_name)
        if not deck:
            return False
        self.delete_deck_files(deck["file"])
        self._save_index([
            item for item in self.get_all_decks() if item["name"] != deck_name
        ])
        return True

    def load_deck_cards(self, relative_path: str):
        file = self.resolve_path(relative_path)
        if not file or not file.exists():
            return []
        try:
            data = self._read_json(file)
            cards = data.get("cards", []) if isinstance(data, dict) else data
            changed = False
            for card in cards:
                if not card.get("id"):
                    card["id"] = str(uuid.uuid4())
                    changed = True
            if changed:
                self.save_deck_content(relative_path, cards)
            return cards
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            logger.error("Failed to load deck %s: %s", relative_path, exc)
            return []

    def import_media(self, deck_relative_path: str, source_path: str) -> str:
        return self._import_media(deck_relative_path, source_path)

    def get_progress(self, deck_relative_path, user_id="guest"):
        file = self._progress_file(deck_relative_path, user_id)
        if not file.exists():
            logger.debug("No saved deck progress for user '%s' at %s", user_id, file)
            return {}
        try:
            progress = self._read_json(file)
            logger.debug(
                "Loaded progress for user '%s' from %s (%d card records)",
                user_id, file, len(progress),
            )
            return progress
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            logger.error("Failed to load progress %s: %s", file, exc)
            return {}

    def save_deck_progress(self, deck_relative_path, progress_data, user_id="guest"):
        file = self._progress_file(deck_relative_path, user_id)
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(json.dumps(progress_data, indent=4), encoding="utf-8")
        logger.debug(
            "Saved progress for user '%s' to %s (%d card records)",
            user_id, file, len(progress_data),
        )

    def get_deck_progress_summary(self, deck_relative_path, user_id="guest"):
        """Return manual-mastery progress for one deck and one user."""
        cards = self.load_deck_cards(deck_relative_path)
        progress = self.get_progress(deck_relative_path, user_id)
        total = len(cards)
        mastered = sum(
            1
            for card in cards
            if progress.get(card.get("id"), {}).get("mastered", False)
        )
        return {
            "mastered": mastered,
            "total": total,
            "percent": round((mastered / total) * 100) if total else 0,
            "has_progress": bool(progress),
        }

    def reset_deck_progress(self, deck_relative_path, user_id="guest"):
        """Remove one user's progress for one deck.

        The deck content and every other user's progress remain unchanged.
        """
        file = self._progress_file(deck_relative_path, user_id)
        if not file.exists():
            logger.info("No deck progress to reset for user '%s' at %s", user_id, file)
            return False
        file.unlink()
        logger.info("Reset deck progress for user '%s' at %s", user_id, file)
        return True

    def clear_user_progress(self, user_id="guest"):
        """Remove one user's progress from every deck and return the count."""
        removed = 0
        for deck in self.get_all_decks():
            if self.reset_deck_progress(deck["file"], user_id):
                removed += 1
        logger.info("Cleared progress for user '%s' from %d decks", user_id, removed)
        return removed

    def prune_progress(self, deck_relative_path, valid_ids):
        progress_dir = self.resolve_path(deck_relative_path).parent / PROGRESS_FOLDER
        if not progress_dir.exists():
            return
        for file in progress_dir.glob("*.json"):
            progress = self._read_json(file)
            cleaned = {key: value for key, value in progress.items() if key in valid_ids}
            file.write_text(json.dumps(cleaned, indent=4), encoding="utf-8")

    def resolve_path(self, path_value: str | Path | None) -> Path | None:
        if not path_value:
            return None
        path = Path(path_value)
        return path if path.is_absolute() else resolve_stored_path(path)

    def _find_by_name(self, name):
        return next((item for item in self.get_all_decks() if item["name"] == name), None)

    def _progress_file(self, deck_relative_path, user_id):
        safe_id = "".join(
            char if char.isalnum() or char in "_-" else "_"
            for char in str(user_id or "guest")
        )
        return (
            self.resolve_path(deck_relative_path).parent
            / PROGRESS_FOLDER
            / f"{safe_id}.json"
        )

    def _import_media(self, deck_relative_path, source_path):
        source = Path(source_path)
        if not source.exists():
            return str(source_path)
        media_dir = self.resolve_path(deck_relative_path).parent / MEDIA_FOLDER
        media_dir.mkdir(parents=True, exist_ok=True)
        target = media_dir / source.name
        counter = 2
        while target.exists() and not self._same_file(source, target):
            target = media_dir / f"{source.stem}_{counter}{source.suffix}"
            counter += 1
        if not target.exists():
            shutil.copy2(source, target)
        return to_stored_path(target)

    @staticmethod
    def _same_file(left, right):
        return left.resolve() == right.resolve()

    @staticmethod
    def _read_json(file):
        return json.loads(file.read_text(encoding="utf-8"))

    @staticmethod
    def _write_deck(file, deck_id, name, cards, moderation=None):
        file.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "id": deck_id,
            "name": name,
            "cards": cards,
        }
        if moderation is not None:
            data["moderation"] = moderation
        file.write_text(json.dumps(data, indent=4), encoding="utf-8")

    def _save_index(self, decks):
        self.index_path.write_text(json.dumps(decks, indent=4), encoding="utf-8")
