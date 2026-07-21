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
- CSV export is the only current public export. Excel, PDF and timesheet-template
  export are unsupported in the shipping WebView.

## Composition and lifecycle

```text
webview_main -> AppRuntime -> ApplicationServices -> WebViewBridge
```

- `AppRuntime` owns the single-instance lease, Collector and every background
  worker thread handle.
- `ApplicationServices` is explicit frozen-dataclass composition with no service
  locator. `WebViewBridge` mixins call `self._services.<capability>.*` and never
  import production API facades.
- `RuntimeMaintenanceCoordinator` solely owns snapshot/replacement ordering and
  the stable fail-closed latch.
- `CollectorControl`/`CollectorStateMachine` own command identity, terminal
  states and collection transitions; `ActivityMaintenanceCommandService`
  atomically seals an open activity and enqueues eligible inference.

Workers are declared by `WorkerSpec` in one `AppRuntime` registry. A worker
is ready only after its own initialization succeeds and it reports readiness
before its stable blocking loop; thread liveness or preflight is not
readiness. AppRuntime alone publishes `started`/`stopped`, signals, joins
every handle, and releases the instance lease only after all writers stop.

## Maintenance

Collector maintenance is not user pause:

```text
OPERATIONAL -> HOLD_REQUESTED -> SEALING -> HELD
HELD -> RESETTING -> HELD
HELD -> RELEASE_REQUESTED -> OPERATIONAL
```

A successful hold closes the current activity and enqueues inference in one
transaction, clears process-local activity state, then blocks Collector
writes without changing durable `user_paused`. The coordinator drains
writers, acquires exclusive ownership, performs the snapshot or replacement,
resets identities while held, restores durable state and releases the hold.
Every acknowledgement matches command ID, kind, completed state, terminal
state and `ok=true`. An unknown/taken outcome, unconfirmed reset/release,
or failure after replacement work enters a stable fail-closed latch:
durable pause set, runtime state cleared, further destructive maintenance
rejected. Ordinary pause/resume cannot clear it; only explicit verified
recovery may. Settings status exposes `maintenance_in_progress`, not a
backup alias.

## Transaction and replacement owners

Ordinary mutations use `DomainUnitOfWork`: a context manager that opens one
SQLite transaction, yields the connection, commits or rolls back on exit.
Physical replacement uses `DatabaseReplacementUnitOfWork`, the sole owner
of the epoch bump, the single live-database commit and process-local
generation publication. Secure backup import enters the maintenance hold,
validates and stages the payload in a separate staging database, then
routes the live replacement through `DatabaseReplacementUnitOfWork`; the
staging database is discarded after replacement.

## Database content manifest

`database_content_manifest` is the single source of truth for current-schema
content table membership. Every table carries a `TableCategory` enum
(`durable_configuration`, `live_activity_data`, `derived_data`,
`projection_operations`, `mutation_receipts`, `maintenance_recovery_state`,
`generation_state`, `worker_progress`); backup, clear, privacy wipe, delete
order and schema coverage governance all derive their table sets from it.

## Report replay identity

Report session replay is members-only. Admission revision is distinct from
durable replay identity: admission accepts a request and returns a stable
projection revision, while replay binds exactly the member operations that
committed under it. Copy, merge, split and undo form a supersede graph;
split closes the source session supersession and creates two new
member-bound sessions. Copy identity never conflates with the source.
Revision-based (non-members) replay is rejected at the read boundary.

## Project, rule and privacy invariants

Schema seeding alone creates system projects. Stable identity, not display
name, controls reserved behavior. Ordinary commands cannot create, rename,
archive, delete or toggle system projects. Shipped lifecycle capabilities
are exactly: user project create / edit / enable-disable / archive.
Missing system rows are reported unavailable; normal API never recreates them.

All keyword/folder mutations use the canonical rule command owner, which
validates project type, normalized patterns, duplicates and batch
atomicity. Excluded rules use explicit catalog commands; callers cannot
combine a reserved project ID with an ordinary service.
Classification/privacy generations publish only after commit; no-op and
rollback publish nothing, and a batch publishes at most once per affected
namespace. Privacy classification is a pure query returning
`ExclusionDecision`; an unresolved private path fails closed and reports
whether refresh is required, while Collector alone schedules the
folder-index refresh.

## Current data contracts

- Database schema: **v13**.
- Encrypted backup payload: **v6**.
- Frontend live-time transport: **LiveClock v2**.
- Old schemas, backup payloads and LiveClock aliases are unsupported.
- Schema SQL files define the exact current fingerprint.
- `database_content_manifest` is the single table inventory; backup, clear
  and delete-order sets derive from it.
- Production `worktrace.db` has no destructive reset/drop helper; tests use
  `tests/support/database.py`.

Exact versions and DTO keys are in
[`runtime-contracts.md`](runtime-contracts.md).

## Live display

Every live-capable row has one exact nine-field clock. Current activity uses
`current_live`; aggregates use `aggregate_live`; closed rows use
`static_closed`. Overlay occurs only when runtime and SQLite agree, including
the database-replacement epoch; mismatched samples stay static. Overview
owns current-activity presentation; Timeline matches an open persisted
activity ID to exactly one live entry. The frontend validates exact keys
and types, never chooses among candidate clocks, and never carries duration
into a new identity. `init.js` owns the runtime store and active-clock
reader; invalid clocks stop the ticker, retain durable seconds and request
bounded reconciliation.

## Pages and writes

- Overview: KPIs, current activity, Recent and pause/resume.
- Timeline: navigation, sessions, summaries and permitted edits.
- Statistics/Export: canonical summaries and display-safe CSV.
- Project Rules: transactional project/rule management.
- Settings/Privacy: privacy status, clipboard control, backup/import and clear-all.

Open sessions allow project and note edits; duration and structural edits
wait for closure. Rule batches are atomic; manual assignments are
preserved. Statistics/export use persisted report facts, not frontend time.

## Validation

Affected validation: `python scripts/run_affected_tests.py`. Full validation:

- `python -m pytest`
- `node --test tests/webview/*.test.js`
- Windows executable and installer smoke in Standard CI

Standard CI validates one exact revision and publishes one bounded Python
diagnostic manifest. Business-test diagnostics are artifact-only: the
frozen workflow uploads a structured `diagnostics.json` and JUnit XML on
failure; job logs never contain failure lists, root-cause groups,
tracebacks or test-log tails. Repairs are grouped by root cause, not
patched one test at a time. Concurrency tests use bounded events/joins
and required risk markers; fixtures exercise current owners through
explicit composed fakes. Only `.github/workflows/ci.yml` and
`_validation.yml` are permanent workflows; acceptance and temporary agent
workflows are absent. Historical WebView phases remain only in
[`history/webview-phases.md`](history/webview-phases.md).
