# Study Buddy

Study Buddy is a local desktop learning application built with Python and
PyQt6. It combines quizzes, adaptive flashcards, progress tracking, content
editing, class invitations, and role-based moderation in one offline-first
application.

## Features

- Six quiz question types: single choice, multiple choice, true/false, short
  answer, matching, and ordering.
- Adaptive flashcard sessions with weighted review, delayed retries, mastery
  tracking, recorded audio, and offline text-to-speech.
- Per-user quiz and flashcard progress, statistics, search, filtering, and
  reset controls.
- Quiz and flashcard editors with image/audio media management and draft,
  class-only, and public visibility.
- Student, teacher, and administrator roles with account and content
  moderation rules.
- Class-only content shared through revocable invitation codes, with teacher
  roster and access management.
- Persistent light/dark themes and English/French language preferences.
- Local JSON repositories with stable content IDs, content-owned media, index
  recovery, and isolated progress files.

## Screenshots

| Learner dashboard | Progress tracking |
|---|---|
| ![Student dashboard](docs/screenshots/02-student-launcher.png) | ![Progress window](docs/screenshots/09-my-progress.png) |

![Moderation dashboard](docs/screenshots/14-moderation-content.png)

Additional screens are available in [`docs/screenshots/`](docs/screenshots/).

## Technologies

- Python 3.10+
- PyQt6 and Qt Multimedia/Text-to-Speech
- QSS light and dark themes
- JSON persistence
- pytest
- Git and GitHub

## Architecture

```text
PyQt6 UI
   -> Controllers
      -> Learning logic and access rules
         -> Repositories
            -> JSON data, progress, and media
```

The UI delegates application flow to controllers, while repositories own file
access and persistence. Shared configuration and access definitions prevent
paths, roles, visibility values, and lifecycle states from being duplicated.

See [docs/architecture.md](docs/architecture.md) for the detailed component and
storage design.

## Project structure

```text
StudyBuddy/
|-- data/                 # Content, users, settings, progress, and media
|-- docs/                 # Architecture, testing, and screenshots
|-- src/
|   |-- controllers/      # Application coordination
|   |-- logic/            # Learning and permission rules
|   |-- storage/          # JSON repositories
|   |-- ui/               # PyQt6 windows and dialogs
|   `-- utils/            # Paths, logging, audio, and TTS
|-- styles/               # Dark and light QSS themes
|-- tests/                # Automated pytest suite
|-- requirements.txt
`-- run_tests.py
```

The complete layout is documented in
[docs/architecture.md](docs/architecture.md#project-layout).

## Installation

Windows is the primary supported platform. From PowerShell in the project
directory:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m src.main
```

Qt uses the system's configured output device for recorded audio and local
text-to-speech.

## Testing

Install the development dependencies and run:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe run_tests.py
```

The suite currently collects 51 pytest cases covering core learning logic,
grading, repositories, progress, sessions, permissions, invitations, and
selected UI behavior. The suite focuses primarily on core business logic and
the JSON storage layer, while much of the PyQt UI is tested manually.

See [docs/testing.md](docs/testing.md) for the complete test inventory and
testing strategy.

## Future plans

1. Add automated test coverage reporting and use it to identify important
   untested logic and integration paths.
2. Add a separate testing mode with persistent attempt history and best/latest
   results.
3. Introduce a Python API and PostgreSQL data layer, initially hosted locally
   and designed for later cloud deployment.
4. Add multi-device identity, secure remote sessions, account recovery, and
   synchronized progress.

## Documentation

- [Architecture and project structure](docs/architecture.md)
- [Testing strategy and test inventory](docs/testing.md)
- [Screenshot catalog](docs/screenshots/README.md)
