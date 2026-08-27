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
                previous = self._stored_quiz_canonical(session, quiz_id)
                incoming = self._source_quiz_canonical(source)
                changed = previous != incoming
                self._delete_quiz_body(session, quiz_id)
                for position, question in enumerate(questions):
                    if not self._add_question(session, metadata, question, position):
                        raise ValueError(f"Invalid question at position {position}")
                if changed:
                    metadata.content_version += 1
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
                previous = self._stored_deck_canonical(session, deck_id)
                incoming = self._source_deck_canonical(source)
                changed = previous != incoming
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
                if changed:
                    metadata.content_version += 1
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
                options_by_question = {}
                pairs_by_question = {}
                variants_by_question = {}
                media_by_question = {}
                if rows:
                    for option in session.scalars(select(QuestionOptionModel).where(
                        QuestionOptionModel.quiz_id == str(quiz_id)
                    ).order_by(
                        QuestionOptionModel.question_id, QuestionOptionModel.position
                    )).all():
                        options_by_question.setdefault(option.question_id, []).append(option)
                    for pair in session.scalars(select(MatchingPairModel).where(
                        MatchingPairModel.quiz_id == str(quiz_id)
                    ).order_by(
                        MatchingPairModel.question_id, MatchingPairModel.position
                    )).all():
                        pairs_by_question.setdefault(pair.question_id, []).append(pair)
                    for variant in session.scalars(select(ShortAnswerVariantModel).where(
                        ShortAnswerVariantModel.quiz_id == str(quiz_id)
                    ).order_by(
                        ShortAnswerVariantModel.question_id,
                        ShortAnswerVariantModel.position,
                    )).all():
                        variants_by_question.setdefault(
                            variant.question_id, []
                        ).append(variant)
                    media_rows = session.execute(select(
                        QuestionMediaModel.question_id,
                        MediaModel.storage_key,
                    ).join(
                        MediaModel, MediaModel.id == QuestionMediaModel.media_id,
                    ).where(
                        QuestionMediaModel.quiz_id == str(quiz_id),
                        QuestionMediaModel.role == "image",
                    ).order_by(
                        QuestionMediaModel.question_id, QuestionMediaModel.media_id,
                    )).all()
                    for question_id, storage_key in media_rows:
                        media_by_question.setdefault(question_id, storage_key)
                return {
                    "id": metadata.id, "name": metadata.name,
                    "content_version": metadata.content_version,
                    "questions": [self._question_from_parts(
                        row,
                        options=options_by_question.get(row.question_id, ()),
                        pairs=pairs_by_question.get(row.question_id, ()),
                        variants=variants_by_question.get(row.question_id, ()),
                        image_path=media_by_question.get(row.question_id, ""),
                        include_answers=include_answers,
                    ) for row in rows],
                }
        except SQLAlchemyError as exc:
            logger.error("Could not load quiz body '%s': %s", quiz_id, exc)
            return None

    def get_flashcard_deck(self, deck_id: str) -> dict | None:
        try:
            with self.session_factory() as session:
                normalized_id = str(deck_id)
                metadata = session.get(FlashcardDeckMetadataModel, normalized_id)
                if metadata is None:
                    return None
                rows = session.scalars(select(FlashcardModel).where(
                    FlashcardModel.deck_id == normalized_id
                ).order_by(FlashcardModel.position)).all()
                media_by_card = {}
                if rows:
                    media_rows = session.execute(select(
                        FlashcardMediaModel.card_id,
                        FlashcardMediaModel.role,
                        MediaModel.storage_key,
                    ).join(
                        MediaModel, MediaModel.id == FlashcardMediaModel.media_id,
                    ).where(
                        FlashcardMediaModel.deck_id == normalized_id,
                    ).order_by(
                        FlashcardMediaModel.card_id,
                        FlashcardMediaModel.role,
                        FlashcardMediaModel.media_id,
                    )).all()
                    for card_id, role, storage_key in media_rows:
                        media_by_card.setdefault(card_id, []).append((role, storage_key))
                return {
                    "id": metadata.id, "name": metadata.name,
                    "content_version": metadata.content_version,
                    "cards": [
                        self._card_from_media(row, media_by_card.get(row.card_id, ()))
                        for row in rows
                    ],
                }
        except SQLAlchemyError as exc:
            logger.error("Could not load flashcard body '%s': %s", deck_id, exc)
            return None

    def get_quiz_progress_items(self, quiz_id: str) -> list[dict]:
        """Return only the stable item identity/text needed by progress summaries."""
        try:
            with self.session_factory() as session:
                rows = session.execute(select(
                    QuizQuestionModel.question_id,
                    QuizQuestionModel.question_text,
                ).where(
                    QuizQuestionModel.quiz_id == str(quiz_id)
                ).order_by(QuizQuestionModel.position)).all()
                return [{"id": row.question_id, "text": row.question_text} for row in rows]
        except SQLAlchemyError as exc:
            logger.error("Could not load quiz progress items '%s': %s", quiz_id, exc)
            return []

    def get_flashcard_progress_items(self, deck_id: str) -> list[dict]:
        """Return only the stable item identity/text needed by progress summaries."""
        try:
            with self.session_factory() as session:
                rows = session.execute(select(
                    FlashcardModel.card_id,
                    FlashcardModel.front_text,
                ).where(
                    FlashcardModel.deck_id == str(deck_id)
                ).order_by(FlashcardModel.position)).all()
                return [{"id": row.card_id, "text": row.front_text} for row in rows]
        except SQLAlchemyError as exc:
            logger.error("Could not load flashcard progress items '%s': %s", deck_id, exc)
            return []

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

    def _stored_quiz_canonical(self, session, quiz_id):
        rows = session.scalars(select(QuizQuestionModel).where(
            QuizQuestionModel.quiz_id == quiz_id
        ).order_by(QuizQuestionModel.position)).all()
        return [self._canonical_question(self._question_public(session, row)) for row in rows]

    @staticmethod
    def _source_quiz_canonical(source):
        return [PostgresContentBodyRepository._canonical_question(question) for question in source["questions"]]

    @staticmethod
    def _canonical_question(question):
        result = {
            "id": str(question.get("id", "")).strip(),
            "question": str(question.get("question") or ""),
            "type": str(question.get("type") or "").strip(),
            "answer": question.get("answer"),
            "choices": [str(value) for value in (question.get("choices") or [])],
            "pairs": [
                {"prompt": str(pair.get("prompt") or ""), "answer": str(pair.get("answer") or "")}
                for pair in (question.get("pairs") or [])
            ],
            "image_path": to_stored_path(question.get("image_path") or question.get("image") or ""),
        }
        return result

    def _stored_deck_canonical(self, session, deck_id):
        rows = session.scalars(select(FlashcardModel).where(
            FlashcardModel.deck_id == deck_id
        ).order_by(FlashcardModel.position)).all()
        return [self._canonical_card(self._card_public(session, row)) for row in rows]

    @staticmethod
    def _source_deck_canonical(source):
        return [PostgresContentBodyRepository._canonical_card(card) for card in source["cards"]]

    @staticmethod
    def _canonical_card(card):
        audio = card.get("audio") or {}
        if isinstance(audio, dict):
            audio = {str(role): to_stored_path(value or "") for role, value in sorted(audio.items())}
        else:
            audio = to_stored_path(audio)
        return {
            "id": str(card.get("id", "")).strip(),
            "front": str(card.get("front") or ""),
            "back": str(card.get("back") or ""),
            "hint": str(card.get("hint") or ""),
            "description": str(card.get("description") or ""),
            "image": to_stored_path(card.get("image") or ""),
            "audio": audio,
        }

    @staticmethod
    def _question_public(session, row, *, include_answers: bool = True):
        options = session.scalars(select(QuestionOptionModel).where(
            QuestionOptionModel.quiz_id == row.quiz_id,
            QuestionOptionModel.question_id == row.question_id,
        ).order_by(QuestionOptionModel.position)).all()
        pairs = session.scalars(select(MatchingPairModel).where(
            MatchingPairModel.quiz_id == row.quiz_id,
            MatchingPairModel.question_id == row.question_id,
        ).order_by(MatchingPairModel.position)).all()
        attachment = session.scalar(select(QuestionMediaModel).where(
            QuestionMediaModel.quiz_id == row.quiz_id,
            QuestionMediaModel.question_id == row.question_id,
            QuestionMediaModel.role == "image",
        ))
        image_path = ""
        if attachment:
            media = session.get(MediaModel, attachment.media_id)
            image_path = media.storage_key
        return PostgresContentBodyRepository._question_from_parts(
            row, options=options, pairs=pairs,
            image_path=image_path, include_answers=include_answers,
        )

    @staticmethod
    def _question_from_parts(
        row, *, options=(), pairs=(), variants=(), image_path="",
        include_answers=True,
    ):
        answer = row.correct_answer
        if answer is None and row.question_type == "short_answer" and variants:
            values = [variant.answer_text for variant in variants]
            answer = values[0] if len(values) == 1 else values
        result = {
            "id": row.question_id, "question": row.question_text,
            "type": row.question_type, "answer": answer,
            "has_image": bool(image_path), "image_path": str(image_path or ""),
        }
        if row.question_type in {"single_choice", "multiple_choice"}:
            result["choices"] = [option.option_text for option in options]
        if pairs:
            result["pairs"] = [
                {"prompt": pair.prompt, "answer": pair.answer} for pair in pairs
            ]
            result.pop("answer", None)
        if not include_answers:
            result.pop("answer", None)
            if "pairs" in result:
                result["pairs"] = [{"prompt": pair["prompt"], "answer": None} for pair in result["pairs"]]
        return result

    @staticmethod
    def _card_public(session, row):
        attachments = session.scalars(select(FlashcardMediaModel).where(
            FlashcardMediaModel.deck_id == row.deck_id,
            FlashcardMediaModel.card_id == row.card_id,
        )).all()
        media_rows = []
        for attachment in attachments:
            media = session.get(MediaModel, attachment.media_id)
            media_rows.append((attachment.role, media.storage_key))
        return PostgresContentBodyRepository._card_from_media(row, media_rows)

    @staticmethod
    def _card_from_media(row, media_rows):
        result = {
            "id": row.card_id, "front": row.front_text, "back": row.back_text,
            "hint": row.hint_text, "description": row.description_text,
            "image": "", "audio": {},
        }
        for role, storage_key in media_rows:
            if role == "image":
                result["image"] = storage_key
            elif role == "audio":
                result["audio"] = storage_key
            elif role.startswith("audio_"):
                if not isinstance(result["audio"], dict):
                    result["audio"] = {}
                result["audio"][role.removeprefix("audio_")] = storage_key
        return result
