"""FastAPI entry point for the local server migration boundary."""

import base64
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from src.api.schemas import (
    AccountStatusRequest,
    ContentMetadataRequest,
    ContentMetadataResponse,
    ContentBodyRequest,
    MediaUploadRequest,
    MediaUploadResponse,
    AttemptResolutionRequest,
    InvitationResponse,
    LearningProgressRequest,
    JoinClassRequest,
    MessageResponse,
    DisplayNameRequest,
    LoginRequest,
    PasswordChangeRequest,
    PreferencesRequest,
    PublicProfilesRequest,
    PublicUserResponse,
    RegistrationRequest,
    RoleUpdateRequest,
    QuizAttemptRequest,
    AssessmentResponseRequest,
    AssessmentSubmitRequest,
    TokenResponse,
    UserResponse,
)
from src.storage.postgres_session_repository import PostgresSessionRepository
from src.storage.postgres_user_repository import PostgresUserRepository
from src.storage.postgres_content_metadata_repository import PostgresContentMetadataRepository
from src.storage.postgres_class_repository import PostgresClassRepository
from src.storage.postgres_learning_repository import PostgresLearningRepository
from src.storage.postgres_content_body_repository import PostgresContentBodyRepository
from src.storage.postgres_content_history_repository import PostgresContentHistoryRepository
from src.logic.test_settings import normalize_test_settings
from src.utils.paths import resolve_stored_path, to_stored_path


bearer = HTTPBearer(auto_error=False)


def create_app(
    user_repository=None, session_repository=None, content_repository=None,
    class_repository=None, learning_repository=None, content_body_repository=None,
    content_history_repository=None,
) -> FastAPI:
    user_repository = user_repository or PostgresUserRepository()
    session_repository = session_repository or PostgresSessionRepository(
        user_repository.session_factory
    )
    content_repository = content_repository or PostgresContentMetadataRepository(
        user_repository.session_factory
    )
    class_repository = class_repository or PostgresClassRepository(
        user_repository.session_factory
    )
    learning_repository = learning_repository or PostgresLearningRepository(
        user_repository.session_factory
    )
    content_body_repository = content_body_repository or PostgresContentBodyRepository(
        user_repository.session_factory
    )
    content_history_repository = content_history_repository or PostgresContentHistoryRepository(
        user_repository.session_factory
    )
    app = FastAPI(
        title="Study Buddy API",
        version="0.1.0",
        description="Local application API backed by PostgreSQL repositories.",
    )
    app.state.user_repository = user_repository
    app.state.session_repository = session_repository
    app.state.content_repository = content_repository
    app.state.class_repository = class_repository
    app.state.learning_repository = learning_repository
    app.state.content_body_repository = content_body_repository
    app.state.content_history_repository = content_history_repository

    def current_token(
        credentials: Annotated[
            HTTPAuthorizationCredentials | None, Depends(bearer)
        ],
    ) -> str:
        if credentials is None or credentials.scheme.casefold() != "bearer":
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authentication required")
        return credentials.credentials

    def current_user(request: Request, token: Annotated[str, Depends(current_token)]):
        user_id = request.app.state.session_repository.resolve(token)
        user = (
            request.app.state.user_repository.get_user_by_id(user_id)
            if user_id is not None
            else None
        )
        if user is None or user.get("status") != "active":
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired session")
        return user

    def current_admin(user: Annotated[dict, Depends(current_user)]):
        if user.get("role") != "admin":
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Administrator access required")
        return user

    def available_content(request: Request, user: dict, kind: str, content_id: str):
        try:
            items = request.app.state.content_repository.get_for_actor(
                user["id"], user["role"],
                "all" if user["role"] == "admin" else "available", kind,
            )
        except ValueError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
        if not any(item["id"] == content_id for item in items):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Content was not found")

    def token_response(request: Request, user: dict) -> TokenResponse:
        token, expires_in = request.app.state.session_repository.create(user["id"])
        return TokenResponse(
            access_token=token,
            expires_in=expires_in,
            user=UserResponse.model_validate(user),
        )

    @app.get("/health", tags=["system"])
    def health():
        return {"status": "ok"}

    @app.get("/ready", tags=["system"])
    def ready(request: Request):
        if not request.app.state.session_repository.is_ready():
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE, "Database is unavailable"
            )
        return {"status": "ready"}

    @app.post(
        "/api/v1/auth/register",
        response_model=TokenResponse,
        status_code=status.HTTP_201_CREATED,
        tags=["authentication"],
    )
    def register(payload: RegistrationRequest, request: Request):
        success, message, user = request.app.state.user_repository.register(
            payload.name, payload.login, payload.password
        )
        if not success or user is None:
            error_status = (
                status.HTTP_409_CONFLICT
                if "already in use" in message
                else status.HTTP_400_BAD_REQUEST
            )
            raise HTTPException(error_status, message)
        return token_response(request, user)

    @app.post(
        "/api/v1/auth/login",
        response_model=TokenResponse,
        tags=["authentication"],
    )
    def login(payload: LoginRequest, request: Request):
        user = request.app.state.user_repository.authenticate(
            payload.login, payload.password
        )
        if user is None:
            ban_message = request.app.state.user_repository.get_ban_message(
                payload.login
            )
            if ban_message:
                raise HTTPException(status.HTTP_403_FORBIDDEN, ban_message)
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid login or password")
        return token_response(request, user)

    @app.post(
        "/api/v1/auth/logout",
        status_code=status.HTTP_204_NO_CONTENT,
        tags=["authentication"],
    )
    def logout(
        request: Request,
        token: Annotated[str, Depends(current_token)],
        _user: Annotated[dict, Depends(current_user)],
    ):
        request.app.state.session_repository.revoke(token)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.get(
        "/api/v1/users/me", response_model=UserResponse, tags=["account"]
    )
    def me(user: Annotated[dict, Depends(current_user)]):
        return user

    @app.post(
        "/api/v1/users/profiles",
        response_model=list[PublicUserResponse],
        tags=["account"],
    )
    def public_profiles(
        payload: PublicProfilesRequest,
        request: Request,
        _user: Annotated[dict, Depends(current_user)],
    ):
        """Resolve only the names/logins needed for authenticated roster views."""
        profiles = []
        seen = set()
        for user_id in payload.user_ids:
            normalized = str(user_id)
            if normalized in seen:
                continue
            seen.add(normalized)
            account = request.app.state.user_repository.get_user_by_id(normalized)
            if account is not None:
                profiles.append({
                    "id": account["id"],
                    "login": account["login"],
                    "name": account["name"],
                })
        return profiles

    @app.put(
        "/api/v1/users/me/preferences",
        response_model=UserResponse,
        tags=["account"],
    )
    def save_preferences(
        payload: PreferencesRequest,
        request: Request,
        user: Annotated[dict, Depends(current_user)],
    ):
        if not request.app.state.user_repository.save_preferences(
            user["id"], payload.preferences
        ):
            raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Unable to save preferences")
        return request.app.state.user_repository.get_user_by_id(user["id"])

    @app.patch(
        "/api/v1/users/me/display-name",
        response_model=UserResponse,
        tags=["account"],
    )
    def update_display_name(
        payload: DisplayNameRequest,
        request: Request,
        user: Annotated[dict, Depends(current_user)],
    ):
        if not request.app.state.user_repository.update_display_name(
            user["id"], payload.name
        ):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unable to update display name")
        return request.app.state.user_repository.get_user_by_id(user["id"])

    @app.post(
        "/api/v1/users/me/change-password",
        status_code=status.HTTP_204_NO_CONTENT,
        tags=["account"],
    )
    def change_password(
        payload: PasswordChangeRequest,
        request: Request,
        user: Annotated[dict, Depends(current_user)],
    ):
        success, message = request.app.state.user_repository.change_password(
            user["id"], payload.current_password, payload.new_password
        )
        if not success:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, message)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.get(
        "/api/v1/admin/users",
        response_model=list[UserResponse],
        tags=["administration"],
    )
    def list_users(
        request: Request, _admin: Annotated[dict, Depends(current_admin)]
    ):
        return request.app.state.user_repository.get_all_users()

    @app.patch(
        "/api/v1/admin/users/{user_id}/role",
        response_model=UserResponse,
        tags=["administration"],
    )
    def update_role(
        user_id: str,
        payload: RoleUpdateRequest,
        request: Request,
        admin: Annotated[dict, Depends(current_admin)],
    ):
        if str(user_id) == str(admin["id"]):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "You cannot change your own role")
        if not request.app.state.user_repository.update_role(user_id, payload.role):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "User was not found")
        return request.app.state.user_repository.get_user_by_id(user_id)

    @app.patch(
        "/api/v1/admin/users/{user_id}/status",
        response_model=UserResponse,
        tags=["administration"],
    )
    def update_account_status(
        user_id: str,
        payload: AccountStatusRequest,
        request: Request,
        admin: Annotated[dict, Depends(current_admin)],
    ):
        if str(user_id) == str(admin["id"]):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "You cannot suspend your own account")
        changed = request.app.state.user_repository.set_account_status(
            admin["role"], user_id, payload.status, payload.reason, actor_id=admin["id"]
        )
        if not changed:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "User was not found")
        return request.app.state.user_repository.get_user_by_id(user_id)

    @app.get(
        "/api/v1/content/metadata",
        response_model=list[ContentMetadataResponse],
        tags=["content"],
    )
    def content_metadata(
        request: Request,
        user: Annotated[dict, Depends(current_user)],
        scope: str = "available",
        kind: str | None = None,
    ):
        if scope not in {"available", "owned", "all"}:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid content scope")
        if scope == "all" and user["role"] != "admin":
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Administrator access required")
        try:
            return request.app.state.content_repository.get_for_actor(
                user["id"], user["role"], scope, kind
            )
        except ValueError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    @app.get(
        "/api/v1/content/metadata/{kind}/{content_id}",
        response_model=ContentMetadataResponse,
        tags=["content"],
    )
    def content_metadata_item(
        kind: str,
        content_id: str,
        request: Request,
        user: Annotated[dict, Depends(current_user)],
    ):
        try:
            allowed = request.app.state.content_repository.get_for_actor(
                user["id"], user["role"],
                "all" if user["role"] == "admin" else "available", kind,
            )
        except ValueError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
        item = next((entry for entry in allowed if entry["id"] == content_id), None)
        if item is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Content was not found")
        return item

    @app.put(
        "/api/v1/content/metadata/{kind}/{content_id}",
        response_model=ContentMetadataResponse,
        tags=["content"],
    )
    def save_content_metadata(
        kind: str,
        content_id: str,
        payload: ContentMetadataRequest,
        request: Request,
        user: Annotated[dict, Depends(current_user)],
    ):
        if payload.id != content_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Content ID does not match path")
        try:
            previous = request.app.state.content_repository.get_by_id(kind, content_id)
            saved = request.app.state.content_repository.save_for_actor(
                kind, payload.model_dump(), user["id"], user["role"]
            )
        except ValueError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
        if not saved:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Content update is not permitted")
        if previous and (
            previous["status"] != payload.status
            or previous["visibility"] != payload.visibility
        ):
            request.app.state.content_history_repository.append_moderation(
                kind, content_id, user["id"], payload.status, payload.review_note
            )
        return request.app.state.content_repository.get_by_id(kind, content_id)

    @app.delete("/api/v1/content/metadata/{kind}/{content_id}", tags=["content"])
    def delete_content_metadata(
        kind: str, content_id: str, request: Request,
        user: Annotated[dict, Depends(current_user)],
    ):
        try:
            existing = request.app.state.content_repository.get_by_id(kind, content_id)
            if existing is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Content was not found")
            deleted = request.app.state.content_repository.delete_for_actor(
                kind, content_id, user["id"], user["role"]
            )
        except ValueError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
        if not deleted:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Content deletion is not permitted")
        return {"message": "Content deleted."}

    @app.post(
        "/api/v1/classes/join",
        response_model=MessageResponse,
        tags=["classes"],
    )
    def join_class(
        payload: JoinClassRequest,
        request: Request,
        user: Annotated[dict, Depends(current_user)],
    ):
        success, message = request.app.state.class_repository.join_with_code(
            payload.code, user["id"]
        )
        if not success:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, message)
        return {"message": message}

    @app.get("/api/v1/classes/owned", tags=["classes"])
    def owned_classes(
        request: Request,
        user: Annotated[dict, Depends(current_user)],
        kind: str | None = None,
    ):
        if user["role"] not in {"teacher", "admin"}:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Teacher access required")
        rows = request.app.state.class_repository.get_owned_classes(user["id"], kind)
        for item in rows:
            content_id = item["content_id"]
            metadata = request.app.state.content_repository.get_by_id(
                item["kind"], content_id
            ) or {}
            item["file"] = content_id
            item["test_settings"] = normalize_test_settings(
                metadata.get("test_settings")
            ) if item["kind"] == "quiz" else {}
            grades = []
            for member in item.get("roster", []):
                if item["kind"] == "quiz":
                    body = request.app.state.content_body_repository.get_quiz(content_id) or {}
                    total = len(body.get("questions") or [])
                    progress = request.app.state.learning_repository.get_quiz_progress(
                        content_id, member["user_id"]
                    )
                    summary = request.app.state.learning_repository.assessment_summary(
                        content_id, member["user_id"]
                    )
                    attempts = request.app.state.learning_repository.get_quiz_attempts(
                        content_id, member["user_id"]
                    )
                    unresolved = next((
                        attempt for attempt in reversed(attempts)
                        if attempt.get("status") in {"in_progress", "abandoned"}
                    ), None)
                    member.update({
                        "mastered": sum(1 for value in progress.values() if value.get("mastered")),
                        "total": total,
                        "percent": round(sum(1 for value in progress.values() if value.get("mastered")) / total * 100) if total else 0,
                        "best_grade": summary["best_percentage"],
                        "average_grade": summary["average_percentage"],
                        "attempts_used": summary["attempts_used"],
                        "assessment_status": "Finished" if summary["attempts_used"] else "Not Started",
                        "unresolved_attempt": unresolved,
                    })
                    if summary["best_percentage"] is not None:
                        grades.append(summary["best_percentage"])
                else:
                    body = request.app.state.content_body_repository.get_flashcard_deck(content_id) or {}
                    total = len(body.get("cards") or [])
                    progress = request.app.state.learning_repository.get_flashcard_progress(
                        content_id, member["user_id"]
                    )
                    mastered = sum(1 for value in progress.values() if value.get("mastered"))
                    member.update({
                        "mastered": mastered, "total": total,
                        "percent": round(mastered / total * 100) if total else 0,
                    })
            item["class_average"] = round(sum(grades) / len(grades), 1) if grades else None
        return rows

    @app.post(
        "/api/v1/classes/{kind}/{content_id}/invitation/rotate",
        response_model=InvitationResponse,
        tags=["classes"],
    )
    def rotate_invitation(
        kind: str,
        content_id: str,
        request: Request,
        user: Annotated[dict, Depends(current_user)],
    ):
        success, result = request.app.state.class_repository.rotate_code(
            kind, content_id, user["id"], user["role"]
        )
        if not success:
            raise HTTPException(status.HTTP_403_FORBIDDEN, result)
        return {"code": result}

    @app.get(
        "/api/v1/classes/{kind}/{content_id}/invitation",
        response_model=InvitationResponse,
        tags=["classes"],
    )
    def active_invitation(
        kind: str, content_id: str, request: Request,
        user: Annotated[dict, Depends(current_user)],
    ):
        repository = request.app.state.class_repository
        direct_lookup = getattr(repository, "get_invitation", None)
        if callable(direct_lookup):
            code = direct_lookup(kind, content_id, user["id"], user["role"])
            if code is None:
                raise HTTPException(
                    status.HTTP_403_FORBIDDEN, "Invitation access is not permitted"
                )
            return {"code": code}
        classes = repository.get_owned_classes(user["id"], kind)
        item = next((row for row in classes if row["content_id"] == content_id), None)
        if item is None:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Invitation access is not permitted")
        return {"code": item.get("invite_code", "")}

    @app.delete(
        "/api/v1/classes/{kind}/{content_id}/members/{user_id}",
        response_model=MessageResponse,
        tags=["classes"],
    )
    def remove_class_member(
        kind: str,
        content_id: str,
        user_id: str,
        request: Request,
        user: Annotated[dict, Depends(current_user)],
    ):
        success, message = request.app.state.class_repository.remove_member(
            kind, content_id, user["id"], user["role"], user_id
        )
        if not success:
            raise HTTPException(status.HTTP_403_FORBIDDEN, message)
        return {"message": message}

    @app.get("/api/v1/progress/summary", tags=["learning"])
    def learning_progress_summary(
        request: Request, user: Annotated[dict, Depends(current_user)],
        include_items: bool = True,
    ):
        return request.app.state.learning_repository.get_progress_summary(
            user["id"], user["role"], include_items=include_items,
        )

    @app.get("/api/v1/progress/{kind}/{content_id}", tags=["learning"])
    def learning_progress(
        kind: str, content_id: str, request: Request,
        user: Annotated[dict, Depends(current_user)],
        include_items: bool = False,
    ):
        available_content(request, user, kind, content_id)
        if kind == "quiz":
            progress = request.app.state.learning_repository.get_quiz_progress(
                content_id, user["id"]
            )
            if include_items:
                bodies = request.app.state.content_body_repository
                if hasattr(bodies, "get_quiz_progress_items"):
                    sources = bodies.get_quiz_progress_items(content_id)
                    text_key = "text"
                else:
                    body = bodies.get_quiz(content_id, include_answers=False) or {}
                    sources = body.get("questions") or []
                    text_key = "question"
        elif kind in {"flashcard", "deck", "flashcard_deck"}:
            progress = request.app.state.learning_repository.get_flashcard_progress(
                content_id, user["id"]
            )
            if include_items:
                bodies = request.app.state.content_body_repository
                if hasattr(bodies, "get_flashcard_progress_items"):
                    sources = bodies.get_flashcard_progress_items(content_id)
                    text_key = "text"
                else:
                    body = bodies.get_flashcard_deck(content_id) or {}
                    sources = body.get("cards") or []
                    text_key = "front"
        else:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unsupported content kind")
        response = {"progress": progress}
        if include_items:
            items = []
            for source in sources:
                item_id = str(source.get("id", ""))
                saved = progress.get(item_id, {})
                items.append({
                    "id": item_id,
                    "text": str(source.get(text_key) or "Untitled"),
                    "mastered": bool(saved.get("mastered", False)),
                    "correct": int(saved.get("correct", 0)),
                    "wrong": int(saved.get("wrong", 0)),
                })
            mastered = sum(1 for item in items if item["mastered"])
            total = len(items)
            response.update({
                "items": items,
                "summary": {
                    "mastered": mastered,
                    "total": total,
                    "percent": round(mastered / total * 100) if total else 0,
                    "has_progress": bool(progress),
                },
            })
        return response

    @app.put("/api/v1/progress/{kind}/{content_id}", tags=["learning"])
    def save_learning_progress(
        kind: str, content_id: str, payload: LearningProgressRequest,
        request: Request, user: Annotated[dict, Depends(current_user)],
    ):
        available_content(request, user, kind, content_id)
        progress = {
            item_id: entry.model_dump() for item_id, entry in payload.progress.items()
        }
        if kind == "quiz":
            saved = request.app.state.learning_repository.import_quiz_progress(
                content_id, user["id"], progress
            )
        elif kind in {"flashcard", "deck", "flashcard_deck"}:
            saved = request.app.state.learning_repository.import_flashcard_progress(
                content_id, user["id"], progress
            )
        else:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unsupported content kind")
        if not saved:
            raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Unable to save progress")
        return {"progress": progress}

    @app.delete("/api/v1/progress/{kind}/{content_id}", tags=["learning"])
    def delete_learning_progress(
        kind: str, content_id: str, request: Request,
        user: Annotated[dict, Depends(current_user)],
    ):
        available_content(request, user, kind, content_id)
        removed = request.app.state.learning_repository.delete_progress(
            kind, content_id, user["id"]
        )
        return {"message": "Progress reset.", "removed": bool(removed)}

    @app.delete("/api/v1/progress/{kind}", tags=["learning"])
    def clear_learning_progress(
        kind: str, request: Request,
        user: Annotated[dict, Depends(current_user)],
    ):
        removed = request.app.state.learning_repository.clear_user_progress(
            kind, user["id"]
        )
        return {"message": "Progress cleared.", "removed": removed}

    @app.get("/api/v1/quizzes/{quiz_id}/attempts", tags=["learning"])
    def quiz_attempts(
        quiz_id: str, request: Request,
        user: Annotated[dict, Depends(current_user)],
    ):
        available_content(request, user, "quiz", quiz_id)
        return request.app.state.learning_repository.get_quiz_attempts(
            quiz_id, user["id"]
        )

    @app.post("/api/v1/quizzes/{quiz_id}/assessments", tags=["assessments"])
    def start_assessment(quiz_id: str, request: Request, user: Annotated[dict, Depends(current_user)]):
        metadata = request.app.state.content_repository.get_by_id("quiz", quiz_id)
        if metadata is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Quiz was not found")
        if metadata.get("status") != "published" or metadata.get("visibility") != "class_only":
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Assessment access is not permitted")
        available_content(request, user, "quiz", quiz_id)
        settings = metadata.get("test_settings") or {}
        from src.logic.test_settings import normalize_test_settings
        normalized = normalize_test_settings(settings)
        if normalized["due_at"]:
            from datetime import datetime, timezone
            due = datetime.fromisoformat(str(normalized["due_at"]).replace("Z", "+00:00"))
            if due.tzinfo is None: due = due.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) > due:
                raise HTTPException(status.HTTP_403_FORBIDDEN, "Assessment is closed")
        body = request.app.state.content_body_repository.get_quiz(quiz_id)
        if body is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Quiz body was not found")
        result = request.app.state.learning_repository.start_assessment(user["id"], metadata, normalized, body.get("questions", []))
        if result is None:
            raise HTTPException(status.HTTP_409_CONFLICT, "Assessment could not be started")
        return result

    @app.get("/api/v1/quizzes/{quiz_id}/assessments/{attempt_id}", tags=["assessments"])
    def get_assessment(quiz_id: str, attempt_id: str, request: Request, user: Annotated[dict, Depends(current_user)]):
        result = request.app.state.learning_repository.get_assessment(user["id"], attempt_id)
        if result is None or result["quiz_id"] != quiz_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Assessment was not found")
        available_content(request, user, "quiz", quiz_id)
        return result

    @app.put("/api/v1/quizzes/{quiz_id}/assessments/{attempt_id}/responses/{position}", tags=["assessments"])
    def checkpoint_assessment(quiz_id: str, attempt_id: str, position: int, payload: AssessmentResponseRequest, request: Request, user: Annotated[dict, Depends(current_user)]):
        current = request.app.state.learning_repository.get_assessment(user["id"], attempt_id)
        if current is None or current["quiz_id"] != quiz_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Assessment was not found")
        available_content(request, user, "quiz", quiz_id)
        result = request.app.state.learning_repository.checkpoint_assessment(user["id"], attempt_id, position, payload.user_answer)
        if result is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Assessment response could not be saved")
        return result

    @app.post("/api/v1/quizzes/{quiz_id}/assessments/{attempt_id}/submit", tags=["assessments"])
    def submit_assessment(quiz_id: str, attempt_id: str, payload: AssessmentSubmitRequest, request: Request, user: Annotated[dict, Depends(current_user)]):
        current = request.app.state.learning_repository.get_assessment(user["id"], attempt_id)
        if current is None or current["quiz_id"] != quiz_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Assessment was not found")
        available_content(request, user, "quiz", quiz_id)
        result = request.app.state.learning_repository.submit_assessment(user["id"], attempt_id, payload.responses)
        if result is None:
            raise HTTPException(status.HTTP_409_CONFLICT, "Assessment could not be submitted")
        return result

    @app.put("/api/v1/quizzes/{quiz_id}/attempts/{attempt_id}", tags=["learning"])
    def save_quiz_attempt(
        quiz_id: str, attempt_id: str, payload: QuizAttemptRequest,
        request: Request, user: Annotated[dict, Depends(current_user)],
    ):
        if payload.quiz_id != quiz_id or payload.id != attempt_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Attempt ID does not match path")
        available_content(request, user, "quiz", quiz_id)
        existing = request.app.state.learning_repository.get_quiz_attempt(attempt_id)
        if existing is not None:
            if existing["user_id"] != user["id"]:
                raise HTTPException(status.HTTP_403_FORBIDDEN, "Attempt belongs to another user")
            if existing["quiz_id"] != quiz_id:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "Attempt belongs to another quiz")
            if existing.get("assessment_snapshot") is not None:
                raise HTTPException(status.HTTP_409_CONFLICT, "Assessment attempts use the assessment workflow")
        source = payload.model_dump()
        source["user_id"] = user["id"]
        if not request.app.state.learning_repository.import_quiz_attempt(source):
            raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Unable to save attempt")
        return next(
            attempt for attempt in request.app.state.learning_repository.get_quiz_attempts(
                quiz_id, user["id"]
            ) if attempt["id"] == attempt_id
        )

    @app.get(
        "/api/v1/classes/quiz/{quiz_id}/students/{student_id}/attempts",
        tags=["learning"],
    )
    def student_quiz_attempts(
        quiz_id: str, student_id: str, request: Request,
        user: Annotated[dict, Depends(current_user)],
    ):
        metadata = request.app.state.content_repository.get_by_id("quiz", quiz_id)
        if metadata is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Quiz was not found")
        if user["role"] != "admin" and metadata["owner_id"] != user["id"]:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Attempt access is not permitted")
        return request.app.state.learning_repository.get_quiz_attempts(
            quiz_id, student_id
        )

    @app.post(
        "/api/v1/classes/quiz/{quiz_id}/attempts/{attempt_id}/resolve",
        tags=["learning"],
    )
    def resolve_quiz_attempt(
        quiz_id: str, attempt_id: str, payload: AttemptResolutionRequest,
        request: Request, user: Annotated[dict, Depends(current_user)],
    ):
        metadata = request.app.state.content_repository.get_by_id("quiz", quiz_id)
        if metadata is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Quiz was not found")
        if user["role"] != "admin" and metadata["owner_id"] != user["id"]:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Attempt resolution is not permitted")
        resolved = request.app.state.learning_repository.resolve_attempt(
            quiz_id, attempt_id, payload.action, user["id"]
        )
        if resolved is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Attempt could not be resolved")
        return resolved

    @app.get("/api/v1/content/bodies/{kind}/{content_id}", tags=["content"])
    def content_body(
        kind: str, content_id: str, request: Request,
        user: Annotated[dict, Depends(current_user)],
    ):
        available_content(request, user, kind, content_id)
        if kind == "quiz":
            # Learners receive an answer-less source projection.  Authors and
            # administrators retain the complete editable body.
            metadata = request.app.state.content_repository.get_by_id("quiz", content_id)
            can_edit = user["role"] == "admin" or (
                user["role"] == "teacher" and metadata and metadata.get("owner_id") == user["id"]
            )
            body = request.app.state.content_body_repository.get_quiz(
                content_id, include_answers=can_edit
            )
        elif kind in {"flashcard", "deck", "flashcard_deck"}:
            body = request.app.state.content_body_repository.get_flashcard_deck(content_id)
        else:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unsupported content kind")
        if body is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Content body was not found")
        return body

    @app.put("/api/v1/content/bodies/{kind}/{content_id}", tags=["content"])
    def save_content_body(
        kind: str, content_id: str, payload: ContentBodyRequest,
        request: Request, user: Annotated[dict, Depends(current_user)],
    ):
        if payload.id != content_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Content ID does not match path")
        try:
            metadata = request.app.state.content_repository.get_by_id(kind, content_id)
        except ValueError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
        if metadata is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Content was not found")
        if metadata["status"] == "banned":
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Banned content is locked")
        if user["role"] != "admin" and (
            user["role"] != "teacher" or metadata["owner_id"] != user["id"]
        ):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Content update is not permitted")
        source = payload.model_dump(exclude_none=True)
        if kind == "quiz":
            saved = payload.questions is not None and request.app.state.content_body_repository.import_quiz(source)
        elif kind in {"flashcard", "deck", "flashcard_deck"}:
            saved = payload.cards is not None and request.app.state.content_body_repository.import_flashcard_deck(source)
        else:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unsupported content kind")
        if not saved:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid content body")
        request.app.state.content_history_repository.append_edit(
            kind, content_id, user["id"], user["role"],
            "Updated quiz questions." if kind == "quiz" else "Updated flashcard cards.",
            changed_fields=["questions" if kind == "quiz" else "cards"],
        )
        return (
            request.app.state.content_body_repository.get_quiz(content_id)
            if kind == "quiz"
            else request.app.state.content_body_repository.get_flashcard_deck(content_id)
        )

    @app.post(
        "/api/v1/content/media/{kind}/{content_id}",
        response_model=MediaUploadResponse,
        tags=["content"],
    )
    def upload_content_media(
        kind: str, content_id: str, payload: MediaUploadRequest,
        request: Request, user: Annotated[dict, Depends(current_user)],
    ):
        try:
            metadata = request.app.state.content_repository.get_by_id(kind, content_id)
        except ValueError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
        if metadata is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Content was not found")
        if metadata["status"] == "banned" or (
            user["role"] != "admin"
            and (user["role"] != "teacher" or metadata["owner_id"] != user["id"])
        ):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Media upload is not permitted")
        try:
            content = base64.b64decode(payload.content_base64, validate=True)
        except (ValueError, TypeError) as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid media encoding") from exc
        if len(content) > 25 * 1024 * 1024:
            raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Media exceeds 25 MB")
        filename = Path(payload.filename).name
        if not filename or filename in {".", ".."}:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid media filename")
        source_file = resolve_stored_path(metadata["source_path"])
        media_dir = source_file.parent / "media"
        media_dir.mkdir(parents=True, exist_ok=True)
        target = media_dir / filename
        counter = 2
        while target.exists() and target.read_bytes() != content:
            target = media_dir / f"{Path(filename).stem}_{counter}{Path(filename).suffix}"
            counter += 1
        if not target.exists():
            target.write_bytes(content)
        return {"stored_path": to_stored_path(target)}

    @app.get("/api/v1/content/history/{kind}/{content_id}", tags=["content"])
    def content_history(
        kind: str, content_id: str, request: Request,
        user: Annotated[dict, Depends(current_user)],
    ):
        try:
            metadata = request.app.state.content_repository.get_by_id(kind, content_id)
        except ValueError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
        if metadata is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Content was not found")
        if user["role"] != "admin" and metadata["owner_id"] != user["id"]:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "History access is not permitted")
        return request.app.state.content_history_repository.get_history(kind, content_id)

    return app


app = create_app()
