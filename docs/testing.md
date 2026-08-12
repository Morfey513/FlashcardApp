# Testing

The project currently collects **51 pytest cases**. Seven of these are
parameterized quiz-grading cases, so the total represents test cases rather
than 51 unrelated test functions.

The suite focuses primarily on core business logic and the JSON storage layer,
while much of the PyQt UI is currently tested manually.

## Running the suite

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe run_tests.py
```

The runner appends complete output to `logs/test_results.log`.

## Test inventory

| Area | Cases | Test file | What is verified |
|---|---:|---|---|
| Flashcard controller | 3 | `test_flashcard_controller.py` | Per-user progress and guest clearing; mastery advances to the next card; completed decks can be reset and restarted. |
| Flashcard learning logic | 6 | `test_flashcard_logic.py` | Weighted correct/wrong mastery formula; mastered-card exclusion; persistent/session counters; 20-card unique shuffled sessions; mistake-weighted selection; delayed retries after wrong answers. |
| Flashcard viewer | 1 | `test_flashcard_viewer.py` | Flip animation changes the visible side at its midpoint. |
| Invitations and roster access | 4 | `test_invitations.py` | Class-only enrollment; code rotation/revocation; owner-only code management; roster progress; access removal; invalid, draft, and banned content restrictions. |
| Login dialog | 2 | `test_login_dialog.py` | Login error state clears before reopening; Enter cannot accidentally trigger Guest or Sign Up. |
| Moderation | 2 | `test_moderation.py` | Moderation status persists after a content save; lifecycle, visibility, and account-ban access rules. |
| Stored paths | 2 | `test_paths.py` | Project-relative/absolute path round trip; empty stored paths. |
| Profile statistics | 1 | `test_profile_statistics.py` | Combined flashcard and quiz progress is read correctly. |
| Question normalization | 3 | `test_question_types.py` | Legacy matching-pair migration; clear invalid-pair error; choice shuffling preserves values. |
| Quiz grading | 7 | `test_quiz_grading.py` | True/false, short answer, single choice, multiple choice, matching, correct ordering, and incorrect ordering. |
| Quiz progress | 4 | `test_quiz_progress.py` | Stable question IDs; per-user progress isolation/reset; completed quiz restart; correct/wrong mastery threshold. |
| Repositories and JSON storage | 12 | `test_repositories.py` | Folder/index layout, index recovery, media copies, delete/copy behavior, stable IDs, progress pruning, summaries, and user-specific clearing. |
| User/session data | 4 | `test_user_session.py` | Stable progress-owner IDs; password hashing; registration preferences; display-name and password updates. |

## Test design

### Fixtures

Repository tests use pytest's built-in `tmp_path` fixture. Each test receives a
fresh temporary JSON/data directory, so it cannot alter the sample content or
saved progress in the project `data/` directory.

### Integration-style tests

Invitation tests intentionally connect several local layers in one temporary
setup: moderation, invitation codes, content selector access, progress, and
teacher roster removal. They verify that these repositories work together
without relying on the real project data.

### Mocking

The current application has no remote API, database service, or clock boundary
to mock. Once the PostgreSQL/API and multi-device roadmap work begins, unit
tests should mock HTTP/database clients and separate server integration tests
should exercise real transactions and permission boundaries.

## Manual verification

The following are currently checked manually because they depend heavily on
native Qt rendering, user interaction, or local-device capabilities:

- complete PyQt windows, dialogs, layouts, and light/dark QSS rendering;
- responsive sizing and visual spacing at different window sizes;
- recorded-audio playback, text-to-speech output, and the selected system
  audio device;
- image preview, zoom, scrolling, and platform-specific behavior;
- less-common visual error paths and end-to-end editor workflows.
