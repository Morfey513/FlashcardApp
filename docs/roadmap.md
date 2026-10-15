# Roadmap: Work -> Clean/Right -> Fast

Status updated 2026-10-14. Priorities express dependencies and release risk,
not deadlines. Phase 1 closure applies to the agreed local/staging scope;
Internet-facing deployment hardening remains in Phase 2.

## Phase 1 — Make it work

| Priority / category | Item, status, evidence | Dependencies and acceptance | Release impact |
| --- | --- | --- | --- |
| **Done / P0 maintenance** | New-device/server bootstrap — closed 2026-10-14. [Script](../tools/bootstrap_server.py) provisions only `study_buddy_test`, migrates, starts the API, and checks health/readiness; [tests](../tests/test_bootstrap_server.py) cover fresh setup, rerun, and unreachable DB. | Local/staging bootstrap with pre-set disposable credentials. | Phase 1 gate resolved; Internet exposure remains Phase 2. |
| **Done / P0 maintenance** | Baseline/demo-data seeding — closed 2026-10-14. The [bootstrap seeder](../tools/bootstrap_server.py) loads the bundled quiz and deck without retired import tooling; [live rerun test](../tests/test_bootstrap_server.py) checks one copy and stable versions. | Bundled demo content is the selected baseline; conflicting content is refused. | Reproducible disposable setup verified. |
| **Done / P0 maintenance** | Backup/restore drill — closed 2026-10-14. [Drill](../tools/backup_restore_drill.py) and [tests](../tests/test_backup_restore_drill.py) verify separate scratch source/target, documented flags, restored API/content/user, repeat runs, and cleanup. [Exact run record](database.md#backuprestore-drill). | Manual `pg_dump`/`pg_restore` procedure remains supported; dump stays outside Git. | Phase 1 drill gate resolved; production operations remain separate. |
| **Done / P1 feature** | Security page — closed 2026-10-14 for password change and active sessions. [UI](../src/ui/security_dialog.py), [API](../src/api/main.py), [UI tests](../tests/test_security_dialog.py), and [API tests](../tests/test_security_sessions_api.py). | Agreed Sections 1–2; sign-in history and 2FA were outside scope. | Agreed page scope verified. |
| **Done / P1 feature** | Online editor/class acceptance — closed 2026-10-14. [Live acceptance test](../tests/test_editor_class_acceptance.py) covers quiz and deck create/edit/publish/assign/invite/access/remove plus role denials on disposable PostgreSQL. | A narrow class-link INSERT ordering fix is in [repository](../src/storage/postgres_class_repository.py). | Online workflow verified. |
| **Done / P1 feature** | Offline update policy — closed 2026-10-14: explicit refresh only, Test Mode freshness, guest/local grading, and account cache locking. Authenticated save failure has explicit retry with file and memory fallback in [controller](../src/controllers/quiz_controller.py), [store](../src/storage/pending_quiz_attempt_store.py), and [tests](../tests/test_pending_test_attempt_retry.py). | [Refresh tests](../tests/test_downloaded_content_service.py) and retry tests cover the selected policy; no background sync. | Policy and identified save-loss gap resolved. |

## Phase 2 — Make it clean/right

| Priority / category | Item, status, evidence | Dependencies and acceptance | Release impact |
| --- | --- | --- | --- |
| P0 / security | Deployment boundary; LAN/Internet needs production security profile. | Decide supported deployment. Threat model/checklist covers TLS, secrets, CORS/hosts, firewall, backup, logging, sessions. | Blocks LAN/Internet exposure. |
| P0 / correctness | PostgreSQL outage/recovery gate is deliberately conditional; current result unverified. | study_buddy_test plus fault injection. No unintended skip; bounded 503 then recovery; no normal DB touched. | Blocks online-fault confidence. |
| P1 / security | Negative API boundaries: malformed/empty/oversized input, ownership, SQL injection, session revocation. | Contract inventory. Representative safe tests for every public read/write boundary. | Needed before broad exposure. |
| P1 / correctness | Assessment integrity regression. | PostgreSQL test environment. Server grading, redaction, snapshot/resume, attempt lifecycle, terminal races proven. | High assessment importance. |
| P1 / correctness | Offline-cache hardening/native crash closure. | Reproduction/policy. Tests for account/logout, malformed/media/path traversal, interrupted replacement, disk/size, updates; crash fixed or closed with evidence. | Blocks robust offline-media claim. |
| P1 / maintenance | Reconcile README/database/testing drift. | Bootstrap/seeding decision. One current source for modes/tests/migration/backup/baseline. | Operations reliability. |
| P2 / maintenance | Windows runner/GUI regression portability. | Supported CI/runner model. Repeatable unique-temp tests and documented GUI prerequisites. | Deferrable. |
| P2 / correctness | Trace suspected redundant calls before removing them. | Request capture. Separate required authorization from duplicate work and regression-test only measured changes. | Not a confirmed defect. |

## Phase 3 — Make it fast

| Priority / category | Item, status, evidence | Dependencies and acceptance | Release impact |
| --- | --- | --- | --- |
| P0 / performance | Clean committed benchmark baseline; 6da8f48 exists but external tooling is dirty. | Review/commit tooling separately. Revision contains harness/tests/docs/fixture isolation/exact profiles. | Blocks trustworthy comparisons. |
| P1 / performance | Four-topology comparison; only W1->W2 smoke recorded. | Same fixture/workload and W2 telemetry. Publish W1/W1, W1/W2, W2/W2, W2/W1 endpoint curves/anomalies. | Needed for knee attribution. |
| P1 / performance | Isolate c=25–32 knee; confirmed locally but not attributed. | Cross-machine plus SQL/pool/request timing. Distinguish client/API/pool/repository/SQL/PG explanations with confidence labels. | Needed before refactors. |
| P2 / performance | Optimize only measured bottlenecks. | Equivalent correctness/soak matrix. Before/after uses identical workload/environment and no unexpected errors. | Defer until diagnosis. |

## Guardrails

Keep Alembic/live repositories separate from retired import utilities. Use only
study_buddy_test plus isolated fixture prefixes for DB tests. Do not call high
CPU, request counts, pool waits, or checkpoints a defect without corroborating
measurement. Do not optimize before the workload and suspected layer are
reproducible.
