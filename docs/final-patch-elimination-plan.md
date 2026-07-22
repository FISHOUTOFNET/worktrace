# Final Patch-Elimination Architecture

Starting baseline: `main` at `163148478a02d00ed84c7b46c1e7af021fb291c9`.

This branch implements a current-only pre-release architecture. Historical
schema, backup, projection and runtime compatibility surfaces are not part of
the contract.

| Responsibility | Sole owner / contract |
| --- | --- |
| Process, long-lived thread and worker lifecycle | `AppRuntime` and its fixed worker registry |
| Platform capabilities | complete `RuntimePlatformAdapter` protocol with explicit Windows and test implementations |
| Collector command state | `RuntimeCollectorControl` with acknowledged terminal command states |
| Maintenance ordering, exclusion, restoration and fail-closed recovery | `RuntimeMaintenanceCoordinator` |
| Database write exclusion | `ProcessDatabaseWriteGate` |
| Business transactions and generation effects | explicit command owner plus root `DomainUnitOfWork` |
| Database replacement identity | database key plus durable `DATABASE_REPLACEMENT` generation |
| Decrypted import staging lifetime | one `ValidatedStaging` resource scope |
| Backup and clear table membership/order | `database_content_manifest.py` |
| Projection admission | persisted admission revision |
| Projection replay | payload v6 plus `ReplayBinding.MEMBERS` only; legacy revision bindings rejected at read boundary |
| Maintenance status | one seven-field backend DTO consumed unchanged by Bridge and JavaScript |
| Production composition | `worktrace.webview_main` and strict `ApplicationServices` |
| Test composition | explicit builders under `tests/support`; no optional production dependencies or global production-class replacement |

## Runtime lifecycle

`AppRuntime` initializes the database and platform boundary, starts Collector
before derived workers, and owns every long-lived worker thread. Shutdown stops
and joins Collector first, then derived workers, then the platform adapter. The
single-instance lock is released only after every writer has stopped and final
runtime state has been committed.

## Maintenance state

The maintenance DTO contains exactly:

- `maintenance_in_progress`
- `maintenance_restored`
- `recovery_blocked`
- `blocked_reason`
- `collector_running`
- `collector_status`
- `user_paused`

Active maintenance and durable fail-closed recovery blocking are distinct.
Clear and encrypted import use the same coordinator and write gate. Both normal
completion and pre-commit failure restoration use one order while Collector is
HELD and the write gate remains EXCLUSIVE:

```text
restore durable state
-> request maintenance release
-> require terminal OPERATIONAL acknowledgement
-> exit EXCLUSIVE scope
-> return IDLE
```

Durable restoration failure sends no release and enters fail-closed. Unknown or
failed release/reset also remains fail-closed. Pre-existing user pause, stopped
Collector and unaccepted privacy notice are preserved; restoration never starts
collection contrary to those durable/runtime facts.

## Replacement and staging identity

A replacement transaction persists one `DATABASE_REPLACEMENT` generation and
publishes only the committed value. Publication failure invalidates the process
clock and therefore degrades to cache miss rather than changing the committed
command result. Database-derived caches use database key plus replacement
identity. The Windows path resolver uses the single adapter reset path instead
of a second epoch-based invalidation mechanism.

Secure backup import enters one `ValidatedStaging` resource scope before
maintenance. That owner creates the decrypted temporary SQLite file, builds the
current schema/indexes, inserts data, seeds defaults, resets derived folder-index
state, validates foreign keys/semantics/replay graph, commits staging, hands the
validated path to live apply and deletes it after every success or failure path.
No caller receives an unowned staging path and cleanup never depends on object
finalization or process exit.

Staging content and semantic validation failures are `BackupCorruptedError`;
local staging infrastructure failures are `BackupStagingInfrastructureError`.
Both occur outside maintenance and cannot alter live data, generations or the
recovery latch. After staging succeeds, all ordinary live
delete/insert/seed/reset, generation-floor/bump, validation, SQLite I/O and
commit failures are `BackupReplacementError`; internal causes are chained
without leaking them to the UI. Maintenance hold/reset/release and fail-closed
errors remain separate.

## Projection and explicit transactions

Current operations use payload v6 and members-only replay binding. Missing,
invalid or non-current payload versions fail closed at the repository read
boundary. Admission revision and durable replay identity are separate.
Repository, replay engine and secure backup validator share one contract
entry point in `report_operation_contract`; malformed payloads produce a
stable `invalid_payload` diagnostic instead of raising.

`DomainUnitOfWork` owns root SQLite transaction/reuse/rollback-only propagation,
declared generation effects and explicitly changed effects. It never examines
SQL text, row counts, `total_changes` or commit hooks to infer semantics.
`mark_changed(namespace)` requires a declared namespace; missing or undeclared
namespaces are contract violations. Nested scopes update the root and each
changed namespace bumps at most once at root commit.

No-op, rollback, worker progress, retry cursor, heartbeat, checkpoint and
receipt-only writes publish no business generation. Canonical assignment,
resource, lifecycle, project/rule/privacy and report-operation owners mark their
actual namespace only when user-visible semantics change. Report mutation writes
an idempotent no-op receipt without `REPORT_STRUCTURE`; an effective operation
marks `REPORT_STRUCTURE` only after operation/members/receipt exist and replay is
`APPLIED` with the expected effect. `DatabaseReplacementUnitOfWork` separately
owns the physical replacement epoch, live commit and process-local publication.
`WorkTraceConnection` retains only write-gate enforcement and read observation.

## Manifest and current-only data contract

Schema v13, encrypted backup payload v6, report operation payload v6 and
LiveClock v2 are current-only. The static database content manifest is the sole
source for schema membership, backup order, delete order, derived/internal
classification and clear-time rebuild membership. Internal worker progress and
derived indexes are not exported.

## Permanent governance and regression coverage

Permanent governance rejects `total_changes` in `DomainUnitOfWork`, zero-argument
production `mark_changed()` calls and SQL-text generation inference. Behavioral
coverage verifies declared/changed namespace separation, undeclared-effect
errors, no-op/rollback/nested publication, report no-op receipt semantics,
staging cleanup across validation/insert/commit/maintenance/live failures,
replacement error taxonomy and durable-restore-before-release ordering.

## Validation

Only the permanent Standard CI workflow (`.github/workflows/ci.yml` and
`_validation.yml`) is used. Business-test diagnostics are artifact-only: the
frozen workflow uploads a structured `diagnostics.json` and JUnit XML on
failure; job logs never contain failure lists, root-cause groups, tracebacks or
raw test-log tails. The workflow is not modified for business-test failures.

The branch remains unmerged and PR #25 remains Draft until explicit user
confirmation. Final implementation status, exact head and Standard CI run are
recorded in the PR description only after all three validation jobs succeed on
the same final revision. This non-skip checkpoint is the sole final validation
revision for the four residual convergence groups.
