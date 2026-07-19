# WorkTrace Architecture Contract

This is the current pre-release architecture contract. It defines ownership,
transaction, concurrency and transport boundaries. Historical implementation
notes are subordinate to this document and to
[`docs/current-state.md`](docs/current-state.md).

## Composition root

```text
worktrace.webview_main
  -> AppRuntime
  -> ApplicationServices
  -> WebViewBridge
  -> explicit bridge-facing APIs and services
```

`webview_main` resolves paths, configures logging, creates `AppRuntime`, builds
`ApplicationServices`, exposes the bridge and guarantees runtime shutdown.
`ApplicationServices` is a lightweight explicit composition object, not a DI
framework. Production code must not add a global container, module-level runtime
locator, `get_runtime()`/`set_runtime()`, string service lookup or dynamic
registry.

Bridge code performs transport validation, stable error translation and explicit
service calls only. It does not own business invariants, transactions, runtime
state or database facts.

## Owner map

| Responsibility | Sole owner |
| --- | --- |
| Process/thread lifecycle | `AppRuntime` |
| Worker declarations and handles | `AppRuntime` worker registry |
| Worker initialization readiness | worker-owned `WorkerStartupReporter` handshake |
| Collector command identity/state | `CollectorControl` / `RuntimeCollectorControl` |
| Collection transitions | `CollectorStateMachine` |
| Atomic maintenance activity seal | `ActivityMaintenanceCommandService` |
| Maintenance ordering/recovery | `RuntimeMaintenanceCoordinator` |
| Backup use cases | `SecureBackupService` module |
| Project lifecycle invariants | `project_service` |
| Rule write invariants | canonical rule command/service layer |
| Verified page read snapshot | `PageReadContext` |
| Row runtime overlay | `ActivityRowOverlay` |
| Exact live-time DTO | `activity_live_clock` |
| Application composition | `ApplicationServices` |
| Frontend exact clock validation/ticking | shared clock functions in `core.js` |
| Accepted runtime-envelope state and refresh coordination | single store in `init.js` |

Two owners must never be synchronized to solve an ownership conflict. The
responsibility must be moved to one owner and the duplicate state deleted.

## Runtime and workers

`AppRuntime` owns the single-instance lease, adapter, Collector thread and every
background worker thread. Background workers are declared by `WorkerSpec` and
tracked by name in `WorkerHandle` mappings. Production code must not reintroduce
`_index_thread`, `_history_thread`, `_inference_thread` or similar parallel
members.

A worker is READY only after the worker itself has completed required
initialization, schema/database access and recovery/validation and reports ready
before entering its stable blocking loop. Thread liveness and AppRuntime
preflight cannot create readiness. The runtime wrapper owns thread start,
startup timeout, unexpected exit, unhandled exception, stopped state and handle
cleanup. Worker functions own initialization signalling, iteration
success/failure, maintenance-paused state and domain health codes only.

Shutdown sets the runtime stop signal, wakes blocking workers, signals each
handle, joins Collector and every registered worker and records any surviving
writer. The single-instance lease is released only after all writers stop.

`RuntimeStartResult` exposes exactly `ok`, `collector_ready`, `workers`,
`already_running`, `degraded` and `error_code`. `workers` is the only worker
status mapping. Runtime transport does not expose worker-specific top-level
fields or a parallel `error` alias; the Bridge translates canonical error codes
for users.

## Collector and maintenance

User pause and runtime maintenance are separate commands. Collector control kinds
are user pause, maintenance hold, database reset and maintenance release. The
maintenance state machine is:

```text
OPERATIONAL
  -> HOLD_REQUESTED
  -> SEALING
  -> HELD
  -> optional RESETTING -> HELD
  -> RELEASE_REQUESTED
  -> OPERATIONAL
```

In HELD, Collector performs no active-window observation, clipboard capture,
activity/heartbeat write or privacy-refresh write. It accepts only reset,
release or shutdown. Maintenance never creates `maintenance_pause`, never
creates a user session boundary and never mutates durable `user_paused`.

Every acknowledgement is identity-bearing: command ID, command kind, completed
state, expected terminal state and `ok=true` must match. A pending command may be
cancelled on timeout. A taken command with unknown result fails closed; the
coordinator cannot enter exclusive maintenance on an unverified hold. On
Collector shutdown or fatal exit, `RuntimeCollectorControl` terminalizes every
unfinished command with an explicit diagnostic, so no taken command remains
permanently unexplained.

The global order is:

```text
capture state
-> Collector hold and HELD acknowledgement
-> clear runtime snapshot
-> write-gate draining
-> drain admitted writers
-> exclusive coordinator capability
-> snapshot or database replacement
-> release exclusive capability
-> reset process-local identities while still HELD (replacement only)
-> restore durable settings
-> Collector release acknowledgement
```

Only one maintenance operation can enter this sequence. Replacement publishes
its database epoch in the same transaction as replacement data. On unknown
state or failed restoration, durable pause/status are committed as a separate
fail-closed safety transition and the runtime snapshot remains cleared. The
fail-closed latch blocks later destructive maintenance until explicit runtime
recovery verifies an operational Collector and inactive write gate.

See [`docs/maintenance-lifecycle.md`](docs/maintenance-lifecycle.md).

## Database and transaction boundaries

The current schema is v12 and is current-only. Startup accepts an empty database
or the exact current schema fingerprint. It does not run compatibility
migrations. Production `worktrace.db` owns initialization, connections, schema
application/fingerprint and defaults; destructive reset/drop helpers are test
only.

`DomainUnitOfWork` owns business transaction effects and generation publication.
Project/rule invariants are enforced inside canonical service transactions and
by current-schema constraints where concurrency requires it. APIs do not scan
whole tables to recreate uniqueness or atomicity.

Database replacement is independent from ordinary report/data generations.
Caches and page-read handshakes include the replacement epoch so facts from an
old database generation cannot overlay a new database.

## Runtime/SQLite handshake

A page request obtains a `PageReadContext` containing the persisted read snapshot
and the verified runtime sample. Runtime overlay is allowed only when the
sample, persisted open row identity, report date, runtime generation and database
replacement epoch agree. Failure is static, not guessed. `ActivityRowOverlay`
may attach one exact row clock; no API or UI layer may reconstruct the clock from
other fields.

## LiveClock v2

The only clock keys are:

```text
sampled_at_epoch_ms
started_at_epoch_ms
elapsed_seconds_at_sample
aggregate_base_seconds
duration_semantic
is_live
live_state
display_span_id
stable_live_key_hash
```

`duration_semantic` is `current_live`, `aggregate_live` or `static_closed`.
`live_state` is `persisted_open`, `suppressed` or `none`. Current activity uses
`current_live`. Aggregate rows use their durable closed base plus the current
verified elapsed sample. Closed and historical rows are static.

The frontend validates the exact key set, primitive types, enums, non-negative
numbers and live identity. It rejects extra/missing keys and never reads v1
aliases. Current duration is `elapsed_at_sample + local_delta`; aggregate
duration additionally includes `aggregate_base_seconds`. It does not recompute
server elapsed from `started_at_epoch_ms`, select maxima, carry old seconds or
use continuity to alter business duration.

Malformed clocks stop that ticker, render durable static duration, record one
deduplicated diagnostic and request an existing low-frequency refresh.

See [`docs/runtime-contracts.md`](docs/runtime-contracts.md).

## Backup and security

`.wtbackup` export/import is owned by `secure_backup_service`, which acquires the
maintenance capability itself. Current payload version is v6 and requires schema
v12 plus the exact schema fingerprint. Old payloads are rejected; there is no
backup migration path. Installation privacy consent is not backup business data
and remains owned by installation metadata.

Collector does not depend on backup service to learn maintenance state. Backup
service depends on the maintenance coordinator, never the reverse.

## Frontend and page boundaries

Frontend scripts are local classic scripts. `core.js` owns the shared exact clock
validator and ticker helpers. `init.js` owns accepted runtime envelope state and
page refresh coordination. Page modules render backend DTOs and row-owned clocks
only. They must not infer database business facts or search aliases.

Overview, Timeline, Details, Statistics and Export use the same canonical report
facts. Natural live-second growth is DOM-local and does not trigger heavy page
reload. Structural/replacement changes flow through explicit revisions and the
existing refresh coordinator.

## Governance

The permanent validation path is Standard CI only: Python 3.11 full suite,
WebView Node tests and Windows package smoke. Acceptance and temporary workflows,
`.github/agent_*.py`, one-off code generators and service locators are forbidden.
Tests preserve behavior and owner contracts; failures are fixed by root-cause
groups, not by deleting tests, weakening assertions or restoring compatibility
fallbacks.
