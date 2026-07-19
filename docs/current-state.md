# WorkTrace Current State

> Default entry point for developers and AI tools. This is the pre-release,
> current-only product contract; historical notes do not override it.

## Product

- Windows desktop application using Python, SQLite, pywebview and WebView2.
- Local-only: no registration, cloud sync, administrator privilege, screenshots,
  screen recording, OCR or keyboard logging.
- WebView is the only shipping UI. Window close runs `AppRuntime.shutdown()`.
- The privacy notice is fail-closed. Sensitive workers and clipboard capture do
  not start before acceptance.
- CSV is the only current public export.

## Composition and lifecycle owners

```text
webview_main -> AppRuntime -> ApplicationServices -> WebViewBridge
```

- `AppRuntime` owns the single-instance lease, Collector and every background
  worker thread handle.
- `ApplicationServices` is explicit process composition; there is no service
  locator, global DI container or dynamic service registry.
- `WebViewBridge` requires composed capabilities and imports no runtime/database
  implementation.
- `RuntimeMaintenanceCoordinator` solely owns snapshot/replacement ordering and
  the stable fail-closed latch.
- `CollectorControl` owns command identity and terminal states;
  `CollectorStateMachine` owns collection transitions.
- `ActivityMaintenanceCommandService` atomically seals an open activity and
  enqueues eligible inference.
- `PageReadContext`, `ActivityRowOverlay` and `activity_live_clock` respectively
  own read consistency, verified runtime overlay and the exact LiveClock DTO.

## Worker startup and shutdown

Workers are declared by `WorkerSpec` in one `AppRuntime` registry. A worker is
ready only after its own initialization succeeds and it reports readiness before
its stable blocking loop. Thread liveness or AppRuntime preflight is not
readiness. AppRuntime alone publishes worker `started`/`stopped`, signals and
joins every handle, and releases the instance lease only after all writers stop.

## Maintenance

Collector maintenance is not user pause:

```text
OPERATIONAL -> HOLD_REQUESTED -> SEALING -> HELD
HELD -> RESETTING -> HELD
HELD -> RELEASE_REQUESTED -> OPERATIONAL
```

A successful hold closes the current activity and enqueues inference in one
transaction, clears process-local activity state, then blocks Collector writes.
It creates no user-pause boundary and does not change durable `user_paused`.
The coordinator drains writers, acquires exclusive ownership, performs the
snapshot or replacement, resets identities while held, restores durable state
and releases the hold.

Every acknowledgement must match command ID, kind, completed state, expected
terminal state and `ok=true`. A known pending hold cancellation is retryable.
An unknown/taken command outcome, unconfirmed reset/release, or failure after
replacement work starts enters a stable fail-closed latch: durable pause is set,
runtime state is cleared and further destructive maintenance is rejected.
Ordinary pause/resume cannot clear this latch; only explicit verified recovery
may do so. The Settings status exposes `maintenance_in_progress`, not a
backup-specific alias. See [`maintenance-lifecycle.md`](maintenance-lifecycle.md).

## Project, rule and privacy invariants

Schema seeding alone creates system projects. Stable identity, not display name,
controls reserved behavior. Ordinary commands cannot create, rename, archive,
delete or toggle system projects. Missing system rows are reported unavailable;
normal API reads or writes never recreate them.

All keyword/folder create, update, delete, enable and batch mutations use the
canonical rule command owner. Excluded rules use explicit catalog commands;
callers cannot combine a reserved project ID with an ordinary service. The owner
validates project type, normalized patterns, duplicates and batch atomicity.
Classification/privacy generations publish only after commit; no-op and rollback
publish nothing, and a batch publishes at most once per affected namespace.

Privacy classification is a pure query returning `ExclusionDecision`. When a
private path is unresolved it fails closed and reports whether refresh is
required; Collector alone schedules the folder-index refresh.

## Current data contracts

- Database schema: **v12**.
- Encrypted backup payload: **v6**.
- Frontend live-time transport: **LiveClock v2**.
- Old schemas, backup payloads and LiveClock aliases are unsupported.
- Schema SQL files define the exact current fingerprint.
- Production `worktrace.db` has no destructive reset/drop helper; tests use
  `tests/support/database.py`.

Exact versions and DTO keys are in
[`runtime-contracts.md`](runtime-contracts.md).

## Live display

Every live-capable row has one exact nine-field clock. Current activity uses
`current_live`; project/session/KPI aggregates use `aggregate_live`; closed rows
use `static_closed`. Overlay occurs only when runtime and SQLite agree, including
the database-replacement epoch. Historical or mismatched samples stay static.

Overview owns current-activity presentation. Timeline is the canonical row
surface that matches an open persisted activity ID to exactly one live entry.
The frontend validates exact keys and types, never chooses among candidate
clocks, and never carries duration into a new identity. `init.js` owns the
accepted runtime store and its narrow active-clock reader; render helpers may
consume that reader but cannot create another clock registry. Invalid clocks
stop the target ticker, retain durable seconds and request bounded reconciliation.

## Pages and writes

- Overview: KPIs, current activity, Recent and pause/resume.
- Timeline: navigation, sessions, summaries and permitted edits.
- Statistics/Export: canonical summaries and display-safe CSV.
- Project Rules: transactional project/rule management.
- Settings/Privacy: privacy status, clipboard control, backup/import and clear-all.

Persisted open normal sessions allow project and note edits, but duration and
structural edits wait for closure. Rule batches are atomic; manual assignments
are preserved. Statistics/export use persisted report facts, not frontend time.

## Validation

Affected validation: `python scripts/run_affected_tests.py`.

Full validation:

- `python -m pytest`
- `node --test tests/webview/*.test.js`
- Windows executable and installer smoke in Standard CI

Standard CI validates one exact revision and publishes one complete bounded
Python diagnostic manifest. Repairs are grouped by root cause, not patched one
test at a time. Concurrency tests use bounded events/joins and required risk
markers. Fixtures exercise current owners through explicit composed fakes.

Only `.github/workflows/ci.yml` and `_validation.yml` are permanent workflows.
Acceptance and temporary agent workflows are absent. Historical WebView phases
remain only in [`history/webview-phases.md`](history/webview-phases.md).
