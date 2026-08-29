# Storage modes and offline content

## Runtime selection

`STUDY_BUDDY_STORAGE` selects the primary repository backend. The default
`json` backend reads and writes the canonical files under `data/`. In
`api`/`http` mode, an authenticated token selects HTTP repositories backed by
FastAPI and PostgreSQL; without a token, newly created controllers use the
local JSON repositories. Logging out therefore returns the desktop UI to its
guest/local data path.

The active local files are:

- `data/users.json` for local accounts;
- `data/quizzes.json` and indexed `data/quizzes/*/quiz.json` packages;
- `data/flashcard_decks.json` and indexed `data/flashcards/*/deck.json`
  packages;
- `data/languages/*.json` for translations;
- content-local progress, attempts, moderation history, and media referenced
  by those packages.

Migration tools use these same JSON formats as import sources. Most tests
construct isolated equivalents under pytest temporary directories.

## Downloaded content

`ContentLibrary` layers downloaded packages over the selected base repository.
Packages are stored as
`cache/library/{quizzes|flashcards}/{content_id}/manifest.json` and
`content.json`. They are local JSON snapshots, not PostgreSQL replicas.
Downloads survive application restart and logout; public packages remain
available to guests, while restricted packages stay on disk and are filtered
by their owner/allowed-account manifest fields.

Explicit bundled `quiz.json` and `deck.json` paths always use the base local
repository. A downloaded `content.json` path or direct accessible cache ID may
use the cache. This prevents a same-ID downloaded snapshot from replacing an
explicit bundled package.

### Phase 6A — explicit content refresh

PostgreSQL owns an integer `content_version` for each quiz/deck envelope.
Authenticated metadata checks compare that value with the cache manifest;
timestamps remain diagnostic and do not override a matching version. Updates
run only after an explicit user action. Metadata and body revisions must match
before the staged JSON package atomically replaces the current package.

The manifest records synchronization/check times, retryable update errors, and
per-account explicit revocation. A server outage marks accessible cached
content stale and never infers revocation. An authorized metadata response can
unlock that account again. Unauthorized/deleted metadata checks return the
same non-probing `404`; known banned lifecycle metadata is locked by the client.
If a process stops during directory replacement, discovery restores the valid
previous package and continues to ignore incomplete staging directories.

### Phase 6B — offline practice and media

Phase 6B adds a distinct `offline_practice` quiz projection. It contains the
evaluation data needed to reconstruct and practice all six question types
offline, but it is never an assessment response or attempt. The normal learner
assessment body remains answer-redacted and cannot be downloaded as a quiz
package. Any locally cached quiz, including legacy editor-complete packages,
is prohibited from entering test/assessment mode; server-backed online quizzes
retain normal server-authoritative assessment behavior.

Quiz authors and administrators may still download a complete editing body
where they are authorized, and restricted complete packages remain account
bound. Public practice packages remain available after logout; restricted
practice packages stay locked until an authorized account logs in. Local
practice never creates, changes, or impersonates a server-authoritative
attempt, assessment snapshot, or progress record.

Media is part of a downloaded package. The service retrieves opaque media IDs
through the owning content's authorization, validates descriptor metadata and
the downloaded bytes, then `ContentLibrary` places the files in the staged
package before the atomic replacement. Client-visible descriptors contain a
stable media ID, owning content ID and version, attachment role, MIME type,
byte size, and SHA-256 checksum; they do not expose server filesystem paths.
Server retrieval is restricted to the managed media root and validates
containment, MIME type, and size before serving.

### Completed and approved Phase 6 scope

- **Phase 6A:** server-authoritative versions, direct metadata/body access
  checks, explicit refresh, account-aware cache access, stale/locked/failed
  states, and atomic package replacement/recovery.
- **Phase 6B:** offline-practice packages, downloaded media, media-aware
  package replacement, and the small controller/UI integration needed to
  expose download, update, offline, locked, and media-unavailable states.
- **Release blockers resolved:** operational repository failures map to `503`
  rather than revocation; authoritative absence/denial uses non-probing `404`;
  media retrieval uses managed opaque IDs; public lifecycle tombstones persist
  across logout/account changes; and downloaded quizzes cannot enter
  assessment/test mode.

The Phase 6 suite was approved with focused cache/service/API/UI coverage,
PostgreSQL migration/concurrency tests, and a full real-PostgreSQL run of
362 passing tests with no failures or skips. Compilation and `git diff --check`
also passed. The historical intermittent native Qt crash was not reproduced;
this does not claim that native issue is definitively fixed.

### Deferred P1 / release polish

These are accepted follow-up items, not unresolved Phase 6 architectural
blockers. They should be planned as bounded pre-production reliability work.

1. **Keep expensive work off the Qt thread.** Discovery can synchronously
   check packages and rehash media. Move synchronization, downloads, hashing,
   and validation to a worker/task boundary so selectors stay responsive.
2. **Use a per-user writable cache location.** Replace `BASE_DIR/cache` with
   the platform application-data location so installed builds need not write
   beside their executable.
3. **Recover persisted `updating` state.** On restart, convert abandoned
   updates into stale/retryable state rather than leaving an entry stuck.
4. **Clean staging and recovery directories deterministically.** Retain safe
   recovery semantics while scheduling bounded cleanup of abandoned artifacts.
5. **Standardize the no-media response.** A valid content item without media
   should return an empty attachment list, not `404`.
6. **Harden package validation.** Validate card/question shape, required
   fields, choices, projection markers, media references, and applicable media
   type/signatures before exposing a package.
7. **Add resource limits and deterministic storage failures.** Define maximum
   package/media sizes, free-space checks, accurate disk accounting, disk-full
   behavior, and bounded/streamed media handling.
8. **Define multi-instance cache ownership.** Either enforce one desktop
   instance or introduce per-entry cache locking before concurrent writers are
   supported.
9. **Keep this storage contract current.** Future delivery work must update
   this document whenever offline-practice, media, or lifecycle semantics
   change.
10. **Document the accepted local-security model.** See the following risks;
    product guidance should make them visible where offline practice is
    enabled.

### Accepted product and security risks

- Offline-practice packages intentionally contain answer/evaluation data.
- A quiz used for both offline practice and online assessment is effectively
  open-book when the same content is assigned.
- Cached content is plaintext and protected by application authorization, not
  encryption at rest.
- Local tampering can affect local practice results, but cannot create or
  modify server-authoritative assessment attempts.

## Canonical demonstration content

The project intentionally keeps one six-question quiz demonstrating every
supported question type and one two-card flashcard deck demonstrating text,
front/back content, hint/description, image, and audio. Retired examples are
preserved under `legacy/data/` and are not part of runtime discovery.
