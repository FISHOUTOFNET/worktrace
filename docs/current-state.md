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
- CSV is the only current public export. Excel, PDF and timesheet-template export
  are unsupported in the shipping WebView.

## Composition and lifecycle owners

```text
webview_main
  -> AppRuntime
  -> ApplicationServices
  -> explicit API-facing capabilities
  -> WebViewBridge
```

- `AppRuntime` owns the single-instance lease, Collector thread and all
  background-worker thread handles.
- `ApplicationServices` is the explicit process composition object. There is no
  service locator, global DI container or dynamic service registry.
- `WebViewBridge` requires explicit capabilities at construction and imports no
  runtime, service or database implementation.
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
branch. Readiness means the worker itself completed initialization and required
schema/database or recovery checks and then reported ready before its stable
blocking loop. `thread.is_alive()` and AppRuntime preflight alone are not
readiness. `AppRuntime` is the sole owner of worker `started` and `stopped`
health transitions. Shutdown signals and joins every registered handle before
the single-instance lease can be released.

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
still held, restores durable settings and releases the hold.

Collector has no secure-backup import guard or backup-service reverse dependency.
Backup and replacement flows obtain safety exclusively through the explicit
maintenance hold and coordinator ordering.

Every acknowledgement must match command ID, kind, completed state, expected
terminal state and `ok=true`. Unknown command or unconfirmed release state enters
a stable fail-closed latch: durable user pause is set, the runtime snapshot is
cleared and further destructive maintenance is rejected. Only explicit verified
runtime recovery can clear the latch. See
[`maintenance-lifecycle.md`](maintenance-lifecycle.md).

## Project, rule and privacy invariants

Current schema seeding is the only creator of system projects. Stable system
identity, not display name, controls reserved behavior. Ordinary commands cannot
create, rename, archive, delete or toggle system projects. The shipped user
project capabilities are: user project create / edit / enable-disable / archive.
Excluded project configuration uses its explicit system-project command. Missing
system catalog rows are reported as unavailable; transport APIs never recreate
them as a side effect of a normal project or rule request.

All keyword/folder rule create, update, delete, enable and batch operations pass
through the canonical rule command owner. It validates project type, normalized
patterns, duplicates and batch atomicity. Classification and privacy generations
are published after commit only: semantic no-op and rollback publish nothing,
and a batch publishes at most once per affected namespace.

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

Every live-capable row owns one exact nine-field clock. Current activity uses
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

## Validation and history

Day-to-day affected validation:

```text
python scripts/run_affected_tests.py
```

Full validation:

- `python -m pytest`
- `node --test tests/webview/*.test.js`
- Windows single-file and installer smoke in Standard CI

Standard CI validates one exact revision and publishes complete Python diagnostics
when the suite fails. Diagnosis and repair are performed by root-cause group from
the full manifest; individual failing tests are not treated as independent patch
targets. Concurrency tests use bounded events or joins rather than explicit sleep
polling, and the inventory gate requires their runtime-risk markers.

Test fixtures exercise current owners rather than manufacturing legacy state:
open activity continuity is seeded through `CollectorStateMachine`, excluded
keyword/folder rules use explicit catalog commands, and frontend governance checks
exact LiveClock v2 behavior rather than historical file placement or aliases.

Only `.github/workflows/ci.yml` and its reusable Standard validation workflow are
used. Acceptance and temporary agent workflows are not part of the architecture.
Historical WebView implementation phases are retained only at
[`history/webview-phases.md`](history/webview-phases.md).
