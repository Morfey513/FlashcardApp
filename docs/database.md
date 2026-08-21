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
- an idempotent JSON-user import command;
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
- an idempotent content metadata import command.
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
- idempotent import of existing authenticated learning files;
- authenticated progress and attempt API endpoints plus a desktop HTTP adapter.

Guest progress and guest attempts deliberately remain local. Guests have no
database identity, so the importer reports and skips their files instead of
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
- an idempotent import of the existing per-content history files.

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

## Local setup on Windows

PostgreSQL commands below assume PostgreSQL 17 is installed. Start its Windows
service from an **Administrator PowerShell** if it is not already running:

```powershell
Start-Service postgresql-x64-17
pg_isready -h 127.0.0.1 -p 5432
```

Create separate application and test databases using your PostgreSQL
administrator account. Enter passwords interactively; do not put them in Git:

```powershell
psql -U postgres -h 127.0.0.1
```

```sql
CREATE ROLE study_buddy LOGIN PASSWORD 'choose-a-local-password';
CREATE DATABASE study_buddy OWNER study_buddy;

CREATE ROLE study_buddy_test LOGIN PASSWORD 'choose-another-local-password';
CREATE DATABASE study_buddy_test OWNER study_buddy_test;
```

Copy `.env.example` to the ignored `.env` file and replace its example
passwords. Study Buddy loads this local configuration automatically, while
explicit shell/CI variables still take precedence. The real `.env` file is
ignored by Git and must never be committed.

```powershell
Copy-Item .env.example .env
notepad .env
```

Install dependencies and apply migrations:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m alembic upgrade head
```

Import existing JSON accounts without changing their IDs or password hashes:

```powershell
.\.venv\Scripts\python.exe tools\migrate_users_to_postgres.py
```

Then import quiz/deck metadata and ownership. Run the account import first so
real owner IDs can satisfy their foreign keys; bundled `legacy` content remains
explicitly unresolved instead of creating a fake account:

```powershell
.\.venv\Scripts\python.exe tools\migrate_content_metadata_to_postgres.py
```

After metadata exists, migrate embedded codes and enrollments:

```powershell
.\.venv\Scripts\python.exe tools\migrate_classes_to_postgres.py
```

Finally, import authenticated progress and attempt history. Guest files are
reported and skipped because they intentionally remain offline/local:

```powershell
.\.venv\Scripts\python.exe tools\migrate_learning_state_to_postgres.py
```

Import question/card bodies and media metadata after the content catalog exists:

```powershell
.\.venv\Scripts\python.exe tools\migrate_content_bodies_to_postgres.py
```

Finally, import edit and moderation history after content metadata exists:

```powershell
.\.venv\Scripts\python.exe tools\migrate_content_history_to_postgres.py
```

Then opt the local application into PostgreSQL user storage:

```powershell
$env:STUDY_BUDDY_STORAGE = "postgresql"
.\.venv\Scripts\python.exe -m src.main
```

Unset `STUDY_BUDDY_STORAGE`, or set it to `json`, to return to the current JSON
backend. This makes rollback safe while other repositories still use JSON.

## Run the local API

With the local `.env` configured, start a development server bound only to
this computer:

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

Leave the API running in the first PowerShell window. The desktop reads the
same `.env`, so a second PowerShell window only needs:

```powershell
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
