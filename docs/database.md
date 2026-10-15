# PostgreSQL migration

Study Buddy completed its first repository-by-repository server handoff. JSON
remains the explicit offline/demo backend; authenticated API mode routes active
desktop domains through FastAPI, whose repositories own PostgreSQL access.

## Current migration slices

The user/account slice now includes:

- a storage-independent user-repository contract;
- the existing JSON implementation;
- an opt-in SQLAlchemy PostgreSQL implementation;
- Alembic tables for users, settings, future server sessions, and account
  moderation history;
- preserved legacy user identifiers during the repository migration;
- a local FastAPI identity service with hashed, revocable bearer sessions;
- repository parity, API behavior tests, and optional live-PostgreSQL tests.

The content-metadata slice now adds:

- relational `quizzes` and `flashcard_decks` catalog tables;
- stable content IDs, names, lifecycle, visibility, and ownership;
- quiz assessment metadata (timer, grade, attempt limit, due date, review policy);
- nullable verified-owner foreign keys plus `source_owner_id` for bundled
  `legacy` content that has no account row;
- the transitional JSON source path, while questions/cards/media remain in
  their current per-content folders;
- PostgreSQL content metadata catalogs for the bundled and server content.
- authenticated FastAPI metadata reads/writes and a desktop HTTP adapter;
- server-side ownership checks that preserve the original owner during an
  administrator edit and reject cross-owner teacher updates.

The class-access slice now adds:

- relational classes and quiz/deck assignment tables;
- revocable invitation history with one active code per imported item;
- active/removed class memberships with enrollment timestamps;
- idempotent migration of existing embedded invite codes and rosters;
- authenticated join, rotate-code, roster, and remove-access API operations;
- Class-Only content discovery based on active PostgreSQL membership.

The learning-state slice now adds:

- per-card flashcard progress and per-question quiz progress for authenticated users;
- durable quiz attempts, including submitted, interrupted, refunded, timed-out,
  and teacher-resolved states;
- per-question JSON answers with ordering and response-time metadata;
- durable authenticated learning-state storage;
- authenticated progress and attempt API endpoints plus a desktop HTTP adapter.

Guest progress and guest attempts deliberately remain local. Guests have no
database identity, so this server boundary skips their local files instead of
creating a synthetic account.

The content-body/media slice now adds:

- relational flashcards and quiz questions for all six supported question types;
- normalized choices, ordering entries, matching pairs, and short-answer variants;
- composite `(quiz_id, question_id)` identity because copied legacy quizzes can
  legitimately contain the same question ID;
- media attachment roles for question images and flashcard image/front/back/
  hint/description audio;
- file size, MIME type, and SHA-256 integrity metadata while binary files remain
  in local storage;
- authenticated body reads and owner/admin writes through FastAPI.

The content-history slice now adds:

- append-only quiz/deck edit history with the acting user, role, timestamp,
  action, summary, and changed-field list;
- append-only quiz/deck moderation history with moderator, action, note, and
  timestamp;
- nullable actor foreign keys plus the original `source_actor_id`, so imported
  `legacy` events remain attributable without inventing database users;
- authenticated owner/admin history reads and server-side audit records for
  future body and lifecycle updates;
- append-only per-content history storage.

Invitation codes remain retrievable because the teacher UI must copy and share
the active code. PostgreSQL stores both the formatted display value and a
normalized unique value used for case/separator-insensitive lookup. Rotation
revokes the previous row rather than deleting history.

PostgreSQL now owns the server-ready content envelope, ownership catalog,
access rules, authenticated learning state, relational question/card bodies,
and attributed histories. In API mode the PyQt study, editor, moderation,
progress, invitation, roster, and account workflows use controller-compatible
HTTP repositories; server authorization remains authoritative. Physical media
files remain in server-local storage while PostgreSQL stores their attachment
and integrity metadata. Guest learning state intentionally remains local
because guests have no server identity.

Authenticated metadata endpoints are available under
`/api/v1/content/metadata`. `available` and `owned` scopes are filtered by the
server; the `all` scope is administrator-only. Class enrollment and
authenticated learning endpoints are available under `/api/v1/classes`,
`/api/v1/progress`, and `/api/v1/quizzes/{quiz_id}/attempts`.

The PyQt client can use PostgreSQL directly for this transitional local stage.
The FastAPI service and desktop HTTP adapter now provide the preferred first
server boundary, so PyQt no longer needs database credentials in API mode.

## Phase 3: Server-authoritative assessment service

Phase 3 adds a server-authoritative Class-Only assessment flow without changing
Study Mode, offline JSON behavior, or legacy generic attempts. An assessment
freezes a randomized question/presentation snapshot at start, including
question order, choices, matching options, and ordering items. Resume reads
that snapshot rather than live or newly randomized source content.

Learners receive answer-safe projections and submit responses for server-side
grading. Deadlines finalize attempts as timed out using persisted responses and
frozen grading keys; post-expiry responses cannot mutate the attempt. The
assessment mutation transaction locks the parent attempt with PostgreSQL
`SELECT ... FOR UPDATE`, serializing checkpoint, submit, timeout, and
snapshot-aware teacher/admin resolution operations.

Terminal results honor `immediate`, `after_due_date`, and `never` answer-review
policies. Generic quiz-body access redacts grading material for learners while
authorized teachers and administrators retain required source-content access.
Snapshot-backed attempts are protected from generic mutation routes, while
legacy attempts with a null assessment snapshot remain compatible.

Migration `20260823_0007_assessment_foundation` is additive: it introduced the
nullable assessment snapshot and frozen question rows without changing the
canonical question tables or requiring historical-attempt backfill.

The implementation is covered by focused assessment/API tests and a dedicated
PostgreSQL concurrency suite covering concurrent checkpoint/submit races and
teacher resolution. Final evidence is 39 focused Phase 3/API tests passed, 196
tests passed in the full suite with no skips, and 15 dedicated PostgreSQL
concurrency tests passed. The full run reported four non-blocking Alembic
deprecation warnings.

## Phase 4: Server-authoritative Class-Only Test Mode

Authenticated desktop API mode now starts, resumes, checkpoints, and submits
Class-Only Test Mode assessments through the Phase 3 server-authoritative
workflow. Frozen randomized question, option, matching, and ordering
presentation is preserved across resume; grading and terminal results remain
server-owned. Remote assessments are resumable and use safe client-side
presentation/input handling without exposing grading keys.

JSON/offline Test Mode, Practice Mode, and legacy generic attempts remain
unchanged. API mode requires the running FastAPI service. No schema or
migration changes were required for this integration milestone.

Final validation: **53 focused Phase 4 tests passed with no skips**; the full
suite passed **205 tests with no skips**; PostgreSQL validation executed
successfully against the dedicated `study_buddy_test` database; and four
Alembic deprecation warnings were non-blocking.

## Phase 5: Offline Library Foundation

Phase 5 is a local cache/library layer, not a database or synchronization
change. Downloaded content uses the separate application cache root and
manifest metadata; it is not written into the JSON authoring stores and does
not add PostgreSQL tables, models, routes, or migrations. Bundled demos and
existing JSON content remain independent and survive **Clear Downloaded Data**.

The cache records source, visibility, ownership restrictions, and version
metadata so public content can remain usable after logout while class/private
content is locked until its authorized account returns. Cache writes are
atomic, and incomplete or invalid entries are ignored without replacing a
previous valid entry. Phase 5 does not implement media downloading or
background synchronization.

## Phase 6A: Explicit content refresh

Phase 6A adds a server-authoritative `content_version` column to quiz and
flashcard-deck metadata. Metadata and body mutations advance the revision in
the same PostgreSQL transaction when effective content or media references
change. The authenticated metadata and body APIs expose the revision so the
client can detect newer downloaded content and perform an explicit refresh.
The client rejects metadata/body revision mismatches and retains the previous
valid cache on failed or inconsistent replacement. Media binaries and learning
state remain outside this phase.

## Local setup on Windows

PostgreSQL commands below assume PostgreSQL 17 is installed. Start its Windows
service from an **Administrator PowerShell** if it is not already running:

```powershell
Start-Service postgresql-x64-17
pg_isready -h 127.0.0.1 -p 5432
```

For a clean PostgreSQL instance, supply
`STUDY_BUDDY_BOOTSTRAP_ADMIN_URL` and `STUDY_BUDDY_TEST_DATABASE_URL` in the
environment through your shell, CI secret store, or process launcher before
running bootstrap. The bootstrap command reads process environment only; it
does not load `.env` or write a credentials file. Do not enter
password-bearing commands into shell history.
The administrator URL must use PostgreSQL's `postgres` maintenance database
and have permission to create the application role and database. The
application URL must name exactly `study_buddy_test`; its username becomes
that database's owner. Both URLs must name the same PostgreSQL host and port.

Install dependencies, then bootstrap the dedicated disposable server database:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe tools\bootstrap_server.py
```

`bootstrap_server.py` first verifies the administrator connection, creates the
login role and `study_buddy_test` database when absent, and refuses an existing
database owned by another role. It never changes a role password on a rerun.
It then verifies the target, runs `alembic upgrade head`, imports the bundled
demo quiz and flashcard deck, starts the local API on `127.0.0.1:8000` if
needed, and checks both `/health` and `/ready`. It is safe to run again: a
verified canonical demo is a no-op, preserving its revision and managed media.
The tool refuses conflicting metadata or body content and refuses an API on
port 8000 unless that API was launched by a prior bootstrap run.
Use `--port 8001` to launch and verify a separate local bootstrap API when
port 8000 is occupied.

The manual equivalent remains useful for diagnosis. Set
`STUDY_BUDDY_DATABASE_URL` temporarily to the same disposable URL, run
`python -m alembic upgrade head`, and start
`python -m uvicorn src.api.main:app --host 127.0.0.1 --port 8000`. The
bootstrap tool uses the current PostgreSQL repositories directly to load the
bundled data.

### Manual database provisioning fallback

Use this only to diagnose bootstrap permissions. PostgreSQL's native tools
prompt for passwords without putting them in command history; bootstrap
normally creates the disposable role/database itself.

```powershell
createuser -h 127.0.0.1 -U postgres --login --pwprompt study_buddy_test
createdb -h 127.0.0.1 -U postgres --owner=study_buddy_test study_buddy_test
```

## Back up and restore PostgreSQL

Use PostgreSQL's native tools for complete database backup and recovery. Store
dumps outside the repository and protect them as application data; never commit
database dumps or credentials to Git.

Create a custom-format backup (the password is requested interactively):

```powershell
pg_dump -h <source-host> -p 5432 -U study_buddy -d study_buddy `
  --format=custom --no-owner --no-privileges --file <outside-repository>\study_buddy.dump
```

Restore into an existing `study_buddy` database while the API and other clients
are stopped:

```powershell
pg_restore -h <target-host> -p 5432 -U study_buddy -d study_buddy `
  --clean --if-exists --no-owner --no-privileges --single-transaction `
  --exit-on-error <outside-repository>\study_buddy.dump
```

### Backup/restore drill

Run the automated drill only with the disposable bootstrap credentials already
used by `tools\bootstrap_server.py`. It creates two new uniquely named scratch
databases, migrates and seeds the source, registers a test account, executes
the `pg_dump` and `pg_restore` commands above with their documented flags, and
verifies the restored demo IDs, content versions, complete question and card
bodies, and account authentication. It also checks the restored API's `/health`,
`/ready`, authenticated login, and demo metadata and body endpoints. It removes
both scratch databases, roles, and its OS-temporary dump file even when the
drill fails.

```powershell
.\.venv\Scripts\python.exe tools\backup_restore_drill.py
```

The drill requires `STUDY_BUDDY_TEST_DATABASE_URL` and
`STUDY_BUDDY_BOOTSTRAP_ADMIN_URL`, plus `pg_dump` and `pg_restore` on `PATH`.
It never reads, dumps, or restores `study_buddy` or `study_buddy_test`; those
environment credentials are only a template for fresh `study_buddy_backup_*`
scratch databases. PostgreSQL passwords are passed to child tools only through
their `PGPASSWORD` process environment.

Last confirmed passing run: **2026-10-14**, source revision
`6cf2f9d2f1ad06530e3f487f55036c923461f25b`, Python **3.13.1**. From the
repository root, with the disposable URLs in the local ignored `.env`:

```powershell
.\.venv\Scripts\python.exe -c "from dotenv import load_dotenv; load_dotenv(); import pytest; raise SystemExit(pytest.main(['-q', 'tests/test_backup_restore_drill.py']))"
```

Result: **10 passed, 0 failed, 0 skipped**, 3 non-failing Alembic warnings;
coverage was not collected. The configured `study_buddy_test` URL supplied
credentials only; the live tests dumped and restored distinct, newly created
`study_buddy_backup_<random>` databases and used the `postgres` maintenance
database for provisioning and cleanup. No non-disposable database was a dump
source or restore target.

## Run the local API manually

The bootstrap command starts and verifies the API automatically. For manual
diagnosis, start a development server bound only to this computer:

```powershell
.\.venv\Scripts\python.exe -m uvicorn src.api.main:app --host 127.0.0.1 --port 8000 --reload
```

Useful local URLs:

- `http://127.0.0.1:8000/health` checks that the API process is running;
- `http://127.0.0.1:8000/ready` verifies that PostgreSQL accepts a query;
- `http://127.0.0.1:8000/docs` opens FastAPI's interactive API documentation.

The first endpoints cover registration, login/logout, the current profile,
preferences, display-name changes, and password changes. Login returns an
opaque bearer token; only its SHA-256 hash is stored in `user_sessions`, and
logout revokes it. Banned accounts cannot log in or continue using an existing
session.

This local HTTP service is a migration/development boundary, not an Internet
deployment. Keep it on `127.0.0.1`; cloud or LAN exposure requires HTTPS,
secret management, restricted CORS/hosts, and production server configuration.

### Connect the desktop through the API

After bootstrap reports success, start the desktop in a second PowerShell
window with the local API selected:

```powershell
$env:STUDY_BUDDY_STORAGE = 'api'
$env:STUDY_BUDDY_API_URL = 'http://127.0.0.1:8000'
.\.venv\Scripts\python.exe -m src.main
```

This desktop process does not need `STUDY_BUDDY_DATABASE_URL`; only the API
process receives PostgreSQL credentials. Accounts, quiz/deck discovery and
editing, moderation, class invitations and rosters, progress, test attempts,
media imports, and audit history use HTTP in this mode. The server derives the
actor and permissions from the bearer session instead of trusting desktop role
or actor fields.

Set `STUDY_BUDDY_STORAGE` back to `json` for the offline application, or to
`postgresql` for the transitional direct-database mode.

The launcher displays `Online` only when its configured API/database passes a
readiness check. JSON mode and an unavailable API display `Offline`; the check
runs in the background and does not freeze PyQt.

## Transitional ID decision

Existing content refers to account IDs such as `"1"`, `"2"`, and UUID strings.
The first PostgreSQL migration therefore uses `VARCHAR(64)` user IDs and
preserves them during import. New registrations receive UUID strings.

Converting every account and content owner reference to PostgreSQL's native
`UUID` type remains possible, but it must happen atomically when the content
repositories are migrated. Converting users alone would break JSON ownership.

## Security boundary

Database credentials are local/server secrets. They must never be embedded in
the PyQt build or committed. Direct PyQt-to-PostgreSQL access is transitional;
the final architecture is:

```text
PyQt client -> HTTPS/JSON -> FastAPI -> repositories -> PostgreSQL
```
