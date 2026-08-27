# PostgreSQL/API scalability audit

Status: completed Phases 1–4. No Phase 5 is planned by this audit.

## Decision summary

The application keeps the normalized PostgreSQL schema as the canonical source
of truth. Reads now build lightweight projections at request time with
set-based SQL and bounded repository/API calls.

The investigation did **not** justify a separate Progress table, persistent
read-model tables, materialized views, synchronization jobs, triggers, or new
indexes. Those mechanisms would add consistency and maintenance cost without
addressing a measured database bottleneck.

The four domains use the following approaches:

| Domain | Result |
| --- | --- |
| Progress | One authenticated summary request backed by one set-based progress projection, plus bounded authentication/profile queries. |
| Quiz body | Bounded metadata, question, child-record, and media queries assembled into the existing domain object. |
| Flashcard body | Bounded deck, card, and media queries assembled into the existing domain object. |
| Editor | Bounded catalog reads and direct ID-based lifecycle/invitation operations; no editor projection table. |

## What was measured and found

### Progress

The old Progress window made one HTTP request per available deck or quiz and
expanded that into approximately seven SQL statements per content item. The
controlled baseline was approximately 100 requests/700 SQL statements/1.17 s
for 100 decks and 1,000 requests/7,000 SQL statements/69.7 s for 1,000 decks.

The final path is one summary request, one set-based projection, and bounded
authentication/profile queries:

| Items | HTTP | SQL | Total |
| ---: | ---: | ---: | ---: |
| 100 | 1 | 4 | ~33 ms |
| 1,000 | 1 | 4 | ~135 ms |
| 10,000 | 1 | 4 | ~459 ms |

The query filters through the same `available_content` authorization semantics
as the existing content paths. It excludes inaccessible, private, unpublished,
and class-restricted content for unauthorized users, while preserving
correct, wrong, mastered, totals, percentages, clear-all, and per-kind reset
behavior. Full content bodies are not loaded for the summary.

### Quiz body

The audit found question-child SQL N+1 in the PostgreSQL body path. The
implementation now loads the quiz metadata, all ordered questions, all
question-owned child records, and applicable media in bounded set-based
queries, then assembles the existing quiz/domain representation in Python.

Question ordering, IDs, supported question types, options, matching pairs,
ordering data, variants, media, hints, answer handling, and student answer
redaction remain unchanged. Owner/admin reads retain the editable
representation. Public and class-only authorization remains enforced before
the body is returned.

### Flashcard body

The audit found per-card and per-media loading in the PostgreSQL body path.
The final path loads deck metadata, all ordered cards, and applicable media in
a constant number of query categories and assembles the relationships in
Python. Card ordering, IDs, front/back content, hints, media references, and
visibility behavior are preserved.

The isolated body benchmark measured the following exact runs:

| Cards | Variant | Legacy SQL / DB ms | Final SQL / DB ms |
| ---: | --- | ---: | ---: |
| 10 | no media | 17 / 33.74 | 8 / 45.76 |
| 100 | no media | 107 / 49.96 | 8 / 17.92 |
| 1,000 | no media | 1,007 / 331.04 | 8 / 40.16 |
| 10 | representative media | 47 / 35.70 | 8 / 12.58 |
| 100 | representative media | 407 / 202.60 | 8 / 18.02 |
| 1,000 | representative media | 4,007 / 2,027.88 | 8 / 114.26 |

HTTP was one request in every body case and response sizes were unchanged.
The small 10-card no-media result is normal measurement noise; the larger
sets demonstrate the removal of linear SQL growth.

### Editor

The editor audit covered opening, listing, opening an item, create/save,
copy, delete, class invitation rotation, and refresh behavior for both quiz
and flashcard editors.

The main measured problems were duplicate available/owned catalog requests,
opposite-kind metadata requests during save/copy, class invitation lookup that
enumerated owned classes, and name-based lifecycle operations that required
extra metadata/body work. The final editor path reuses owned metadata
snapshots, uses direct ID-based copy/delete/lifecycle operations, and performs
direct invitation lookup.

Class-dense benchmark results (10/100/1,000 owned items) were:

| Kind | Operation | Dataset | Legacy HTTP / SQL / total ms | Final HTTP / SQL / total ms |
| --- | --- | ---: | ---: | ---: |
| Quiz | open list | 10 | 2 / 9 / 29.22 | 1 / 4 / 22.83 |
| Quiz | open list | 100 | 2 / 9 / 24.54 | 1 / 4 / 17.85 |
| Quiz | open list | 1,000 | 2 / 9 / 141.87 | 1 / 4 / 145.43 |
| Quiz | open item | 10 | 2 / 86 / 112.41 | 2 / 18 / 76.67 |
| Quiz | open item | 100 | 2 / 716 / 485.10 | 2 / 18 / 41.99 |
| Quiz | open item | 1,000 | 2 / 7,016 / 4,047.25 | 2 / 18 / 109.72 |
| Flashcard | open list | 10 | 2 / 9 / 18.61 | 1 / 4 / 12.21 |
| Flashcard | open list | 100 | 2 / 9 / 21.66 | 1 / 4 / 15.44 |
| Flashcard | open list | 1,000 | 2 / 9 / 73.46 | 1 / 4 / 69.70 |
| Flashcard | open item | 10 | 2 / 82 / 70.07 | 2 / 14 / 39.73 |
| Flashcard | open item | 100 | 2 / 712 / 394.56 | 2 / 14 / 34.68 |
| Flashcard | open item | 1,000 | 2 / 7,012 / 3,889.19 | 2 / 14 / 63.63 |

Save and copy also use fewer calls. For example, at 1,000 items Quiz save
changed from 8 HTTP/65 SQL/215.34 ms to 4 HTTP/41 SQL/182.61 ms; Flashcard
save changed from 7/53/208.41 ms to 4/38/133.47 ms. Quiz copy changed from
6/48/181.38 ms to 3/34/104.05 ms; Flashcard copy changed from 5/39/129.93 ms
to 3/30/86.96 ms. Delete and invitation rotation remain bounded operations.

The editor does not load class rosters as part of normal content editing;
roster/analytics workflows remain separate. Published Quiz save behavior was
also regression-tested so the server transition to pending review remains
immediate and authoritative.

## Consistency and authorization

All projections are generated from committed canonical rows at request time.
There is no refresh step to get correctness and no asynchronous projection
state that can silently lag.

Consequently, the next read reflects a committed teacher edit, card/question
addition or removal, metadata change, publish/unpublish, class assignment or
removal, copy, delete, progress answer, reset, clear-all, or membership
change. Student body and progress reads continue to apply public/class-only
visibility and membership authorization. Owner/admin reads retain their
existing editing and moderation permissions; answer redaction was not relaxed.

## Query-plan findings

`EXPLAIN (ANALYZE, BUFFERS)` was reviewed for representative large catalog,
class-link, invitation, card, and media queries. Existing primary keys and
unique/index prefixes were sufficient:

- 1,000-item catalog reads were sequential scan plus sort at approximately
  8.6 ms for quizzes and 10.3 ms for flashcards in the isolated run.
- Class-link lookup was a sequential scan at approximately 0.12 ms.
- Invitation lookup used the existing `ix_class_invitations_class_id` bitmap
  index at approximately 0.06 ms.
- Card ordering used the existing `uq_flashcards_position` access path.
- Media loading used existing primary-key paths; the representative 1,000-card
  media plan was approximately 20.15 ms.

No measured plan justified an Alembic migration or additional index.

## Regression and verification coverage

The completed phases added or extended coverage for:

- progress authorization, visibility, membership removal, publish/unpublish,
  deleted content, correct/wrong/mastered state, empty state, multiple kinds,
  clear-all, and per-kind clearing;
- quiz and flashcard body equivalence, ordering, IDs, child records, media,
  empty/small/large bodies, redaction, and public/class-only/owner/admin paths;
- bounded SQL query counts for body loading and direct invitation lookup;
- editor list/open/save/copy/delete behavior, ownership, moderation,
  invitations, failure handling, immediate refresh, and UI initialization;
- PostgreSQL stress utilities for progress, quiz body, flashcard body, and
  editor operations.

The relevant completed validation included 112 backend/controller tests, 11
editor UI tests, 3 moderation UI tests, and a published-Quiz API regression.
The known intermittent Windows Qt native access violation in the unrelated
auto-scroll path was isolated; the editor UI rerun passed. `git diff --check`
passed for the audit changes.

## Files and maintenance boundary

The implementation touched the existing API, controllers, repositories,
PostgreSQL access paths, editor UI/controller tests, and benchmark utilities.
It did not add a persistent projection schema. The canonical tables remain the
only write authority, so normal writes do not need triggers, jobs, refresh
commands, or dual-write error handling.

Remaining costs are the unavoidable response serialization/client construction
cost for very large catalogs and body payloads, plus the bounded authentication
and profile queries around authenticated requests. Those are not evidence for
another read-model layer.

## Final decision

Keep the current architecture: normalized canonical PostgreSQL tables with
request-time, set-based projections. Do not add Progress, deck, quiz, editor,
or synchronization tables; materialized views; triggers; cache changes;
authentication changes; Qt lifecycle changes; or speculative indexes based on
this audit.
