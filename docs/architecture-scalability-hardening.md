# Architecture scalability hardening

This change set completes the runtime and reporting ownership boundaries introduced by the prior architecture hardening work.

## Durable facts

- Activity creation persists the activity row, initial assignment, resource and zero-second recovery checkpoint in one transaction.
- Activity transitions and bulk close operations are atomic.
- Project inference is a post-commit, retryable derivation and cannot suppress an already-created activity id.
- SQLite enforces at most one open activity row.

## Canonical reporting

- Canonical projection reads activity, assignment, project and resource facts from an independent report fact repository.
- Immutable operations and their members are bulk-loaded rather than queried per operation.
- Durable operation replay binds to persisted member identities; admission revisions remain write-time concurrency guards.
- Timeline no longer owns a second session builder.
- Full page loads derive their structure revision from the canonical snapshot already built for the request.

## Bounded derived work

- Rule impact is planned in a read transaction before any write lock is requested.
- Small rule history mutations reuse the same cursor job runner as large mutations.
- Large mutations persist their cutoff, cursor and counters and resume after process restart.
- Folder indexes build into a staging generation and switch the active generation only after complete validation.

## Maintenance boundaries

- Backup export quiesces Collector writes before acquiring a consistent database snapshot.
- Runtime history jobs and folder index entries remain derived state and are reset during database replacement.
- Non-Windows single-instance ownership uses a kernel file lock so a stale pathname cannot block restart after a crash.

## Dependency rules

```text
Collector / API -> command services -> repositories -> SQLite
SQLite -> report fact repository -> canonical projection -> page adapters
Committed facts -> bounded workers -> assignments / index generations
```

Canonical projection must not depend on Timeline page adapters, and production services must not share implementation through cross-module private symbols.
