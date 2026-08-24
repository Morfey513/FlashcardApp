# src/logic/quiz_logic.py

import random
import logging
import uuid
from src.logic.question_types import QuestionFactory

logger = logging.getLogger(__name__)


class Quiz:
    def __init__(self, questions: list, shuffle=False, max_questions=20, preserve_presentation=False):
        logger.info(f"Initializing Quiz with {len(questions)} questions")

        if not questions:
            self.cards = []
            self.index = 0
            self.score = 0
            return

        # 1. Convert ALL raw data to Question objects first
        all_cards = []
        raw_cards = []
        for q in questions:
            if 'id' not in q or not q['id']:
                q['id'] = str(uuid.uuid4())
            all_cards.append(QuestionFactory.from_dict(q))
            raw_cards.append(q)

        # 2. Shuffle the entire pool FIRST (to get random selection)
        if shuffle and not preserve_presentation:
            logger.debug("Shuffling entire question pool for random selection")
            random.shuffle(all_cards)

        # 3. NOW limit to max_questions
        if max_questions and len(all_cards) > max_questions:
            logger.info(f"Selecting {max_questions} random questions from pool")
            self.cards = all_cards[:max_questions]
            raw_cards = raw_cards[:max_questions]
        else:
            self.cards = all_cards

        # 4. Shuffle internal options for the chosen 20
        for card, raw in zip(self.cards, raw_cards if preserve_presentation else self.cards):
            if preserve_presentation:
                if hasattr(card, "shuffled_options"):
                    if card.type == "matching":
                        card.shuffled_options = list(raw.get("right_options") or [])
                    elif card.type == "ordering":
                        card.shuffled_options = list(raw.get("items") or raw.get("choices") or [])
                    else:
                        card.shuffled_options = list(raw.get("choices") or [])
            else:
                card.shuffle()

        self.index = 0
        self.score = 0

    @property
    def current_card(self):
        """Standardized access for the Controller/UI."""
        if 0 <= self.index < len(self.cards):
            return self.cards[self.index]
        return None

    def get_current(self):
        """Get current question."""
        if 0 <= self.index < len(self.cards):
            return self.cards[self.index]
        return None

    def next(self):
        """Move to next question."""
        if self.index < len(self.cards) - 1:
            self.index += 1
            return True
        return False

    def previous(self):
        """Move to previous question."""
        if self.index > 0:
            self.index -= 1
            return True
        return False

    def jump_to(self, index):
        """Jump to specific question index."""
        if 0 <= index < len(self.cards):
            self.index = index
            return True
        return False

    def reset(self):
        """Reset quiz to beginning."""
        self.index = 0
        self.score = 0
