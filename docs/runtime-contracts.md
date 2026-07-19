# Runtime and Data Contract Versions

WorkTrace is in pre-release development. Runtime/data contracts are current-only;
there is no compatibility parser or migration layer.

## Version table

| Contract | Current version | Compatibility policy |
| --- | ---: | --- |
| SQLite schema | 12 | Empty database or exact v12 fingerprint only |
| Encrypted backup payload | 6 | Exact v6 + schema v12 + exact fingerprint only |
| Live display clock | 2 | Exact key set; LiveClock v1 aliases rejected |
| Runtime envelope | 2 | Explicit schema version and one exact clock |

## SQLite v12

`worktrace.db.CURRENT_SCHEMA_VERSION` is 12. `schema.sql`,
`schema_internal.sql` and `schema_indexes.sql` are applied to an empty database
and define the expected fingerprint. A non-empty database with a different user
version or fingerprint raises `database_schema_incompatible`; no old-schema
migration runs.

Schema v12 includes the current normalized keyword-rule pattern and its
concurrency-safe uniqueness constraint. Application services remain the semantic
owners of project/rule invariants; database constraints close unavoidable
concurrent-write races rather than duplicate service logic.

## Backup payload v6

`secure_backup_service.PAYLOAD_VERSION` is 6. Import validates:

- `format == "worktrace-local-data"`;
- `version == 6`;
- `schema_version == "12"`;
- exact current schema fingerprint;
- exact current export-table set; and
- list/object row shapes before staging and replacement.

Payload v5 and earlier are unsupported. Export never emits both old and new
fields. Durable worker queues such as `activity_inference_job` are intentionally
excluded from backup payloads and are rebuilt or recovered by their current
runtime owners after replacement. See
[`v0.2-local-security-design.md`](v0.2-local-security-design.md).

## RuntimeStartResult exact transport

Runtime startup exposes exactly one normalized result shape:

```text
ok
collector_ready
workers
already_running
degraded
error_code
```

`workers` is the sole worker-name mapping. There are no worker-specific top-level
status fields and no parallel `error` alias. User-facing error text is translated
at the Bridge boundary; runtime transport retains the canonical `error_code`.

## LiveClock v2 exact DTO

The key set is exactly:

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

No extra or missing key is valid.

Primitive rules:

- timestamps, elapsed and aggregate base are non-negative integers;
- `is_live` is a boolean;
- span ID and stable hash are strings;
- a live clock requires positive sample/start timestamps, non-empty identities,
  `live_state=persisted_open`, and non-static duration semantics.

Allowed `duration_semantic` values:

- `current_live`: current activity elapsed only;
- `aggregate_live`: durable closed aggregate base plus current elapsed;
- `static_closed`: no local ticker.

Allowed `live_state` values:

- `persisted_open`;
- `suppressed`;
- `none`.

Retired aliases include `duration_seconds_at_sample`, `carry_seconds`,
`live_started_at_epoch_ms`, `sample_epoch_ms`,
`current_live_duration_seconds`, `persisted_duration_seconds`,
`active_elapsed_at_sample`, `current_elapsed_at_sample`,
`current_duration_live`, `project_duration_live` and
`is_project_duration_live`.

## Clock formulas

For `current_live`:

```text
elapsed_seconds_at_sample
+ max(0, floor((now_ms - sampled_at_epoch_ms) / 1000))
```

For `aggregate_live`:

```text
aggregate_base_seconds
+ elapsed_seconds_at_sample
+ max(0, floor((now_ms - sampled_at_epoch_ms) / 1000))
```

For `static_closed`, the UI uses the durable row duration and does not start a
ticker. `started_at_epoch_ms` is identity/context and is not used to recompute
server elapsed.

## Runtime envelope v2

The envelope may contain schema version, surface/date scope, verified snapshot
metadata, current static metadata, Recent first row, Collector/runtime phase,
worker mapping, generations, database replacement epoch, errors, consistency and
full-refresh request. It contains one `clock`. It does not duplicate the clock's
span identity, stable hash, sample timestamp or live flags through aliases.

Every production bridge caller supplies explicit runtime and Collector status.
Missing required dependencies produce a contract error that the bridge logs and
maps to a generic UI failure; APIs do not silently invent `{}` status.

## Frontend ownership

`core.js` owns the exact clock validator and ticker helpers. `init.js` owns the
single accepted runtime-envelope store and refresh coordination. Overview and
Timeline consume those shared owners; governance checks shipping behavior across
all shipping scripts and do not require an owner to remain in a historical file.

## Malformed frontend behavior

The shared frontend validator rejects wrong keys/types/enums or invalid live
identity. The affected target then:

1. stops ticking;
2. renders durable static seconds;
3. records one diagnostic deduplicated by surface/reason/schema/span;
4. requests the existing low-frequency full refresh; and
5. never consults a retired alias.

Continuity keys may prevent unnecessary DOM reconstruction but cannot retain a
maximum duration, carry prior seconds or modify the formula.
