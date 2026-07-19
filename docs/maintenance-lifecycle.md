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
-> release exclusive capability
-> restore durable settings
-> request maintenance release
-> require OPERATIONAL acknowledgement
```

`secure_backup_service.export_encrypted_backup()` acquires this capability
itself. API and bridge callers cannot invoke an unsafe public payload builder or
supply an alternative barrier.

## Database replacement order

```text
capture durable/runtime state
-> request maintenance hold
-> require HELD acknowledgement
-> clear runtime snapshot
-> enter write-gate draining
-> drain already admitted writers
-> promote coordinator to exclusive writer
-> replace data and publish database-replacement epoch in one transaction
-> release exclusive capability
-> request process-local database reset while Collector remains HELD
-> require reset acknowledgement with terminal HELD
-> restore durable settings
-> request maintenance release
-> require OPERATIONAL acknowledgement
```

The reset clears Collector/adaptor identities from the old database generation.
An old persisted activity ID cannot be reused after replacement.

## Restoration and failure semantics

The coordinator captures installation privacy authorization, durable user-pause
intent, Collector liveness/status, write generation and replacement epoch before
maintenance.

- A previously running, privacy-authorized, non-user-paused Collector resumes.
- A pre-existing durable user pause remains paused.
- An unaccepted privacy notice never starts collection.
- A previously stopped Collector remains stopped.
- Failed replacement rolls back business data and replacement epoch.
- Any destructive-operation exception after a verified hold keeps the coordinator
  in stable `FAILED_CLOSED`, even when the business transaction rolled back.
- Unknown hold/reset/release state, release failure or shutdown ambiguity fails
  closed: durable pause/status are committed as a separate safety transition,
  runtime activity state is cleared and collection is not resumed optimistically.

The fail-closed latch remains queryable as `FAILED_CLOSED` and rejects subsequent
destructive maintenance. It is cleared only by explicit recovery after the
registered runtime is verified running, the command channel is OPERATIONAL and
the write gate is inactive. Recovery clears the durable latch markers but
preserves the safety-created durable user pause until the user explicitly resumes.

Restoration and fail-closed settings writes publish their normal settings
change. They do not fabricate replacement success.

## Concurrency and lock order

Only one snapshot or replacement may own the coordinator operation lock. Collector
seal finishes before write-gate draining, so a new Collector writer cannot race
the drain. The write gate has no permanent thread whitelist; only the short-lived
coordinator capability may write during draining/exclusive maintenance.

Worker identity is not a write capability. Backup service depends on this
coordinator; Collector never depends on backup service to determine maintenance
state.
