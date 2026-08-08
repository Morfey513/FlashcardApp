# src/question_types.py
from dataclasses import dataclass, field
import random
from collections.abc import Mapping
from typing import List, Optional, Union


MATCH_PROMPT_KEY = "prompt"
MATCH_ANSWER_KEY = "answer"


def normalize_matching_pairs(pairs: object) -> tuple[List[dict], bool]:
    """Convert legacy matching pairs to an explicit prompt/answer schema."""
    if not isinstance(pairs, list):
        raise ValueError("Matching pairs must be a list.")

    normalized: List[dict] = []
    changed = False
    for index, pair in enumerate(pairs, start=1):
        if not isinstance(pair, Mapping):
            raise ValueError(f"Matching pair {index} must be an object.")

        prompt = pair.get(MATCH_PROMPT_KEY, pair.get("1"))
        answer = pair.get(MATCH_ANSWER_KEY, pair.get("2"))
        if prompt is None or answer is None:
            raise ValueError(
                f"Matching pair {index} must contain '{MATCH_PROMPT_KEY}' and "
                f"'{MATCH_ANSWER_KEY}'."
            )

        normalized_pair = {
            MATCH_PROMPT_KEY: str(prompt),
            MATCH_ANSWER_KEY: str(answer),
        }
        normalized.append(normalized_pair)
        changed = changed or dict(pair) != normalized_pair

    return normalized, changed


@dataclass
class BaseQuestion:
    """The foundation for all question types."""
    type: str
    question: str
    id: str = ""
    has_image: bool = False
    image_path: Optional[str] = None

    def shuffle(self):
        """Default: do nothing. Overridden by subclasses."""
        pass


@dataclass
class TextQuestion(BaseQuestion):
    """Handles short_answer, open, and text types."""
    answer: str = ""


@dataclass
class ChoiceQuestion(BaseQuestion):
    """Handles single_choice and multiple_choice."""
    choices: List[str] = field(default_factory=list)
    # The 'answer' could be a single string or a list of strings
    answer: Union[str, List[str]] = field(default_factory=list)
    shuffled_options: List[str] = field(default_factory=list)

    def shuffle(self):
        self.shuffled_options = list(self.choices)
        random.shuffle(self.shuffled_options)


@dataclass
class MatchingQuestion(BaseQuestion):
    """Handles matching and ordering."""
    pairs: List[dict] = field(default_factory=list)
    # For ordering, 'answer' is the correct sequence
    answer: List[str] = field(default_factory=list)
    shuffled_options: List[str] = field(default_factory=list)

    def shuffle(self):
        if self.type == "matching":
            # Shuffle only the right-hand side of the pairs
            self.shuffled_options = [p[MATCH_ANSWER_KEY] for p in self.pairs]
            random.shuffle(self.shuffled_options)
        elif self.type == "ordering":
            # Shuffle the correct answer list to present it out of order
            self.shuffled_options = list(self.answer)
            random.shuffle(self.shuffled_options)


class QuestionFactory:
    """The 'Brain' that decides which class to use based on the JSON 'type'."""

    @staticmethod
    def from_dict(d: dict) -> BaseQuestion:
        q_type = d.get("type", "short_answer")

        # 1. Base attributes for everyone
        base_args = {
            "type": q_type,
            "question": d.get("question", ""),
            "id": d.get("id", ""),
            "has_image": d.get("has_image", False),
            "image_path": d.get("image_path")
        }

        # 2. Dispatch to specific classes
        if q_type in ("single_choice", "multiple_choice"):
            return ChoiceQuestion(
                **base_args,
                choices=d.get("choices", []),
                answer=d.get("answer", [])
            )

        elif q_type in ("matching", "ordering"):
            pairs = d.get("pairs", [])
            if q_type == "matching":
                pairs, _ = normalize_matching_pairs(pairs)
            return MatchingQuestion(
                **base_args,
                pairs=pairs,
                answer=d.get("answer", [])
            )

        # Default for short_answer / open text
        return TextQuestion(
            **base_args,
            answer=d.get("answer", "")
        )
