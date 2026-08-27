# src/controllers/flashcard_editor_controller.py

import logging
import uuid
from pathlib import Path
from src.utils.paths import resolve_stored_path, to_stored_path
from src.logic.access_control import (
    can_create_content,
    can_edit_content,
    is_visibility,
    visibility_submission_status,
)
from src.storage.repository_factory import (
    create_class_repository,
    create_flashcard_repository,
    create_moderation_repository,
)

logger = logging.getLogger(__name__)


class FlashcardEditorController:
    def __init__(
        self, owner_id="legacy", role="teacher", user_repository=None,
        repo=None, moderation=None, class_repository=None,
    ):
        self.repo = repo or create_flashcard_repository(user_repository)
        self.moderation = moderation or create_moderation_repository(
            user_repository, flashcards=self.repo
        )
        self.invitations = class_repository or create_class_repository(
            user_repository, self.moderation
        )
        self.owner_id = str(owner_id)
        self.role = role
        self.current_deck_info = None
        self.current_cards = []
        self.has_unsaved_changes = False
        self._editable_by_name = {}

    def get_deck_names(self):
        return [d["name"] for d in self._editable_decks()]

    def get_deck_entries(self):
        """Editable deck rows with their lifecycle status."""
        metadata = {item["file"]: item for item in self._moderation_items()}
        rows = [
            {**deck, "status": metadata[deck["file"]]["status"],
             "visibility": metadata[deck["file"]].get("visibility", "private")}
            for deck in self._editable_decks()
        ]
        self._editable_by_name = {row["name"]: row for row in rows}
        return rows

    def get_current_moderation(self):
        if not self.current_deck_info:
            return {}
        return next(
            (item for item in self._moderation_items() if item["file"] == self.current_deck_info["file"]),
            {},
        )

    def get_current_invite_code(self):
        if not self.current_deck_info:
            return ""
        return self.invitations.get_invitation(
            self.current_deck_info["file"], "flashcard"
        ).get("code", "")

    def generate_or_rotate_invite_code(self):
        if not self.current_deck_info:
            return False, "Open a deck before generating an invitation code."
        return self.invitations.generate_or_rotate_code(
            self.current_deck_info["file"], "flashcard", self.owner_id
        )

    def get_invite_code(self, name):
        deck = next((item for item in self._editable_decks() if item["name"] == name), None)
        return self.invitations.get_invitation(deck["file"], "flashcard").get("code", "") if deck else ""

    def create_deck(self, name):
        if not can_create_content(self.role):
            return False
        return self.repo.create_deck(
            name, owner_id=self.owner_id, actor_role=self.role
        )

    def load_deck(self, name):
        self.current_deck_info = self._editable_by_name.get(name)
        if self.current_deck_info is None:
            decks = self._editable_decks()
            self.current_deck_info = next((d for d in decks if d["name"] == name), None)
        if self.current_deck_info:
            self.current_cards = self.repo.load_deck_cards(self.current_deck_info["file"])
            self.has_unsaved_changes = False
            return True
        return False

    def save_deck(self, cards, visibility="private"):
        """Save private work or submit public/class-only work for review."""
        try:
            if not self.current_deck_info:
                logger.error("No deck loaded to save")
                return False
            if not is_visibility(visibility):
                return False

            # 1. Ensure IDs exist (crucial for progress tracking)
            for card in cards:
                if not card.get('id'):
                    card['id'] = str(uuid.uuid4())

            # 2. Persist the JSON file
            rel_path = self.current_deck_info["file"]
            saved = self.repo.save_deck_content(
                rel_path, cards, actor_id=self.owner_id, actor_role=self.role
            )
            # Legacy JSON repositories return None after a successful write;
            # HTTP repositories return an explicit boolean.
            if saved is False:
                return False
            status = visibility_submission_status(visibility)
            current = self.current_deck_info
            if current.get("source_path"):
                moderated = self.moderation.update_status(
                    current, status, self.owner_id, visibility=visibility,
                    actor_role=self.role,
                )
            else:
                moderated = self.moderation.set_content_status(
                    rel_path, "flashcard", status, self.owner_id,
                    visibility=visibility, actor_role=self.role,
                )
            if not moderated:
                return False
            current.update({"status": status, "visibility": visibility})

            # 3. Progress Cleanup: Remove mastery data for cards that no longer exist
            valid_ids = {c['id'] for c in cards}
            self.repo.prune_progress(rel_path, valid_ids)

            self.has_unsaved_changes = False
            self.current_cards = cards
            logger.info(f"Saved deck with {len(cards)} cards")
            return True

        except Exception as e:
            logger.error(f"Controller save failed: {e}")
            return False

    # =========================================================
    # CARD CRUD OPERATIONS
    # =========================================================

    def add_card(self, card_data: dict):
        """Add a new card with generated ID."""
        card_data["id"] = str(uuid.uuid4())
        self.current_cards.append(card_data)
        self.has_unsaved_changes = True
        logger.debug(f"Added new card with ID: {card_data['id']}")
        return True

    def update_card(self, index: int, card_data: dict):
        """Update existing card, preserving its ID."""
        if 0 <= index < len(self.current_cards):
            # Preserve original ID
            card_data["id"] = self.current_cards[index].get("id")
            self.current_cards[index] = card_data
            self.has_unsaved_changes = True
            logger.debug(f"Updated card at index {index}")
            return True
        return False

    def duplicate_card(self, index: int):
        """Clone a card with a fresh ID."""
        if 0 <= index < len(self.current_cards):
            new_card = self.current_cards[index].copy()
            new_card["id"] = str(uuid.uuid4())
            new_card["front"] += " (Copy)"
            self.current_cards.append(new_card)
            self.has_unsaved_changes = True
            logger.debug(f"Duplicated card at index {index}")
            return True
        return False

    def remove_card(self, index: int):
        """Remove a card from the deck."""
        if 0 <= index < len(self.current_cards):
            removed = self.current_cards.pop(index)
            self.has_unsaved_changes = True
            logger.debug(f"Removed card: {removed.get('front', 'Unknown')[:30]}")
            return True
        return False

    def delete_deck(self, name):
        """Delete a deck permanently."""
        return self.delete_deck_result(name)["status"] == "deleted"

    def delete_deck_result(self, name):
        """Delete a deck while preserving an HTTP failure category for the UI."""
        deck = self._editable_by_name.get(name)
        if deck is None:
            deck = next((item for item in self._editable_decks() if item["name"] == name), None)
        if not deck or not can_edit_content(
            self.role,
            self._owner_for(deck) == self.owner_id,
        ):
            return {"status": "forbidden", "status_code": None}
        delete_item = getattr(self.repo, "delete_deck_item_result", None)
        if callable(delete_item):
            return delete_item(deck)
        delete_result = getattr(self.repo, "delete_deck_result", None)
        if callable(delete_result):
            return delete_result(name)
        return {
            "status": "deleted" if self.repo.delete_deck_permanently(name) else "failed",
            "status_code": None,
        }

    def copy_deck(self, original_name, new_name):
        """Copy a deck with new IDs."""
        deck = self._editable_by_name.get(original_name)
        if deck is None:
            deck = next(
                (item for item in self._editable_decks() if item["name"] == original_name),
                None,
            )
        if not deck or not can_edit_content(
            self.role,
            self._owner_for(deck) == self.owner_id,
        ):
            return False
        copy_item = getattr(self.repo, "copy_deck_item", None)
        if callable(copy_item):
            return copy_item(
                deck, new_name, self.owner_id, actor_role=self.role
            )
        return self.repo.copy_deck(
            original_name, new_name, self.owner_id, actor_role=self.role
        )

    def get_current_edit_history(self):
        if not self.current_deck_info:
            return []
        return self.repo.get_edit_history(self.current_deck_info["file"])

    def _owner_for(self, deck):
        if deck.get("owner_id") is not None:
            return str(deck["owner_id"])
        item = next(
            (entry for entry in self._moderation_items() if entry["file"] == deck["file"]),
            {},
        )
        return str(item.get("owner_id", ""))

    def _editable_decks(self):
        if self.role not in {"teacher", "admin"}:
            return []
        items = self._moderation_items()
        allowed = {
            item["file"] for item in items
            if item["kind"] == "flashcard"
            and (self.role == "admin" or str(item["owner_id"]) == self.owner_id)
        }
        owned_items = getattr(self.repo, "get_owned_content_items", None)
        if self.role == "teacher" and callable(owned_items):
            rows = [{**item, "file": item["file"]} for item in items]
        else:
            rows = (self.repo.get_owned_decks()
                    if hasattr(self.repo, "get_owned_decks")
                    else self.repo.get_all_decks())
        return [deck for deck in rows if deck["file"] in allowed]

    def _moderation_items(self):
        owned_items = getattr(self.repo, "get_owned_content_items", None)
        if self.role == "teacher" and callable(owned_items):
            return owned_items()
        return self.moderation.get_all_content(kind="flashcard")

    # =========================================================
    # PATH HELPERS (Business Logic)
    # =========================================================

    def process_image_path(self, absolute_path: str) -> str:
        """
        Convert absolute file path to project-relative storage format.

        Args:
            absolute_path: Absolute path from QFileDialog

        Returns:
            Relative path string for JSON storage
        """
        if self.current_deck_info:
            stored_path = self.repo.import_media(
                self.current_deck_info["file"], absolute_path
            )
        else:
            stored_path = to_stored_path(absolute_path)
        logger.debug(f"Converted path: {absolute_path} -> {stored_path}")
        return stored_path

    def process_audio_path(self, absolute_path: str) -> str:
        """
        Convert absolute audio path to project-relative storage format.

        Args:
            absolute_path: Absolute path from QFileDialog

        Returns:
            Relative path string for JSON storage
        """
        # Same logic as image paths
        return self.process_image_path(absolute_path)

    def get_absolute_path(self, stored_path: str) -> Path:
        """
        Convert stored path back to absolute Path for UI display/loading.

        Args:
            stored_path: Path string from JSON (relative or absolute)

        Returns:
            Absolute Path object
        """
        return resolve_stored_path(stored_path)
