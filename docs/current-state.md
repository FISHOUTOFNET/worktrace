# WorkTrace Current State

> Default entry point for developers and AI tools. This file describes the
> pre-release current-only product contract. Historical migration notes do not
> override this document.

## Product

- Windows desktop application using Python, SQLite, pywebview and WebView2.
- Local-only: no registration, cloud sync, administrator privilege, screenshots,
  screen recording, OCR or keyboard logging.
- WebView is the only shipping UI. Closing the window runs `AppRuntime.shutdown()`.
- The privacy notice is fail-closed. Collector, folder indexing and clipboard
  capture cannot start before acceptance.

## Composition and lifecycle owners

```text
webview_main
  -> AppRuntime
  -> ApplicationServices
  -> WebViewBridge
  -> explicit bridge-facing APIs/services
```

- `AppRuntime` owns the single-instance lease, Collector thread and all
  background-worker thread handles.
- `ApplicationServices` is the explicit process composition object. There is no
  service locator, global DI container or dynamic service registry.
- `RuntimeMaintenanceCoordinator` is the only owner of consistent-snapshot and
  database-replacement ordering.
- `CollectorControl` owns command identity and terminal command states.
- `CollectorStateMachine` owns process-local collection transitions.
- `ActivityMaintenanceCommandService` owns the atomic maintenance seal and
  inference enqueue transaction.
- `PageReadContext` owns the runtime/SQLite optimistic handshake.
- `ActivityRowOverlay` owns verified row-level runtime overlay.
- `activity_live_clock` owns the exact LiveClock transport DTO.

## Worker startup and shutdown

Background workers are declared in the `AppRuntime` worker registry. Adding a
worker requires one `WorkerSpec`, not another parallel thread member or startup
branch. Readiness means initialization and required schema/database checks have
completed and the worker has entered its stable loop; `thread.is_alive()` alone
is not readiness. `AppRuntime` is the sole owner of worker `started` and
`stopped` health transitions. Shutdown signals and joins every registered handle
before the single-instance lease can be released.

## Maintenance

Collector maintenance is distinct from user pause:

```text
OPERATIONAL -> HOLD_REQUESTED -> SEALING -> HELD
HELD -> RESETTING -> HELD
HELD -> RELEASE_REQUESTED -> OPERATIONAL
```

A successful hold closes the current activity and enqueues eligible inference in
one transaction, clears process-local activity state, and then prevents active
window, clipboard, heartbeat, privacy-refresh and activity writes. It does not
create a session boundary, write a maintenance activity or change durable
`user_paused` intent. Snapshot/replacement maintenance then drains writers and
enters exclusive write ownership. Database replacement publishes its epoch in
the replacement transaction, resets process-local identities while Collector is
still held, restores durable settings and releases the hold. Unknown command
state fails closed. See [`maintenance-lifecycle.md`](maintenance-lifecycle.md).

## Data contracts

- Current database schema: **v12**.
- Current encrypted backup payload: **v6**.
- Current frontend live-time transport: **LiveClock v2**.
- This pre-release build does not migrate old schemas, import old backup payloads
  or accept LiveClock v1 aliases.
- `schema.sql`, `schema_internal.sql` and `schema_indexes.sql` define the exact
  current database fingerprint.
- Production `worktrace.db` exposes no destructive reset/drop helper; tests use
  `tests/support/database.py`.

The exact versions and LiveClock keys are documented in
[`runtime-contracts.md`](runtime-contracts.md).

## Live display

Every live-capable row owns one exact clock. Current activity uses
`current_live`; project/session/KPI aggregates use `aggregate_live`; closed rows
use `static_closed`. Overlay occurs only when the runtime sample and SQLite
snapshot agree, including database-replacement epoch. Historical dates and
mismatched samples remain static.

The frontend validates the exact key set and types. It never reads aliases,
chooses a maximum among candidates or carries a prior duration into a new
payload. Malformed clocks stop the affected ticker, retain durable static
seconds, emit one deduplicated diagnostic and request a low-frequency full
refresh. DOM continuity may avoid unnecessary redraws but cannot alter duration.

## Pages and write capabilities

- Overview: daily KPIs, current activity, Recent and pause/resume.
- Timeline: date navigation, sessions, activity summaries and permitted edits.
- Statistics/Export: canonical summaries and display-safe CSV export.
- Project Rules: project and rule management with canonical transactional
  invariants.
- Settings/Privacy: privacy status, clipboard control, encrypted backup/import
  and clear-all.

Persisted open normal sessions allow project and note edits, but duration and
structural edits remain disabled until closure. Rule batch changes are atomic;
manual assignments are preserved. Statistics and export use persisted canonical
report facts, not frontend live-time inference.

## Validation

- `python -m pytest`
- `node --test tests/webview/*.test.js`
- Windows single-file and installer smoke in Standard CI

Only `.github/workflows/ci.yml` and its reusable Standard validation workflow are
used. Acceptance and temporary agent workflows are not part of the architecture.
