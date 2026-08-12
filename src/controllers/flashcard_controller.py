# src/controllers/flashcard_controller.py

import logging
from src.logic.flashcard_logic import FlashcardSession
from src.logic.translator import get_translator
from src.storage.flashcard_repository import FlashcardRepository
from src.utils.paths import resolve_stored_path
from src.storage.invitation_repository import InvitationRepository

logger = logging.getLogger(__name__)


class FlashcardController:
    """
    Flashcard controller - single point of contact for UI.
    Handles both study sessions AND deck management.
    """

    def __init__(self, user_id="guest", repo=None, role="student"):
        self.repo = repo or FlashcardRepository()
        self.user_id = user_id or "guest"
        self.role = role
        self.session = None
        self.current_deck_id = ""
        self.translator = get_translator()
        logger.info("FlashcardController initialized")

    # =========================================================
    # DECK MANAGEMENT (For Viewer UI)
    # =========================================================

    def get_deck_names(self):
        """Get list of all deck names for selection UI."""
        return [d["name"] for d in self._visible_decks()]

    def refresh_decks(self):
        """Force refresh of deck list (useful after external changes)."""
        return self._visible_decks()

    def get_deck_summaries(self):
        """Return deck metadata plus the current user's manual mastery progress."""
        summaries = []
        for deck in self._visible_decks():
            summaries.append({
                **deck,
                **self.repo.get_deck_progress_summary(deck["file"], self.user_id),
            })
        return summaries

    def get_deck_summary(self, deck_name):
        """Return the current user's progress summary for a named deck."""
        return next(
            (summary for summary in self.get_deck_summaries() if summary["name"] == deck_name),
            None,
        )

    def is_deck_complete(self, deck_name):
        """A non-empty deck is complete when all of its cards are mastered."""
        summary = self.get_deck_summary(deck_name)
        return bool(
            summary
            and summary["total"] > 0
            and summary["mastered"] == summary["total"]
        )

    def reset_deck_progress(self, deck_name):
        """Reset only the current user's saved progress for the selected deck."""
        deck = next(
            (item for item in self._visible_decks() if item["name"] == deck_name),
            None,
        )
        if not deck:
            logger.warning("Cannot reset progress: deck '%s' was not found", deck_name)
            return False
        reset = self.repo.reset_deck_progress(deck["file"], self.user_id)
        logger.info("Deck progress reset requested for '%s' by user '%s': %s", deck_name, self.user_id, reset)
        return reset

    def clear_guest_progress(self):
        """Clear every guest progress file; authenticated users are never affected."""
        if self.user_id != "guest":
            logger.warning("Guest-progress clear ignored for authenticated user '%s'", self.user_id)
            return 0
        removed = self.repo.clear_user_progress("guest")
        logger.info("Guest deck progress cleared from %d decks", removed)
        return removed

    def clear_all_progress(self):
        """Clear every saved deck progress file belonging to this controller's user."""
        removed = self.repo.clear_user_progress(self.user_id)
        logger.info("All deck progress cleared for user '%s' (%d decks)", self.user_id, removed)
        return removed

    def join_with_code(self, code):
        if self.user_id == "guest":
            return False, "Sign in to join a class with an invitation code."
        return InvitationRepository().enroll_with_code(code, self.user_id)

    # =========================================================
    # STUDY SESSION MANAGEMENT
    # =========================================================

    def start_deck(self, deck_name):
        """
        Start a study session for a specific deck.

        Args:
            deck_name: Name of the deck to study

        Returns:
            First card data dict or None if failed
        """
        logger.info("Starting deck '%s' for user '%s'", deck_name, self.user_id)

        try:
            # Get deck info from repository
            decks = self._visible_decks()
            deck_info = next((d for d in decks if d["name"] == deck_name), None)

            if not deck_info:
                logger.error(f"Deck not found: {deck_name}")
                return None

            # Store current deck path
            if deck_info.get("moderation_status") == "banned":
                logger.warning("Blocked attempt to study banned deck '%s'", deck_name)
                return None
            self.current_deck_id = deck_info["file"]

            # Load cards and progress
            cards = self.repo.load_deck_cards(self.current_deck_id)
            progress = self.repo.get_progress(self.current_deck_id, self.user_id)

            # Create session
            self.session = FlashcardSession(cards, progress)

            # Return first card
            first_card = self.session.get_current_card()
            logger.info(
                "Deck '%s' started: %d total cards, %d cards in learning queue",
                deck_name, len(cards), len(self.session.study_cards),
            )
            return first_card

        except Exception as e:
            logger.exception(f"Failed to start deck: {e}")
            return None

    def process_answer(self, is_correct):
        """
        Mark answer and move to next card.

        Args:
            is_correct: Whether user answered correctly

        Returns:
            Next card data dict or None if session complete
        """
        if not self.session:
            logger.warning("No active session")
            return None

        # Update session progress
        current_card = self.session.get_current_card()
        self.session.mark_answer(is_correct)

        # Save progress to disk immediately
        self.repo.save_deck_progress(
            self.current_deck_id, self.session.progress, self.user_id
        )
        stats = self.session.progress.get(current_card["id"], {})
        logger.info(
            "Recorded %s attempt for flashcard '%s': correct=%d wrong=%d",
            "correct" if is_correct else "wrong",
            current_card["id"], stats.get("correct", 0), stats.get("wrong", 0),
        )

        # Move to next card
        if self.session.next_card():
            return self.session.get_current_card()

        logger.info("Study session complete")
        return None

    def toggle_current_card_mastery(self):
        """
        Toggle mastery status for current card.

        Returns:
            New mastery state (True/False) or None if no session
        """
        if not self.session:
            logger.warning("No active session")
            return None

        # Toggle in session
        current_card = self.session.get_current_card()
        new_state = self.session.toggle_mastery()

        # Save immediately
        self.repo.save_deck_progress(
            self.current_deck_id, self.session.progress, self.user_id
        )

        next_card = None
        if new_state and self.session.next_card():
            next_card = self.session.get_current_card()

        logger.info("Flashcard '%s' mastery changed to %s", current_card["id"], new_state)
        return new_state, next_card

    def end_session(self):
        """Safely terminate the current study session."""
        if self.session:
            logger.info(f"Ending session. Stats: {self.session.session_stats}")

        self.session = None
        self.current_deck_id = ""

    # =========================================================
    # UI HELPER METHODS
    # =========================================================

    def _visible_decks(self):
        """Apply lifecycle/visibility rules while retaining repository APIs."""
        from src.storage.moderation_repository import ModerationRepository
        content = {
            item["file"]: item
            for item in ModerationRepository(flashcards=self.repo).get_content_for_selector(
                self.user_id, self.role
            )
            if item["kind"] == "flashcard"
        }
        return [
            {
                **deck,
                "moderation_status": content[deck["file"]]["status"],
                "moderation_reason": content[deck["file"]].get("review_note", ""),
                "is_owner": str(content[deck["file"]].get("owner_id")) == str(self.user_id),
                "can_view_moderation_reason": (
                    str(content[deck["file"]].get("owner_id")) == str(self.user_id)
                    or self.role == "admin"
                ),
            }
            for deck in self.repo.get_all_decks()
            if deck["file"] in content
        ]

    def get_progress_string(self):
        """Get progress text for UI label."""
        if not self.session:
            return ""
        return self.translator.t("flashcard_viewer.card_counter",
                                 current=self.session.current_index + 1,
                                 total=len(self.session.study_cards))

    def get_session_summary(self):
        if not self.session:
            return ""
        t = self.translator
        stats = self.session.session_stats
        mastered, total_cards = self.session.get_mastery_stats()
        return {
            "known": stats["known"],
            "unknown": stats["unknown"],
            "mastered": mastered,
            "total_cards": total_cards
        }

    def get_absolute_image_path(self, img_path):
        """
        Convert stored image path to absolute Path for UI.

        Args:
            img_path: Relative or absolute image path

        Returns:
            Path object or None
        """
        return resolve_stored_path(img_path)
