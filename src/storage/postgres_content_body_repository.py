"""Relational question/card bodies with local-file media metadata."""

import hashlib
import logging
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import delete, func, select
from sqlalchemy.exc import SQLAlchemyError

from src.storage.database import create_session_factory
from src.storage.postgres_models import (
    FlashcardDeckMetadataModel, FlashcardMediaModel, FlashcardModel,
    MatchingPairModel, MediaModel, QuestionMediaModel, QuestionOptionModel,
    QuizMetadataModel, QuizQuestionModel, ShortAnswerVariantModel,
)
from src.utils.paths import resolve_stored_path, to_stored_path
from src.storage.content_revision import advance_revision
from src.storage.errors import RepositoryUnavailable
from src.storage.media_storage import (
    InvalidMedia, resolve_managed_media, store_media,
)

logger = logging.getLogger(__name__)


class PostgresContentBodyRepository:
    def __init__(
        self, session_factory=None, *, allow_legacy_paths=False, media_root=None,
    ):
        self.session_factory = session_factory or create_session_factory()
        self.allow_legacy_paths = bool(allow_legacy_paths)
        self.media_root = Path(media_root).resolve() if media_root else None

    def import_quiz(self, source: dict) -> bool:
        quiz_id = str(source.get("id", "")).strip()
        questions = source.get("questions")
        if not quiz_id or not isinstance(questions, list):
            return False
        try:
            with self.session_factory.begin() as session:
                locked, media_before, parents_by_media = self._lock_import_envelopes(
                    session, "quiz", quiz_id, source
                )
                metadata = locked.get(("quiz", quiz_id))
                if metadata is None:
                    return False
                previous = self._stored_quiz_canonical(session, quiz_id)
                previous_media = self._stored_media_state(session, "quiz", quiz_id)
                incoming = self._source_quiz_canonical(source)
                changed = previous != incoming
                self._delete_quiz_body(session, quiz_id)
                for position, question in enumerate(questions):
                    if not self._add_question(session, metadata, question, position):
                        raise ValueError(f"Invalid question at position {position}")
                session.flush()
                changed = changed or previous_media != self._stored_media_state(
                    session, "quiz", quiz_id
                )
                self._advance_import_revisions(
                    session, locked, ("quiz", quiz_id), changed,
                    media_before, parents_by_media,
                )
                return True
        except SQLAlchemyError as exc:
            logger.error("Database failed while importing quiz body '%s': %s", quiz_id, exc)
            raise RepositoryUnavailable("Content body storage is unavailable") from exc
        except (OSError, ValueError, TypeError) as exc:
            logger.error("Could not import quiz body '%s': %s", quiz_id, exc)
            return False

    def import_flashcard_deck(self, source: dict) -> bool:
        deck_id = str(source.get("id", "")).strip()
        cards = source.get("cards")
        if not deck_id or not isinstance(cards, list):
            return False
        try:
            with self.session_factory.begin() as session:
                locked, media_before, parents_by_media = self._lock_import_envelopes(
                    session, "flashcard", deck_id, source
                )
                metadata = locked.get(("flashcard", deck_id))
                if metadata is None:
                    return False
                previous = self._stored_deck_canonical(session, deck_id)
                previous_media = self._stored_media_state(session, "flashcard", deck_id)
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
                session.flush()
                changed = changed or previous_media != self._stored_media_state(
                    session, "flashcard", deck_id
                )
                self._advance_import_revisions(
                    session, locked, ("flashcard", deck_id), changed,
                    media_before, parents_by_media,
                )
                return True
        except SQLAlchemyError as exc:
            logger.error("Database failed while importing flashcard body '%s': %s", deck_id, exc)
            raise RepositoryUnavailable("Content body storage is unavailable") from exc
        except (OSError, ValueError, TypeError) as exc:
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
                        MediaModel.id,
                    ).join(
                        MediaModel, MediaModel.id == QuestionMediaModel.media_id,
                    ).where(
                        QuestionMediaModel.quiz_id == str(quiz_id),
                        QuestionMediaModel.role == "image",
                    ).order_by(
                        QuestionMediaModel.question_id, QuestionMediaModel.media_id,
                    )).all()
                    for question_id, media_id in media_rows:
                        media_by_question.setdefault(question_id, media_id)
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
            raise RepositoryUnavailable("Content body storage is unavailable") from exc

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
                        MediaModel.id,
                    ).join(
                        MediaModel, MediaModel.id == FlashcardMediaModel.media_id,
                    ).where(
                        FlashcardMediaModel.deck_id == normalized_id,
                    ).order_by(
                        FlashcardMediaModel.card_id,
                        FlashcardMediaModel.role,
                        FlashcardMediaModel.media_id,
                    )).all()
                    for card_id, role, media_id in media_rows:
                        media_by_card.setdefault(card_id, []).append((role, media_id))
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
            raise RepositoryUnavailable("Content body storage is unavailable") from exc

    def get_practice_package(self, kind: str, content_id: str) -> dict | None:
        """Return a complete offline-practice projection without storage keys."""
        normalized_kind = self._normalize_kind(kind)
        if normalized_kind == "quiz":
            body = self.get_quiz(content_id, include_answers=True)
        else:
            body = self.get_flashcard_deck(content_id)
        if body is None:
            return None
        attachments = self.get_media_descriptors(normalized_kind, content_id)
        by_item: dict[str, list[dict]] = {}
        for attachment in attachments or []:
            by_item.setdefault(attachment["item_id"], []).append({
                "media_id": attachment["media_id"],
                "role": attachment["attachment_role"],
            })
        if normalized_kind == "quiz":
            for question in body.get("questions", []):
                question.pop("image_path", None)
                question["has_image"] = bool(by_item.get(str(question.get("id"))))
                question["media"] = by_item.get(str(question.get("id")), [])
        else:
            for card in body.get("cards", []):
                card.pop("image", None)
                card.pop("audio", None)
                card["media"] = by_item.get(str(card.get("id")), [])
        body["package_type"] = "offline_practice"
        return body

    def get_media_descriptors(self, kind: str, content_id: str) -> list[dict] | None:
        """Describe attached media without exposing its server storage key."""
        normalized_kind = self._normalize_kind(kind)
        model = QuizMetadataModel if normalized_kind == "quiz" else FlashcardDeckMetadataModel
        try:
            with self.session_factory() as session:
                metadata = session.get(model, str(content_id))
                if metadata is None:
                    return None
                if normalized_kind == "quiz":
                    rows = session.execute(select(
                        QuestionMediaModel.question_id,
                        QuestionMediaModel.role,
                        MediaModel,
                    ).join(
                        MediaModel, MediaModel.id == QuestionMediaModel.media_id,
                    ).where(
                        QuestionMediaModel.quiz_id == str(content_id),
                    ).order_by(
                        QuestionMediaModel.question_id,
                        QuestionMediaModel.role,
                        QuestionMediaModel.media_id,
                    )).all()
                else:
                    rows = session.execute(select(
                        FlashcardMediaModel.card_id,
                        FlashcardMediaModel.role,
                        MediaModel,
                    ).join(
                        MediaModel, MediaModel.id == FlashcardMediaModel.media_id,
                    ).where(
                        FlashcardMediaModel.deck_id == str(content_id),
                    ).order_by(
                        FlashcardMediaModel.card_id,
                        FlashcardMediaModel.role,
                        FlashcardMediaModel.media_id,
                    )).all()
                return [self._media_descriptor(
                    normalized_kind, metadata.content_version, str(content_id),
                    item_id, role, media,
                ) for item_id, role, media in rows]
        except SQLAlchemyError as exc:
            logger.error("Could not load media descriptors '%s': %s", content_id, exc)
            raise RepositoryUnavailable("Media metadata is unavailable") from exc

    def get_media_attachment(self, kind: str, content_id: str, media_id: str) -> dict | None:
        """Return one attached media record; storage_key remains repository-internal."""
        normalized_kind = self._normalize_kind(kind)
        try:
            with self.session_factory() as session:
                if normalized_kind == "quiz":
                    row = session.execute(select(
                        QuestionMediaModel.question_id,
                        QuestionMediaModel.role,
                        MediaModel,
                    ).join(
                        MediaModel, MediaModel.id == QuestionMediaModel.media_id,
                    ).where(
                        QuestionMediaModel.quiz_id == str(content_id),
                        QuestionMediaModel.media_id == str(media_id),
                    )).first()
                    metadata = session.get(QuizMetadataModel, str(content_id))
                else:
                    row = session.execute(select(
                        FlashcardMediaModel.card_id,
                        FlashcardMediaModel.role,
                        MediaModel,
                    ).join(
                        MediaModel, MediaModel.id == FlashcardMediaModel.media_id,
                    ).where(
                        FlashcardMediaModel.deck_id == str(content_id),
                        FlashcardMediaModel.media_id == str(media_id),
                    )).first()
                    metadata = session.get(FlashcardDeckMetadataModel, str(content_id))
                if row is None or metadata is None:
                    return None
                item_id, role, media = row
                result = self._media_descriptor(
                    normalized_kind, metadata.content_version, str(content_id),
                    item_id, role, media,
                )
                result["storage_key"] = media.storage_key
                return result
        except SQLAlchemyError as exc:
            logger.error("Could not load media attachment '%s': %s", media_id, exc)
            raise RepositoryUnavailable("Media metadata is unavailable") from exc

    def register_uploaded_media(self, owner_id: str, data: bytes, filename: str) -> dict:
        """Persist uploaded bytes in managed storage and register their opaque ID."""
        stored = store_media(data, filename, root=self.media_root)
        try:
            with self.session_factory.begin() as session:
                session.add(MediaModel(
                    id=stored["media_id"], storage_key=stored["storage_key"],
                    owner_id=str(owner_id), original_filename=stored["original_filename"],
                    media_type=stored["mime_type"].split("/", 1)[0],
                    mime_type=stored["mime_type"], size_bytes=stored["size_bytes"],
                    checksum_sha256=stored["checksum_sha256"],
                ))
            return {key: stored[key] for key in (
                "media_id", "mime_type", "size_bytes", "checksum_sha256"
            )}
        except SQLAlchemyError as exc:
            try:
                resolve_managed_media(
                    stored["storage_key"], root=self.media_root
                ).unlink(missing_ok=True)
            except (OSError, InvalidMedia):
                pass
            raise RepositoryUnavailable("Media storage is unavailable") from exc

    @staticmethod
    def _normalize_kind(kind):
        if kind == "quiz":
            return "quiz"
        if kind in {"flashcard", "deck", "flashcard_deck"}:
            return "flashcard"
        raise ValueError("Unsupported content kind")

    @staticmethod
    def _media_descriptor(kind, content_version, content_id, item_id, role, media):
        return {
            "media_id": media.id,
            "content_id": content_id,
            "content_kind": kind,
            "content_version": int(content_version),
            "item_id": str(item_id),
            "attachment_role": str(role),
            "mime_type": media.mime_type,
            "size_bytes": media.size_bytes,
            "checksum_sha256": media.checksum_sha256,
            "required": False,
        }

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

    def _lock_import_envelopes(self, session, kind, content_id, source):
        """Lock shared media first, then every affected parent in one order."""
        current_ids = self._attached_media_ids(session, kind, content_id)
        incoming_ids = self._source_media_ids(kind, source)
        media_ids = sorted(current_ids | incoming_ids)
        self._lock_media_identities(session, media_ids)

        media_rows = session.scalars(select(MediaModel).where(
            MediaModel.id.in_(media_ids)
        ).order_by(MediaModel.id).with_for_update()).all() if media_ids else []
        media_before = {
            row.id: self._media_download_signature(row) for row in media_rows
        }
        parents_by_media = self._parents_by_media(session, media_ids)
        parent_keys = {(kind, str(content_id))}
        for parents in parents_by_media.values():
            parent_keys.update(parents)

        locked = {}
        quiz_ids = sorted(key[1] for key in parent_keys if key[0] == "quiz")
        deck_ids = sorted(key[1] for key in parent_keys if key[0] == "flashcard")
        if quiz_ids:
            for row in session.scalars(select(QuizMetadataModel).where(
                QuizMetadataModel.id.in_(quiz_ids)
            ).order_by(QuizMetadataModel.id).with_for_update()).all():
                locked[("quiz", row.id)] = row
        if deck_ids:
            for row in session.scalars(select(FlashcardDeckMetadataModel).where(
                FlashcardDeckMetadataModel.id.in_(deck_ids)
            ).order_by(FlashcardDeckMetadataModel.id).with_for_update()).all():
                locked[("flashcard", row.id)] = row
        return locked, media_before, parents_by_media

    @staticmethod
    def _attached_media_ids(session, kind, content_id):
        model = QuestionMediaModel if kind == "quiz" else FlashcardMediaModel
        parent_column = model.quiz_id if kind == "quiz" else model.deck_id
        return set(session.scalars(select(model.media_id).where(
            parent_column == str(content_id)
        )).all())

    @staticmethod
    def _source_media_ids(kind, source):
        values = []
        items = source.get("questions", []) if kind == "quiz" else source.get("cards", [])
        for item in items:
            if kind == "quiz":
                value = item.get("image_path") or item.get("image")
                if value:
                    values.append(value)
            else:
                if item.get("image"):
                    values.append(item["image"])
                audio = item.get("audio")
                if isinstance(audio, dict):
                    values.extend(value for value in audio.values() if value)
                elif audio:
                    values.append(audio)
        result = set()
        for value in values:
            normalized = str(value)
            try:
                result.add(str(UUID(normalized)))
            except ValueError:
                result.add(str(uuid5(
                    NAMESPACE_URL, f"study-buddy-media:{to_stored_path(value)}"
                )))
        return result

    @staticmethod
    def _lock_media_identities(session, media_ids):
        if session.get_bind().dialect.name != "postgresql":
            return
        for media_id in media_ids:
            key = int.from_bytes(
                hashlib.sha256(media_id.encode("utf-8")).digest()[:8],
                byteorder="big", signed=True,
            )
            session.execute(select(func.pg_advisory_xact_lock(key)))

    @staticmethod
    def _parents_by_media(session, media_ids):
        result = {media_id: set() for media_id in media_ids}
        if not media_ids:
            return result
        for media_id, quiz_id in session.execute(select(
            QuestionMediaModel.media_id, QuestionMediaModel.quiz_id,
        ).where(QuestionMediaModel.media_id.in_(media_ids))).all():
            result[media_id].add(("quiz", str(quiz_id)))
        for media_id, deck_id in session.execute(select(
            FlashcardMediaModel.media_id, FlashcardMediaModel.deck_id,
        ).where(FlashcardMediaModel.media_id.in_(media_ids))).all():
            result[media_id].add(("flashcard", str(deck_id)))
        return result

    @staticmethod
    def _media_download_signature(media):
        return media.mime_type, media.size_bytes, media.checksum_sha256

    def _advance_import_revisions(
        self, session, locked, current_key, current_changed,
        media_before, parents_by_media,
    ):
        session.flush()
        media_ids = sorted(media_before)
        current_rows = session.scalars(select(MediaModel).where(
            MediaModel.id.in_(media_ids)
        ).order_by(MediaModel.id)).all() if media_ids else []
        current_signatures = {
            row.id: self._media_download_signature(row) for row in current_rows
        }
        changed_media_ids = {
            media_id for media_id, signature in media_before.items()
            if current_signatures.get(media_id) != signature
        }
        to_advance = {current_key} if current_changed else set()
        for media_id in changed_media_ids:
            to_advance.update(parents_by_media.get(media_id, ()))
        for key in sorted(to_advance, key=lambda value: (value[0] != "quiz", value[1])):
            metadata = locked.get(key)
            if metadata is not None:
                advance_revision(metadata)

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

    def _media(self, session, owner_id, path_value, media_type):
        reference = str(path_value).strip()
        media = session.get(MediaModel, reference)
        if media is not None:
            if media.owner_id != owner_id:
                raise ValueError("Media is not owned by this content owner")
            if not str(media.mime_type or "").startswith(f"{media_type}/"):
                raise ValueError("Media type is incompatible with its attachment role")
            # A database row is not sufficient: only managed keys may be attached
            # through the HTTP editing boundary.
            resolve_managed_media(media.storage_key, root=self.media_root)
            return media
        if not self.allow_legacy_paths:
            raise ValueError("Media references must use an uploaded media ID")

        source = resolve_stored_path(reference)
        stable_id = str(uuid5(NAMESPACE_URL, f"study-buddy-media:{to_stored_path(reference)}"))
        media = session.get(MediaModel, stable_id)
        if source is not None and source.is_file():
            stored = store_media(
                source.read_bytes(), source.name, media_id=stable_id,
                root=self.media_root,
            )
            if media is None:
                media = MediaModel(id=stable_id, owner_id=owner_id)
                session.add(media)
            media.storage_key = stored["storage_key"]
            media.original_filename = stored["original_filename"]
            media.media_type = media_type
            media.mime_type = stored["mime_type"]
            media.size_bytes = stored["size_bytes"]
            media.checksum_sha256 = stored["checksum_sha256"]
        else:
            # Preserve optional missing legacy attachments without retaining or
            # exposing their unmanaged source path.
            suffix = Path(reference).suffix.casefold()
            if media is None:
                media = MediaModel(
                    id=stable_id, storage_key=f"{stable_id}{suffix}", owner_id=owner_id,
                    original_filename=Path(reference).name, media_type=media_type,
                    mime_type="application/octet-stream", size_bytes=None,
                    checksum_sha256=None,
                )
                session.add(media)
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
    def _stored_media_state(session, kind, content_id):
        if kind == "quiz":
            rows = session.execute(select(
                QuestionMediaModel.question_id, QuestionMediaModel.role, MediaModel,
            ).join(MediaModel, MediaModel.id == QuestionMediaModel.media_id).where(
                QuestionMediaModel.quiz_id == content_id,
            )).all()
        else:
            rows = session.execute(select(
                FlashcardMediaModel.card_id, FlashcardMediaModel.role, MediaModel,
            ).join(MediaModel, MediaModel.id == FlashcardMediaModel.media_id).where(
                FlashcardMediaModel.deck_id == content_id,
            )).all()
        return sorted((
            str(item_id), str(role), media.id, media.storage_key,
            media.mime_type, media.size_bytes, media.checksum_sha256,
        ) for item_id, role, media in rows)

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
            "image_path": PostgresContentBodyRepository._canonical_media_reference(
                question.get("image_path") or question.get("image") or ""
            ),
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
            audio = {
                str(role): PostgresContentBodyRepository._canonical_media_reference(value)
                for role, value in sorted(audio.items())
            }
        else:
            audio = PostgresContentBodyRepository._canonical_media_reference(audio)
        return {
            "id": str(card.get("id", "")).strip(),
            "front": str(card.get("front") or ""),
            "back": str(card.get("back") or ""),
            "hint": str(card.get("hint") or ""),
            "description": str(card.get("description") or ""),
            "image": PostgresContentBodyRepository._canonical_media_reference(
                card.get("image") or ""
            ),
            "audio": audio,
        }

    @staticmethod
    def _canonical_media_reference(value):
        normalized = str(value or "")
        if not normalized:
            return ""
        try:
            return str(UUID(normalized))
        except ValueError:
            return str(uuid5(
                NAMESPACE_URL, f"study-buddy-media:{to_stored_path(normalized)}"
            ))

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
            image_path = media.id
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
            media_rows.append((attachment.role, media.id))
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
