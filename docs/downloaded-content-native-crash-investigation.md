# Downloaded-content / native-crash isolation

Date: 2026-08-26

Status: downloaded-content routing defect resolved; historical native crash
not reproduced or proven to share the same cause.

> **Historical note.** This investigation predates the approved Phase 6B
> offline-practice/media work. Learner assessment bodies remain redacted and
> are not downloaded as assessment packages. Offline practice now uses a
> separate complete `offline_practice` projection, and any locally cached quiz
> is barred from assessment/test mode. Media is now retrieved by authorized
> opaque media ID and cached as part of the package. The historic native crash
> remains unproven; these changes do not claim to have fixed it.

## Symptom and current evidence

The desktop application has intermittently terminated on Windows with
`0xC0000409` / `BEX64`, with `Qt6Core.dll` reported as the faulting module.
Some live reports correlate the termination with quizzes that had previously
been downloaded, but download/cache involvement has not been proved as the
cause of the native failure.

A separate deterministic defect was confirmed earlier. An explicit bundled
`quiz.json` or `deck.json` path could be converted to its parent content ID by
`_LibraryRepository._cached()`, allowing a same-ID downloaded package to replace
the bundled body. For learner quiz downloads, that package could contain
answer-redacted Matching pairs. The routing collision is fixed: explicit
bundled paths now stay on the base repository, while downloaded `content.json`
paths and direct downloaded IDs use the cache.

The real bundled quiz, now retained as `Question Types Demo Quiz`, has ID
`da5430fa-b771-4262-9383-90e4e3abc3f0` and a complete Matching pair body at
`data/quizzes/da5430fa-b771-4262-9383-90e4e3abc3f0/quiz.json`. The previously
downloaded reproducing packages were manually removed. Earlier runtime
diagnostics captured one package supplying `answer: None` while the bundled
file contained `Madrid` and `Oslo`.

## Download and cache lifecycle

```text
QuizViewer.keep_quiz_offline / FlashcardViewer.keep_deck_offline
    -> HTTP or base repository body read
    -> ContentLibrary.store_download / refresh_download
    -> cache/library/{quizzes|flashcards}/{content_id}/
         manifest.json
         content.json
    -> _LibraryRepository
    -> QuizController / FlashcardController
    -> Quiz / flashcard session
    -> viewer widgets
```

Creation and replacement are performed by `ContentLibrary.store_download()`.
It writes a temporary sibling directory and atomically replaces the current
content-ID directory. `refresh_download()` first requires equal metadata/body
revisions and then uses the same replacement path. There is one cache slot per
kind and sanitized content ID; a second download or update replaces the prior
package. A transient `.previous` directory protects ordinary Python-level
replacement failures.

`manifest.json` records the content ID, kind, name, source, visibility, owner,
allowed accounts, content version, remote update timestamp, and placeholder
media metadata. `content.json` stores the body exactly as received. Remote
media references remain in the body but are deliberately not resolved as
local files.

Reads validate both files and parse `content.json` afresh. No downloaded body
is held in a process-wide in-memory cache, and controller/`Quiz` construction
does not write the body back. Invalid, incomplete, inaccessible, temporary, or
orphan backup directories are not listed.

Downloaded data survives viewer close, repository reconstruction, application
restart, and logout. Public packages remain available to guests. Restricted
packages stay on disk but are filtered by manifest ownership/allowed-account
data. The current UI deletion operation is `clear_downloaded_data()`, which
removes all valid downloaded quiz/deck entries, not one selected item.

### Source selection

- Local bundled rows use explicit `.../quiz.json` or `.../deck.json` paths and
  always delegate to the base repository.
- Downloaded rows use `.../content.json` and select the cache.
- A direct content ID selects an accessible cache entry when one exists and
  otherwise delegates to the base repository.
- HTTP metadata rows use raw content IDs. Therefore a same-ID downloaded
  package is intentionally preferred by the read-through adapter for that
  online row. This remains an important representation boundary: the caller's
  intent is inferred from the value shape rather than an explicit source type.
- `_LibraryRepository.get_all_quizzes()` and `get_all_decks()` suppress a
  downloaded duplicate when a base row has the same ID, retaining the base
  row. `ContentLibrary.list()` itself concatenates both sources without
  deduplication, but no production caller currently uses that method.

## Bundled versus downloaded representation

The focused comparison used complete Matching quiz data with stable question
IDs, all answer fields, a remote image reference, and content-version metadata.
The bundled/base and downloaded paths preserve the same Python object shape
after JSON deserialization. Repeated reads, controller construction, and
`Quiz` construction did not alter the stored bytes or parsed body.

Learner API assessment quiz bodies are intentionally answer-redacted. In particular,
Matching pairs are projected as `{prompt: value, answer: None}`. The cache
preserves that representation exactly. `QuestionFactory.from_dict()` then
rejects it in `normalize_matching_pairs()` before Qt answer-widget creation.
This deterministic Python failure is reproducible without PyQt and is not
cache corruption. It is an incompatibility between the learner download
projection and the local `Quiz` execution contract.

The global cache slot is keyed by kind/content ID. Phase 6 added explicit
package/projection markers, authorization metadata, global lifecycle
tombstones, and cache coherence validation. Restricted packages remain
account-bound, public packages survive logout, and the current package model
does not reuse a role-specific assessment projection as learner practice.

Progress and local quiz attempts are delegated to the base JSON repository.
For a downloaded `content.json` path, those files are placed below the cache
entry directory. Replacing, updating, or clearing that package therefore also
removes any such colocated local progress/attempt files. Progress
synchronization is outside this investigation, but this lifecycle should be
addressed separately from the immutable downloaded package boundary.

## Observed non-Qt matrix

| Scenario | Result |
|---|---|
| Bundled quiz, never downloaded | PASS — base `quiz.json` and complete answers used |
| Download complete quiz | PASS — exact body and manifest stored |
| Open complete downloaded quiz | PASS — repository, controller, and `Quiz` construct |
| Reopen complete downloaded quiz | PASS — body reparsed unchanged |
| Download, reconstruct repository, reopen | PASS |
| Download same complete content twice | PASS — exact body retained; atomic replacement completes |
| Explicit update of downloaded content | PASS — coherent revision replaces body exactly |
| Delete downloads, reopen bundled content | PASS |
| Delete and re-download complete quiz | PASS |
| Multiple downloaded quizzes | PASS |
| Downloaded content after repository/application-style restart | PASS |
| Public download after logout | PASS — intentionally remains available |
| Restricted download after logout/login | PASS — locked for guest/other account and restored for owner |
| Same-ID bundled plus downloaded quiz/deck | PASS — explicit bundled path wins |
| Redacted downloaded Matching body read/reopen | PASS — remains byte-for-byte redacted |
| Construct `Quiz` from redacted downloaded Matching body | FAIL deterministically before Qt with the expected `ValueError` |
| Reproduce native `Qt6Core.dll` crash without Qt | NOT REPRODUCED — non-Qt code cannot produce the native failure |

## What has and has not been isolated

No evidence was found that valid cache JSON becomes corrupted, changes between
reads, mutates during `Quiz` construction, or selects a different cached
version after restart. The previous explicit bundled-path collision remains
covered and corrected.

Downloaded content does correlate with a deterministic pre-Qt exception when
its Matching answers are redacted. It is not yet established whether an
uncaught occurrence of that exception in a real Qt signal callback explains
the reported `Qt6Core.dll` termination. The native crash also has historical
reports outside this exact deterministic path. Current storage regression
coverage supports closing the downloaded-body routing defect, but does not
prove that the historical Qt failure itself was fixed.

## Follow-up if the native crash returns

Run the real desktop application with a controlled pair of downloaded packages:
one complete body and one learner-redacted body. Capture `sys.excepthook`, Qt
message output, faulthandler output, and the final callback marker around
`QuizViewer.start_quiz_from_selection()` without changing lifecycle behavior.
The key experiment is whether the redacted package produces the same
`0xC0000409` termination rather than an ordinary reported `ValueError`, while
the complete package repeatedly opens and closes successfully. If the native
failure also occurs with the complete package, continue upward into the
existing Qt lifecycle investigation; do not alter cache routing based on the
current evidence alone.
