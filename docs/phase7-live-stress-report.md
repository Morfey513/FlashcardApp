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

Remaining assessment-concurrency coverage gaps are:

- multiple different students concurrently starting the same assessment; and
- multiple concurrent terminal submissions against the same attempt.

Concurrent same-position checkpoints have schema protection and a passing
race test, but that test does not explicitly assert that the resulting answer
row count is exactly one.

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
| Assessment contention | BLOCKED (this run only) | HTTP 403 for all c=2/5/10/20 starts prevented this run's intended path. Successful Aug. 29/30 and Sep. 2 validation is documented above. |
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
- multiple-student assessment-start contention
- concurrent terminal submissions against one assessment attempt
