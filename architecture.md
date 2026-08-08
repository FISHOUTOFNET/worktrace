# WorkTrace Architecture Contract

This is the current pre-release architecture contract. It defines ownership,
transaction, concurrency and transport boundaries. Historical implementation
notes are subordinate to this document and to
[`docs/current-state.md`](docs/current-state.md).

## Composition root

```text
worktrace.webview_main
  -> DesktopShellController / WindowsTrayHost
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

`PostPrivacyStartupCoordinator` is the single post-consent startup entry for the
Collector and a fixed tuple of narrow `PostPrivacyParticipant` capabilities.
The composition root supplies that tuple explicitly; there is no discovery or
registry. Before authoritative consent, enabling an optional integration
persists preference only and creates or navigates no helper window.

Bridge code performs transport validation, stable error translation and explicit
service calls only. It does not own business invariants, transactions, runtime
state or database facts.

## Owner map

| Responsibility | Sole owner |
| --- | --- |
| Window/tray visible-hidden-exiting state | `DesktopShellController` |
| Notification-area icon lifetime | `WindowsTrayHost` |
| Current-user login registration | `WindowsStartupRegistration` / HKCU Run |
| Existing-instance activation Event | `ApplicationInstanceCoordinator` |
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
| External project identity use-case boundary | `ProjectIdentityIntegrationCapability` |
| Post-commit external-state invalidation | `ApplicationDataLifecycle` fixed participant tuple |
| FD Work plugin/privacy/token/binding policy | `FDWorkIntegrationService` |
| FD Work interaction owner and operation lifetime | `FDWorkInteractionCoordinator` |
| FD Work helper lifetime/page phase/window mutations | `FDWorkWindowController` |
| FD Work URL/selectors/picker/fill DOM contract | `FDWorkPageAdapter` / adapter v5 |
| FD Work helper callback surface | `FDWorkHelperBridge` |
| Main-window FD Work callback serialization | `FDWorkMainWindowSink` |
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

The desktop shell is outside `AppRuntime`. A close request may become a hide
transition only while the tray icon is available. Tray Open and named-Event
activation call the idempotent shell show command. Tray Exit sets EXITING,
removes the icon and destroys the WebView window; the existing composition-root
`finally` remains the only caller of `AppRuntime.shutdown()`. The tray thread
never calls Runtime, database or Collector APIs.

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
capture durable/runtime state
-> Collector hold
-> require HELD acknowledgement
-> clear runtime snapshot
-> enter write-gate DRAINING
-> drain admitted writers
-> promote to EXCLUSIVE
-> run snapshot or replacement body
-> replacement only: reset process-local identities while still EXCLUSIVE and HELD
-> restore durable settings while still EXCLUSIVE and HELD
-> request Collector release while still EXCLUSIVE
-> require OPERATIONAL acknowledgement
-> verify recovery seal/final state
-> exit EXCLUSIVE/DRAINING scope
-> return IDLE
```

Only one maintenance operation can enter this sequence. Replacement publishes
its database epoch in the same transaction as replacement data. On unknown
state or failed restoration, durable pause/status are committed as a separate
fail-closed safety transition and the runtime snapshot remains cleared. The
fail-closed latch blocks later destructive maintenance until explicit runtime
recovery verifies an operational Collector and inactive write gate.

See [`docs/maintenance-lifecycle.md`](docs/maintenance-lifecycle.md).

## Database and transaction boundaries

The current schema is v13 and is current-only. Startup accepts an empty database
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
v13 plus the exact schema fingerprint. Old payloads are rejected; there is no
backup migration path. Installation privacy consent is not backup business data
and remains owned by installation metadata.

Collector does not depend on backup service to learn maintenance state. Backup
service depends on the maintenance coordinator, never the reverse.

Optional plugin state is outside the main database and backup manifest. FD Work
project bindings use a lazily-created, independently versioned SQLite sidecar at
`plugins/fd_work/state.db`, injected by the composition root. Replacement and
clear-local-data operations invalidate or remove these bindings fail-closed;
ordinary backup export never includes them.

Core project CRUD remains owned by `project_service`. Project Rules sees only the
use-case-level `ProjectIdentityIntegrationCapability` and opaque external
identity proof/binding results; it does not know selection nonce, navigation,
adapter or picker concepts. The composition root injects the concrete integration
with core CRUD callbacks, so dependencies are one-way from the integration to the
application port. Shipping `fd_work_*` DTO names exist only at WebView transport
compatibility boundaries. Settings and Backup trigger a fixed
`ApplicationDataLifecycle` participant tuple after successful main-data commits;
they do not import or instantiate an integration.

FD Work case selection has one interaction owner. With the plugin disabled,
Project Rules keeps the ordinary editable local project-name field and does not
create or show the helper. With the plugin enabled, new projects use the FD Work
native Ant Design Select through an explicit helper-window picker; WorkTrace
renders only the read-only confirmed label and picker controls. It does not run
cross-window autocomplete from focus, click or input events. A process-memory,
one-use selection token is required before a new bound project can be saved.

Session state (`disabled`, `deferred_by_privacy`, `idle`, `probing`,
`login_required`, `ready`, `error`, `shutdown`) is separate from interaction
ownership (`none`, `user_auth`, `user_picker`, `automation_fill`, `user_review`).
Only one non-`none` owner exists. Picker and authentication are user-owned;
Timeline fill is automation-owned until verified readback, then becomes
user-review-owned and performs no further writes. Helper close, navigation,
disable and shutdown invalidate the current nonce/generation. The helper exposes
only `confirm_case_picker` and `cancel_case_picker`; it has no application service
access and never creates bindings.

Every helper `show`, `hide`, `restore`, `focus` and `destroy` mutation goes through
the GUI dispatcher with window, navigation and operation guards before and after
the mutation. No pywebview mutation occurs while the controller lock is held.
Passive probes are hidden and side-effect free. Adapter v5's stable-shell check
observes visibility, viewport, overlays and stable geometry only; it never focuses,
clicks, types, blurs or sends Escape. Durable sidecar binding validity is
independent of adapter version, so v4-created bindings remain valid under v5.

## Frontend and page boundaries

Frontend scripts are local classic scripts. `core.js` owns the shared exact clock
validator and ticker helpers. `init.js` owns accepted runtime envelope state and
page refresh coordination. Page modules render backend DTOs and row-owned clocks
only. They must not infer database business facts or search aliases.

`window.WorkTraceApp` remains the public classic-script namespace, not a shared
mutable-state owner. Timeline, Statistics, Rules, Settings, Overview and FD Work
own their transient generation state and expose fixed `resetGeneration` methods.
The central generation reset bumps the runtime generation, resets the runtime
store, and invokes those static lifecycle hooks without reading page-private
fields. FD Work owns picker request, selection-proof and binding-editor state;
Project Rules calls only the narrow `projectIdentity` editor interface.

Overview, Timeline, Details, Statistics and Export use the same canonical report
facts. Natural live-second growth is DOM-local and does not trigger heavy page
reload. Structural/replacement changes flow through explicit revisions and the
existing refresh coordinator.

Statistics date-range transport uses a single semantic: empty `date_from` and
`date_to` together mean canonical all-time (1970-01-01 to today); any other
combination must be non-empty ISO dates. The frontend explicitly computes and
sends the first day of the current month and today on default entry, so the
backend never infers "default this month" from empty strings. A single
`resolve_statistics_date_range` function owns this resolution; one empty and
one non-empty date returns `invalid_date`.

Statistics CSV export is a mandatory-ticket contract: the bridge, protocol,
API and service all require a non-empty `expected_export_ticket_revision`
that matches the current snapshot revision, normalized date range, project
scope, CSV format, and schema version. There is no optional or `None` path.
The bridge validates the ticket before opening the save dialog. The service
unconditionally raises `stale_statistics_snapshot` on any mismatch.

One CSV export operation builds exactly one canonical snapshot via
`build_visible_snapshot`. That single snapshot object is used for both the
export ticket computation/validation and the CSV record iteration, closing
the check-then-use time window. CSV records are streamed row-by-row inside
the atomic file output context; they are never fully materialized as a list.
Zero records raise `empty_data` inside the context, so no target file or
temp residue is committed.

## Governance

The permanent validation path is Standard CI only: Python 3.11 full suite,
WebView Node tests and Windows package smoke. Acceptance and temporary workflows,
`.github/agent_*.py`, one-off code generators and service locators are forbidden.
Tests preserve behavior and owner contracts; failures are fixed by root-cause
groups, not by deleting tests, weakening assertions or restoring compatibility
fallbacks.
