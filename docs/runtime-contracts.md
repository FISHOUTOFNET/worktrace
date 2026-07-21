# Runtime and Data Contract Versions

WorkTrace is in pre-release development. Runtime/data contracts are current-only;
there is no compatibility parser or migration layer.

## Version table

| Contract | Current version | Compatibility policy |
| --- | ---: | --- |
| SQLite schema | 13 | Empty database or exact v13 fingerprint only |
| Encrypted backup payload | 6 | Exact v6 + schema v13 + exact fingerprint only |
| Report operation payload | 6 | Exact v6; `ReplayBinding.MEMBERS` only; legacy revision rejected at read boundary |
| Live display clock | 2 | Exact key set; LiveClock v1 aliases rejected |
| Runtime envelope | 2 | Explicit schema version and one exact clock |

## SQLite v13

`worktrace.db.CURRENT_SCHEMA_VERSION` is 13. `schema.sql`,
`schema_internal.sql` and `schema_indexes.sql` are applied to an empty database
and define the expected fingerprint. A non-empty database with a different user
version or fingerprint raises `database_schema_incompatible`; no old-schema
migration runs.

Schema v13 includes the current normalized keyword-rule pattern and its
concurrency-safe uniqueness constraint. Application services remain the semantic
owners of project/rule invariants; database constraints close unavoidable
concurrent-write races rather than duplicate service logic.

## Backup payload v6

`secure_backup_service.PAYLOAD_VERSION` is 6. Import validates:

- `format == "worktrace-local-data"`;
- `version == 6`;
- `schema_version == "13"`;
- exact current schema fingerprint;
- exact current export-table set; and
- list/object row shapes before staging and replacement.

Payload v5 and earlier are unsupported. Export never emits both old and new
fields. Durable worker queues such as `activity_inference_job` are intentionally
excluded from backup payloads and are rebuilt or recovered by their current
runtime owners after replacement. See
[`v0.2-local-security-design.md`](v0.2-local-security-design.md).

### Staging resource contract

The decrypted SQLite staging file is owned by one `ValidatedStaging` resource
scope. The scope creates the file, closes the staging connection, validates the
complete current schema/foreign-key/replay/semantic graph, hands the validated
path to live apply, and deletes the file after success, maintenance rejection or
any exception. The path is never delegated without its owner. Cleanup does not
depend on object finalization or process exit and cleanup failure never replaces
the original operation exception.

Staging construction, schema/index execution, table insertion, defaults/index
reset, validation and staging commit failures are `BackupCorruptedError` because
they establish that the supplied current-format payload cannot form a valid
staging database. They occur before maintenance and cannot alter the live DB,
generation clock or recovery latch.

After staging succeeds, live delete/insert, default seeding, folder-index reset,
generation-floor read, replacement epoch bump, live final validation, SQLite I/O
or commit failure is `BackupReplacementError`. The stable public error does not
claim the backup is corrupt; the original exception is retained through chaining
for internal diagnostics. Maintenance hold/reset/release failures remain their
dedicated maintenance error types.

A successful replacement publishes each committed durable generation and then
loads the same values into the process generation clock. Pre-commit validation,
generation-write or database-commit failure preserves the live database and its
existing clock alignment. A process publication failure recovers by reloading the
committed durable values; it does not invent a second replacement generation.

## Explicit generation-effect contract

`DomainUnitOfWork` owns ordinary domain transactions. A root transaction has two
separate sets:

- declared effects: namespaces the transaction is permitted to change; and
- changed effects: namespaces explicitly marked after a real semantic change.

`mark_changed(namespace)` is mandatory for publication. Calling it without a
namespace or with an undeclared namespace is a stable contract error. SQL text,
row count, `connection.total_changes`, commit hooks and declared-effect count are
never used to infer semantics. Nested scopes reuse the root transaction, add
declarations to the root and mark the root; nested failure makes the root
rollback-only. A changed namespace is bumped once at most per root commit.

No-op, rollback, mutation receipt only, retry cursor, worker progress,
operational heartbeat and activity checkpoint writes do not publish a business
generation. Assignment/resource/lifecycle/catalog owners mark their namespace
only when their durable semantic value changes. An effective report operation
writes operation members and receipt, verifies replay state `APPLIED` and expected
effect, then marks `REPORT_STRUCTURE`. A no-effect or duplicate request may retain
an idempotent receipt but does not publish.

`DatabaseReplacementUnitOfWork` remains the separate and sole owner of the
physical `DATABASE_REPLACEMENT` epoch, live commit and process-local replacement
publication.

## Report operation payload v6

`report_operation_contract.OPERATION_PAYLOAD_VERSION` is 6. Repository read
boundary, replay engine and secure backup validator share one contract entry
point. The contract validates operation type, payload version, replay binding
(`ReplayBinding.MEMBERS` only), allowed fields, role set and member graph.
Malformed payloads (e.g., list/dict `payload_version`, missing binding,
unknown fields) produce a stable `invalid_payload` diagnostic instead of
raising `TypeError`/`ValueError`/`KeyError`. Legacy revision-based replay is
rejected at the read boundary. No compatibility parser or migration layer
exists.

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
A successful startup has `error_code=null`, including when `degraded=true`
because an optional worker failed; the affected worker entry retains the exact
diagnostic. A non-null top-level error code is reserved for startup failure.

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
