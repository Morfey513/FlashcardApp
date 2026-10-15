# Project status

Status recorded 2026-10-10. This is a documentation-only recovery audit.

## Evidence

- **Verified** means inspected in the current repository.
- **Historical** means retained in a report, log, or task record; it was not
  re-run for this document.
- **Open** means the evidence does not answer the question.

## Current baseline

| Item | Value |
| --- | --- |
| Branch | main |
| HEAD | 4406a76a431b596c50febef43f279dd35747933e |
| Subject | chore: remove legacy JSON to PostgreSQL import scripts |
| Worktree | Intentionally dirty; preserve all existing changes |

**Verified:** existing changes include UI/audio/test work, GUI regression
tooling, and uncommitted Phase 7 external-client tooling. In particular,
tools/phase7_stress.py, tools/phase7_fixture.py, tests/test_phase7_external.py,
and docs/phase7-external-client.md are not in HEAD. They are not a committed
benchmark baseline.

HEAD removed six one-time JSON-to-PostgreSQL import scripts. It retained
migrations/, migrations/versions/, migrations/env.py, and alembic.ini; these
are required Alembic schema migrations. This does not authorize removal of live
repository import methods.

## Architecture

**Verified** from architecture.md, src/api/main.py, and repository_factory.py.

    PyQt6 desktop -> controllers/logic -> repository contracts
      -> JSON offline/demo, or HTTP adapters -> FastAPI -> PostgreSQL

- PyQt6 UI lives in src/ui/; controllers coordinate learning, editors, classes,
  moderation, settings, and progress.
- JSON is the offline/demo backend. Guest progress and attempts are local.
- Authenticated HTTP mode keeps database credentials on FastAPI; direct
  PostgreSQL mode is transitional.
- FastAPI uses opaque bearer sessions and derives actor/authorization server
  side.
- SQLAlchemy repositories and Alembic revisions 0001–0008 define PostgreSQL.
- Offline library packages use cache/library, account-aware access, atomic
  replacement/recovery, and explicit version refresh.

STUDY_BUDDY_STORAGE controls repository selection. JSON is default; HTTP/API
is used for authenticated online domains.

## Running and testing

**Verified** from README.md, docs/database.md, and run_tests.py.

    .\.venv\Scripts\python.exe -m src.main
    .\.venv\Scripts\python.exe -m uvicorn src.api.main:app --host 127.0.0.1 --port 8000 --reload
    .\.venv\Scripts\python.exe -m alembic upgrade head
    .\.venv\Scripts\python.exe run_tests.py

The runner uses pytest with .temp/pytest, writes coverage under .temp/coverage,
appends logs/test_results.log, and enforces controller, quiz-controller, and
utility coverage gates. Do not run Alembic/imports against normal data;
PostgreSQL-gated tests require disposable study_buddy_test.

| Evidence | Result | Status |
| --- | --- | --- |
| logs/test_results.log, 2026-08-28 | 326 passed, 4 warnings; 67.2% total coverage | Historical |
| Phase 7 checkpoint | Normal 369 passed, 31 skipped; PostgreSQL gated 30 passed, 1 intentional skip before outage follow-up | Historical |
| External focused run | phase7 stress plus external tests: 16 passed in 0.60s | Historical, against dirty tooling |
| Current HEAD/worktree | No full suite run for this audit | Not verified |

Older documents contain successive counts (158, 205, 221, 326); they are not
a current dashboard. Release/soak gates must record exact revision, command,
Python, database target, pass/fail/skip, and coverage.

Historical limitations: Windows pytest temporary-directory permissions required
a unique base temp in a focused run; a PyQt offscreen/native run recorded an
access violation in src/ui/auto_scroll.py; Alembic warnings were non-blocking;
the PostgreSQL outage/recovery test is deliberately gated and not reverified
here.

## Feature and operational inventory

| Area | Classification | Evidence / next action |
| --- | --- | --- |
| Roles, sessions, classes, moderation | Implemented; current end-to-end verification pending | API/repositories/access tests exist; rerun PostgreSQL/API tests before release. |
| Assessments | Implemented with substantial coverage | Server-authoritative and race tests/Phase 7 reports exist; run gated outage test on final test DB. |
| Editors/content lifecycle | Verified online on 2026-10-13 | `tests/test_editor_class_acceptance.py`: real TestClient against a migrated, unique disposable PostgreSQL scratch database verifies quiz and flashcard create, edit/version, teacher submit, admin publish, class invitation, student access, removal, code rotation, and role/ownership denials. The live run exposed and fixed a flashcard class-creation INSERT ordering defect in `PostgresClassRepository.rotate_code`. |
| Offline Library/media | Implemented foundation; hardening deferred | Native-crash investigation, worker/disk/multi-instance/full-package questions remain. |
| Teacher updates / offline update policy | **Implemented and verified** | Explicit refresh only (no background sync), decided 2026-10-14. Freshness required for Test Mode, not Practice; guest Test Mode exempt (locally graded, no server round-trip, confirmed in code). Account-switch/logout cache-locking policy confirmed implemented (`can_access`, revocation vs. stale distinction). Non-class-only authenticated Test Mode save failures are handled via an explicit, student-visible retry with a durable local pending file and an in-memory fallback — `src/storage/pending_quiz_attempt_store.py`, `tests/test_pending_test_attempt_retry.py`. No automatic/background sync exists or is planned. |
| First-run DB setup | Planned/not found automated | Manual database, .env, Alembic instructions exist; define operator workflow. |
| Baseline data seeding | Open | Old import tools removed; database docs still mention stale imports. Decide supported fresh-server data source. |
| Backup/restore | Manual procedure documented | pg_dump/pg_restore exist; no restore drill evidenced. |
| Security page | Open | No Security UI page found in inspected UI/controller paths. Define scope first. |
| Guest behaviour | Implemented design, policy open | Guest is local JSON; confirm cache persistence and local-security policy. |
| Unexpected administrative calls | Possible, not a defect | Trace current requests before changing behaviour. |

## Documentation and owner decisions

docs/database.md and README.md contain historical import/future-phase text that
conflicts with newer source and storage-mode documentation. Reconcile them
after deciding:

1. Security page purpose: account/session, cache privacy, or administration?
2. Who provisions a server and what baseline/demo data, if any, it receives?
3. Is backup/restore manual or a release requirement with restore drills?
4. ~~Is explicit refresh enough, or is automatic sync required?~~ **Decided 2026-10-14: explicit refresh only.** See Feature inventory above.
5. Is deployment local-only, LAN, or Internet? LAN/Internet needs separate
   HTTPS, secret, CORS/host, and firewall configuration.

See roadmap.md and performance/soak_test_history.md.
