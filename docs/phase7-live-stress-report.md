# Phase 7.3 Live Stress-Test Report

Date: 2026-08-31  
Application commit: `31c13ed20ba2fe765efe6705044965f3239002c3`  
Alembic revision: `20260824_0008`  
Environment: Windows, Python 3.13.1, PostgreSQL 17.0  
Database: dedicated `study_buddy_test` only

## Retrospective assessment-contention correction

This report's August 31 assessment result is historical evidence for that
specific run, not a statement that assessment contention was unimplemented or
never validated.  Earlier successful artifacts and later isolated PostgreSQL
and HTTP race tests establish the following:

- **August 29:** `assessment-cohort` completed at c=2, c=5, and c=10.  Each
  run recorded concurrent authenticated starts, a checkpoint, a submit, an
  expected post-active HTTP 409, and passing active-attempt, attempt-limit,
  and terminal-submission checks.
- **August 30:** `phase72` repeated that workflow at c=2, c=5, c=10, and
  c=20 with the same passing invariants.
- **September 2:** `test_attempt_limit_completed_boundary_http_race` used ten
  independently issued tokens for an authorized student in a class-backed
  assessment.  It proved a single shared active attempt, successful terminal
  submission, and HTTP 409 responses after the completed-attempt boundary.
  The dedicated PostgreSQL assessment race tests also passed for concurrent
  starts, checkpoint/submit, same-position checkpoints, expiry, and teacher
  resolution races.

The August 31 c=2/c=5/c=10/c=20 assessment run below returned HTTP 403 before
the contention path.  It is therefore classified as a **blocked/invalid
fixture or authorization setup**, not as evidence against the successful
validation above.  The retained August 29/30 JSON artifacts do not record an
application Git revision or stress-harness revision/hash.  The application
revision recorded below applies to the August 31 run only; it must not be read
as the exact harness revision for every historical artifact.

The September 8 expanded rerun closes the two assessment-concurrency gaps:
multiple different authorized students and multiple terminal submissions. It
also checks one persisted answer per attempt for the new profiles. The older
same-position checkpoint test remains useful coverage, but does not itself
assert an answer-row count.

## Test setup

The live runner used the unique fixture prefix `phase7-20260831-130804-b8fa6e69` and cleaned all rows with that prefix in `finally`. A temporary media root was created for the run and removed on exit.

Seeded data:

- 2 privileged users (`teacher`, `admin`)
- 10 student users
- 1 public quiz
- 1 private quiz
- 1 public flashcard deck
- 2 uploaded media objects

No passwords, tokens, authorization headers, or database URLs were written to artifacts.

## Commands executed

```powershell
.\.venv\Scripts\python.exe -u -
```

Artifacts written:

- `phase7-20260831-130804-b8fa6e69-auth-c1.json` / `.csv`
- `phase7-20260831-130804-b8fa6e69-auth-c2.json` / `.csv`
- `phase7-20260831-130804-b8fa6e69-auth-c4.json` / `.csv`
- `phase7-20260831-130804-b8fa6e69-auth-c8.json` / `.csv`
- `phase7-20260831-130804-b8fa6e69-auth-c16.json` / `.csv`
- `phase7-20260831-130804-b8fa6e69-auth-c32.json` / `.csv`
- `phase7-20260831-130804-b8fa6e69-sessions-c2.json` / `.csv`
- `phase7-20260831-130804-b8fa6e69-sessions-c5.json` / `.csv`
- `phase7-20260831-130804-b8fa6e69-sessions-c10.json` / `.csv`
- `phase7-20260831-130804-b8fa6e69-progress-same-c2.json` / `.csv`
- `phase7-20260831-130804-b8fa6e69-progress-same-c5.json` / `.csv`
- `phase7-20260831-130804-b8fa6e69-progress-same-c10.json` / `.csv`
- `phase7-20260831-130804-b8fa6e69-progress-diff-c2.json` / `.csv`
- `phase7-20260831-130804-b8fa6e69-progress-diff-c5.json` / `.csv`
- `phase7-20260831-130804-b8fa6e69-progress-diff-c10.json` / `.csv`
- `phase7-20260831-130804-b8fa6e69-assessment-c2.json` / `.csv`
- `phase7-20260831-130804-b8fa6e69-assessment-c5.json` / `.csv`
- `phase7-20260831-130804-b8fa6e69-assessment-c10.json` / `.csv`
- `phase7-20260831-130804-b8fa6e69-assessment-c20.json` / `.csv`
- `phase7-20260831-130804-b8fa6e69-reads-c25.json` / `.csv`
- `phase7-20260831-130804-b8fa6e69-reads-c50.json` / `.csv`
- `phase7-20260831-130804-b8fa6e69-reads-c100.json` / `.csv`
- `phase7-20260831-130804-b8fa6e69-media-c5.json` / `.csv`
- `phase7-20260831-130804-b8fa6e69-media-c10.json` / `.csv`
- `phase7-20260831-130804-b8fa6e69-media-c20.json` / `.csv`
- `phase7-20260831-130804-b8fa6e69-media-c40.json` / `.csv`
- `phase7-20260831-130804-b8fa6e69-soak.json` / `.csv`

## PASS / FAIL / NOT EXECUTED

| Workload | Result | Notes |
|---|---|---|
| Authentication ladder | PASS | c=1,2,4,8,16,32 all returned HTTP 200. p99 rose from 551.92 ms at c=1 to 2755.28 ms at c=32. |
| Same-account sessions | PASS | c=2,5,10 all returned HTTP 200. Logout of one token did not invalidate sibling sessions. |
| Progress concurrency | PASS | c=2,5,10 on same-account and different-account writes returned HTTP 200 with no unexpected failures. Final state remained a complete snapshot. |
| Assessment contention | PASS (expanded Sept. 8 rerun) | The historical Aug. 31 fixture was blocked by 403. The c=2/5/10/20 rerun exercised same-user, different-student, and terminal-submit contention with no unexpected results. |
| Read load | PASS | c=25/50/100 completed with HTTP 200 plus expected 409s from protected/versioned media-path responses; no unexpected 5xx. |
| Media/content workload | PASS | c=5/10/20/40 completed with HTTP 200 plus expected 409s; no unexpected 5xx. |
| Mixed soak | PASS | 30 minutes at c=12 completed; 96,983 requests total; 83,315 successful and 13,668 expected 403s. |
| Cleanup | PASS | Prefix-scoped cleanup removed all generated users, quizzes, decks, attempts, and progress rows. |

## Results

### Authentication

| Concurrency | Requests | Success | p50 | p95 | p99 | Max |
|---|---:|---:|---:|---:|---:|---:|
| 1 | 1 | 1 | 551.92 ms | 551.92 ms | 551.92 ms | 551.92 ms |
| 2 | 2 | 2 | 648.32 ms | 648.32 ms | 648.32 ms | 757.40 ms |
| 4 | 4 | 4 | 1010.17 ms | 1010.17 ms | 1010.17 ms | 1024.61 ms |
| 8 | 8 | 8 | 1204.37 ms | 1219.02 ms | 1219.02 ms | 1219.02 ms |
| 16 | 16 | 16 | 2073.51 ms | 2234.85 ms | 2234.85 ms | 2234.85 ms |
| 32 | 32 | 32 | 2755.28 ms | 2762.84 ms | 2762.84 ms | 2762.84 ms |

### Same-account sessions

| Concurrency | Requests | Success | p50 | p95 | p99 | Max |
|---|---:|---:|---:|---:|---:|---:|
| 2 | 2 | 2 | 555.71 ms | 572.17 ms | 572.17 ms | 572.17 ms |
| 5 | 5 | 5 | 770.61 ms | 774.18 ms | 774.18 ms | 774.18 ms |
| 10 | 10 | 10 | 1314.52 ms | 1322.14 ms | 1322.14 ms | 1322.14 ms |

Token A logout invalidated only token A. Token B and token C remained valid. Reauthentication succeeded without invalidating the sibling sessions.

### Progress concurrency

| Scenario | Concurrency | Successful requests | p99 | Max |
|---|---:|---:|---:|---:|
| Same account / same content | 2, 5, 10 | 17 / 17 | 132.48-147.02 ms | 147.02 ms |
| Different accounts / same content | 2, 5, 10 | 17 / 17 | 67.46-156.58 ms | 156.58 ms |

Observed semantics:

- last committed snapshot won
- no hybrid or union snapshot was observed
- no duplicate key error appeared in this live run
- no unexpected HTTP 500 appeared

### Read load

| Concurrency | Requests | Success | Expected non-success | p99 | Max |
|---|---:|---:|---:|---:|---:|
| 25 | 25 | 20 | 5 | 311.24 ms | 448.97 ms |
| 50 | 50 | 40 | 10 | 2828.91 ms | 3052.99 ms |
| 100 | 100 | 80 | 20 | 7698.39 ms | 8041.71 ms |

The main response mix was 200 plus expected 409s for protected or versioned media/content operations.

### Media/content

| Concurrency | Requests | Success | Expected non-success | p99 | Max |
|---|---:|---:|---:|---:|---:|
| 5 | 5 | 4 | 1 | 89.04 ms | 105.86 ms |
| 10 | 10 | 8 | 2 | 119.22 ms | 129.87 ms |
| 20 | 20 | 15 | 5 | 261.64 ms | 270.43 ms |
| 40 | 40 | 30 | 10 | 918.56 ms | 1015.90 ms |

### Assessment

The intended assessment contention workload did not meaningfully execute
against this run's fixture set. All start attempts returned HTTP 403. This is
a blocked/invalid fixture or authorization setup for August 31 only; it does
not supersede the successful August 29/30 runs or September 2 race tests
summarized above.

### Assessment expanded rerun — 2026-09-08

Run artifacts (JSON contains provenance and per-operation HTTP results):

- `.temp/phase7/phase7-20260908-provenance-c2.json`
- `.temp/phase7/phase7-20260908-provenance-c5.json`
- `.temp/phase7/phase7-20260908-provenance-c10.json`
- `.temp/phase7/phase7-20260908-provenance-c20.json`

Each run used the dedicated `study_buddy_test` PostgreSQL database, a
class-backed published assessment, active class membership, individually
issued student sessions, burst shape, and one request per worker. The recorded
application revision was `b29a62747aa9a0d5f7b247e7c514454b4f550ccf` on
branch `main`. The harness source was uncommitted at run time, so its exact
reproducibility identifier is SHA-256
`170b65ac46ab83726d44718bae310b15705afba812319f943f7f75a9b7ff7c58`, not an
invented Git revision. Each artifact records its unique fixture identity
(`phase7-…`), fixture version `class-backed-assessment-v2`, target identifier
`postgresql/study_buddy_test`, and pool settings. The harness uses
`pool_pre_ping=true`, `max_overflow=0`, and `pool_size=max(5, concurrency)`;
these are test-harness settings and did not alter production configuration.

| c | Same-user starts | Different-student start/checkpoint/submit | Concurrent terminal submit | DB invariants | Unexpected results |
|---:|---|---|---|---|---:|
| 2 | 2×200; follow-up 409 | 2×200 / 2×200 / 2×200 | 1×200, 1×409 | all pass | 0 |
| 5 | 5×200; follow-up 409 | 5×200 / 5×200 / 5×200 | 1×200, 4×409 | all pass | 0 |
| 10 | 10×200; follow-up 409 | 10×200 / 10×200 / 10×200 | 1×200, 9×409 | all pass | 0 |
| 20 | 20×200; follow-up 409 | 20×200 / 20×200 / 20×200 | 1×200, 19×409 | all pass | 0 |

The harness verifies one active assessment for the same user/quiz, charged
attempts within the configured limit, final submitted state, independent
attempt ownership for every student, one answer per completed different-user
attempt, and exactly one charged terminal transition/answer for the contested
attempt. No unexpected 5xx or database-integrity result was recorded. The
loopback server did log the expected database unique-key conflict while it
collapsed same-user concurrent starts to the surviving active attempt; the
HTTP results were all 200 and the invariant passed.

### Mixed soak

- Start: 2026-08-31T13:08:04 UTC
- End: 2026-08-31T13:39:13 UTC
- Duration: 30 minutes
- Concurrency: 12
- Total requests: 96,983
- Successful requests: 83,315
- Expected non-success: 13,668
- Unexpected failures: 0
- p99 latency: 1118.05 ms
- Max latency: 2007.24 ms
- Samples collected: 120

Observed soak behavior:

- no sustained failure mode
- no runaway resource exhaustion
- no soak-time stall
- only expected authorization-related failures were seen

### Soak evidence verification

The soak artifact is complete and machine-readable: `phase7-20260831-130804-b8fa6e69-soak.json` and `.csv` were finalized at 09:39:13 EDT. It records 96,983 requests at concurrency 12, with 83,315 HTTP 200 responses, 13,668 expected HTTP 403 responses, zero unexpected failures, p50 140.52 ms, p90 444.62 ms, p95 836.65 ms, p99 1,118.05 ms, and maximum 2,007.24 ms. The report and cleanup verification were written at 09:43:03 EDT.

The runner/Python process was observed alive from approximately 09:07:58 EDT through completion at 09:39:13 EDT (about 31 minutes), and the artifact timestamps show the preceding ladder finishing between 09:08 and 09:09, followed by the soak artifact at 09:39:13. This is consistent with a real 30-minute mixed run; no stdout/stderr capture or separate runner metadata file exists beyond the JSON/CSV artifacts and report.

PostgreSQL log `postgresql-2026-08-29_054809.log` covers the interval. During the soak window (09:08–09:39 EDT), checkpoints were recorded at 09:12, 09:17, 09:22, 09:27, 09:32, and 09:37. Checkpoint total times increased from 23.371 s to 61.661 s, with WAL distance increasing from 1,865 kB to 5,240 kB; the 09:37 checkpoint completed at 09:38:07.429. No ERROR, FATAL, PANIC, deadlock, or connection-failure messages were present in that window. The next checkpoint at 09:42:05–09:42:52 occurred after the soak and is not included in the run.

The checkpoint/WAL activity is temporally consistent with the sustained write-heavy soak and supports that the database was busy during the run. It is correlation, not independent proof of request execution; proof comes from the process lifetime, finalized soak artifact, request totals, concurrency, and cleanup evidence together.

## Resource observations

The runner sampled PostgreSQL backend count periodically and preserved the sample stream in-process. No resource crash or cleanup failure occurred. No OS-level CPU/RSS export was available from the current lightweight runner, so that portion remains unavailable in this execution.

## Failures and reproduction information

Assessment contention:

- Result: BLOCKED / INVALID FIXTURE (August 31 only)
- Reproduction: concurrent `POST /api/v1/quizzes/{quiz_id}/assessments` against the seeded public quiz returned HTTP 403 for every request at c=2, c=5, c=10, and c=20
- Artifact: `phase7-20260831-130804-b8fa6e69-assessment-c*.json`

Successful assessment-contention evidence is retained separately in
`phase7-live-20260829/assessment-cohort-c*.json`,
`phase7-phase72-assessment-c*.json`, and the September 2 JUnit artifacts.
The September 8 expanded rerun above is the current authoritative evidence
for different-student and terminal-submit contention.

No other confirmed correctness failure was observed in this live run.

## Cleanup confirmation

Prefix-scoped cleanup removed the generated rows for this run. Verification after the runner exited returned zero matching rows in:

- `users`
- `quizzes`
- `flashcard_decks`
- `quiz_attempts`
- `flashcard_progress`
- `quiz_question_progress`

## Final soak classification

**PASS** — a real 30-minute mixed soak at concurrency 12 is reproducibly recorded by the finalized JSON/CSV artifact, matching process and cleanup timestamps, and corroborated (but not proven solely) by PostgreSQL checkpoint/WAL activity. Resource evidence is limited to the runner's PostgreSQL backend sampling; OS-level CPU/RSS data was unavailable.

## Remaining deferred scenarios

- transient PostgreSQL failure injection
- lock-wait/deadlock instrumentation beyond what the existing harness exposed

## September 9 30-minute read-soak baseline

This is a new, isolated baseline, not an optimization result. The existing
multi-account profile ran six sequential five-minute soak slices at c=12
(one request loop per worker) against `postgresql/study_buddy_test`: 30 minutes
of measured endpoint soak in total. Its artifacts are
`.temp/phase7/phase7-20260909-30m-multi-account-soak.json` and the matching
`.csv` file.

- Application and harness Git revision: `7525ca1a253e80ecfeb92925e91fa1c02d6b2be7`
  on `main`.
- Harness content SHA-256: `170b65ac46ab83726d44718bae310b15705afba812319f943f7f75a9b7ff7c58`.
- Fixture: `phase7-1788960339-cb7d4caa`, `class-backed-assessment-v2`.
- Pool: test-harness `pool_pre_ping=true`, `pool_size=12`, `max_overflow=0`.
  Production configuration was not changed.
- Total requests: 67,370; unexpected results: 0; stderr: empty.

| Endpoint | Requests | p50 | p95 | p99 | Max | Result |
|---|---:|---:|---:|---:|---:|---|
| available metadata | 20,790 | 166 ms | 253 ms | 402 ms | 692 ms | 200 only |
| preview | 7,773 | 474 ms | 598 ms | 655 ms | 793 ms | 200 only |
| practice download | 6,703 | 549 ms | 693 ms | 749 ms | 907 ms | 200 only |
| media manifest | 9,323 | 387 ms | 506 ms | 561 ms | 785 ms | 200 only |
| media read | 8,658 | 427 ms | 516 ms | 557 ms | 685 ms | 200 only |
| restricted read | 14,122 | 256 ms | 329 ms | 367 ms | 513 ms | expected 404 only |

No new deadlock, waiting-lock, connection/pool, timeout, or integrity failure
was observed. PostgreSQL did not have `pg_stat_statements` installed, so this
run cannot attribute latency to individual SQL statements. The worker process
held approximately 111–121 MiB working set while consuming sustained CPU; no
system-wide CPU/RSS sample was available. The earlier c=25/50/100 content-read
tail figures were not reproduced or contradicted: this baseline is sustained
c=12 and is not a concurrency-scaling comparison.

## September 9 read-scaling matrix

This follow-up used the same committed application/harness revision
`7525ca1a253e80ecfeb92925e91fa1c02d6b2be7`, source SHA-256
`170b65ac46ab83726d44718bae310b15705afba812319f943f7f75a9b7ff7c58`, branch
`main`, isolated `postgresql/study_buddy_test`, and
`class-backed-assessment-v2` fixtures. Each level used six sequential
10-second read-only soak slices (`available_metadata`, `preview`,
`practice_download`, `media_manifest`, `media_read`, and `restricted_denied`),
with one request loop per worker. Artifacts are
`.temp/phase7/phase7-20260909-read-scaling-c{12,16,20,25,32,40,50,75,100}.json`
and matching CSV/log files. Each artifact records pool settings
`pool_pre_ping=true`, `pool_size=max(5,c)`, `max_overflow=0`.

The aggregate latency percentile across unlike endpoint distributions is not
statistically meaningful, so endpoint values remain in the JSON artifacts.
The table uses `available_metadata` as a consistent reference endpoint and
names the worst p99 endpoint at each level. All successful reads were HTTP
200; all `restricted_denied` reads were expected HTTP 404; unexpected results
were zero at every level.

| c | Requests | Measured duration | Total req/s | Metadata p50/p95/p99/max | Worst endpoint p99 | Unexpected |
|---:|---:|---:|---:|---|---|---:|
| 12 | 4,270 | 60 s | 71.17 | 232/349/474/481 ms | preview 530 ms | 0 |
| 16 | 5,079 | 60 s | 84.65 | 178/307/338/386 ms | practice 453 ms | 0 |
| 20 | 5,084 | 60 s | 84.73 | 202/275/433/483 ms | practice 670 ms | 0 |
| 25 | 4,154 | 60 s | 69.23 | 341/536/598/681 ms | media read 932 ms | 0 |
| 32 | 2,273 | 60 s | 37.88 | 986/1089/1320/1389 ms | practice 1402 ms | 0 |
| 40 | 2,319 | 60 s | 38.65 | 993/1290/1586/1714 ms | practice 1976 ms | 0 |
| 50 | 2,600 | 60 s | 43.33 | 1320/1422/1455/1510 ms | practice 2072 ms | 0 |
| 75 | 2,451 | 60 s | 40.85 | 2171/2375/2431/2503 ms | practice 2872 ms | 0 |
| 100 | 2,666 | 60 s | 44.43 | 2426/2870/2966/3020 ms | practice 4561 ms | 0 |

### Scaling interpretation and telemetry

- **c=12–20:** throughput grows to about 85 req/s while endpoint p99 remains
  below 0.7 seconds.
- **c=25:** degradation begins; total throughput falls and media-read p99
  reaches 932 ms.
- **c=32:** broad degradation is evident: throughput falls to 38 req/s and
  every successful read profile has roughly 1.0–1.4 second p99 latency.
- **c=40–100:** latency rises sharply with little throughput gain. c=100 is
  stable enough to complete, but not healthy as a latency target.

This reproduces the historical *shape* of the scaling knee, but not its exact
numbers: historical results reported approximately c=25 p99 311 ms, c=50 p99
2829 ms, and c=100 p99 7698 ms. The new worst endpoint p99 values are 932 ms,
2072 ms, and 4561 ms respectively. Workload mix, fixture/run conditions, and
the historical aggregate definition prevent treating the differences as a
regression or improvement claim.

Post-run telemetry found no waiting locks, new deadlocks, connection errors,
timeouts, or integrity errors. `pg_stat_statements` is not installed and was
not enabled because that typically requires server preload/restart. Global
table counters show substantial accumulated sequential scans on `users`,
`user_sessions`, `quizzes`, and `quiz_questions`, but they were not reset or
captured per level; they are **suspicious**, not endpoint-attributable proof.
At c=100 the harness pool size equals PostgreSQL `max_connections=100`; no
failure occurred, but connection-acquisition timing was not captured, so pool
saturation is also **suspicious**, not confirmed.

**Bottleneck classification:** the c=25–32 throughput/latency knee is
**confirmed** as observed behavior. Its root cause is **unknown**. SQL scan
counters, c=100 pool geometry, and sustained Python CPU are **suspicious**;
lock/deadlock contention is not supported by this run. No production
optimization is justified without per-statement SQL and connection-acquisition
telemetry.

### Post-matrix diagnostic code-path review

Read-path inspection materially narrows, but does not prove, the cause of the
c=25–32 knee. Each request authenticates through separate synchronous
repository calls for opaque-session resolution and user lookup. Content access
then performs further synchronous repository calls. The available-metadata path
materializes the catalog and separately resolves active class content IDs. The
quiz preview builds a full question projection using several sequential queries
(questions, options, pairs, variants, and media). Practice download performs
that full quiz projection and then a separate media-descriptor query. These
paths explain why practice download and preview are the earliest/slowest
profiles under load.

This is **strongly suspicious**, not a confirmed SQL or pool bottleneck:
request-level timing does not separate authentication, connection checkout, SQL
execution, Python projection/serialization, and response time. Likewise, the
routes are synchronous FastAPI handlers, but no server thread/event-loop queue
telemetry was captured. The smallest useful next experiment is therefore a
short c=20/25/28/32/36/40/50 matrix with per-request timing spans for pool
checkout, SQL execution, and response serialization plus process CPU/RSS and
PostgreSQL active-session sampling. It should use the same isolated fixture and
must not alter production settings or behavior.

## September 10 narrow projection cleanup and comparison

Two repository changes remove work that the code review established was unused:

- Learner quiz preview (`include_answers=False`) no longer reads
  `short_answer_variants`. The public preview remains answer-redacted; an
  answer-bearing projection still reads variants and returns the same answers.
- Quiz practice no longer performs the intermediate `image_path` lookup that
  it immediately removes before attaching its dedicated media descriptors.
  Practice media references and descriptor semantics are unchanged.

Focused repository and API validation passed (`4 passed`). The repository-level
fixture changes learner preview from six body queries to five. The full local
pytest command could not collect the GUI-regression test because its local
environment lacked `psutil`; this is an environment dependency issue, not a
failure from these changes.

The post-change comparison used the same `multi-account` profile, six
sequential 10-second soak slices, two-second ramp, dedicated
`postgresql/study_buddy_test`, and `class-backed-assessment-v2` fixture as the
September 9 matrix. Artifacts are
`.temp/phase7/phase7-20260910-postchange-read-scaling-c{20,25,32,40,50}.json`
and matching CSV files. The application base revision is
`7525ca1a253e80ecfeb92925e91fa1c02d6b2be7`; the harness source was
uncommitted and records SHA-256
`208c695efaac74c560f83247cef17e26693c0528d0a7e99af983c9523112c23e`.

| c | Previous total req/s | Post-change total req/s | Previous Practice p99 | Post-change Practice p99 | Previous Preview p99 | Post-change Preview p99 | Unexpected |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 20 | 84.73 | 93.45 | 670 ms | 420 ms | 569 ms | 253 ms | 0 |
| 25 | 69.23 | 80.47 | 440 ms | 537 ms | 686 ms | 566 ms | 0 |
| 32 | 37.88 | 82.08 | 1,402 ms | 640 ms | 1,177 ms | 641 ms | 0 |
| 40 | 38.65 | 85.00 | 1,976 ms | 802 ms | 1,657 ms | 835 ms | 0 |
| 50 | 43.33 | 105.00 | 2,072 ms | 854 ms | 1,867 ms | 680 ms | 0 |

The c=32–50 results are substantially better, while c=25 is mixed. They do
not establish that the two cleanup changes removed the scaling knee: all four
untouched read profiles also improved sharply during the same post-change
matrix. This is a materially different local runtime condition, not a
controlled causal result.

### Post-change 30-minute c=12 stability soak

The same six sequential five-minute c=12 slices completed with zero unexpected
results. Artifacts are
`.temp/phase7/phase7-20260910-postchange-30m-multi-account-soak.json` and the
matching CSV. The artifact records 199,376 requests; Preview p99 was 191 ms
and Practice Download p99 was 228 ms. Every endpoint improved relative to the
September 9 artifact, including untouched metadata, media, and restricted-read
paths. It is therefore a successful stability/regression run, but not evidence
that the two projection cleanups caused the broader throughput gain.

### Current decision

The cleanup changes are retained because they remove confirmed unnecessary
work. No further local optimization is justified by this comparison. The next
test is the identical c=20/25/32/40/50 matrix and c=12 30-minute soak on a
second workstation, recording application revision, harness SHA-256, machine
details, OS CPU/RSS, and endpoint artifacts before comparing results.
