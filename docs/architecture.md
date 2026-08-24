# Architecture

Study Buddy is currently an offline-first PyQt6 desktop application. Its
repository contracts allow persistence to move incrementally from JSON to
PostgreSQL and later behind an API without rewriting the learning UI.

## Layered design

```text
PyQt6 windows and dialogs
        |
        v
Controllers and application flow
        |
        v
Learning logic and shared access rules
        |
        v
Repository / data-access layer
        |
        v
JSON/PostgreSQL repositories or the staged local HTTP API
```

### UI layer

`src/ui/` contains the launcher, study views, editors, account dialogs,
progress statistics, moderation, class management, and reusable interaction
helpers. UI classes render state and forward user actions; they should not
construct storage paths or edit JSON directly.

QSS files in `styles/` provide application-owned light and dark themes. The
translation files under `data/languages/` supply English and French text.

### Controllers

`src/controllers/` coordinates windows, learning sessions, editors, progress,
and repositories. Controllers translate UI actions into repository and logic
operations while keeping widgets independent from persistence details.

Main controller responsibilities include authentication state, preferences,
role-aware navigation, and opening the appropriate child windows. Quiz and
flashcard controllers own study-session flow; editor controllers coordinate
content creation and media import.

### Logic layer

`src/logic/` contains rules that do not depend on PyQt rendering or JSON file
layout:

- flashcard selection, retries, attempts, and mastery eligibility;
- quiz question conversion, answer shuffling, and grading;
- normalization and validation for supported question types;
- user-session role checks;
- content roles, lifecycle states, visibility values, and transitions;
- persistent application preferences and translation selection.

`access_control.py` is the canonical source for roles, account states,
moderation states, visibility choices, labels, and lifecycle rules.

### Repository layer

`src/storage/` owns persistence and content discovery. JSON supports offline
and demo use; authenticated API mode has interchangeable desktop adapters and
server-owned PostgreSQL implementations:

| Repository | Responsibility |
|---|---|
| `QuizRepository` | Quiz metadata, questions, indexes, progress, and quiz-owned media. |
| `FlashcardRepository` | Deck metadata, cards, indexes, per-user progress, and deck-owned media. |
| `UserRepositoryContract` | Storage-independent account operations used by controllers. |
| `JsonUserRepository` | Default local accounts, hashes, preferences, roles, and status. |
| `PostgresUserRepository` | SQLAlchemy implementation of the same account contract. |
| `HttpUserRepository` | Desktop adapter that maps the same contract to FastAPI requests. |
| `HttpQuizRepository` / `HttpFlashcardRepository` | Controller-compatible remote content, progress, attempt, media, and history operations. |
| `HttpClassRepository` | Remote invitations, enrollment, roster, analytics, and attempt resolution. |
| PostgreSQL content repositories | Relational metadata, bodies, classes, learning state, media metadata, and append-only histories. |
| `ModerationRepository` | Content lifecycle, visibility, review history, and selector access. |
| `InvitationRepository` | Class-only codes, enrollments, teacher rosters, and access removal. |

JSON repositories receive configurable paths, while SQL repositories receive a
SQLAlchemy session factory. Both allow isolated tests without production data.

### Shared utilities and configuration

- `src/config.py` centralizes project directories and shared UI constants.
- `src/utils/paths.py` converts between stored project-relative paths and
  resolved filesystem paths.
- `src/utils/logger_setup.py` configures application logging.
- `src/utils/recorded_audio.py` coordinates recorded media playback.
- `src/utils/text_to_speech.py` provides local speech fallback.
- `src/ui/auto_scroll.py` implements reusable middle-click auto-scrolling.

## Data model and storage

Content is organized by stable ID. Each quiz or deck owns its JSON data and
media, while progress is stored separately for each user.

```text
data/
|-- users.json
|-- settings.json
|-- languages/
|-- quizzes.json
|-- flashcard_decks.json
|-- quizzes/
|   `-- <quiz-id>/
|       |-- quiz.json
|       |-- moderation_history.json
|       |-- media/
|       `-- progress/
|           `-- <user-id>.json
`-- flashcards/
    `-- <deck-id>/
        |-- deck.json
        |-- moderation_history.json
        |-- media/
        `-- progress/
            `-- <user-id>.json
```

Index files make content discovery inexpensive and are rebuilt from content
metadata when missing or invalid. Stable content/question/card IDs keep
progress associated with the correct item after renaming or copying.

Media paths are stored project-relative. Editors copy uploaded media into the
owning content folder, keeping quizzes and decks portable as complete units.

## Roles and permissions

| Capability | Student | Teacher | Admin |
|---|---:|---:|---:|
| Study public/enrolled content | Yes | Yes | Yes |
| View own progress | Yes | Yes | Yes |
| Create and edit content | No | Own content | All content |
| Manage class-only invitations/rosters | No | Own content | No |
| Moderate global content | No | No | Yes |
| Change roles or ban accounts | No | No | Yes |

Content lifecycle and visibility are independent:

- Lifecycle: `draft`, `pending_review`, `published`, `rejected`, `banned`.
- Visibility: `private`, `class_only`, `public`.

Class-only and public content follow moderation before becoming available.
Class-only access additionally requires enrollment through an active code.

## Project layout

```text
StudyBuddy/
|-- data/                         # Runtime/sample JSON and content media
|   |-- flashcards/
|   |-- quizzes/
|   `-- languages/
|-- docs/
|   |-- architecture.md
|   |-- testing.md
|   `-- screenshots/
|-- src/
|   |-- main.py                   # Application entry point
|   |-- config.py                 # Shared paths and constants
|   |-- controllers/
|   |   |-- main_controller.py
|   |   |-- quiz_controller.py
|   |   |-- flashcard_controller.py
|   |   |-- quiz_editor_controller.py
|   |   |-- flashcard_editor_controller.py
|   |   `-- profile_statistics_controller.py
|   |-- logic/
|   |   |-- access_control.py
|   |   |-- app_settings.py
|   |   |-- flashcard_logic.py
|   |   |-- question_types.py
|   |   |-- passwords.py
|   |   |-- quiz_logic.py
|   |   |-- translator.py
|   |   `-- user_session.py
|   |-- storage/
|   |   |-- flashcard_repository.py
|   |   |-- invitation_repository.py
|   |   |-- http_user_repository.py
|   |   |-- moderation_repository.py
|   |   |-- postgres_models.py
|   |   |-- postgres_user_repository.py
|   |   |-- quiz_repository.py
|   |   |-- repository_factory.py
|   |   |-- user_repository_contract.py
|   |   `-- user_repository.py
|   |-- api/
|   |   |-- main.py
|   |   `-- schemas.py
|   |-- ui/
|   |   |-- editor/
|   |   |-- main_window.py
|   |   |-- quiz_view.py
|   |   |-- flashcard_viewer.py
|   |   |-- moderation_dialog.py
|   |   `-- account/progress/settings dialogs
|   `-- utils/
|-- styles/
|   |-- style.qss
|   `-- style_light.qss
|-- tests/
|-- migrations/                    # Alembic PostgreSQL schema revisions
|-- requirements.txt
|-- requirements-dev.txt
`-- run_tests.py
```

## Refactoring decisions already applied

- Filesystem paths and configuration were centralized.
- Media paths use one shared conversion/resolution implementation.
- Quiz images use the normalized `image_path` field.
- Matching pairs use explicit `prompt` and `answer` objects.
- Content uses stable-ID folders with owned media and per-user progress.
- Roles, states, visibility, labels, and transitions use shared definitions.
- Repositories accept alternate paths for isolated automated tests.
- Repository factories select local JSON contracts for offline/guest use and
  authenticated HTTP contracts for API sessions without changing UI classes.
- The local FastAPI identity service issues opaque, hashed, revocable sessions;
  `HttpUserRepository` lets the unchanged desktop controller use that
  server-owned boundary without receiving PostgreSQL credentials.
- Relational content histories preserve both a verified actor foreign key and
  the original source actor value. New API writes derive the actor from the
  bearer session, so administrator edits remain attributable to the actual
  editor without changing content ownership.

Git history records the implementation sequence and individual refactoring
changes; this document describes only the architecture that remains relevant.

## Architectural evolution

## Phase 5: Offline Library Foundation

Phase 5 adds a local content-library layer without changing the existing JSON
or HTTP repository contracts. Downloaded entries live under the separate
`cache/library` root (configured from `CACHE_DIR`); bundled demos and existing
`data/` JSON authoring/progress content remain application-owned and are never
copied into that cache.

The library records the content kind, stable content ID, source, visibility,
ownership restrictions, and version/staleness metadata in a manifest. Bundled
content is available to guests and authenticated users. Downloaded public
content remains available after logout. Downloaded class/private content stays
on disk after logout but is locked for guests and other accounts, then becomes
available again for the authorized account.

Only repositories that explicitly advertise `supports_offline_download` can
offer the user an explicit **Keep offline** action; the capability is a source
boundary, not an authorization decision. The read-through `_LibraryRepository`
and cache adapter provide cached read access while preserving the existing
repository's progress and authoring delegation. Cache clearing removes only
entries whose manifest source is `downloaded`; it does not remove bundled
demos, JSON indexes, `data/quizzes`, `data/flashcards`, progress, or authoring
data.

Cache writes use temporary locations followed by atomic replacement. Invalid or
incomplete manifests/content are not exposed, and a failed write leaves an
existing valid entry intact. Remote media is represented safely when it is not
locally available; Phase 5 does not download media, synchronize progress, run
background downloads, or automatically refresh content.

Phase 5 provides the local offline-library foundation. It does not provide full
synchronization or automatic content updates.

### Phase 6 roadmap

Future offline work may add content version/update detection, explicit cache
refresh/update, media download and media-cache management, offline
availability/error handling, and synchronization rules where required. The
design of those behaviors is intentionally deferred.

### Phase 5 hardening notes

- `_LibraryRepository` currently delegates methods generically through
  `__getattr__`; future hardening should explicitly reject writes against
  cached content.
- Selector integration currently performs some library/adapter orchestration;
  future UI work should avoid moving more cache coordination into widgets.

The intended migration keeps the current boundaries:

```text
PyQt6 client
    -> HTTPS API (Python)
        -> PostgreSQL
        -> Object storage for uploaded media
```

The local API now replaces direct database access for authenticated desktop
workflows and enforces authentication, ownership, roles, moderation,
invitations, progress, and attempt rules. Cloud deployment still requires
HTTPS, managed secrets, production hosting, object storage, and explicit
offline synchronization policy; those deployment changes do not require a UI
rewrite.
