# Phase 7 performance and soak-test history

Status recorded 2026-10-10. All numbers below are historical evidence from
reports/artifacts, not tests re-run for this audit.

Phase 7 must use disposable PostgreSQL database study_buddy_test, unique
fixture prefixes, and a dedicated media root. It must never target normal
application data. Primary sources are docs/phase7-live-stress-report.md and
docs/postgresql-api-scalability-audit.md.

Ignored .temp/phase7 artifacts are local evidence, not source. Sanitize any
archive: do not commit tokens, credentials, DB URLs, dumps, or secret-bearing
fixture manifests.

## Completed work

| Date / code | Workload | Result / limitation |
| --- | --- | --- |
| 2026-08-29/30; revision unavailable | Assessment races c=2/5/10/20 | Start/checkpoint/submit invariants passed; exact harness revision unavailable. |
| 2026-08-31; 31c13ed | Auth c=1–32, sessions, progress, reads/media, mixed soak c=12 | Valid workloads had no unexpected results; OS CPU/RSS unavailable. |
| 2026-09-08; b29a627, harness SHA 170b65... | Expanded assessment races c=2/5/10/20 | Expected 200/409 and DB invariants; supersedes invalid Aug-31 assessment fixture. |
| 2026-09-09; 7525ca1 | Six-profile 30-minute read soak c=12 | 67,370 requests, zero unexpected; pg_stat_statements/system CPU unavailable. |
| 2026-09-09; 7525ca1 | Read scaling c=12/16/20/25/32/40/50/75/100 | Clear knee, zero unexpected; local single-machine topology. |
| 2026-09-10 | Narrow read-path comparison and c=12 soak | Better local numbers, including untouched endpoints; no causal proof. |
| 2026-09-25; uncommitted tooling | W1 to W2 HTTP smoke c=2 | Auth/workload smoke and cleanup passed; no ladder or soak. |

The August mixed soak: 30 minutes c=12; 96,983 requests; 83,315 HTTP 200,
13,668 expected HTTP 403; zero unexpected. p50 140.52 ms, p95 836.65 ms,
p99 1,118.05 ms, max 2,007.24 ms. Its assessment profile was invalid (403
fixture setup) and is not assessment-contention evidence.

## September 9 local read matrix

| c | Requests/60 s | Req/s | Metadata p99 | Worst p99 | Unexpected |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 12 | 4,270 | 71.17 | 474 ms | preview 530 ms | 0 |
| 16 | 5,079 | 84.65 | 338 ms | practice 453 ms | 0 |
| 20 | 5,084 | 84.73 | 433 ms | practice 670 ms | 0 |
| 25 | 4,154 | 69.23 | 598 ms | media read 932 ms | 0 |
| 32 | 2,273 | 37.88 | 1,320 ms | practice 1,402 ms | 0 |
| 40 | 2,319 | 38.65 | 1,586 ms | practice 1,976 ms | 0 |
| 50 | 2,600 | 43.33 | 1,455 ms | practice 2,072 ms | 0 |
| 75 | 2,451 | 40.85 | 2,431 ms | practice 2,872 ms | 0 |
| 100 | 2,666 | 44.43 | 2,966 ms | practice 4,561 ms | 0 |

**Confirmed:** local throughput fell around c=25; broad degradation was visible
at c=32. No unexpected HTTP, deadlock, timeout, or integrity result was
recorded. **Possible:** synchronous session/auth, catalog/class query work,
process contention, pool behaviour, or interaction. **Unknown:** SQL and wait
attribution and whether the knee persists across split workstations.

Commit 6da8f48 preserves two narrow changes: skip short-answer variant lookup
when answers are excluded, and skip Practice's discarded image-path lookup.
Later improvements are not causal proof because untouched endpoints improved.

## Cross-machine status

| Topology | Status |
| --- | --- |
| W1 client -> W1 API -> W1 PostgreSQL | Recorded local baseline; machine identity not recovered here |
| W1 client -> W2 API -> W2 PostgreSQL | Smoke only; W1 10.0.0.150, W2 10.0.0.20 in task record |
| W2 client -> W2 API -> W2 PostgreSQL | Not evidenced as run |
| W2 client -> W1 API -> W1 PostgreSQL | Not evidenced as run |

W2 pre-flight was historically recorded at 4406a76 with API 0.0.0.0:8000,
PostgreSQL 17.11, and health/readiness 200; this is not current verification.

External-client support is currently uncommitted: tools/phase7_fixture.py,
external mode in tools/phase7_stress.py, tests, and docs. It must be reviewed,
tested, and committed separately before reproducible comparison. The older
local harness creates a local fixture/server/direct DB connection, so changing
only its DB URL would use the wrong topology.

## Preserve before next run

1. Commit app and harness together; 6da8f48 is last committed W2 performance
   baseline and 4406a76 adds legacy-import cleanup.
2. Record exact command/profile/duration/ladder/fixture/endpoint mix and
   expected 403/404 policy.
3. Require exact database study_buddy_test; never put normal-data URLs in runs.
4. Record machine roles, hardware, OS, Python/PostgreSQL, API bind, topology.
5. Collect W2 server telemetry independently; label W1 values client-observed.
6. Store sanitized result JSON/CSV/logs outside Git with revision/environment.

Do not change workload, pool/database/API settings during a comparison. Record
anomaly timestamps before retrying or changing anything.
