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
Clear and encrypted import use the same coordinator and write gate. Restoration
returns to the pre-maintenance running, stopped or user-paused state; an
unverified hold/reset/release remains fail-closed.

## Replacement and cache identity

A replacement transaction persists one `DATABASE_REPLACEMENT` generation and
publishes only the committed value. Publication failure invalidates the process
clock and therefore degrades to cache miss rather than changing the committed
command result. Database-derived caches use database key plus replacement
identity. The Windows path resolver uses the single adapter reset path instead
of a second epoch-based invalidation mechanism.

## Projection and transactions

Current operations use payload v6 and members-only replay binding. Missing,
invalid or non-current payload versions fail closed at the repository read
boundary. Admission revision and durable replay identity are separate.
`DomainUnitOfWork` owns business generation effects: rollback and no-op do not
publish, nested scopes reuse the root transaction, and each namespace is bumped
at most once per root commit. `DatabaseReplacementUnitOfWork` owns the physical
replacement epoch bump, live commit and process-local publication.
`WorkTraceConnection` retains only write-gate enforcement and read observation.

## Manifest and current-only data contract

Schema v13 and backup payload v6 are current-only. The static database content
manifest is the sole source for schema membership, backup order, delete order,
derived/internal classification and clear-time rebuild membership. Internal
worker progress and derived indexes are not exported.

## Validation

Only the permanent Standard CI workflow (`.github/workflows/ci.yml` and
`_validation.yml`) is used. Business-test diagnostics are artifact-only: the
frozen workflow uploads a structured `diagnostics.json` and JUnit XML on
failure; job logs never contain failure lists, root-cause groups, tracebacks or
raw test-log tails. The workflow is not modified for business-test failures.

The branch remains unmerged and PR #25 remains Draft until explicit user
confirmation.
