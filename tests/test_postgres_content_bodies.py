from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import sessionmaker

from src.logic.passwords import PasswordHasher
from src.storage.postgres_content_body_repository import PostgresContentBodyRepository
from src.storage.postgres_models import (
    Base, FlashcardDeckMetadataModel, FlashcardModel, MatchingPairModel,
    MediaModel, QuestionOptionModel, QuizMetadataModel, QuizQuestionModel,
    ShortAnswerVariantModel, UserModel,
)
from src.utils.paths import to_stored_path


def _repository(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'content.db'}")
    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    with sessions.begin() as session:
        session.add(UserModel(
            id="teacher-1", username="teacher", display_name="Teacher",
            password_hash=PasswordHasher.hash("password1"), role="teacher",
            status="active", ban_reason="",
        ))
        session.flush()
        common = {
            "owner_id": "teacher-1", "source_owner_id": "teacher-1",
            "lifecycle": "published", "visibility": "public",
        }
        session.add(QuizMetadataModel(
            id="quiz-1", name="Quiz", source_path="quiz.json", **common
        ))
        session.add(FlashcardDeckMetadataModel(
            id="deck-1", name="Deck", source_path="deck.json", **common
        ))
    return PostgresContentBodyRepository(sessions), sessions, engine


def _quiz(image_path=""):
    return {
        "id": "quiz-1", "name": "Quiz", "questions": [
            {"id": "q1", "question": "Planet?", "type": "single_choice",
             "choices": ["Mars", "Saturn"], "answer": "Saturn",
             "image_path": image_path},
            {"id": "q2", "question": "Fruits?", "type": "multiple_choice",
             "choices": ["Apple", "Carrot", "Banana"],
             "answer": ["Apple", "Banana"], "image_path": ""},
            {"id": "q3", "question": "True?", "type": "true_false",
             "answer": True, "image_path": ""},
            {"id": "q4", "question": "Capital?", "type": "short_answer",
             "answer": "Tokyo", "image_path": ""},
            {"id": "q5", "question": "Match", "type": "matching",
             "pairs": [{"prompt": "Spain", "answer": "Madrid"}], "image_path": ""},
            {"id": "q6", "question": "Order", "type": "ordering",
             "answer": ["Red", "Orange"], "image_path": ""},
        ],
    }


def test_quiz_body_import_round_trip_all_types_and_is_idempotent(tmp_path):
    repository, sessions, engine = _repository(tmp_path)
    image = tmp_path / "planet.png"
    image.write_bytes(b"fake-png")
    source = _quiz(str(image))
    assert repository.import_quiz(source)
    assert repository.import_quiz(source)

    loaded = repository.get_quiz("quiz-1")
    assert len(loaded["questions"]) == 6
    assert loaded["questions"][0]["choices"] == ["Mars", "Saturn"]
    assert loaded["questions"][0]["image_path"] == to_stored_path(image)
    assert loaded["questions"][4]["pairs"] == [{"prompt": "Spain", "answer": "Madrid"}]
    assert loaded["questions"][5]["answer"] == ["Red", "Orange"]
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(QuizQuestionModel)) == 6
        assert session.scalar(select(func.count()).select_from(QuestionOptionModel)) == 7
        assert session.scalar(select(func.count()).select_from(MatchingPairModel)) == 1
        assert session.scalar(select(func.count()).select_from(ShortAnswerVariantModel)) == 1
        media = session.scalar(select(MediaModel))
        assert media.size_bytes == len(b"fake-png")
        assert len(media.checksum_sha256) == 64
    engine.dispose()


def test_flashcard_body_round_trip_separate_audio_roles(tmp_path):
    repository, sessions, engine = _repository(tmp_path)
    image = tmp_path / "image.jpg"
    front_audio = tmp_path / "front.mp3"
    back_audio = tmp_path / "back.mp3"
    image.write_bytes(b"image")
    front_audio.write_bytes(b"front")
    back_audio.write_bytes(b"back")
    source = {
        "id": "deck-1", "name": "Deck", "cards": [{
            "id": "card-1", "front": "Question", "back": "Answer",
            "hint": "Hint", "description": "Description", "image": str(image),
            "audio": {"front": str(front_audio), "back": str(back_audio)},
        }],
    }
    assert repository.import_flashcard_deck(source)
    assert repository.import_flashcard_deck(source)
    loaded = repository.get_flashcard_deck("deck-1")
    assert loaded["cards"][0]["front"] == "Question"
    assert loaded["cards"][0]["image"] == to_stored_path(image)
    assert loaded["cards"][0]["audio"] == {
        "front": to_stored_path(front_audio), "back": to_stored_path(back_audio)
    }
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(FlashcardModel)) == 1
        assert session.scalar(select(func.count()).select_from(MediaModel)) == 3
    engine.dispose()


def test_body_import_requires_existing_metadata_and_valid_ids(tmp_path):
    repository, _sessions, engine = _repository(tmp_path)
    assert not repository.import_quiz({"id": "missing", "questions": []})
    assert not repository.import_flashcard_deck({
        "id": "deck-1", "cards": [{"front": "No ID", "back": "Answer"}]
    })
    engine.dispose()


def test_body_import_increments_parent_content_revision(tmp_path):
    repository, sessions, engine = _repository(tmp_path)
    assert repository.import_quiz(_quiz())
    with sessions() as session:
        assert session.scalar(select(QuizMetadataModel).where(QuizMetadataModel.id == "quiz-1")).content_version == 2
    engine.dispose()


def test_unchanged_quiz_import_does_not_increment_revision_and_changes_do(tmp_path):
    repository, sessions, engine = _repository(tmp_path)
    source = _quiz()
    assert repository.import_quiz(source)
    assert repository.import_quiz(source)
    with sessions() as session:
        assert session.scalar(select(QuizMetadataModel).where(QuizMetadataModel.id == "quiz-1")).content_version == 2
    changed = _quiz()
    changed["questions"][0]["question"] = "Changed"
    assert repository.import_quiz(changed)
    with sessions() as session:
        assert session.scalar(select(QuizMetadataModel).where(QuizMetadataModel.id == "quiz-1")).content_version == 3
    engine.dispose()


def test_flashcard_import_revision_is_idempotent_and_media_reference_sensitive(tmp_path):
    repository, sessions, engine = _repository(tmp_path)
    source = {"id": "deck-1", "name": "Deck", "cards": [{
        "id": "card-1", "front": "Q", "back": "A", "image": "one.png",
        "audio": {"front": "one.mp3"},
    }]}
    assert repository.import_flashcard_deck(source)
    assert repository.import_flashcard_deck(source)
    with sessions() as session:
        assert session.scalar(select(FlashcardDeckMetadataModel).where(FlashcardDeckMetadataModel.id == "deck-1")).content_version == 2
    changed = {**source, "cards": [{**source["cards"][0], "image": "two.png"}]}
    assert repository.import_flashcard_deck(changed)
    with sessions() as session:
        assert session.scalar(select(FlashcardDeckMetadataModel).where(FlashcardDeckMetadataModel.id == "deck-1")).content_version == 3
    engine.dispose()
