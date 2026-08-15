"""Local invite-code generation and per-item enrolment management."""

import json
import re
import secrets
from datetime import datetime, timezone

from src.logic.access_control import default_visibility_for_status
from src.storage.moderation_repository import ModerationRepository


class InvitationRepository:
    """Manage codes shared by class-only quizzes and flashcard decks."""

    ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

    def __init__(self, moderation=None):
        self.moderation = moderation or ModerationRepository()

    @staticmethod
    def normalize_code(code):
        return re.sub(r"[^A-Z2-9]", "", str(code).upper())

    def get_invitation(self, relative_path, kind):
        item = self._find_item(relative_path, kind)
        if not item:
            return {}
        data = self._read_data(item)
        return dict(data.get("moderation", {}).get("invite", {}))

    def generate_or_rotate_code(self, relative_path, kind, owner_id):
        """Create a readable unique code; existing enrolments remain valid."""
        item = self._find_item(relative_path, kind)
        if not item or str(item.get("owner_id")) != str(owner_id):
            return False, "Only the content owner can manage its invitation code."
        data = self._read_data(item)
        metadata = self._metadata(data)
        code = self._new_unique_code(item["name"])
        metadata["invite"] = {
            "code": code,
            "created_at": self._now(),
            "rotated_at": self._now() if metadata.get("invite", {}).get("code") else None,
        }
        data["moderation"] = metadata
        self._write_data(item, data)
        return True, code

    def enroll_with_code(self, code, user_id):
        """Enrol a local account in a published class-only item."""
        normalized = self.normalize_code(code)
        if not normalized:
            return False, "Enter an invitation code."
        for item in self.moderation.get_all_content():
            data = self._read_data(item)
            metadata = self._metadata(data)
            invitation = metadata.get("invite", {})
            if self.normalize_code(invitation.get("code", "")) != normalized:
                continue
            if metadata.get("status") != "published" or metadata.get("visibility") != "class_only":
                return False, "This invitation is not currently available."
            enrollment_key = str(user_id)
            enrollments = metadata.setdefault("enrollments", {})
            already_enrolled = enrollment_key in enrollments
            enrollments.setdefault(enrollment_key, {"enrolled_at": self._now()})
            allowed = {str(value) for value in metadata.setdefault("allowed_user_ids", [])}
            allowed.add(enrollment_key)
            metadata["allowed_user_ids"] = sorted(allowed)
            data["moderation"] = metadata
            self._write_data(item, data)
            state = "already enrolled in" if already_enrolled else "enrolled in"
            return True, f"You are {state} {item['name']}."
        return False, "That invitation code was not found."

    def get_owned_classes(self, owner_id, kind="all"):
        """Return active Class-Only items owned by one teacher with roster stats."""
        classes = []
        for item in self.moderation.get_all_content():
            if str(item.get("owner_id")) != str(owner_id):
                continue
            if kind != "all" and item["kind"] != kind:
                continue
            # Draft, pending, rejected, and banned content cannot grant access.
            if item.get("status") != "published" or item.get("visibility") != "class_only":
                continue
            data = self._read_data(item)
            metadata = self._metadata(data)
            roster = []
            for user_id, enrollment in metadata.get("enrollments", {}).items():
                summary = self._progress_summary(item, user_id)
                assessment = self._assessment_summary(item, user_id)
                roster.append({
                    "user_id": str(user_id),
                    "enrolled_at": enrollment.get("enrolled_at", "") if isinstance(enrollment, dict) else "",
                    **summary,
                    **assessment,
                })
            graded = [row["best_grade"] for row in roster if row.get("best_grade") is not None]
            classes.append({
                **item,
                "invite_code": metadata.get("invite", {}).get("code", ""),
                "roster": roster,
                "test_settings": (
                    self.moderation.quizzes.get_test_settings(item["file"])
                    if item["kind"] == "quiz" else {}
                ),
                "class_average": round(sum(graded) / len(graded), 1) if graded else None,
            })
        return classes

    def get_student_attempts(self, relative_path, owner_id, student_id):
        item = self._find_item(relative_path, "quiz")
        if not item or str(item.get("owner_id")) != str(owner_id):
            return []
        return self.moderation.quizzes.get_test_attempts(relative_path, student_id)

    def resolve_attempt(self, relative_path, owner_id, attempt_id, action):
        item = self._find_item(relative_path, "quiz")
        if not item or str(item.get("owner_id")) != str(owner_id):
            return False, "Only the quiz owner can resolve interrupted attempts."
        result = self.moderation.quizzes.resolve_test_attempt(
            relative_path, attempt_id, action, owner_id
        )
        return (True, "Attempt resolved.") if result else (False, "Attempt could not be resolved.")

    def update_answer_review_policy(self, relative_path, owner_id, policy):
        if policy not in {"immediate", "after_due_date", "never"}:
            return False
        item = self._find_item(relative_path, "quiz")
        if not item or str(item.get("owner_id")) != str(owner_id):
            return False
        settings = self.moderation.quizzes.get_test_settings(relative_path)
        settings["answer_review_policy"] = policy
        questions = self.moderation.quizzes.load_quiz_questions(relative_path)
        self.moderation.quizzes.save_quiz_content(relative_path, questions, settings)
        return True

    def get_quiz_analytics(self, relative_path, owner_id):
        item = self._find_item(relative_path, "quiz")
        if not item or str(item.get("owner_id")) != str(owner_id):
            return []
        questions = self.moderation.quizzes.load_quiz_questions(relative_path)
        attempts = [
            attempt for attempt in self.moderation.quizzes.get_test_attempts(relative_path)
            if attempt.get("status") in {"submitted", "timed_out", "marked_zero"}
        ]
        rows = []
        for question in questions:
            answers = [
                answer for attempt in attempts for answer in attempt.get("answers", [])
                if answer.get("question_id") == question.get("id")
                and isinstance(answer.get("is_correct"), bool)
            ]
            correct = sum(1 for answer in answers if answer.get("is_correct") is True)
            rate = round((correct / len(answers)) * 100, 1) if answers else None
            timings = [
                answer.get("response_seconds") for answer in answers
                if isinstance(answer.get("response_seconds"), (int, float))
            ]
            rows.append({
                "question_id": question.get("id"),
                "question": question.get("question", "Untitled question"),
                "correct": correct,
                "responses": len(answers),
                "correct_rate": rate,
                "average_seconds": round(sum(timings) / len(timings), 1) if timings else None,
                "difficulty": (
                    "Not rated" if rate is None else "Easy" if rate >= 75
                    else "Medium" if rate >= 50 else "Hard"
                ),
            })
        return rows

    def remove_enrollment(self, relative_path, kind, owner_id, student_id):
        """Remove one learner from an owner's active Class-Only item."""
        item = self._find_item(relative_path, kind)
        if not item or str(item.get("owner_id")) != str(owner_id):
            return False, "Only the content owner can remove enrolled students."
        data = self._read_data(item)
        metadata = self._metadata(data)
        if metadata.get("status") != "published" or metadata.get("visibility") != "class_only":
            return False, "Access can only be managed for published Class-Only content."
        student_id = str(student_id)
        if student_id not in metadata.get("enrollments", {}):
            return False, "That student is not enrolled in this item."
        metadata["enrollments"].pop(student_id, None)
        metadata["allowed_user_ids"] = [
            value for value in metadata.get("allowed_user_ids", [])
            if str(value) != student_id
        ]
        data["moderation"] = metadata
        self._write_data(item, data)
        return True, "Student access removed."

    def _new_unique_code(self, title):
        prefix = "".join(character for character in title.upper() if character in self.ALPHABET)[:4]
        prefix = prefix or "CLASS"
        existing = {
            self.normalize_code(self._read_data(item).get("moderation", {}).get("invite", {}).get("code", ""))
            for item in self.moderation.get_all_content()
        }
        while True:
            code = f"{prefix}-{''.join(secrets.choice(self.ALPHABET) for _ in range(4))}"
            if self.normalize_code(code) not in existing:
                return code

    def _progress_summary(self, item, user_id):
        repo = self.moderation.flashcards if item["kind"] == "flashcard" else self.moderation.quizzes
        if item["kind"] == "flashcard":
            return repo.get_deck_progress_summary(item["file"], user_id)
        return repo.get_quiz_progress_summary(item["file"], user_id)

    def _assessment_summary(self, item, user_id):
        if item["kind"] != "quiz":
            return {}
        attempts = self.moderation.quizzes.get_test_attempts(item["file"], user_id)
        completed = [
            attempt for attempt in attempts
            if attempt.get("status") in {"submitted", "timed_out", "marked_zero"}
        ]
        charged = [
            attempt for attempt in completed
            if attempt.get("counts_toward_limit", True)
        ]
        grades = [float(attempt.get("percentage", 0) or 0) for attempt in charged]
        unresolved = next((
            attempt for attempt in attempts
            if attempt.get("status") in {"abandoned", "in_progress"}
        ), None)
        latest_completed = completed[0] if completed else None
        if unresolved:
            status = "Abandoned"
        elif latest_completed:
            status = "Finished"
        else:
            status = "Not Started"
        return {
            "best_grade": max(grades) if grades else None,
            "average_grade": round(sum(grades) / len(grades), 1) if grades else None,
            "attempts_used": len(charged),
            "assessment_status": status,
            "unresolved_attempt": unresolved,
            "latest_attempt": latest_completed,
        }

    def _find_item(self, relative_path, kind):
        return next(
            (
                item for item in self.moderation.get_all_content()
                if item["kind"] == kind and item["file"] == relative_path
            ),
            None,
        )

    @staticmethod
    def _read_data(item):
        return json.loads(item["path"].read_text(encoding="utf-8"))

    @staticmethod
    def _write_data(item, data):
        item["path"].write_text(json.dumps(data, indent=4), encoding="utf-8")

    @staticmethod
    def _now():
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _metadata(data):
        metadata = data.setdefault("moderation", {})
        metadata.setdefault("status", "draft")
        metadata.setdefault("visibility", default_visibility_for_status(metadata["status"]))
        metadata.setdefault("allowed_user_ids", [])
        metadata.setdefault("enrollments", {})
        return metadata
