"""Read-only aggregation of one learner's saved study progress."""

from src.storage.flashcard_repository import FlashcardRepository
from src.storage.quiz_repository import QuizRepository


class ProfileStatisticsController:
    def __init__(self, user_id, flashcard_repo=None, quiz_repo=None):
        self.user_id = str(user_id)
        self.flashcard_repo = flashcard_repo or FlashcardRepository()
        self.quiz_repo = quiz_repo or QuizRepository()

    def get_flashcard_stats(self):
        collections = []
        total = mastered = 0
        for deck in self.flashcard_repo.get_all_decks():
            cards = self.flashcard_repo.load_deck_cards(deck["file"])
            progress = self.flashcard_repo.get_progress(deck["file"], self.user_id)
            rows = [self._row(card.get("front", ""), progress.get(card.get("id"), {})) for card in cards]
            collection_mastered = sum(row["mastered"] for row in rows)
            collections.append({"name": deck["name"], "mastered": collection_mastered, "total": len(rows), "rows": rows})
            total += len(rows)
            mastered += collection_mastered
        return {"mastered": mastered, "total": total, "collections": collections}

    def get_quiz_stats(self):
        collections = []
        total = mastered = 0
        for quiz in self.quiz_repo.get_all_quizzes():
            questions = self.quiz_repo.load_quiz_questions(quiz["file"])
            progress = self.quiz_repo.get_quiz_progress(quiz["file"], self.user_id)
            rows = [self._row(question.get("question", ""), progress.get(question.get("id"), {})) for question in questions]
            collection_mastered = sum(row["mastered"] for row in rows)
            collections.append({"name": quiz["name"], "mastered": collection_mastered, "total": len(rows), "rows": rows})
            total += len(rows)
            mastered += collection_mastered
        return {"mastered": mastered, "total": total, "collections": collections}

    def reset_collection(self, collection_type, name):
        repo = self.flashcard_repo if collection_type == "flashcards" else self.quiz_repo
        collections = repo.get_all_decks() if collection_type == "flashcards" else repo.get_all_quizzes()
        item = next((item for item in collections if item["name"] == name), None)
        if not item:
            return False
        if collection_type == "flashcards":
            return repo.reset_deck_progress(item["file"], self.user_id)
        return repo.reset_quiz_progress(item["file"], self.user_id)

    def reset_all(self, collection_type=None):
        """Clear one study mode, or both, without changing account data."""
        removed = 0
        if collection_type in (None, "flashcards"):
            removed += self.flashcard_repo.clear_user_progress(self.user_id)
        if collection_type in (None, "quizzes"):
            removed += self.quiz_repo.clear_user_progress(self.user_id)
        return removed

    @staticmethod
    def _row(text, progress):
        return {
            "text": str(text or "Untitled"),
            "mastered": bool(progress.get("mastered", False)),
            "correct": int(progress.get("correct", 0)),
            "wrong": int(progress.get("wrong", 0)),
        }
