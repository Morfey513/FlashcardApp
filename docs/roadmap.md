# Roadmap: Work -> Clean/Right -> Fast

Status recorded 2026-10-10. Priorities express dependencies and release risk,
not deadlines.

## Phase 1 — Make it work

| Priority / category | Item, status, evidence | Dependencies and acceptance | Release impact |
| --- | --- | --- | --- |
| P0 / maintenance | New-device/server bootstrap; only manual DB/.env/Alembic instructions found. | Decide operator/deployment. New device safely configures DB, upgrades schema, starts API, proves health/readiness without secret leakage. | Blocks supported server release. |
| P0 / maintenance | Baseline/demo-data seeding after retired JSON imports; open. | Decide canonical source. Document an idempotent supported process or explicitly provide no seed data. | Blocks reproducible fresh setup if content is required. |
| P0 / maintenance | Backup/restore drill; manual pg_dump/pg_restore docs exist, no drill evidence. | Disposable restore target/policy. Demonstrate restore plus API/content/user checks; dumps outside Git. | Blocks production-data release. |
| P1 / feature | Security page; no implementation found, requirements open. | Owner defines account/session, cache privacy, or admin scope. User stories, roles, UI actions, tests precede implementation. | Defer unless policy requires it. |
| P1 / feature | Online editor/class acceptance; implementation exists, real workflow evidence incomplete. | Disposable API/PG. Teacher/admin/student create/edit/publish/assign/invite/remove access correctly. | Important online release. |
| P1 / feature | Offline update policy; explicit refresh exists, automatic sync does not. | Product freshness/conflict decision. UI and tests cover update availability/account transitions/selected policy. | Defer if explicit refresh accepted. |

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
