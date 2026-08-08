import random

from src.config import (
    FLASHCARD_MAX_REQUEUES_PER_CARD,
    FLASHCARD_REQUEUE_DISTANCE,
    FLASHCARD_SESSION_CARD_LIMIT,
    MASTERY_REQUIRED_SCORE,
    MASTERY_WRONG_PENALTY,
)


class FlashcardSession:
    """A bounded, adaptive learning queue for one flashcard deck."""

    def __init__(
        self,
        cards,
        progress_data,
        session_limit=FLASHCARD_SESSION_CARD_LIMIT,
        rng=None,
    ):
        self.all_cards = cards
        self.progress = progress_data
        self.session_limit = session_limit
        self.rng = rng or random.Random()
        self.study_cards = self._build_study_queue()
        self.requeue_counts = {}

        self.current_index = 0
        self.session_stats = {"known": 0, "unknown": 0}

    def _build_study_queue(self):
        """Select up to one session's worth of unique, non-mastered cards."""
        candidates = [
            card
            for card in self.all_cards
            if not self.progress.get(card.get("id"), {}).get("mastered", False)
        ]

        if len(candidates) <= self.session_limit:
            queue = list(candidates)
            self.rng.shuffle(queue)
            return queue

        selected = []
        pool = list(candidates)
        while pool and len(selected) < self.session_limit:
            weights = [self._selection_weight(card) for card in pool]
            card = self.rng.choices(pool, weights=weights, k=1)[0]
            selected.append(card)
            pool.remove(card)
        # Selection decides which cards need attention; shuffle decides their
        # presentation order, matching the quiz session experience.
        self.rng.shuffle(selected)
        return selected

    def _selection_weight(self, card):
        """Favor weaker cards while preserving a chance for every unmastered card."""
        progress = self.progress.get(card.get("id"), {})
        correct = progress.get("correct", 0)
        wrong = progress.get("wrong", 0)
        mastery_score = correct - wrong * MASTERY_WRONG_PENALTY
        return max(1.0, 1.0 + (MASTERY_REQUIRED_SCORE - mastery_score))

    def get_current_card(self):
        """Return current card with stats and manual-mastery eligibility."""
        if 0 <= self.current_index < len(self.study_cards):
            card = self.study_cards[self.current_index].copy()
            card_id = card.get("id")
            stats = self._ensure_card_progress(card_id)
            card["stats"] = stats
            card["can_master"] = self.is_eligible_for_mastery(card_id)
            return card
        return None

    def mark_answer(self, is_correct):
        card = self.study_cards[self.current_index]
        card_id = card.get("id")
        card_progress = self._ensure_card_progress(card_id)

        if is_correct:
            card_progress["correct"] += 1
            self.session_stats["known"] += 1
        else:
            card_progress["wrong"] += 1
            self.session_stats["unknown"] += 1
            self._requeue_after_mistake(card)

    def _requeue_after_mistake(self, card):
        """Give an incorrect card one delayed retry in the current session."""
        card_id = card.get("id")
        count = self.requeue_counts.get(card_id, 0)
        if count >= FLASHCARD_MAX_REQUEUES_PER_CARD:
            return

        insert_at = min(
            self.current_index + FLASHCARD_REQUEUE_DISTANCE + 1,
            len(self.study_cards),
        )
        self.study_cards.insert(insert_at, card)
        self.requeue_counts[card_id] = count + 1

    def toggle_mastery(self):
        """Toggle 'mastered' for the current card and drop any queued retry."""
        card = self.study_cards[self.current_index]
        card_id = card.get("id")
        card_progress = self._ensure_card_progress(card_id)
        new_state = not card_progress["mastered"]
        card_progress["mastered"] = new_state

        if new_state:
            remaining = self.study_cards[self.current_index + 1:]
            self.study_cards = (
                self.study_cards[:self.current_index + 1]
                + [queued for queued in remaining if queued.get("id") != card_id]
            )
        return new_state

    def _ensure_card_progress(self, card_id):
        """Fill missing fields in legacy or partially saved progress records."""
        card_progress = self.progress.setdefault(card_id, {})
        card_progress.setdefault("correct", 0)
        card_progress.setdefault("wrong", 0)
        card_progress.setdefault("mastered", False)
        return card_progress

    def is_eligible_for_mastery(self, card_id):
        """Use correct answers minus a weighted penalty for wrong answers."""
        progress = self.progress.get(card_id, {})
        correct = progress.get("correct", 0)
        wrong = progress.get("wrong", 0)
        return correct - wrong * MASTERY_WRONG_PENALTY >= MASTERY_REQUIRED_SCORE

    def is_mastered(self, card_id):
        return self.progress.get(card_id, {}).get("mastered", False)

    def get_mastery_stats(self):
        mastered_count = sum(
            self.progress.get(card.get("id"), {}).get("mastered", False)
            for card in self.all_cards
        )
        return mastered_count, len(self.all_cards)

    def next_card(self):
        self.current_index += 1
        return self.current_index < len(self.study_cards)
