# Runtime Maintenance Lifecycle

`RuntimeMaintenanceCoordinator` is the sole application owner for consistent
snapshots and database replacement. It owns one operation lock, one state
machine, one runtime-control registration point, and the write-gate ordering.

## Consistent snapshot

1. Capture privacy authorization, durable user-pause intent, Collector liveness,
   runtime generation, and database replacement epoch.
2. Ask the Collector to seal its current durable activity while normal write
   admission is still open.
3. Require an explicit acknowledgement. Timeout or unknown command state fails
   closed.
4. Clear the process-local runtime snapshot.
5. Enter write-gate draining, wait for existing writers, then promote the
   coordinator thread to exclusive ownership.
6. Build the snapshot payload.
7. Exit exclusivity, restore durable user intent, and let a previously running,
   privacy-authorized Collector resume from the next real sample.

Maintenance sealing closes the current activity and schedules any eligible
closed-activity inference job in one transaction. It does not insert a
`session_boundary`, does not write `maintenance_pause`, and does not mutate
`user_paused`.

`secure_backup_service.export_encrypted_backup()` owns this context itself.
Transport facades and WebView callers do not supply an extra barrier and cannot
reach an unsafe public payload builder.

## Database replacement

Database import and clear-all use the same quiesce and write-gate sequence, then
replace data and publish the database-replacement epoch exactly once in the
replacement transaction. The exclusive gate is released before process-local
Collector and adapter identities are reset. No old persisted activity ID may
survive into the new database generation.

After replacement, the coordinator restores the pre-maintenance state:

- a previously running, privacy-authorized, non-user-paused Collector resumes;
- durable user pause remains paused, including when collection is also blocked
  by the privacy gate;
- an unaccepted privacy notice never starts collection;
- failed or unknown quiesce/reset/restore state fails closed.

Restoration and fail-closed writes publish the settings generation whenever
`user_paused` changes. Cached readers therefore cannot retain an unsafe value
from before maintenance. The runtime snapshot is cleared before replacement;
it is not cleared again after restoration because the Collector may already
have published the first sample of the new generation.

A failed replacement rolls back business data and the replacement epoch. The
subsequent fail-closed command is a separate committed safety transition, so it
may advance the settings generation while leaving all replacement generations
unchanged.

Neither secure import nor clear-all is a durable user session boundary.

## Write capability

Worker identity is not a write capability. The write gate has no permanent
Collector thread whitelist. Collector sealing completes before draining begins;
only the short-lived coordinator owner may write during draining/exclusive
maintenance.
