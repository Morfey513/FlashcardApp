"""Dedicated PostgreSQL fixtures used only by visible GUI test runs."""
from __future__ import annotations

import os
import uuid
from dataclasses import dataclass

from sqlalchemy import create_engine, delete
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker


TEST_DATABASE = "study_buddy_test"


@dataclass(frozen=True)
class Account:
    role: str
    login: str
    password: str
    user_id: str


class GuiFixtures:
    """Small deterministic accounts/content; cleanup owns only this prefix.

    The default visible-content set deliberately contains one public quiz and
    one public deck.  Qt exposes the corresponding QListWidget rows as
    anonymous UIA ListItems, so a smoke run cannot safely distinguish multiple
    visible quizzes by name without a production accessibility change.
    Assessment fixtures are therefore opt-in for a dedicated assessment flow.
    """
    def __init__(self, database_url: str, prefix: str, *, include_assessment: bool = False):
        parsed = make_url(database_url)
        if parsed.get_backend_name() != "postgresql" or parsed.database != TEST_DATABASE:
            raise ValueError("STUDY_BUDDY_TEST_DATABASE_URL must target study_buddy_test")
        self.prefix = prefix
        self.include_assessment = include_assessment
        self.engine = create_engine(database_url, pool_pre_ping=True)
        self.sessions = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.accounts: dict[str, Account] = {}
        self.quiz_id = f"{prefix}-quiz"
        self.public_quiz_id = f"{prefix}-public-quiz"
        self.deck_id = f"{prefix}-deck"
        self.class_id = f"{prefix}-class"
        self.assessment_quiz_name = f"{prefix} Assessment Quiz"
        self.public_quiz_name = f"{prefix} Public Quiz"
        self.public_deck_name = f"{prefix} Public Deck"

    def seed(self) -> dict[str, Account]:
        from src.logic.passwords import PasswordHasher
        from src.storage.postgres_content_body_repository import PostgresContentBodyRepository
        from src.storage.postgres_content_metadata_repository import PostgresContentMetadataRepository
        from src.storage.postgres_models import ClassMemberModel, ClassModel, ClassQuizModel, UserModel
        roles = ("student", "teacher", "admin")
        for role in roles:
            login = f"{self.prefix}-{role}"
            self.accounts[role] = Account(role, login, "GuiRunnerPassword9!", f"{self.prefix}-{role}")
        with self.sessions.begin() as session:
            for account in self.accounts.values():
                session.add(UserModel(id=account.user_id, username=account.login, email=f"{account.login}@gui.invalid", password_hash=PasswordHasher.hash(account.password), display_name=f"GUI {account.role}", role=account.role, status="active"))
            session.flush()
            session.add(ClassModel(id=self.class_id, owner_id=self.accounts["teacher"].user_id, name=f"{self.prefix} class", status="active"))
            # The membership uses an explicitly assigned class id, but PostgreSQL
            # still needs the parent insert flushed before the dependent row.
            session.flush()
            session.add(ClassMemberModel(class_id=self.class_id, user_id=self.accounts["student"].user_id, status="active"))
        metadata = PostgresContentMetadataRepository(self.sessions)
        bodies = PostgresContentBodyRepository(self.sessions)
        teacher = self.accounts["teacher"].user_id
        if self.include_assessment:
            metadata.import_quiz({"id": self.quiz_id, "name": self.assessment_quiz_name, "moderation": {"owner_id": teacher, "status": "published", "visibility": "class_only"}, "test_settings": {"attempt_limit": 2}}, f"gui://{self.quiz_id}")
            bodies.import_quiz({"id": self.quiz_id, "name": f"{self.prefix} Quiz", "questions": [
                {"id": "single", "question": "GUI single", "type": "single_choice", "options": ["one", "two"], "answer": "one"},
                {"id": "multiple", "question": "GUI multiple", "type": "multiple_choice", "options": ["one", "two"], "answer": ["one"]},
                {"id": "boolean", "question": "GUI true false", "type": "true_false", "answer": True},
                {"id": "short", "question": "GUI short", "type": "short_answer", "answer": "one"},
                {"id": "matching", "question": "GUI matching", "type": "matching", "pairs": [{"prompt": "one", "answer": "1"}, {"prompt": "two", "answer": "2"}]},
                {"id": "ordering", "question": "GUI ordering", "type": "ordering", "items": ["one", "two"], "answer": ["one", "two"]},
            ]})
        # Public fixture covers guest/student practice in the default smoke
        # environment.  A class-only fixture is seeded only for an explicit
        # assessment scenario, so the anonymous UIA list has one valid row.
        metadata.import_quiz({"id": self.public_quiz_id, "name": self.public_quiz_name, "moderation": {"owner_id": teacher, "status": "published", "visibility": "public"}}, f"gui://{self.public_quiz_id}")
        bodies.import_quiz({"id": self.public_quiz_id, "name": self.public_quiz_name, "questions": [
            {"id": "single", "question": "GUI single", "type": "single_choice", "options": ["one", "two"], "answer": "one"},
            {"id": "multiple", "question": "GUI multiple", "type": "multiple_choice", "options": ["one", "two"], "answer": ["one"]},
            {"id": "boolean", "question": "GUI true false", "type": "true_false", "answer": True},
            {"id": "short", "question": "GUI short", "type": "short_answer", "answer": "one"},
            {"id": "matching", "question": "GUI matching", "type": "matching", "pairs": [{"prompt": "one", "answer": "1"}, {"prompt": "two", "answer": "2"}]},
            {"id": "ordering", "question": "GUI ordering", "type": "ordering", "items": ["one", "two"], "answer": ["one", "two"]},
        ]})
        metadata.import_flashcard_deck({"id": self.deck_id, "name": self.public_deck_name, "moderation": {"owner_id": teacher, "status": "published", "visibility": "public"}}, f"gui://{self.deck_id}")
        bodies.import_flashcard_deck({"id": self.deck_id, "name": self.public_deck_name, "cards": [
            {"id": "card-1", "front": "GUI front", "back": "GUI back", "hint": "GUI hint"},
            {"id": "card-2", "front": "GUI front two", "back": "GUI back two"},
        ]})
        if self.include_assessment:
            with self.sessions.begin() as session:
                session.add(ClassQuizModel(class_id=self.class_id, quiz_id=self.quiz_id))
        return self.accounts

    def cleanup(self) -> None:
        from src.storage.postgres_models import (ClassInvitationModel, ClassMemberModel, ClassModel, ClassQuizModel, UserModel, UserSessionModel,
            QuizAttemptAnswerModel, QuizAttemptModel, QuizAttemptQuestionModel, QuizMetadataModel, QuizQuestionModel,
            FlashcardDeckMetadataModel, FlashcardModel)
        try:
            with self.sessions.begin() as session:
                ids = [item.user_id for item in self.accounts.values()]
                attempts = session.query(QuizAttemptModel.id).filter(QuizAttemptModel.user_id.in_(ids)).statement
                session.execute(delete(UserSessionModel).where(UserSessionModel.user_id.in_(ids)))
                session.execute(delete(QuizAttemptAnswerModel).where(QuizAttemptAnswerModel.attempt_id.in_(attempts)))
                session.execute(delete(QuizAttemptQuestionModel).where(QuizAttemptQuestionModel.attempt_id.in_(attempts)))
                session.execute(delete(QuizAttemptModel).where(QuizAttemptModel.user_id.in_(ids)))
                session.execute(delete(ClassInvitationModel).where(ClassInvitationModel.class_id == self.class_id))
                session.execute(delete(ClassMemberModel).where(ClassMemberModel.class_id == self.class_id))
                session.execute(delete(ClassQuizModel).where(ClassQuizModel.class_id == self.class_id))
                session.execute(delete(ClassModel).where(ClassModel.id == self.class_id))
                session.execute(delete(QuizQuestionModel).where(QuizQuestionModel.quiz_id.in_([self.quiz_id, self.public_quiz_id])))
                session.execute(delete(QuizMetadataModel).where(QuizMetadataModel.id.in_([self.quiz_id, self.public_quiz_id])))
                session.execute(delete(FlashcardModel).where(FlashcardModel.deck_id == self.deck_id))
                session.execute(delete(FlashcardDeckMetadataModel).where(FlashcardDeckMetadataModel.id == self.deck_id))
                session.execute(delete(UserModel).where(UserModel.id.in_(ids)))
        finally:
            self.engine.dispose()
