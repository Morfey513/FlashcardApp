# Study Buddy

A local PyQt6 study application with quiz, flashcard, and content-editor modes.
Content, settings, and flashcard study progress are stored as JSON files under
`data/`.

## Technology

- **Python 3.10+** — application, learning logic, controllers, repositories,
  and tests.
- **PyQt6** — native desktop user interface, dialogs, media playback, and
  offline text-to-speech.
- **QSS** — application-owned light and dark theme stylesheets in `styles/`.
- **JSON files** — local content, user accounts, preferences, progress,
  moderation metadata, enrolments, and indexes; no server or database is
  required for the current offline version.
- **pytest** — automated logic, repository, controller, and UI-component
  verification.

## Architecture

```text
PyQt6 UI and dialogs
        ↓
Controllers (application flow and permissions)
        ↓
Learning logic and shared access rules
        ↓
Repositories / data-access layer
        ↓
JSON storage under data/ (content, media, users, settings, progress)
```

The UI avoids direct filesystem access. Controllers coordinate user actions,
repositories own JSON reads/writes and media import, and `src/config.py`
centralizes filesystem locations and shared configuration.

## Current capabilities

- Quiz mode supports short answer, single-choice, multiple-choice, true/false,
  matching, and ordering questions. Questions and applicable answers can be
  shuffled.
- Flashcard mode records correct and wrong answers, allows manual mastery after
  the card is eligible, and excludes mastered cards from a new study session.
- Flashcards support per-field recorded audio, with local offline Qt
  text-to-speech as a fallback when a recording is absent.
- Teacher/admin accounts can access quiz and flashcard editors; students and
  guests can study only.
- Editors can create, copy, update, and delete quizzes/decks, including media
  paths for images and audio.
- Teachers can make an item Class-Only, generate or rotate its readable invite
  code, and copy that code from the editor. Signed-in learners can join a
  published Class-Only quiz or deck from either study menu; rotating a code
  blocks new uses of the old code without removing existing enrolments.
- Teachers have a Class Management view for their active Class-Only quizzes
  and decks. It shows enrolled students, per-item mastery totals, invitation
  code copy controls, and a confirmed remove-access action.
- Theme and language preferences persist separately for guest mode and each
  signed-in account. Changing language refreshes the main window, settings
  panel, login dialog, and registration dialog without restarting.
- Signed-in users have Account Settings for their display name, password
  change, and their own flashcard/quiz progress reset actions.
- Signed-in users can open My Progress to review overall and per-item
  flashcard/quiz mastery plus correct and wrong learning attempts. Large
  collections are collapsed by default, expand in 50-item batches, and support
  text search, mastery filtering, and middle-click auto-scroll.
- Quiz and flashcard repositories rebuild their index files if an index is
  missing or invalid, and permanently backfill missing content IDs.

## Screenshots

Screenshots are generated from the real Windows UI so they use the installed
system fonts and current content. With the app closed, run:

```powershell
.\.venv\Scripts\python.exe tools\capture_readme_screenshots.py
```

The utility captures every top-level dialog and primary screen in
`docs/screenshots/`. Review and commit the images when they reflect the
current UI. This avoids committing stale test data or headless renders with
missing fonts.

## Project layout

```text
project/
|-- data/
|   |-- quizzes/
|   |   `-- <quiz-id>/
|   |       |-- quiz.json
|   |       `-- media/
|   |-- flashcards/
|   |   `-- <deck-id>/
|   |       |-- deck.json
|   |       |-- media/
|   |       `-- progress/
|   |           `-- <user-id>.json
|   |-- languages/
|   |-- quizzes.json                 # quiz index
|   `-- flashcard_decks.json         # deck index
|-- src/
|   |-- main.py                      # application entry point
|   |-- config.py                    # shared paths and UI constants
|   |-- controllers/
|   |-- logic/
|   |-- storage/
|   |-- ui/
|   `-- utils/
`-- styles/
    |-- style.qss                    # dark theme
    `-- style_light.qss              # light theme
```

## Running the application

### Requirements and dependencies

- Python 3.10 or newer (the project is currently developed with Python 3.13).
- Windows is the primary supported platform. Qt uses the system's configured
  audio output for recorded audio and local text-to-speech.
- Runtime dependencies are listed in `requirements.txt`; development and test
  dependencies extend them in `requirements-dev.txt`.

Create an environment in the project directory and install the runtime
dependencies:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m src.main
```

## Running tests

Install the development dependency and use the project test runner:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe run_tests.py
```

The runner prints the result and appends the complete output to
`logs/test_results.log`.

### Test approach

- **pytest unit tests** cover learning logic, grading, repositories, media
  storage, index recovery, authentication/session rules, content moderation,
  and UI-component behaviour that can run off-screen.
- **Fixtures:** pytest's built-in `tmp_path` fixture gives every repository
  test a clean temporary JSON/data directory, so tests never modify the
  project's sample content or a user's saved progress.
- **Local integration coverage:** invitation tests combine the moderation,
  invitation, selector-access, progress, and roster repositories in one
  temporary data setup. They verify owner-only code control, invalid and
  rotated/revoked codes, enrollment removal, and that draft, banned, or
  unpublished content cannot be enrolled in or shown in an active roster.
- **Mocking:** the current application has no remote services, clock, or
  network boundary to mock. When server-backed identity or multi-device
  support is introduced, HTTP/database clients should be mocked in unit tests
  and covered by separate server integration tests.

## Version-control notes

The repository keeps sample content, media, language files, and the test
accounts needed to run the application. It ignores machine-specific settings,
learning-progress files, virtual environments, IDE configuration, logs, and
Python/test caches. If any of those files were committed before being ignored,
Git will continue tracking them until they are explicitly removed from the Git
index with `git rm --cached`.

## Refactoring

### Completed

- **Shared media-path handling:** `src.utils.paths` now handles conversion to
  stored project-relative paths and resolution back to absolute paths. The
  controllers and repositories use it instead of duplicate implementations.
- **Quiz image schema:** quiz content now uses `image_path` only. Legacy
  `image` fields are migrated automatically when a quiz is loaded or saved.
- **Matching-pair schema:** matching data now uses explicit
  `{ "prompt": ..., "answer": ... }` objects. Legacy `{ "1": ..., "2": ... }`
  pairs are validated and migrated automatically; the existing quiz data has
  been migrated.
- **Content-owned storage:** each deck and quiz now has a stable-ID folder
  containing its JSON and copied media. Deck progress is stored alongside the
  deck in a separate file for each user.
- **Test coverage:** logic, grading, paths, repositories, index recovery,
  media import, CRUD, user progress isolation, moderation, invitations, and
  roster access rules are covered by pytest.
- **Shared access definitions:** `src.logic.access_control` is the canonical
  source for roles, account states, content lifecycle states, visibility
  values, labels, and lifecycle transition rules. Storage validation and
  editor/moderation choices import it rather than maintaining independent
  lists.

### Next refactoring candidates

1. **Re-evaluate SQLite only when required.** JSON storage is suitable for the
   current small local-data application. Do not add a database merely for
   architecture's sake.

## New features to implement

1. **Expand identity features.** Login, registration, guest mode, per-account
   theme/language preferences, role-based editor access, and local salted
   password hashes, and personal learning statistics exist. Administrative
   user management and multi-device security do not.
2. **Optional testing-mode history.** Keep all quiz questions available and
   persist completed attempts per user, including best/latest score and attempt
   count. This is intentionally separate from learning-mode mastery, because
   showing the correct answer before manually marking a question learned is
   useful for study but would distort a formal test result.

## Project milestones

1. **Screenshots:** add representative light- and dark-theme screenshots to
   the README, covering the launcher, study views, editor, progress, and
   moderation screens.
2. **Requirements and dependencies:** maintain a clear production dependency
   list and a separate development/test dependency list, with installation
   instructions that match them.
3. **Git history:** continue creating small, descriptive commits for completed
   changes and push the history to the GitHub repository.
4. **CI/CD:** add a GitHub Actions workflow that installs dependencies and runs
   the off-screen PyQt test suite for every push and pull request.
5. **Database:** reassess the JSON storage model once shared users, classes,
   invitations, or larger data volumes require stronger querying and
   concurrent-write support. SQLite is the likely first migration target, not
   an immediate requirement.

### Implemented: deck progress and reset

The flashcard selection screen now shows **manually mastered / total** for each
deck, with a progress bar. Each row has a confirmed reset action that removes
only the active user's progress for that deck. In guest mode, **Clear Guest
Progress** removes only the guest's progress across all decks. Other users'
progress is unaffected. Granular resets are now centralized in **My Progress**:
each deck/quiz can be reset there, and its footer offers reset-all controls for
flashcards, quizzes, or both. Flashcard and quiz selection screens provide a
non-destructive **Manage Progress** shortcut. Account Settings offers only the
global clear action, while guest Settings offers one **Clear Guest Learning
Data** action; none of these actions affect account credentials or preferences.

### Implemented: adaptive flashcard sessions

Each study session now takes up to 20 unique, non-mastered cards. Selection is
randomized and gives more weight to cards with weaker correct/wrong history.
An incorrect answer adds one delayed retry later in the same session. The
manual mastery button appears when `correct - wrong * 1.5 >= 5`.

### Implemented: flashcard text-to-speech

Flashcards provide an offline text-to-speech button in the card's top-left
corner. It uses a local Qt speech engine when available and reads the currently
visible side: the front reads its prompt, while the back reads its answer and
optional description with a short pause between them. It stops when the card
is flipped or replaced. Hints use a translucent card overlay with their own
speaker control that reads only the hint.

### Implemented: flashcard recorded audio

Each flashcard may optionally store recordings for its `front`, `back`,
`hint`, and `description` fields. Recordings are copied into the owning deck's
`media/` folder by the editor and stored in the card's `audio` object. The same
speaker controls play the matching recording first, then fall back to offline
TTS for any missing field. Back-side audio plays the answer and description in
order, with a short pause between them.

### Implemented: quiz learning progress

Quiz results now let a learner manually mark individual questions as mastered.
Mastery is stored per quiz and per user, and mastered questions are excluded
from future learning sessions. The quiz menu shows mastered / total, offers a
per-quiz reset, and provides a clear-all action in both the menu and Settings.
Saving quiz edits prunes progress for questions that no longer exist.

### Implemented: local roles and moderation lifecycle

The local user store supports **student**, **teacher**, and **admin** roles,
plus an admin-controlled account status (`active` or `banned`). The main
launcher groups study actions separately from staff actions; only admins see
the **Moderation** dashboard. Its **Content** tab manages content lifecycle
states, while the **Users** tab can change roles or ban/unban accounts.

Each deck and quiz records moderation metadata and an append-only
`moderation_history.json` beside its data file. Content follows the states
`draft`, `pending_review`, `published`, `rejected`, and `banned`. Learners see
only published public content (or content they are explicitly allowed to see).
Creators can see their own draft, rejected, and banned work in the selector so
they can read its moderation reason; banned content cannot be opened for study.
Admins inspect all lifecycle states through Moderation. A rejected item is
returned to draft for editing before it is resubmitted for review.

Lifecycle is separate from visibility: **Draft (Private)** is creator-only,
**Class-Only** is available to enrolled students via a locally stored invite
code, and **Public** is available to all learners after approval. Class-Only
content follows the same moderation submission path as Public content. Teachers
can search their own active Class-Only items and enrolled learners, filter by
content type, copy the active code, and remove a learner from a specific item.
Invite codes are deliberately stored in plain text in this offline prototype because
the owner must be able to view and copy them; a server-backed version should
store only a hash.

In the editor, saving as **Draft** keeps work private (and returns edited
published content to draft). The editor's **Visibility** selector chooses Draft (Private),
Class-Only (Invite Code), or Public (Submit for Review), then a single **Save
Changes** action applies that choice. Class-Only and Public save the current
version and move it to `pending_review`. The Moderation Content tab opens on
pending submissions, and can also filter and search every lifecycle state by
content title or author. Admins can publish, reject, or ban a pending item;
unbanning returns it to draft so its creator must edit and resubmit it.

## Bugs and verification status

### Resolved: deck-selection controls did not fit at the current window width

The flashcard viewer now uses a 750 px fixed width, leaving space for the
bottom progress-reset control, **Back**, and **Start** on one line.

### Resolved: flashcard study action row overflow

**Mark as Mastered** now appears in a reserved top-right slot beside the card
counter. The action row contains only **I Don't Know**, the hint control, and
**I Know This**, so its fixed-width controls fit within the flashcard window.
The counter remains centered whether or not the mastery control is visible.

The flashcard study window was then reduced to 750 × 770 px. Its navigation
buttons use the earlier, larger and closer spacing, while the card, mastery
button, and primary correct-action button retain a shared right edge.

### Resolved: QLineEdit and QTextEdit theme styling

Both themes explicitly style `QLineEdit` and `QTextEdit`, including their focus
states, after the general `QFrame` rule. A rendered off-screen PyQt6 check
confirmed that both widgets have normal borders and show the blue focus border
in dark and light themes. No change is currently required.

### Resolved in source: transparent dropdown in the light theme

The light stylesheet assigns an opaque background to both the standard combo
box popup (`QComboBox QAbstractItemView`) and the settings combo popup
(`QComboBox#settings_combo QAbstractItemView`). The original transparent-popup
note is therefore no longer an active source issue. Verify again only if it
reappears on a particular Windows/Qt version.

### QSS and layout maintenance candidates

- Quiz-editor object names currently inherit generic styles because dedicated
  `quiz_editor_*` selectors have not yet been added to both QSS files.
- A few legacy-mastery selectors are intentionally retained for compatibility;
  remove them only after the related UI is retired.
- Fixed window and button dimensions should be checked again when adding more
  languages, high-DPI support, or larger accessibility fonts.
- Initial stylesheet loading has a readable fallback, but applying a missing
  stylesheet during a later theme switch currently only logs the failure.

## Historical notes

Older roadmap notes described missing repositories, flashcard logic, answer
shuffling, role-based access, centralized base/data paths, runtime-only IDs,
and missing UI retranslation. The corresponding features are now present.
