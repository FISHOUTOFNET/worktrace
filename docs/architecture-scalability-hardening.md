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

## Daily projection provider

`ReportProjectionProvider` is the single owner for day-level projection reads. It manages a bounded (max 3 dates) LRU cache of immutable `DayProjection` snapshots and provides O(1) entry/contribution indexes for detail lookups.

### Three revision concepts

1. **Projection Source Version** — an O(1) token derived from durable generation counters (`REPORT_STRUCTURE` generation, `DATABASE_REPLACEMENT` epoch, `projection_schema_version`). Used for cache validity, heartbeat, and stale selection detection. Never scans activity rows.
2. **Snapshot Revision** — a content hash of the complete projection output, computed once during projection build. Used for mutation receipts, export consistency, and projection diagnostics.
3. **Projection Revision** — per-session identity for optimistic concurrency control during edit/merge/split/copy/hide operations.

### Cache boundaries

- Cross-request cache stores canonical `DayProjection` (entries, contributions, indexes, diagnostics) — never final page DTOs, DOM, or runtime state.
- Mutation transactions bypass the cache and use the caller's transaction connection to see uncommitted state.
- Cache is cleared on database replacement; old database caches are not reusable.
- Single-flight: concurrent misses for the same `(database_key, report_date, source_version)` build only once.

### Timeline / Detail sharing

- Timeline and Detail share the same immutable day projection.
- Detail lookups use `entry_by_key` O(1) lookup instead of scanning all `final_entries`.
- Detail contributions use `contributions_by_key` O(1) lookup instead of scanning all `final_contributions`.
- Stale selection: if `expected_source_version` does not match current, the frontend retries once; if the session key is missing after refresh, the selection is cleared.

### Context projection complexity

- Context attribution runs in O(N) via bidirectional anchor precomputation.
- A shared `BoundaryIndex` provides O(log B) boundary-crossing checks via bisect, replacing O(B) linear scans.
- The forward anchor is precomputed in a single backward pass; the backward anchor is tracked at runtime during the forward build (reproducing the old algorithm's propagation effect on mutated rows).

### Fact query window

- The fact query window is `[day_start - carry_seconds, day_end + carry_seconds]`, where `carry_seconds` is capped at `REPORT_CONTEXT_SHORT_MERGE_SECONDS`.
- The overlap SQL is split into closed/open branches via `UNION ALL`, each using a dedicated index (`idx_activity_closed_overlap` for closed, `idx_activity_time` for open).

### Future extension point

`ProjectionSourceVersion` is designed to support future date-level generation fields (`report_day_generation`, `catalog_generation`, `report_policy_generation`) without changing the cache key structure. The current global `REPORT_STRUCTURE` generation conservatively invalidates historical date caches when today's activities change; this is accepted as a correctness-over-precision tradeoff.

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
