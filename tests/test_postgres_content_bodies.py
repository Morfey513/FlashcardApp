from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import sessionmaker

from src.logic.passwords import PasswordHasher
from src.storage.postgres_content_body_repository import PostgresContentBodyRepository
from src.storage.postgres_models import (
    Base, FlashcardDeckMetadataModel, FlashcardMediaModel, FlashcardModel, MatchingPairModel,
    MediaModel, QuestionOptionModel, QuizMetadataModel, QuizQuestionModel,
    ShortAnswerVariantModel, UserModel,
)
from src.utils.paths import to_stored_path

PNG = b"\x89PNG\r\n\x1a\n"
MP3 = b"ID3"


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
    return PostgresContentBodyRepository(
        sessions, allow_legacy_paths=True, media_root=tmp_path / "managed-media"
    ), sessions, engine


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
    image.write_bytes(PNG + b"fake-png")
    source = _quiz(str(image))
    assert repository.import_quiz(source)
    assert repository.import_quiz(source)

    loaded = repository.get_quiz("quiz-1")
    assert len(loaded["questions"]) == 6
    assert [row["id"] for row in loaded["questions"]] == [f"q{i}" for i in range(1, 7)]
    assert loaded["questions"][0]["choices"] == ["Mars", "Saturn"]
    assert loaded["questions"][0]["answer"] == "Saturn"
    assert loaded["questions"][1]["choices"] == ["Apple", "Carrot", "Banana"]
    assert loaded["questions"][1]["answer"] == ["Apple", "Banana"]
    assert loaded["questions"][2]["answer"] is True
    assert loaded["questions"][3]["answer"] == "Tokyo"
    assert loaded["questions"][0]["image_path"]
    assert loaded["questions"][0]["image_path"] != to_stored_path(image)
    assert loaded["questions"][4]["pairs"] == [{"prompt": "Spain", "answer": "Madrid"}]
    assert loaded["questions"][5]["answer"] == ["Red", "Orange"]
    redacted = repository.get_quiz("quiz-1", include_answers=False)
    assert all("answer" not in row for row in redacted["questions"])
    assert redacted["questions"][4]["pairs"] == [
        {"prompt": "Spain", "answer": None},
    ]
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(QuizQuestionModel)) == 6
        assert session.scalar(select(func.count()).select_from(QuestionOptionModel)) == 7
        assert session.scalar(select(func.count()).select_from(MatchingPairModel)) == 1
        assert session.scalar(select(func.count()).select_from(ShortAnswerVariantModel)) == 1
        media = session.scalar(select(MediaModel))
        assert media.size_bytes == len(PNG + b"fake-png")
        assert len(media.checksum_sha256) == 64
    engine.dispose()


def test_flashcard_body_round_trip_separate_audio_roles(tmp_path):
    repository, sessions, engine = _repository(tmp_path)
    image = tmp_path / "image.jpg"
    front_audio = tmp_path / "front.mp3"
    back_audio = tmp_path / "back.mp3"
    image.write_bytes(b"\xff\xd8\xff" + b"image")
    front_audio.write_bytes(MP3 + b"front")
    back_audio.write_bytes(MP3 + b"back")
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
    assert loaded["cards"][0]["image"]
    assert loaded["cards"][0]["audio"]["front"]
    assert loaded["cards"][0]["audio"]["back"]
    package = repository.get_practice_package("flashcard", "deck-1")
    descriptors = repository.get_media_descriptors("flashcard", "deck-1")
    assert "image" not in package["cards"][0]
    assert "audio" not in package["cards"][0]
    assert {item["role"] for item in package["cards"][0]["media"]} == {
        "image", "audio_front", "audio_back",
    }
    assert all("storage_key" not in item for item in descriptors)
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(FlashcardModel)) == 1
        assert session.scalar(select(func.count()).select_from(MediaModel)) == 3
    engine.dispose()


def test_progress_item_projections_use_one_query_without_loading_full_bodies(tmp_path):
    repository, _sessions, engine = _repository(tmp_path)
    assert repository.import_quiz(_quiz())
    assert repository.import_flashcard_deck({
        "id": "deck-1", "name": "Deck", "cards": [
            {"id": "card-1", "front": "Front 1", "back": "Back 1"},
            {"id": "card-2", "front": "Front 2", "back": "Back 2"},
        ],
    })
    statements = []

    def record_statement(_connection, _cursor, statement, _parameters, _context, _many):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", record_statement)
    try:
        assert repository.get_quiz_progress_items("quiz-1") == [
            {"id": f"q{index}", "text": text}
            for index, text in enumerate(
                ["Planet?", "Fruits?", "True?", "Capital?", "Match", "Order"], 1
            )
        ]
        assert len(statements) == 1
        statements.clear()
        assert len(repository.get_quiz("quiz-1", include_answers=False)["questions"]) == 6
        assert len(statements) <= 6
        statements.clear()
        assert repository.get_flashcard_progress_items("deck-1") == [
            {"id": "card-1", "text": "Front 1"},
            {"id": "card-2", "text": "Front 2"},
        ]
        assert len(statements) == 1
        statements.clear()
        assert len(repository.get_flashcard_deck("deck-1")["cards"]) == 2
        assert len(statements) <= 3
    finally:
        event.remove(engine, "before_cursor_execute", record_statement)
        engine.dispose()


def test_quiz_body_query_count_is_bounded_for_one_and_one_hundred_questions(tmp_path):
    repository, _sessions, engine = _repository(tmp_path)

    def source(count):
        return {
            "id": "quiz-1", "name": "Quiz", "questions": [{
                "id": f"q{position}", "question": f"Question {position}",
                "type": "single_choice", "choices": ["A", "B", "C"],
                "answer": "B", "image_path": "",
            } for position in range(count)],
        }

    statements = []
    event.listen(
        engine, "before_cursor_execute",
        lambda _connection, _cursor, statement, _params, _context, _many:
            statements.append(statement),
    )
    try:
        assert repository.import_quiz(source(1))
        statements.clear()
        assert len(repository.get_quiz("quiz-1")["questions"]) == 1
        one_question_count = len(statements)

        assert repository.import_quiz(source(100))
        statements.clear()
        loaded = repository.get_quiz("quiz-1")
        hundred_question_count = len(statements)

        assert len(loaded["questions"]) == 100
        assert [row["id"] for row in loaded["questions"]] == [
            f"q{position}" for position in range(100)
        ]
        assert one_question_count <= 6
        assert hundred_question_count <= 6
        assert hundred_question_count == one_question_count
    finally:
        engine.dispose()


def test_empty_quiz_body_uses_only_fixed_parent_queries(tmp_path):
    repository, _sessions, engine = _repository(tmp_path)
    assert repository.import_quiz({"id": "quiz-1", "name": "Quiz", "questions": []})
    statements = []
    event.listen(
        engine, "before_cursor_execute",
        lambda _connection, _cursor, statement, _params, _context, _many:
            statements.append(statement),
    )
    try:
        assert repository.get_quiz("quiz-1")["questions"] == []
        assert len(statements) <= 2
    finally:
        engine.dispose()


def test_flashcard_body_query_count_is_bounded_with_media(tmp_path):
    repository, _sessions, engine = _repository(tmp_path)

    def source(count):
        return {
            "id": "deck-1", "name": "Deck", "cards": [{
                "id": f"card-{position:03d}", "front": f"Front {position}",
                "back": f"Back {position}", "hint": f"Hint {position}",
                "description": f"Description {position}",
                "image": f"images/{position}.png",
                "audio": {
                    "front": f"audio/{position}-front.mp3",
                    "back": f"audio/{position}-back.mp3",
                },
            } for position in range(count)],
        }

    statements = []
    listener = lambda *_args: statements.append(1)
    event.listen(engine, "before_cursor_execute", listener)
    try:
        assert repository.import_flashcard_deck(source(1))
        statements.clear()
        one = repository.get_flashcard_deck("deck-1")
        one_card_count = len(statements)

        assert repository.import_flashcard_deck(source(100))
        statements.clear()
        hundred = repository.get_flashcard_deck("deck-1")
        hundred_card_count = len(statements)

        assert len(one["cards"]) == 1
        assert len(hundred["cards"]) == 100
        assert [row["id"] for row in hundred["cards"]] == [
            f"card-{position:03d}" for position in range(100)
        ]
        assert one_card_count <= 3
        assert hundred_card_count <= 3
        assert hundred_card_count == one_card_count
        card = hundred["cards"][37]
        assert {key: card[key] for key in (
            "id", "front", "back", "hint", "description"
        )} == {
            "id": "card-037", "front": "Front 37", "back": "Back 37",
            "hint": "Hint 37", "description": "Description 37",
        }
        assert card["image"] and "/" not in card["image"]
        assert card["audio"]["back"] and "/" not in card["audio"]["back"]
        assert card["audio"]["front"] and "/" not in card["audio"]["front"]
    finally:
        event.remove(engine, "before_cursor_execute", listener)
        engine.dispose()


def test_flashcard_body_empty_one_and_large_decks_are_current(tmp_path):
    repository, sessions, engine = _repository(tmp_path)
    assert repository.import_flashcard_deck({"id": "deck-1", "name": "Deck", "cards": []})
    assert repository.get_flashcard_deck("deck-1")["cards"] == []

    one = {"id": "only", "front": "Original", "back": "Answer",
           "hint": "Hint", "description": "Description"}
    assert repository.import_flashcard_deck({
        "id": "deck-1", "name": "Deck", "cards": [one],
    })
    assert repository.get_flashcard_deck("deck-1")["cards"][0]["id"] == "only"

    cards = [{
        "id": f"large-{position:04d}", "front": f"Front {position}",
        "back": f"Back {position}", "hint": f"Hint {position}",
        "description": f"Description {position}",
    } for position in range(1_000)]
    assert repository.import_flashcard_deck({
        "id": "deck-1", "name": "Deck", "cards": cards,
    })
    loaded = repository.get_flashcard_deck("deck-1")
    assert len(loaded["cards"]) == 1_000
    assert [row["id"] for row in loaded["cards"]] == [row["id"] for row in cards]

    edited = [dict(cards[1]), {**cards[0], "front": "Edited"}]
    assert repository.import_flashcard_deck({
        "id": "deck-1", "name": "Deck", "cards": edited,
    })
    with sessions.begin() as session:
        metadata = session.get(FlashcardDeckMetadataModel, "deck-1")
        metadata.name = "Renamed"
    current = repository.get_flashcard_deck("deck-1")
    assert current["name"] == "Renamed"
    assert [row["id"] for row in current["cards"]] == ["large-0001", "large-0000"]
    assert current["cards"][1]["front"] == "Edited"
    engine.dispose()


def test_flashcard_body_skips_deleted_media_and_keeps_remaining_roles(tmp_path):
    repository, sessions, engine = _repository(tmp_path)
    assert repository.import_flashcard_deck({
        "id": "deck-1", "name": "Deck", "cards": [{
            "id": "card-1", "front": "Front", "back": "Back",
            "image": "image.png",
            "audio": {"front": "front.mp3", "back": "back.mp3"},
        }],
    })
    with sessions.begin() as session:
        image = session.scalar(select(MediaModel).where(
            MediaModel.original_filename == "image.png"
        ))
        session.delete(image)

    loaded = repository.get_flashcard_deck("deck-1")["cards"][0]
    assert loaded["image"] == ""
    assert set(loaded["audio"]) == {"back", "front"}
    assert all(value and "/" not in value for value in loaded["audio"].values())
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(FlashcardMediaModel)) == 2
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


def test_practice_projection_uses_stable_media_references_and_descriptors(tmp_path):
    repository, _sessions, engine = _repository(tmp_path)
    image = tmp_path / "practice.png"
    image.write_bytes(PNG + b"practice-image")
    assert repository.import_quiz(_quiz(str(image)))

    package = repository.get_practice_package("quiz", "quiz-1")
    descriptors = repository.get_media_descriptors("quiz", "quiz-1")

    assert package["package_type"] == "offline_practice"
    assert len(package["questions"]) == 6
    assert "image_path" not in package["questions"][0]
    assert package["questions"][0]["media"] == [{
        "media_id": descriptors[0]["media_id"], "role": "image",
    }]
    assert descriptors[0]["content_id"] == "quiz-1"
    assert descriptors[0]["attachment_role"] == "image"
    assert descriptors[0]["size_bytes"] == len(PNG + b"practice-image")
    assert len(descriptors[0]["checksum_sha256"]) == 64
    assert "storage_key" not in descriptors[0]
    attached = repository.get_media_attachment(
        "quiz", "quiz-1", descriptors[0]["media_id"]
    )
    assert attached["storage_key"] != to_stored_path(image)
    assert "/" not in attached["storage_key"] and "\\" not in attached["storage_key"]
    assert repository.get_media_attachment("flashcard", "deck-1", descriptors[0]["media_id"]) is None
    engine.dispose()


def test_media_bytes_changed_at_same_key_advances_parent_revision(tmp_path):
    repository, sessions, engine = _repository(tmp_path)
    image = tmp_path / "changing.png"
    image.write_bytes(PNG + b"first")
    source = _quiz(str(image))
    assert repository.import_quiz(source)
    with sessions() as session:
        initial = session.get(QuizMetadataModel, "quiz-1").content_version

    image.write_bytes(PNG + b"second-content")
    assert repository.import_quiz(source)
    with sessions() as session:
        metadata = session.get(QuizMetadataModel, "quiz-1")
        media = session.scalar(select(MediaModel))
        assert metadata.content_version == initial + 1
        assert media.size_bytes == len(PNG + b"second-content")
    engine.dispose()


def test_shared_media_change_advances_every_attached_envelope_once(tmp_path):
    repository, sessions, engine = _repository(tmp_path)
    shared = tmp_path / "shared.png"
    shared.write_bytes(PNG + b"first")
    quiz = _quiz(str(shared))
    deck = {"id": "deck-1", "cards": [{
        "id": "card-1", "front": "F", "back": "B", "image": str(shared),
    }]}
    assert repository.import_quiz(quiz)
    assert repository.import_flashcard_deck(deck)

    shared.write_bytes(PNG + b"second-content")
    assert repository.import_quiz(quiz)
    with sessions() as session:
        assert session.get(QuizMetadataModel, "quiz-1").content_version == 3
        assert session.get(FlashcardDeckMetadataModel, "deck-1").content_version == 3
    quiz_media = repository.get_media_descriptors("quiz", "quiz-1")[0]
    deck_media = repository.get_media_descriptors("flashcard", "deck-1")[0]
    assert quiz_media["checksum_sha256"] == deck_media["checksum_sha256"]
    assert quiz_media["content_version"] == deck_media["content_version"] == 3

    assert repository.import_quiz(quiz)
    with sessions() as session:
        assert session.get(QuizMetadataModel, "quiz-1").content_version == 3
        assert session.get(FlashcardDeckMetadataModel, "deck-1").content_version == 3
    engine.dispose()


def test_detaching_shared_media_advances_only_edited_envelope(tmp_path):
    repository, sessions, engine = _repository(tmp_path)
    shared = tmp_path / "detach.png"
    shared.write_bytes(PNG + b"stable")
    quiz = _quiz(str(shared))
    deck = {"id": "deck-1", "cards": [{
        "id": "card-1", "front": "F", "back": "B", "image": str(shared),
    }]}
    assert repository.import_quiz(quiz)
    assert repository.import_flashcard_deck(deck)

    detached = _quiz()
    assert repository.import_quiz(detached)
    with sessions() as session:
        assert session.get(QuizMetadataModel, "quiz-1").content_version == 3
        assert session.get(FlashcardDeckMetadataModel, "deck-1").content_version == 2
    engine.dispose()


def test_multiple_shared_media_changes_increment_each_envelope_only_once(tmp_path):
    repository, sessions, engine = _repository(tmp_path)
    first = tmp_path / "shared-first.png"
    second = tmp_path / "shared-second.png"
    first.write_bytes(PNG + b"first-a")
    second.write_bytes(PNG + b"first-b")
    quiz = _quiz(str(first))
    quiz["questions"][1]["image_path"] = str(second)
    deck = {"id": "deck-1", "cards": [
        {"id": "c1", "front": "F1", "back": "B1", "image": str(first)},
        {"id": "c2", "front": "F2", "back": "B2", "image": str(second)},
    ]}
    assert repository.import_quiz(quiz)
    assert repository.import_flashcard_deck(deck)

    first.write_bytes(PNG + b"second-a")
    second.write_bytes(PNG + b"second-b")
    assert repository.import_quiz(quiz)
    with sessions() as session:
        assert session.get(QuizMetadataModel, "quiz-1").content_version == 3
        assert session.get(FlashcardDeckMetadataModel, "deck-1").content_version == 3
    engine.dispose()
