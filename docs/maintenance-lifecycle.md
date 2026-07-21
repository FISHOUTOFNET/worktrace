# Runtime Maintenance Lifecycle

`RuntimeMaintenanceCoordinator` is the sole application owner for consistent
snapshots and database replacement. It owns one operation lock, one state
machine, one runtime-control registration point and the write-gate order.

## Collector hold state machine

Maintenance is not user pause. Collector control uses identity-bearing commands:

```text
OPERATIONAL
  -> HOLD_REQUESTED
  -> SEALING
  -> HELD
  -> optional RESETTING -> HELD
  -> RELEASE_REQUESTED
  -> OPERATIONAL
```

A hold is complete only after Collector has:

1. taken the exact hold command;
2. closed the current activity with the maintenance seal command;
3. enqueued any eligible closed-activity inference job in the same transaction;
4. cleared process-local current-activity state;
5. disabled clipboard capture; and
6. entered HELD.

HELD permits reset, release and shutdown only. It performs no foreground-window
observation, clipboard read, activity write, heartbeat write or privacy-refresh
write. Release starts observation from the next real sample.

Maintenance does not create a `session_boundary`, does not persist a maintenance
activity/status and does not mutate durable `user_paused` intent.

## Acknowledgement contract

A successful command response must match all of:

```text
response.command_id == requested command ID
response.command_kind == expected kind
response.command_state == completed
response.terminal_state == expected terminal state
response.ok is true
response.command_state_unknown is false
```

Runtime-control fakes and integration fixtures must emit this same exact contract;
partial legacy responses such as `quiesce_pending=false` are not accepted as
maintenance success.

A timeout before Collector takes the command cancels that command, returns the
hold channel to OPERATIONAL and leaves the coordinator IDLE; it does not create a
fail-closed latch. A timeout after take has unknown outcome and fails closed.
Completed command state may be read from `CollectorControl` when response delivery
is uncertain. Exclusive maintenance must never begin while hold state is unknown.

## Consistent snapshot order

```text
capture durable/runtime state
-> request maintenance hold
-> require HELD acknowledgement
-> clear runtime snapshot
-> enter write-gate draining
-> drain already admitted writers
-> promote coordinator to exclusive writer
-> build snapshot
-> restore durable settings while Collector remains HELD
-> request maintenance release
-> require OPERATIONAL acknowledgement
-> exit exclusive write-gate scope
-> coordinator returns IDLE
```

`secure_backup_service.export_encrypted_backup()` acquires this capability
itself. API and bridge callers cannot invoke an unsafe public payload builder or
supply an alternative barrier.

## Database replacement order

For secure backup import, a single `ValidatedStaging` resource scope creates,
builds, validates, hands off and deletes the decrypted temporary SQLite file.
The scope is entered **before** maintenance and remains active until live apply,
maintenance rejection or failure completes. No external caller owns an orphanable
staging path. The destructive replacement order is:

```text
enter validated-staging resource scope
-> create, build and fully validate staging database outside maintenance
-> capture durable/runtime state
-> request maintenance hold
-> require HELD acknowledgement
-> clear runtime snapshot
-> enter write-gate draining
-> drain already admitted writers
-> promote coordinator to exclusive writer
-> apply validated staging to live database and publish replacement epoch in one transaction
-> request process-local database reset while Collector remains HELD
-> require reset acknowledgement with terminal HELD
-> restore durable settings while Collector remains HELD
-> request maintenance release
-> require OPERATIONAL acknowledgement
-> exit exclusive write-gate scope
-> delete staging database on every success/failure path
-> coordinator returns IDLE
```

For `clear_all_live_data`, staging is not applicable; the delete/seed/replacement
publish happens inside the same maintenance scope.

The reset clears Collector/adaptor identities from the old database generation.
An old persisted activity ID cannot be reused after replacement.

## Pre-commit failure restoration order

A failure before replacement commit uses the same restoration protocol as the
successful path; it does not run a best-effort unordered cleanup routine:

```text
live transaction rolled back to a known state
-> Collector remains HELD
-> restore durable settings
-> if durable restore succeeds, request maintenance release
-> require terminal OPERATIONAL acknowledgement
-> exit exclusive write-gate scope
-> coordinator returns IDLE
```

If durable restoration fails, `maintenance_release` is never sent. Collector
remains HELD and the coordinator enters durable fail-closed. If release raises or
its acknowledgement is unknown, the coordinator also enters fail-closed. A
post-commit reset/release failure remains fail-closed because replacement already
committed and runtime identity cannot be verified.

## DRAINING and promote failure recovery

A failure in `drain_existing_writers()` or `lease.promote()` happens before the
EXCLUSIVE scope is reached. The coordinator tracks an explicit
`exclusive_finalization_completed` flag that is set `True` only when failure
finalization has run inside the EXCLUSIVE scope (via
`_finalize_failure_inside_exclusive` or the post-body fail-closed handoff).
DRAINING/promote failures leave this flag `False`, so the outer exception handler
must run `_restore_after_failure()` to recover collector hold, durable intent,
runtime snapshot and recovery seal via the standard path. The previous "lease
exists" check is no longer used to decide whether failure finalization has run.

When restore succeeds, the coordinator returns to `IDLE` with the write gate
`OPEN` and no recovery block. When restore fails or collector state cannot be
verified, the coordinator enters the existing fail-closed state with the
recovery seal present.

## External runtime mutation guard

External user-initiated runtime start/resume and clipboard enable pass through
`RuntimeMaintenanceCoordinator.external_runtime_mutation_guard()`. The guard
reuses the same `_operation_lock` as destructive/snapshot maintenance, so active
maintenance and external runtime mutation are mutually exclusive. The guard also
rejects when the coordinator is recovery-blocked.

Coordinator-internal recovery calls (`restore_after_maintenance` ->
`start_collector`) do not pass through this guard and therefore cannot self-lock.
Clipboard disable always bypasses the guard, so sensitive observation can be
stopped without waiting for the operation lock.

## Sensitive staging residue and recovery seal

`maintenance_recovery_latch_repository.read_latch()` always reports
`sensitive_residue_present` on every return path, including when a marker is
present. When a marker and residue coexist, the latch stays blocked and reports
both. Explicit recovery (`recover_fail_closed`) must clear residue first, then
clear the database mirror, then delete the correct-epoch marker, then clear the
recovery block. If residue deletion fails, the coordinator stays fail-closed and
the marker is preserved.

## Restoration and failure semantics

The coordinator captures installation privacy authorization, durable user-pause
intent, Collector liveness/status, write generation and replacement epoch before
maintenance.

- A previously running, privacy-authorized, non-user-paused Collector resumes.
- A pre-existing durable user pause remains paused.
- An unaccepted privacy notice never starts collection.
- A previously stopped Collector remains stopped.
- Failed live replacement rolls back business data and replacement epoch.
- Fail-closed is mandatory when runtime state cannot be verified:
  - `CollectorCommandNotAcknowledgedError` with `fail_closed=True`;
  - replacement committed but post-commit reset/restoration cannot be verified;
  - pre-maintenance state could not be captured;
  - durable restoration fails; or
  - release/terminal acknowledgement fails.
- Live replacement failure before commit, when durable restoration and release
  both succeed, does not enter durable fail-closed. The live transaction is
  rolled back by `DatabaseReplacementUnitOfWork` and runtime returns to its
  pre-maintenance state. This applies to `clear_all_live_data` failures as well.
- Pure staging failures never enter maintenance, never alter the live database or
  generation, and never trigger fail-closed.
- Unknown hold/reset/release state or shutdown ambiguity fails closed: durable
  pause/status are committed as a separate safety transition, runtime activity
  state is cleared and collection is not resumed optimistically.

The fail-closed latch remains queryable as `FAILED_CLOSED` and rejects subsequent
destructive maintenance. It is cleared only by explicit recovery after the
registered runtime is verified running, the command channel is OPERATIONAL and
the write gate is inactive. Recovery clears the durable latch markers but
preserves the safety-created durable user pause until the user explicitly resumes.

Restoration and fail-closed settings writes publish their normal settings
change. They do not fabricate replacement success.

## Backup error classification

- `BackupDecryptionError`: passphrase, authentication or decryption failure.
- `BackupVersionNotSupportedError`: backup payload or schema version unsupported.
- `BackupCorruptedError`: input JSON, table structure, row shape, foreign key,
  semantic, replay graph, schema/index construction, table insert, seed/reset or
  staging commit/validation failure. It is limited to input/staging phases.
- `BackupReplacementError`: after staging validation succeeds, any ordinary live
  delete/insert, seed/reset, generation-floor read, generation bump, final live
  validation, SQLite I/O or commit failure. The original exception is chained for
  internal diagnosis; the caller receives the stable replacement error.
- Maintenance/recovery errors: hold, reset, release, runtime recovery and
  fail-closed state remain dedicated maintenance errors.

External error messages and cleanup logs never expose staging paths, user paths,
SQL, tracebacks, database fields or decrypted business content. Cleanup failure
is logged with a stable resource type and never replaces the original exception.

## Concurrency and lock order

Only one snapshot or replacement may own the coordinator operation lock. Collector
seal finishes before write-gate draining, so a new Collector writer cannot race
the drain. The write gate has no permanent thread whitelist; only the short-lived
coordinator capability may write during draining/exclusive maintenance.

Worker identity is not a write capability. Backup service depends on this
coordinator; Collector never depends on backup service to determine maintenance
state.
