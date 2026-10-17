# Project status

Status updated 2026-10-17. The original 2026-10-10 recovery snapshot is
retained below as historical context; the Phase 1 inventory and verification
record reflect the current local/staging implementation.

## Evidence

- **Verified** means inspected in the current repository.
- **Historical** means retained in a report, log, or task record; it was not
  re-run for this document.
- **Open** means the evidence does not answer the question.

## Historical recovery baseline (2026-10-10)

| Item | Value |
| --- | --- |
| Branch | main |
| Snapshot HEAD | 4406a76a431b596c50febef43f279dd35747933e |
| Subject | chore: remove legacy JSON to PostgreSQL import scripts |
| Snapshot worktree | Intentionally dirty; preserve all existing changes |

**Historical:** existing changes then included UI/audio/test work, GUI regression
tooling, and uncommitted Phase 7 external-client tooling. In particular,
tools/phase7_stress.py, tools/phase7_fixture.py, tests/test_phase7_external.py,
and docs/phase7-external-client.md were not in that snapshot's HEAD. At that
time, they were not a committed benchmark baseline.

That snapshot removed six one-time JSON-to-PostgreSQL import scripts. It retained
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
- SQLAlchemy repositories and Alembic revisions 0001–0009 define PostgreSQL.
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
| Revision `6cf2f9d2f1ad06530e3f487f55036c923461f25b`, 2026-10-14 | `.\.venv\Scripts\python.exe -m pytest -q tests`: 502 passed, 0 failed, 0 skipped; Python 3.13.1; disposable PostgreSQL/temporary SQLite targets where applicable; coverage not collected | Verified |
| Same revision, disposable PostgreSQL, 2026-10-14 | Exact targeted command below: 26 passed, 0 failed, 0 skipped; Python 3.13.1; `study_buddy_test` plus unique `study_buddy_backup_*` and editor scratch databases; coverage not collected | Verified |
| Same revision, backup drill alone, 2026-10-14 | Exact command, Python, database targets, and 10 passed / 0 failed / 0 skipped recorded in [database.md](database.md#backuprestore-drill) | Verified |
| HEAD `a2fe5f6ba761aa738429e57391f5da51c9066815`, 2026-10-17 | `.\.venv\Scripts\python.exe -m pytest -q tests`: 506 passed, 0 failed, 0 skipped, 10 warnings in 200.35s; Python 3.13.1, pytest 9.1.1. Database targets: disposable PostgreSQL `study_buddy_test` plus unique `study_buddy_bootstrap_*` and `study_buddy_backup_*` scratch databases; temporary SQLite where applicable. The `postgres` maintenance database is used for scratch provisioning. This command does not collect coverage; local ignored `logs/pytest_run.txt:1-18` records output. | Verified from saved console output and configured disposable URLs |
| Same HEAD, 2026-10-17 | `.\.venv\Scripts\python.exe run_tests.py`: 506 passed, 0 failed, 0 skipped, 10 warnings in 244.04s; 71.4% total coverage; controller/quiz-controller/utility gates 88.2% / 85.2% / 96.0%. Database targets: disposable PostgreSQL `study_buddy_test` plus unique `study_buddy_bootstrap_*` and `study_buddy_backup_*` scratch databases; temporary SQLite where applicable. The `postgres` maintenance database is used for scratch provisioning. Local ignored `logs/test_results.log:369-478` records output. | Verified from saved runner log and configured disposable URLs |

The targeted live command loaded only the disposable credentials from the
ignored local `.env`:

```powershell
.\.venv\Scripts\python.exe -c "from dotenv import load_dotenv; load_dotenv(); import pytest; raise SystemExit(pytest.main(['-q', 'tests/test_bootstrap_server.py', 'tests/test_backup_restore_drill.py', 'tests/test_editor_class_acceptance.py']))"
```

A repository-root `python -m pytest -q` invocation could not collect a
permission-restricted `cache/library/` directory; the recorded full suite
uses the `tests/` path and completed without a test failure.

Older documents contain successive counts (158, 205, 221, 326); they are not
a current dashboard. Release/soak gates must record exact revision, command,
Python, database target, pass/fail/skip, and coverage.

Historical limitations: a restricted tool shell redirected TEMP and blocked
loopback PostgreSQL, causing hundreds of spurious suite errors; use a normal
user shell ([testing.md](testing.md#running-the-suite)). The earlier claim
that `src/ui/auto_scroll.py` caused the native crash is retracted; see the
root-cause record below. The PostgreSQL outage/recovery test remains gated and
was not reverified here.

## Phase 2 native crash and runner evidence

- **Verified — root cause:** [quiz_view.py:1145-1151](../src/ui/quiz_view.py#L1145)
  calls `controller.get_test_policy(selected_name)` from the Qt selection
  callback. The `ControllerStub` used by
  `test_true_false_ui_returns_boolean_value` lacked that method; it now matches
  the real controller's no-policy `None` return and false start decision
  ([test_quiz_view.py:60-84](../tests/test_quiz_view.py#L60),
  [quiz_controller.py:116-123](../src/controllers/quiz_controller.py#L116)).
  The link from the default `sys.excepthook` to a PyQt6 `qFatal()` termination
  is inferred from the WER dump stack and `0xC0000409` /
  `FAST_FAIL_FATAL_APP_EXIT`, not from an instrumented PyQt call. The committed
  [conftest.py:15-33](../tests/conftest.py#L15) hook turns such escaped callback
  exceptions into named pytest errors.
- **Historical — diagnostic evidence:** two WER dumps had matching faulting
  stacks, including one captured with page heap enabled. With the test hook
  installed before the stub fix, the escaped `AttributeError` occurred at test
  447; the full run reported 505 passed and 1 error:
  `test_true_false_ui_returns_boolean_value`, with the missing
  `get_test_policy` `AttributeError`. The dumps and diagnostic console output
  are no longer available in this repository; those observations are retained
  from the investigation, not rechecked for this update.
- **Historical — retracted:** earlier "native crash fixed" claims attached to
  the committed [auto_scroll.py:19-31](../src/ui/auto_scroll.py#L19)
  `sip.isdeleted()` guard and the committed
  [conftest.py:36-68](../tests/conftest.py#L36) QApplication consolidation
  did not identify this crash's cause. Heap-corruption theories and both page
  heap suite runs were inconclusive and are superseded by the callback error.
  The committed [run_tests.py:39-45](../run_tests.py#L39) native-exit
  detection is defensive logging, not the fix.
- **Verified — app hook:** commit `d5bb161` installs
  [main.py:18-39](../src/main.py#L18) after logging setup
  ([main.py:76-79](../src/main.py#L76)). The committed
  [unit test](../tests/test_main_exception_hook.py#L7) checks traceback logging
  and a non-fatal message; the reported 506-pass suite includes that test.
- **Open:** why isolated bisection runs did not raise the callback exception.
  Windows runner/GUI regression portability and the remaining offline-cache
  hardening cases are still open in [roadmap.md](roadmap.md#phase-2--make-it-cleanright).

## Feature and operational inventory

| Area | Classification | Evidence / next action |
| --- | --- | --- |
| Roles, sessions, classes, moderation | Implemented; current end-to-end verification pending | API/repositories/access tests exist; rerun PostgreSQL/API tests before release. |
| Assessments | Implemented with substantial coverage | Server-authoritative and race tests/Phase 7 reports exist; run gated outage test on final test DB. |
| Editors/content lifecycle | **Phase 1 closed; verified online 2026-10-14** | [Acceptance test](../tests/test_editor_class_acceptance.py) runs TestClient against migrated unique disposable PostgreSQL for quiz and deck create, edit/version, submit, publish, assign, invite, access, removal, rotation, and role/ownership denials. The run exposed and the [repository fix](../src/storage/postgres_class_repository.py) resolved a class-link INSERT ordering defect. |
| Offline Library/media | Implemented foundation; hardening deferred | Native-crash investigation, worker/disk/multi-instance/full-package questions remain. |
| Teacher updates / offline update policy | **Phase 1 closed; verified 2026-10-14** | Explicit refresh only. Test Mode freshness, local guest grading, and account cache locking were confirmed in code; [refresh tests](../tests/test_downloaded_content_service.py) cover access/revisions. Authenticated save failures have student-visible retry with a durable [pending store](../src/storage/pending_quiz_attempt_store.py) and memory fallback, covered by [retry tests](../tests/test_pending_test_attempt_retry.py). No background sync. |
| First-run DB setup | **Phase 1 closed; verified 2026-10-14** | [Bootstrap](../tools/bootstrap_server.py) provisions the disposable database, migrates, starts the local API, and checks health/readiness; [tests](../tests/test_bootstrap_server.py) cover fresh setup, rerun, and failure. [Operator procedure](database.md#local-setup-on-windows). |
| Baseline data seeding | **Phase 1 closed; verified 2026-10-14** | The same [bootstrap tool](../tools/bootstrap_server.py) seeds the bundled demo quiz and flashcard deck; its [live rerun test](../tests/test_bootstrap_server.py) checks idempotency without retired JSON import scripts. |
| Backup/restore | **Phase 1 closed; verified 2026-10-14** | The [drill](../tools/backup_restore_drill.py) uses documented `pg_dump`/`pg_restore` flags and separate scratch databases; [tests](../tests/test_backup_restore_drill.py) check restored account/content/API, rerun, and failure cleanup. [Exact passing-run record](database.md#backuprestore-drill). Manual commands remain the supported procedure. |
| Security page | **Phase 1 closed for agreed Sections 1–2; verified 2026-10-14** | [Security dialog](../src/ui/security_dialog.py) moves password change and manages active sessions; [UI tests](../tests/test_security_dialog.py) and [API tests](../tests/test_security_sessions_api.py) cover confirmations, ownership, admin gating, and throttled activity. Sign-in history and 2FA were outside this scope. |
| Guest behaviour | Implemented design, policy open | Guest is local JSON; confirm cache persistence and local-security policy. |
| Unexpected administrative calls | Possible, not a defect | Trace current requests before changing behaviour. |

## Documentation and owner decisions

The Phase 1 owner decisions are recorded here; broader documentation drift is
still tracked under Phase 2 maintenance.

1. ~~Security page purpose?~~ **Decided 2026-10-14:** password change and active
   sessions for the user, with a narrow admin-only session API. Sign-in history
   is a separate future task.
2. ~~Who provisions a server and what baseline data?~~ **Decided 2026-10-14:**
   `tools/bootstrap_server.py` provisions disposable local/staging PostgreSQL
   and seeds the bundled demo quiz and flashcard deck.
3. ~~Is backup/restore manual or a release requirement with restore drills?~~
   **Decided 2026-10-14:** manual `pg_dump`/`pg_restore` remains the procedure;
   the disposable automated drill verifies it.
4. ~~Is explicit refresh enough, or is automatic sync required?~~ **Decided 2026-10-14: explicit refresh only.** See Feature inventory above.
5. ~~Is deployment local-only, LAN, or Internet?~~ **Decided:** eventually
   Internet-facing. TLS, secret, CORS/host, and firewall configuration remain
   in Phase 2's Deployment boundary task, outside the Phase 1 local/staging
   bootstrap.

See roadmap.md and performance/soak_test_history.md.
