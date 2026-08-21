# Testing

The project currently collects **158 pytest cases** and reports **52.7% branch
coverage** across the complete `src` tree. In a normal local run, 157 pass and
the explicitly configured live-PostgreSQL smoke test is skipped. Seven tests are parameterized
quiz-grading cases, and the role-based launcher test covers four roles through
parameters. The permission matrix also covers four roles through parameters,
so the total represents cases rather than 158
unrelated test functions.

The suite focuses primarily on core business logic and the JSON/PostgreSQL/API persistence layers,
with a deliberately small behavioral safety net around important PyQt flows.
Pixel-level rendering and most layout behavior remain manual checks.

## Running the suite

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe run_tests.py
```

The runner appends complete output to `logs/test_results.log`.

It also prints missing line and branch information, writes an interactive HTML
report to `htmlcov/index.html`, and writes a machine-readable Cobertura report
to `coverage.xml`. Both generated reports are ignored by Git. The command also
checks the complete controller and utility layers. It fails if overall
controller branch coverage or the Quiz/Test Mode controller drops below
**80%**, or if utility coverage drops below **90%**.

To run pytest without producing coverage artifacts during a quick local check:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

## Coverage baseline

The namespace-aware baseline, recorded with Python 3.13, 157 passing cases, and
one optional live-database skip, is **52.7% branch coverage** across every
Python module under `src`.
This includes complete PyQt windows, editor screens, the application entry
point, and local audio/TTS adapters—even modules currently at 0%—rather than
excluding difficult areas to make the percentage look higher.

Controller and orchestration code is reported separately because it is much
more valuable to unit test than visual layout code:

| Controller area | Branch coverage |
|---|---:|
| All controllers | **87.5%** |
| Main/session/settings orchestration | 94.9% |
| Flashcard study controller | 87.8% |
| Profile statistics controller | 98.4% |
| Quiz/Test Mode controller | 83.4% |
| Quiz editor controller | 84.5% |
| Flashcard editor controller | 89.5% |

Utility coverage is **98.5%**: path conversion is 100%, logging setup is
96.0%, recorded-audio sequencing is 98.3%, and text-to-speech orchestration is
99.0%. Audio/TTS tests mock Qt's engine and player boundaries; actual speakers,
voice output, codecs, and operating-system device routing remain manual tests.

The report highlights possible later targets rather than unfinished coverage
quotas:

- moderation and class-roster UI actions around permissions and destructive
  confirmations;
- User Repository error handling before it becomes an API/database boundary;
- selected application-entry and translation fallback behavior.

The controller, Quiz/Test Mode controller, and utility floors prevent silent regression in behavior that
is well suited to automated tests. They are not demands to chase industry
percentages; a floor should rise only when meaningful tests justify it.

## Test inventory

| Area | Cases | Test file | What is verified |
|---|---:|---|---|
| Permission matrix | 4 | `test_access_control.py` | Guest, student, teacher, and admin permissions for content creation/editing, class ownership, moderation, and account bans—including negative cases. |
| Application settings | 2 | `test_app_settings.py` | Guest launcher geometry and independent per-window sizes are persisted separately from authenticated-user preferences. |
| Flashcard controller | 6 | `test_flashcard_controller.py` | Per-user progress and guest clearing; mastery/answer transitions and persistence; completed-deck restart; missing-session/deck handling; signed-in invitation delegation. |
| Editor controllers | 6 | `test_editor_controllers.py` | Quiz/deck ownership filtering; blocked student and cross-owner calls; admin access; copy/delete outcomes; question/card CRUD; generated IDs; visibility submission; assessment settings; media/invitation delegation; progress pruning; and save failures. |
| Main controller | 5 | `test_main_controller.py` | Authentication and banned-account messages; registration/session transitions; profile updates; guest/user preference isolation; theme/language routing; validated per-identity window geometry. |
| Identity/content HTTP API and desktop adapters | 14 | `test_identity_api.py` | Health/readiness; identity and bearer-session behavior; server-enforced administrator actions; metadata, class, learning, body, attributed-history HTTP boundaries; and a complete PyQt-facing remote repository workflow. |
| Flashcard learning logic | 6 | `test_flashcard_logic.py` | Weighted correct/wrong mastery formula; mastered-card exclusion; persistent/session counters; 20-card unique shuffled sessions; mistake-weighted selection; delayed retries after wrong answers. |
| Flashcard viewer | 1 | `test_flashcard_viewer.py` | Flip animation changes the visible side at its midpoint. |
| Invitations and roster access | 6 | `test_invitations.py` | Class-only enrollment; code rotation/revocation; owner-only code management; roster progress and grade summaries; per-question analytics; answer-review policy; access removal; invalid, draft, and banned content restrictions. |
| Shared Join with Code UI | 3 | `test_join_with_code_dialog.py` | Guest access to the prompt, callback wiring, success refresh/confirmation, and failure feedback without an incorrect refresh. |
| Login dialog | 3 | `test_login_dialog.py` | Required credentials, single credential emission, password clearing, reusable error state, and protection against Enter accidentally triggering Guest or Sign Up. |
| Registration dialog | 1 | `test_registration_dialog.py` | Password mismatch rejection, normalized account-data emission, and password/confirmation clearing. |
| Role-based launcher UI | 5 | `test_main_window_ui.py` | Guest, student, teacher, and admin dashboards expose only their permitted study, editor, progress, class-roster, moderation, login, and logout actions, with backend status feedback. |
| Moderation | 2 | `test_moderation.py` | Moderation status persists after a content save; lifecycle, visibility, and account-ban access rules. |
| Moderation dialog | 1 | `test_moderation_dialog.py` | Applying a selected interrupted-attempt resolution accepts the dialog and preserves the chosen action. |
| Stored paths | 3 | `test_paths.py` | Project-relative, external absolute, empty, and already-absolute path behavior. |
| Logging setup | 1 | `test_logger_setup.py` | Nested log-directory creation, UTF-8 file output, levels, and safe handler replacement without duplicates. |
| Recorded audio | 2 | `test_recorded_audio.py` | Recorded-file playback, TTS fallback, sequential continuation, empty fields, player errors, pauses, and cancellation through mocked Qt multimedia boundaries. |
| Text to speech | 3 | `test_text_to_speech.py` | Missing/failed engines, text normalization, active-speech cancellation, multi-part sequencing, pauses, completion callbacks, and stale-work rejection through a mocked Qt TTS engine. |
| Profile statistics | 2 | `test_profile_statistics.py` | Combined flashcard/quiz progress aggregation plus named and global reset orchestration. |
| Question normalization | 3 | `test_question_types.py` | Legacy matching-pair migration; clear invalid-pair error; choice shuffling preserves values. |
| Quiz grading | 7 | `test_quiz_grading.py` | True/false, short answer, single choice, multiple choice, matching, correct ordering, and incorrect ordering. |
| Quiz progress and Test Mode | 11 | `test_quiz_progress.py` | Stable question IDs; per-user progress isolation/reset; completed quiz restart; correct/wrong mastery threshold; full-pool Test Mode persistence; configurable timers, due-date expiry, passing grades and finite/unlimited attempt policies; checkpointed abandoned attempts; teacher refund, partial-grade, and zero-resolution rules; public tests remain repeatable. |
| Quiz Controller boundaries | 6 | `test_quiz_controller_boundaries.py` | Missing/empty/banned quiz state, safe inactive-session behavior, empty submissions, navigation edges, timer and review-policy boundaries, idempotent attempt finalization/abandonment, and inactive mastery guards. |
| Quiz and deck selector UI | 4 | `test_quiz_view.py` | Custom quiz rows expose and update the selected state; True/False controls return Boolean values for grading; visibility chips show Public or Class-Only; completed finite-attempt tests are disabled with explanatory feedback. |
| Repositories and JSON storage | 12 | `test_repositories.py` | Folder/index layout, index recovery, media copies, delete/copy behavior, stable IDs, progress pruning, summaries, and user-specific clearing. |
| Content audit history | 5 | `test_content_audit.py` | Actor/role attribution, summaries, append-only behavior, malformed-history recovery, and editor audit delegation. |
| PostgreSQL account repository | 9 | `test_postgres_user_repository.py` | Registration/authentication parity; preferences and profile changes; role/password/ban behavior; legacy JSON import; JSON/PostgreSQL/API backend selection and configuration; optional real-PostgreSQL round trip. |
| PostgreSQL classes and invitations | 3 | `test_postgres_classes.py` | Idempotent class/invitation/member import, code rotation/join/removal, ownership, and available-content filtering. |
| PostgreSQL content metadata | 4 | `test_postgres_content_metadata.py` | Idempotent catalog import, unresolved legacy owners, visibility/access scopes, ownership-preserving admin updates, and teacher authorization. |
| PostgreSQL content bodies/media | 3 | `test_postgres_content_bodies.py` | All six quiz types, cards, role-specific media, integrity metadata, stored-path normalization, idempotency, and validation. |
| PostgreSQL learning state | 4 | `test_postgres_learning.py` | Progress and attempt import/read/write, lifecycle states, answers, guest skipping, and idempotency. |
| PostgreSQL content histories | 2 | `test_postgres_content_history.py` | Idempotent edit/moderation import, unresolved legacy actor preservation, verified actor foreign keys, append operations, and combined reads. |
| Password hashing | 1 | `test_passwords.py` | PBKDF2 round trip, wrong-password rejection, malformed hashes, and missing values. |
| User/session data | 6 | `test_user_session.py` | Stable progress-owner IDs; password hashing; registration preferences; launcher-size preference preservation; per-user subwindow-size isolation; display-name and password updates. |
| Cross-layer user journeys | 2 | `test_user_journeys.py` | Teacher submission/admin publication/student code enrollment/Test Mode completion/roster grade reporting; public practice persistence followed by immediate access removal after an admin ban. |

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

Two explicit user-journey tests extend that integration layer. One follows a
Class-Only assessment from teacher creation through admin publication, student
enrollment and completion, and teacher roster reporting. The other verifies
that public practice persists progress and that a later moderation ban removes
real controller access immediately. Existing invitation and interrupted-attempt
tests cover roster removal and teacher resolution/refund journeys without
duplicating them in another file.

### Permission boundaries

The permission matrix is enforced below the presentation layer. Editor
controllers reject student calls and prevent teachers from copying or deleting
another teacher's content even if those methods are invoked directly. Admins
may edit all content. The moderation repository accepts global lifecycle
decisions only from admins and permits teachers only to submit or return their
own work to draft; the account repository exposes a separate admin-guarded
suspension entry point. Invitation and roster repositories separately enforce
content ownership, publication state, Class-Only visibility, enrollment, and
revoked/invalid codes. UI visibility tests remain a secondary usability check,
not the security boundary.

### Mocking

The server migration now has a real API/database boundary. FastAPI tests inject
isolated SQLite-backed SQLAlchemy repositories and exercise HTTP validation,
hashed sessions, accounts, content ownership and bodies, moderation history,
classes, learning state, and the controller-compatible desktop adapters without
requiring a developer's live PostgreSQL instance. The optional live PostgreSQL
smoke test remains separate and runs only when
`STUDY_BUDDY_TEST_DATABASE_URL` is configured.

## Manual verification

Important event-level behavior now has automated coverage, including form
validation/signals, enrollment outcomes, role-gated navigation, selector state,
card flipping, and interrupted/test-attempt controls. The following remain
manual because they depend heavily on native Qt rendering, complex interaction,
or local-device capabilities:

- complete PyQt windows, dialogs, layouts, and light/dark QSS rendering;
- responsive sizing and visual spacing at different window sizes;
- recorded-audio playback, text-to-speech output, and the selected system
  audio device;
- image preview, zoom, scrolling, and platform-specific behavior;
- less-common visual error paths and end-to-end editor workflows.
