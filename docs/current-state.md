# WorkTrace Current State

> Default entry point for developers and AI tools. This is the pre-release,
> current-only product contract; historical notes do not override it.

## Product
- Windows desktop application using Python, SQLite, pywebview and WebView2.
- Local-only: no registration, cloud sync, administrator privilege, screenshots,
  screen recording, OCR or keyboard logging.
- WebView is the only shipping UI. Window close runs `AppRuntime.shutdown()`.
- The privacy notice is fail-closed; sensitive workers and clipboard capture do
  not start before acceptance.
- CSV export is the only current public export; Excel, PDF and timesheet-template
  export are unsupported in the shipping WebView.

## Composition and lifecycle
```text
webview_main -> AppRuntime -> ApplicationServices -> WebViewBridge
```
- `AppRuntime` owns the single-instance lease, Collector and every background
  worker thread handle.
- `ApplicationServices` is explicit frozen-dataclass composition with no service
  locator. `WebViewBridge` calls `self._services.<capability>.*` only.
- `RuntimeMaintenanceCoordinator` solely owns snapshot/replacement ordering and
  the stable fail-closed latch.
- `CollectorControl`/`CollectorStateMachine` own command identity, terminal
  states and collection transitions; the maintenance command atomically seals
  an open activity and enqueues eligible inference.

Workers are declared by `WorkerSpec` in one `AppRuntime` registry. Readiness
requires successful initialization and an explicit ready signal before the stable
blocking loop. AppRuntime alone publishes lifecycle state, signals and joins all
handles, and releases the instance lease only after every writer stops.

## Maintenance
Collector maintenance is not user pause:
```text
OPERATIONAL -> HOLD_REQUESTED -> SEALING -> HELD
HELD -> RESETTING -> HELD
HELD -> RELEASE_REQUESTED -> OPERATIONAL
```
A successful hold seals the current activity, clears process-local activity state
and blocks Collector writes without changing durable `user_paused`. The
coordinator drains writers, enters exclusive ownership, performs the operation,
restores durable state, releases the hold and verifies terminal OPERATIONAL before
leaving the exclusive scope. Pre-commit failure uses the same order. Durable
restore failure sends no release; Collector remains HELD and fail-closed is set.
Unknown hold/reset/release outcomes also fail closed. Ordinary pause/resume cannot
clear that latch; only explicit verified recovery may.

## Transaction and replacement owners
`DomainUnitOfWork` owns ordinary root/nested SQLite transactions, rollback-only
propagation, declared effects and explicitly changed effects. SQL text, row
counts, `total_changes` and commit hooks never infer business semantics.
`mark_changed(namespace)` requires a declared namespace; missing or undeclared
effects are contract errors. Root commit bumps each marked namespace at most once.
No-op, rollback, worker progress, checkpoint and receipt-only writes publish no
business generation. Effective report operations publish `REPORT_STRUCTURE` once;
no-effect and duplicate receipts do not publish.

`DatabaseReplacementUnitOfWork` solely owns the replacement epoch, live commit
and process-local generation publication. Secure import creates decrypted staging
inside one `ValidatedStaging` scope, fully validates it before maintenance and
deletes it after success, maintenance rejection or any failure. Staging content
and semantic validation failures raise `BackupCorruptedError`; local staging
infrastructure failures raise `BackupStagingInfrastructureError`. Neither changes
live data, generations or recovery state. Once staging is valid, ordinary live
apply/generation/validation/commit/I/O failures raise `BackupReplacementError`
with the internal cause chained. Maintenance/recovery errors remain separate.

## Database content manifest
`database_content_manifest` is the only current-schema table inventory. Each table
has a `TableCategory`; backup, clear, privacy wipe, delete order and schema
coverage derive their sets from this manifest.

## Report replay identity
Report replay is members-only. Admission revision and durable replay identity are
separate. Copy, merge, split and undo form a supersede graph. Non-members legacy
revision replay is rejected at the read boundary. Operation payload version is
`6`; repository, replay engine and backup validator share one contract owner.

## Project, rule and privacy invariants
Schema seeding alone creates system projects. Stable identity controls reserved
behavior. Ordinary commands cannot create, rename, archive, delete or toggle
system projects; missing system rows are reported unavailable rather than
recreated by normal API calls. Shipped lifecycle capabilities are exactly:
user project create / edit / enable-disable / archive.

Keyword/folder mutations use the canonical rule command owner for project type,
normalized pattern, duplicate and batch-atomicity validation. Excluded rules use
explicit catalog commands. Classification/privacy generations publish only after
commit; no-op and rollback publish nothing and each affected namespace bumps at
most once. Privacy classification is a pure `ExclusionDecision` query; unresolved
private paths fail closed while Collector alone schedules folder-index refresh.

## Current data contracts
- Database schema: **v13**.
- Encrypted backup payload: **v6**.
- Report operation payload: **v6**.
- Frontend live-time transport: **LiveClock v2**.
- Old schemas, payloads, replay bindings and LiveClock aliases are unsupported.

Exact versions and DTO keys are in [`runtime-contracts.md`](runtime-contracts.md).

## Live display
Every live-capable row has one exact nine-field clock: `current_live` for current
activity, `aggregate_live` for aggregates and `static_closed` for closed rows.
Overlay occurs only when runtime and SQLite identities agree, including the
replacement epoch. Overview owns current-activity presentation; Timeline matches
one persisted open activity ID to one live entry. The frontend validates exact
keys/types, never selects among candidate clocks and never carries duration into a
new identity. Invalid clocks stop ticking, retain durable seconds and request
bounded reconciliation.

## Pages and writes
- Overview: today total, current atomic activity snapshot, recent records
  (merged report sessions including in-progress and needs-attention items),
  and an attention subset of recent records (at most three); editing hands
  off to Timeline. Attention is a subset of recent, not a disjoint partition.
  The subset constraint holds at the payload level: every visible attention
  item is also present in the visible recent list, even after both are
  truncated to their display limits.
- Timeline: reverse chronological sessions, authoritative project filtering,
  debounced autosave, always-visible activity details, direct two-step deletion,
  and a compact-window focus-trapped Drawer.
- Statistics/Export: this-month default with all-time/custom options, optional
  project scope, automatic latest-request acceptance, and display-safe CSV bound
  to the accepted export ticket.
- Project Rules: searchable/sortable project summaries with backend-owned last
  use, three direct project actions, and contextual Drawers.
- Settings/Privacy: five user-facing categories, plain-language health summary,
  collapsed diagnostics, privacy status, clipboard control, backup/import and
  clear-all. Secret inputs remain local and are cleared after use.

Open sessions allow project and note edits; duration and structural edits wait for
closure. Rule batches are atomic, manual assignments are preserved, and
statistics/export use persisted report facts rather than frontend time.

## Validation
Affected validation: `python scripts/run_affected_tests.py`. Full validation:
- `python -m pytest`
- `node --test tests/webview/*.test.js`
- Windows executable and installer smoke in Standard CI

Standard CI validates one exact revision. Python business-test diagnostics are
artifact-only (`diagnostics.json` and JUnit XML); logs do not replay failures,
tracebacks or test tails. Repairs are grouped by semantic root cause. Concurrency
tests use bounded events/joins and required risk markers. Only
`.github/workflows/ci.yml` and `_validation.yml` are permanent workflows;
acceptance and temporary agent workflows remain absent. Historical WebView phases
are archived in [`history/webview-phases.md`](history/webview-phases.md).
