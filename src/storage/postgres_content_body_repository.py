"""Relational question/card bodies with local-file media metadata."""

import hashlib
import logging
import mimetypes
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import delete, select
from sqlalchemy.exc import SQLAlchemyError

from src.storage.database import create_session_factory
from src.storage.postgres_models import (
    FlashcardDeckMetadataModel, FlashcardMediaModel, FlashcardModel,
    MatchingPairModel, MediaModel, QuestionMediaModel, QuestionOptionModel,
    QuizMetadataModel, QuizQuestionModel, ShortAnswerVariantModel,
)
from src.utils.paths import resolve_stored_path, to_stored_path

logger = logging.getLogger(__name__)


class PostgresContentBodyRepository:
    def __init__(self, session_factory=None):
        self.session_factory = session_factory or create_session_factory()

    def import_quiz(self, source: dict) -> bool:
        quiz_id = str(source.get("id", "")).strip()
        questions = source.get("questions")
        if not quiz_id or not isinstance(questions, list):
            return False
        try:
            with self.session_factory.begin() as session:
                metadata = session.get(QuizMetadataModel, quiz_id)
                if metadata is None:
                    return False
                self._delete_quiz_body(session, quiz_id)
                for position, question in enumerate(questions):
                    if not self._add_question(session, metadata, question, position):
                        raise ValueError(f"Invalid question at position {position}")
                return True
        except (SQLAlchemyError, OSError, ValueError, TypeError) as exc:
            logger.error("Could not import quiz body '%s': %s", quiz_id, exc)
            return False

    def import_flashcard_deck(self, source: dict) -> bool:
        deck_id = str(source.get("id", "")).strip()
        cards = source.get("cards")
        if not deck_id or not isinstance(cards, list):
            return False
        try:
            with self.session_factory.begin() as session:
                metadata = session.get(FlashcardDeckMetadataModel, deck_id)
                if metadata is None:
                    return False
                self._delete_deck_body(session, deck_id)
                for position, card in enumerate(cards):
                    card_id = str(card.get("id", "")).strip()
                    if not card_id:
                        raise ValueError(f"Missing card ID at position {position}")
                    session.add(FlashcardModel(
                        deck_id=deck_id, card_id=card_id,
                        front_text=str(card.get("front") or ""),
                        back_text=str(card.get("back") or ""),
                        hint_text=str(card.get("hint") or ""),
                        description_text=str(card.get("description") or ""),
                        position=position,
                    ))
                    session.flush()
                    image = str(card.get("image") or "").strip()
                    if image:
                        self._attach_flashcard_media(
                            session, metadata, deck_id, card_id, image, "image"
                        )
                    audio = card.get("audio")
                    if isinstance(audio, dict):
                        for role, path in audio.items():
                            if path:
                                self._attach_flashcard_media(
                                    session, metadata, deck_id, card_id, path,
                                    f"audio_{role}",
                                )
                    elif audio:
                        self._attach_flashcard_media(
                            session, metadata, deck_id, card_id, audio, "audio"
                        )
                return True
        except (SQLAlchemyError, OSError, ValueError, TypeError) as exc:
            logger.error("Could not import flashcard body '%s': %s", deck_id, exc)
            return False

    def get_quiz(self, quiz_id: str, *, include_answers: bool = True) -> dict | None:
        try:
            with self.session_factory() as session:
                metadata = session.get(QuizMetadataModel, str(quiz_id))
                if metadata is None:
                    return None
                rows = session.scalars(select(QuizQuestionModel).where(
                    QuizQuestionModel.quiz_id == str(quiz_id)
                ).order_by(QuizQuestionModel.position)).all()
                return {
                    "id": metadata.id, "name": metadata.name,
                    "questions": [self._question_public(session, row, include_answers=include_answers) for row in rows],
                }
        except SQLAlchemyError as exc:
            logger.error("Could not load quiz body '%s': %s", quiz_id, exc)
            return None

    def get_flashcard_deck(self, deck_id: str) -> dict | None:
        try:
            with self.session_factory() as session:
                metadata = session.get(FlashcardDeckMetadataModel, str(deck_id))
                if metadata is None:
                    return None
                rows = session.scalars(select(FlashcardModel).where(
                    FlashcardModel.deck_id == str(deck_id)
                ).order_by(FlashcardModel.position)).all()
                return {
                    "id": metadata.id, "name": metadata.name,
                    "cards": [self._card_public(session, row) for row in rows],
                }
        except SQLAlchemyError as exc:
            logger.error("Could not load flashcard body '%s': %s", deck_id, exc)
            return None

    def _add_question(self, session, metadata, source, position):
        question_id = str(source.get("id", "")).strip()
        question_type = str(source.get("type", "")).strip()
        if not question_id or question_type not in {
            "single_choice", "multiple_choice", "true_false", "short_answer",
            "matching", "ordering",
        }:
            return False
        correct_answer = source.get("answer")
        if question_type == "matching":
            correct_answer = source.get("pairs") or []
        session.add(QuizQuestionModel(
            quiz_id=metadata.id, question_id=question_id,
            question_text=str(source.get("question") or ""),
            question_type=question_type, position=position,
            correct_answer=correct_answer,
        ))
        session.flush()
        choices = source.get("choices") or []
        if question_type == "ordering":
            choices = source.get("answer") or []
        correct_values = source.get("answer")
        if not isinstance(correct_values, list):
            correct_values = [correct_values]
        for option_position, option in enumerate(choices):
            session.add(QuestionOptionModel(
                quiz_id=metadata.id, question_id=question_id,
                position=option_position, option_text=str(option),
                is_correct=option in correct_values,
            ))
        for pair_position, pair in enumerate(source.get("pairs") or []):
            session.add(MatchingPairModel(
                quiz_id=metadata.id, question_id=question_id,
                position=pair_position, prompt=str(pair.get("prompt") or ""),
                answer=str(pair.get("answer") or ""),
            ))
        if question_type == "short_answer":
            variants = source.get("answer")
            variants = variants if isinstance(variants, list) else [variants]
            for variant_position, answer in enumerate(variants):
                if answer is not None:
                    session.add(ShortAnswerVariantModel(
                        quiz_id=metadata.id, question_id=question_id,
                        position=variant_position, answer_text=str(answer),
                    ))
        image_path = str(source.get("image_path") or "").strip()
        if image_path:
            media = self._media(session, metadata.owner_id, image_path, "image")
            session.add(QuestionMediaModel(
                quiz_id=metadata.id, question_id=question_id,
                media_id=media.id, role="image",
            ))
        return True

    def _attach_flashcard_media(self, session, metadata, deck_id, card_id, path, role):
        media_type = "image" if role == "image" else "audio"
        media = self._media(session, metadata.owner_id, path, media_type)
        session.add(FlashcardMediaModel(
            deck_id=deck_id, card_id=card_id, media_id=media.id, role=role,
        ))

    @staticmethod
    def _media(session, owner_id, path_value, media_type):
        stored = to_stored_path(path_value)
        media_id = str(uuid5(NAMESPACE_URL, f"study-buddy-media:{stored}"))
        media = session.get(MediaModel, media_id)
        if media is None:
            media = MediaModel(id=media_id, storage_key=stored, owner_id=owner_id)
            session.add(media)
        path = resolve_stored_path(path_value)
        if media.owner_id is None and owner_id is not None:
            media.owner_id = owner_id
        media.original_filename = Path(stored).name
        media.media_type = media_type
        media.mime_type = mimetypes.guess_type(stored)[0] or "application/octet-stream"
        if path and path.is_file():
            data = path.read_bytes()
            media.size_bytes = len(data)
            media.checksum_sha256 = hashlib.sha256(data).hexdigest()
        else:
            media.size_bytes = None
            media.checksum_sha256 = None
        session.flush()
        return media

    @staticmethod
    def _delete_quiz_body(session, quiz_id):
        session.execute(delete(QuestionMediaModel).where(QuestionMediaModel.quiz_id == quiz_id))
        session.execute(delete(QuestionOptionModel).where(QuestionOptionModel.quiz_id == quiz_id))
        session.execute(delete(MatchingPairModel).where(MatchingPairModel.quiz_id == quiz_id))
        session.execute(delete(ShortAnswerVariantModel).where(ShortAnswerVariantModel.quiz_id == quiz_id))
        session.execute(delete(QuizQuestionModel).where(QuizQuestionModel.quiz_id == quiz_id))

    @staticmethod
    def _delete_deck_body(session, deck_id):
        session.execute(delete(FlashcardMediaModel).where(FlashcardMediaModel.deck_id == deck_id))
        session.execute(delete(FlashcardModel).where(FlashcardModel.deck_id == deck_id))

    @staticmethod
    def _question_public(session, row, *, include_answers: bool = True):
        result = {
            "id": row.question_id, "question": row.question_text,
            "type": row.question_type, "answer": row.correct_answer,
            "has_image": False, "image_path": "",
        }
        options = session.scalars(select(QuestionOptionModel).where(
            QuestionOptionModel.quiz_id == row.quiz_id,
            QuestionOptionModel.question_id == row.question_id,
        ).order_by(QuestionOptionModel.position)).all()
        if row.question_type in {"single_choice", "multiple_choice"}:
            result["choices"] = [option.option_text for option in options]
        pairs = session.scalars(select(MatchingPairModel).where(
            MatchingPairModel.quiz_id == row.quiz_id,
            MatchingPairModel.question_id == row.question_id,
        ).order_by(MatchingPairModel.position)).all()
        if pairs:
            result["pairs"] = [{"prompt": pair.prompt, "answer": pair.answer} for pair in pairs]
            result.pop("answer", None)
        attachment = session.scalar(select(QuestionMediaModel).where(
            QuestionMediaModel.quiz_id == row.quiz_id,
            QuestionMediaModel.question_id == row.question_id,
            QuestionMediaModel.role == "image",
        ))
        if attachment:
            media = session.get(MediaModel, attachment.media_id)
            result["has_image"] = True
            result["image_path"] = media.storage_key
        if not include_answers:
            result.pop("answer", None)
            if "pairs" in result:
                result["pairs"] = [{"prompt": pair["prompt"], "answer": None} for pair in result["pairs"]]
        return result

    @staticmethod
    def _card_public(session, row):
        result = {
            "id": row.card_id, "front": row.front_text, "back": row.back_text,
            "hint": row.hint_text, "description": row.description_text,
            "image": "", "audio": {},
        }
        attachments = session.scalars(select(FlashcardMediaModel).where(
            FlashcardMediaModel.deck_id == row.deck_id,
            FlashcardMediaModel.card_id == row.card_id,
        )).all()
        for attachment in attachments:
            media = session.get(MediaModel, attachment.media_id)
            if attachment.role == "image":
                result["image"] = media.storage_key
            elif attachment.role == "audio":
                result["audio"] = media.storage_key
            elif attachment.role.startswith("audio_"):
                if not isinstance(result["audio"], dict):
                    result["audio"] = {}
                result["audio"][attachment.role.removeprefix("audio_")] = media.storage_key
        return result
