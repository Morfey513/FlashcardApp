# Architecture

Study Buddy is currently an offline-first PyQt6 desktop application. It uses a
layered design so the present JSON persistence can later be replaced by an API
and PostgreSQL without rewriting the learning UI.

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
JSON content, users, progress, indexes, and media
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

`src/storage/` owns JSON reads/writes and content discovery:

| Repository | Responsibility |
|---|---|
| `QuizRepository` | Quiz metadata, questions, indexes, progress, and quiz-owned media. |
| `FlashcardRepository` | Deck metadata, cards, indexes, per-user progress, and deck-owned media. |
| `UserRepository` | Local accounts, password hashes, preferences, roles, and account status. |
| `ModerationRepository` | Content lifecycle, visibility, review history, and selector access. |
| `InvitationRepository` | Class-only codes, enrollments, teacher rosters, and access removal. |

Repositories receive configurable base/index paths, which allows tests to use
isolated temporary directories instead of the real project data.

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
|   |   |-- quiz_logic.py
|   |   |-- translator.py
|   |   `-- user_session.py
|   |-- storage/
|   |   |-- flashcard_repository.py
|   |   |-- invitation_repository.py
|   |   |-- moderation_repository.py
|   |   |-- quiz_repository.py
|   |   `-- user_repository.py
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

Git history records the implementation sequence and individual refactoring
changes; this document describes only the architecture that remains relevant.

## Planned server evolution

The intended migration keeps the current boundaries:

```text
PyQt6 client
    -> HTTPS API (Python)
        -> PostgreSQL
        -> Object storage for uploaded media
```

The API will replace direct repository access from the desktop client and
enforce authentication, roles, moderation, invitations, and progress rules on
the server. Keeping UI, logic, and persistence separated now reduces the
amount of client code that must change during that migration.
