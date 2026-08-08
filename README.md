# Study Buddy

A local PyQt6 study application with quiz, flashcard, and content-editor modes.
Content, settings, and flashcard study progress are stored as JSON files under
`data/`.

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

Create an environment in the project directory and install PyQt6:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install PyQt6
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
  media import, CRUD, and user progress isolation are covered by pytest.

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
only published public content (or content they are explicitly allowed to see);
authors can preview their own non-banned content and admins can inspect all
content. A rejected item is returned to draft for editing before it is
resubmitted for review.

In the editor, **Save Draft** keeps work private (and returns edited published
content to draft). **Publish** means “submit for review”: it saves the current
version and moves it to `pending_review`. The Moderation content tab therefore
shows only pending submissions; admins can publish, reject, or ban the
selected item. Draft and pending states are not exposed as manual moderation
buttons.

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
