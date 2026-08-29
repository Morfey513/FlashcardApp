from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from src.logic.passwords import PasswordHasher
from src.storage.postgres_class_repository import PostgresClassRepository
from src.storage.postgres_content_metadata_repository import PostgresContentMetadataRepository
from src.storage.postgres_models import (
    Base, ClassInvitationModel, ClassMemberModel, UserModel,
)


def _repositories(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'classes.db'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    with sessions.begin() as session:
        for user_id, login, role in (
            ("teacher-1", "teacher", "teacher"),
            ("student-1", "student", "student"),
            ("student-2", "student2", "student"),
        ):
            session.add(UserModel(
                id=user_id, username=login, display_name=login.title(),
                password_hash=PasswordHasher.hash("password1"), role=role,
                status="active", ban_reason="",
            ))
    return (
        PostgresContentMetadataRepository(sessions),
        PostgresClassRepository(sessions), sessions, engine,
    )


def _source(status="published", code="MATH-8X2K"):
    return {
        "id": "quiz-1", "name": "Math Class",
        "moderation": {
            "owner_id": "teacher-1", "status": status, "visibility": "class_only",
            "invite": {"code": code, "created_at": "2026-08-01T10:00:00+00:00"},
            "enrollments": {
                "student-1": {"enrolled_at": "2026-08-02T10:00:00+00:00"}
            },
        },
    }


def test_import_preserves_code_membership_and_is_idempotent(tmp_path):
    metadata, classes, sessions, engine = _repositories(tmp_path)
    source = _source()
    assert metadata.import_quiz(source, "quiz.json")
    assert classes.import_content_access(source, "quiz")
    assert classes.import_content_access(source, "quiz")

    owned = classes.get_owned_classes("teacher-1")
    assert len(owned) == 1
    assert owned[0]["content_id"] == "quiz-1"
    assert owned[0]["invite_code"] == "MATH-8X2K"
    assert owned[0]["roster"][0]["user_id"] == "student-1"
    with sessions() as session:
        assert len(session.scalars(select(ClassInvitationModel)).all()) == 1
        assert len(session.scalars(select(ClassMemberModel)).all()) == 1
    engine.dispose()


def test_join_rotation_removal_and_class_only_discovery(tmp_path):
    metadata, classes, _sessions, engine = _repositories(tmp_path)
    source = _source()
    assert metadata.import_quiz(source, "quiz.json")
    assert classes.import_content_access(source, "quiz")

    assert classes.join_with_code("MATH 8X2K", "student-2")[0]
    assert classes.has_active_content_access("student-2", "quiz", "quiz-1")
    assert not classes.has_active_content_access("student-2", "quiz", "missing")
    assert metadata.get_for_actor("student-2", "student", "available")[0]["id"] == "quiz-1"
    success, rotated = classes.rotate_code("quiz", "quiz-1", "teacher-1", "teacher")
    assert success and rotated != "MATH-8X2K"
    assert not classes.join_with_code("MATH-8X2K", "student-1")[0]
    assert classes.join_with_code(rotated, "student-1")[0]

    assert not classes.remove_member(
        "quiz", "quiz-1", "student-2", "student", "student-1"
    )[0]
    assert classes.remove_member(
        "quiz", "quiz-1", "teacher-1", "teacher", "student-2"
    )[0]
    assert not classes.has_active_content_access("student-2", "quiz", "quiz-1")
    assert metadata.get_for_actor("student-2", "student", "available") == []
    engine.dispose()


def test_unpublished_content_cannot_accept_invitation(tmp_path):
    metadata, classes, _sessions, engine = _repositories(tmp_path)
    source = _source(status="pending_review")
    assert metadata.import_quiz(source, "quiz.json")
    assert classes.import_content_access(source, "quiz")
    success, message = classes.join_with_code("MATH-8X2K", "student-2")
    assert not success
    assert "not currently available" in message
    engine.dispose()


def test_direct_invitation_lookup_is_bounded_across_owned_classes(tmp_path):
    metadata, classes, _sessions, engine = _repositories(tmp_path)
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    for index in range(100):
        code = f"CODE-{alphabet[index // len(alphabet)]}{alphabet[index % len(alphabet)]}"
        source = {
            "id": f"quiz-{index}", "name": f"Quiz {index}",
            "moderation": {
                "owner_id": "teacher-1", "status": "published",
                "visibility": "class_only",
                "invite": {"code": code},
            },
        }
        assert metadata.import_quiz(source, f"quiz-{index}.json")
        assert classes.import_content_access(source, "quiz")

    statements = []
    listener = lambda *_args: statements.append(1)
    event.listen(engine, "before_cursor_execute", listener)
    try:
        assert classes.get_invitation(
            "quiz", "quiz-0", "teacher-1", "teacher"
        ) == "CODE-AA"
        one_lookup = len(statements)
        statements.clear()
        assert classes.get_invitation(
            "quiz", "quiz-99", "teacher-1", "teacher"
        ) == f"CODE-{alphabet[99 // len(alphabet)]}{alphabet[99 % len(alphabet)]}"
        hundredth_lookup = len(statements)
        statements.clear()
        assert classes.get_invitation(
            "quiz", "quiz-0", "student-1", "student"
        ) is None

        assert one_lookup <= 3
        assert hundredth_lookup <= 3
        assert hundredth_lookup == one_lookup
        assert len(statements) <= 2
    finally:
        event.remove(engine, "before_cursor_execute", listener)
        engine.dispose()
