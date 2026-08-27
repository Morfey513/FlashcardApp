"""Read-only aggregation of one learner's saved study progress."""

from src.storage.repository_factory import create_flashcard_repository, create_quiz_repository


class ProfileStatisticsController:
    def __init__(
        self, user_id, flashcard_repo=None, quiz_repo=None, user_repository=None,
    ):
        self.user_id = str(user_id)
        self.flashcard_repo = flashcard_repo or create_flashcard_repository(user_repository)
        self.quiz_repo = quiz_repo or create_quiz_repository(user_repository)
        self._stats_cache = {}

    def get_flashcard_stats(self):
        if "flashcards" in self._stats_cache:
            return self._stats_cache["flashcards"]
        if self._load_batched_stats():
            return self._stats_cache["flashcards"]
        collections = []
        total = mastered = 0
        for deck in self.flashcard_repo.get_all_decks():
            details_loader = getattr(self.flashcard_repo, "get_progress_items", None)
            if callable(details_loader):
                details = details_loader(deck["file"], self.user_id)
                rows = [self._item_row(item) for item in details.get("items", [])]
            else:
                cards = self.flashcard_repo.load_deck_cards(deck["file"])
                progress = self.flashcard_repo.get_progress(deck["file"], self.user_id)
                rows = [self._row(card.get("front", ""), progress.get(card.get("id"), {})) for card in cards]
            collection_mastered = sum(row["mastered"] for row in rows)
            collections.append({"name": deck["name"], "mastered": collection_mastered, "total": len(rows), "rows": rows})
            total += len(rows)
            mastered += collection_mastered
        result = {"mastered": mastered, "total": total, "collections": collections}
        self._stats_cache["flashcards"] = result
        return result

    def get_quiz_stats(self):
        if "quizzes" in self._stats_cache:
            return self._stats_cache["quizzes"]
        if self._load_batched_stats():
            return self._stats_cache["quizzes"]
        collections = []
        total = mastered = 0
        for quiz in self.quiz_repo.get_all_quizzes():
            details_loader = getattr(self.quiz_repo, "get_quiz_progress_items", None)
            if callable(details_loader):
                details = details_loader(quiz["file"], self.user_id)
                rows = [self._item_row(item) for item in details.get("items", [])]
            else:
                questions = self.quiz_repo.load_quiz_questions(quiz["file"])
                progress = self.quiz_repo.get_quiz_progress(quiz["file"], self.user_id)
                rows = [self._row(question.get("question", ""), progress.get(question.get("id"), {})) for question in questions]
            collection_mastered = sum(row["mastered"] for row in rows)
            collections.append({"name": quiz["name"], "mastered": collection_mastered, "total": len(rows), "rows": rows})
            total += len(rows)
            mastered += collection_mastered
        result = {"mastered": mastered, "total": total, "collections": collections}
        self._stats_cache["quizzes"] = result
        return result

    def reset_collection(self, collection_type, name):
        repo = self.flashcard_repo if collection_type == "flashcards" else self.quiz_repo
        collections = repo.get_all_decks() if collection_type == "flashcards" else repo.get_all_quizzes()
        item = next((item for item in collections if item["name"] == name), None)
        if not item:
            return False
        if collection_type == "flashcards":
            result = repo.reset_deck_progress(item["file"], self.user_id)
        else:
            result = repo.reset_quiz_progress(item["file"], self.user_id)
        self._stats_cache.pop(collection_type, None)
        return result

    def reset_all(self, collection_type=None):
        """Clear one study mode, or both, without changing account data."""
        removed = 0
        if collection_type in (None, "flashcards"):
            removed += self.flashcard_repo.clear_user_progress(self.user_id)
        if collection_type in (None, "quizzes"):
            removed += self.quiz_repo.clear_user_progress(self.user_id)
        if collection_type is None:
            self._stats_cache.clear()
        else:
            self._stats_cache.pop(collection_type, None)
        return removed

    def _load_batched_stats(self):
        loader = getattr(self.flashcard_repo, "get_progress_summary", None)
        if not callable(loader):
            loader = getattr(self.quiz_repo, "get_progress_summary", None)
        if not callable(loader):
            return False
        response = loader()
        grouped = {"flashcards": [], "quizzes": []}
        for collection in response.get("collections", []):
            key = "quizzes" if collection.get("kind") == "quiz" else "flashcards"
            grouped[key].append({
                "name": collection.get("name", "Untitled"),
                "mastered": int(collection.get("summary", {}).get("mastered", 0)),
                "total": int(collection.get("summary", {}).get("total", 0)),
                "rows": [self._item_row(item) for item in collection.get("items", [])],
            })
        totals = response.get("summary", {})
        for key in ("flashcards", "quizzes"):
            summary = totals.get(key, {})
            self._stats_cache[key] = {
                "mastered": int(summary.get("mastered", 0)),
                "total": int(summary.get("total", 0)),
                "collections": grouped[key],
            }
        return True

    @staticmethod
    def _row(text, progress):
        return {
            "text": str(text or "Untitled"),
            "mastered": bool(progress.get("mastered", False)),
            "correct": int(progress.get("correct", 0)),
            "wrong": int(progress.get("wrong", 0)),
        }

    @staticmethod
    def _item_row(item):
        return {
            "text": str(item.get("text") or "Untitled"),
            "mastered": bool(item.get("mastered", False)),
            "correct": int(item.get("correct", 0)),
            "wrong": int(item.get("wrong", 0)),
        }
