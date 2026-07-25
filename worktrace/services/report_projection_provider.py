"""Single owner for day-level report projection reads.

This module implements the architectural principle of one projection
read owner. :class:`ReportProjectionProvider` is the sole component that
builds, caches and publishes immutable :class:`DayProjection` snapshots
for page-read paths (Timeline, Detail, Overview).

Key design properties
---------------------
* **Cross-request date slot cache** — at most 3 dates, LRU eviction.
  Keyed by ``(database_key, report_date)``, value validated by
  :class:`ProjectionSourceVersion`. No generation in the key.
* **Request-level cache** — inside a :func:`page_read_scope` the
  :class:`PageReadContext` caches the DayProjection so repeated calls
  within the same request (e.g. Timeline + Detail) are free.
* **Single-flight** — same ``(database_key, report_date, source_version)``
  is built by at most one thread; others wait on a
  :class:`concurrent.futures.Future` with a bounded timeout.
* **Cache epoch** — :func:`clear_cache` increments a monotonic epoch.
  Builds started before the increment do not publish results into the
  new cache.  Old builders and their waiters still complete normally;
  new requests start fresh builds.
* **Transaction bypass** — mutation paths that pass ``conn=`` bypass
  the provider entirely and use :func:`build_visible_snapshot` directly.
* **Compact storage** — entries and contributions are stored exactly
  once; indexes reference the same immutable objects.
"""

from __future__ import annotations

import concurrent.futures
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Mapping

from ..data_generation_repository import DataGenerationNamespace
from ..db import get_connection, get_db_key
from .page_read_context import current_page_read_context
from .projection_performance import record_cache_hit, stage
from .report_projection_builder import ProjectionComputation, compute_projection
from .report_projection_model import FrozenDict, OperationDiagnostic, freeze_value
from .report_revision_service import (
    PROJECTION_SCHEMA_VERSION,
    ProjectionSourceVersion,
    get_projection_source_version,
)


class ProjectionWaitTimeout(Exception):
    """Raised when waiting for an in-flight projection build exceeds the timeout.

    Carries structured diagnostic fields (no privacy-sensitive data like
    window titles, paths, or project names).
    """

    def __init__(
        self,
        *,
        report_date: str,
        source_version_token: str,
        build_epoch: int,
        timeout_seconds: float,
        builder_elapsed_seconds: float,
        waiter_count: int,
        total_in_flight_count: int,
    ):
        self.report_date = report_date
        self.source_version_token = source_version_token
        self.build_epoch = build_epoch
        self.timeout_seconds = timeout_seconds
        self.builder_elapsed_seconds = builder_elapsed_seconds
        self.waiter_count = waiter_count
        self.total_in_flight_count = total_in_flight_count
        super().__init__(
            f"projection build wait timed out: date={report_date} "
            f"source_version={source_version_token} "
            f"build_epoch={build_epoch} "
            f"timeout={timeout_seconds}s "
            f"builder_elapsed={builder_elapsed_seconds:.1f}s "
            f"waiter_count={waiter_count} "
            f"total_in_flight={total_in_flight_count}"
        )


@dataclass(frozen=True)
class DayProjection:
    """Compact immutable day-level projection with O(1) lookup indexes.

    Stores ``entries`` and ``contributions`` exactly once. The
    ``entry_by_key`` and ``contributions_by_key`` indexes reference the
    same immutable objects — no copies.

    Mutually exclusive subsets (``final_sessions``, ``standalone_entries``)
    are NOT stored separately; callers that need them can filter
    ``entries`` by ``row_kind``.
    """

    report_date: str
    source_version: ProjectionSourceVersion
    entries: tuple[Mapping[str, Any], ...]
    contributions: tuple[Mapping[str, Any], ...]
    operation_diagnostics: tuple[OperationDiagnostic, ...]
    snapshot_revision: str
    entry_by_key: Mapping[str, Mapping[str, Any]]
    contributions_by_key: Mapping[str, tuple[Mapping[str, Any], ...]]

    @property
    def final_sessions(self) -> tuple[Mapping[str, Any], ...]:
        """Subset of entries with ``row_kind == 'project_session'``."""
        return tuple(
            e for e in self.entries
            if str(e.get("row_kind") or "project_session") == "project_session"
        )

    @property
    def standalone_status_entries(self) -> tuple[Mapping[str, Any], ...]:
        """Subset of entries with ``row_kind == 'standalone_status'``."""
        return tuple(
            e for e in self.entries
            if str(e.get("row_kind") or "") == "standalone_status"
        )

    @property
    def source_version_token(self) -> str:
        return self.source_version.token()


@dataclass
class _CacheEntry:
    projection: DayProjection
    last_used: float


@dataclass
class _InFlight:
    """Single-flight entry tracking a build and its waiters.

    Diagnostic fields (no privacy-sensitive data):
    * ``started_at_monotonic`` — when the builder started (for elapsed).
    * ``waiter_count`` — how many threads are waiting on the Future.
    """

    future: concurrent.futures.Future
    epoch: int
    started_at_monotonic: float = field(default_factory=time.monotonic)
    waiter_count: int = 0


_MAX_SLOTS = 3
_PROJECTION_WAIT_TIMEOUT: float = 30.0

# Unified state lock: protects _cache_epoch, _cache, _in_flight, LRU updates,
# waiter_count, and in-flight registration/cleanup. SQL, projection
# computation, materialization, Future waits, and ViewModel assembly run
# outside the lock so different dates can build in parallel.
_state_lock = threading.Lock()
_cache: dict[tuple[str, str], _CacheEntry] = {}
_cache_epoch: int = 0
_in_flight: dict[tuple[str, str, str], _InFlight] = {}

_lru_counter = 0.0


def _next_lru() -> float:
    global _lru_counter
    _lru_counter += 1.0
    return _lru_counter


def _evict_if_needed() -> None:
    """Evict LRU entries while cache exceeds ``_MAX_SLOTS``. Caller holds lock."""
    while len(_cache) > _MAX_SLOTS:
        oldest_key = min(_cache, key=lambda k: _cache[k].last_used)
        _cache.pop(oldest_key, None)


def _cross_request_get(
    database_key: str,
    report_date: str,
    expected_version: ProjectionSourceVersion,
) -> DayProjection | None:
    with _state_lock:
        entry = _cache.get((database_key, report_date))
        if entry is None:
            return None
        if entry.projection.source_version != expected_version:
            # Stale: version changed, evict.
            _cache.pop((database_key, report_date), None)
            return None
        entry.last_used = _next_lru()
        return entry.projection


def _cross_request_put(
    database_key: str,
    report_date: str,
    projection: DayProjection,
    *,
    build_epoch: int,
) -> None:
    """Publish to cross-request cache only if the epoch hasn't changed."""
    with _state_lock:
        if _cache_epoch != build_epoch:
            return
        _cache[(database_key, report_date)] = _CacheEntry(
            projection=projection,
            last_used=_next_lru(),
        )
        _evict_if_needed()


def _build_day_projection(
    conn,
    report_date: str,
    source_version: ProjectionSourceVersion,
) -> DayProjection:
    """Build a compact, recursively-immutable DayProjection.

    Uses the shared projection computation (no duplicated business rules),
    then freezes entries/contributions, builds O(N) indexes, and assembles
    the :class:`DayProjection` as three distinct measured steps so timing
    artifacts reflect real work. The full :class:`ReportProjectionSnapshot`
    freeze (base_sessions, mutually-exclusive subsets) is skipped.
    """
    with stage("projection_compute"):
        comp = compute_projection(conn, report_date, report_date)
    with stage("projection_materialize"):
        frozen_data = freeze_projection_data(comp)
    with stage("index_build"):
        indexes = build_projection_indexes(frozen_data)
    with stage("projection_assemble"):
        projection = assemble_day_projection(
            frozen_data,
            indexes,
            source_version,
            report_date=report_date,
        )
    return projection


@dataclass(frozen=True, slots=True)
class FrozenProjectionData:
    """Frozen entries, contributions, and pass-through metadata.

    The single immutable input to index construction and assembly.
    Entries have ``_projection_contributions`` stripped before freezing;
    contributions are frozen exactly once.  Pass-through fields
    (``operation_diagnostics``, ``snapshot_revision``, ``start_date``)
    are already immutable and carried verbatim so :func:`assemble_day_projection`
    is a pure function of frozen inputs.
    """

    entries: tuple[Mapping[str, Any], ...]
    contributions: tuple[Mapping[str, Any], ...]
    operation_diagnostics: tuple[OperationDiagnostic, ...]
    snapshot_revision: str
    start_date: str


@dataclass(frozen=True, slots=True)
class ProjectionIndexes:
    """O(1) lookup indexes referencing the same frozen objects.

    ``entry_by_key`` and ``contributions_by_key`` reference the exact
    same immutable objects stored in :class:`FrozenProjectionData` —
    no duplicate freeze, no deep copy.
    """

    entry_by_key: Mapping[str, Mapping[str, Any]]
    contributions_by_key: Mapping[str, tuple[Mapping[str, Any], ...]]


def freeze_projection_data(
    computation: ProjectionComputation,
) -> FrozenProjectionData:
    """Freeze entries and contributions exactly once.

    Strips ``_projection_contributions`` from compact entries before
    freezing — page-read paths use ``contributions_by_key`` instead.
    The full :class:`ReportProjectionSnapshot` keeps the inline field
    for mutation and export compatibility.

    Pure function: no SQLite, no cache, no telemetry, no module state.
    """

    # Strip _projection_contributions from compact entries before
    # freezing. Page-read paths use contributions_by_key instead. The
    # full ReportProjectionSnapshot keeps the field for mutation and
    # export compatibility.
    compact_entries: list[Mapping[str, Any]] = []
    for raw_entry in computation.final_entries:
        item = dict(raw_entry)
        item.pop("_projection_contributions", None)
        compact_entries.append(freeze_value(item))
    entries = tuple(compact_entries)

    # Freeze contributions exactly once.
    contributions = tuple(
        freeze_value(contribution)
        for contribution in computation.final_contributions
    )

    return FrozenProjectionData(
        entries=entries,
        contributions=contributions,
        operation_diagnostics=tuple(computation.operation_diagnostics),
        snapshot_revision=computation.snapshot_revision,
        start_date=computation.start_date,
    )


def build_projection_indexes(
    frozen_data: FrozenProjectionData,
) -> ProjectionIndexes:
    """Build O(1) lookup indexes from frozen data.

    Indexes reference the SAME immutable objects (no duplicate freeze,
    no deep copy).  O(N) accumulation into lists, frozen once at the
    end — avoids the O(K^2) tuple-rebuild pattern (``*existing, item``).

    Pure function: no SQLite, no cache, no telemetry, no module state.
    """

    # contributions_by_key — O(N) accumulation into lists, frozen once.
    mutable_contributions_by_key: dict[str, list[Mapping[str, Any]]] = {}
    for contribution in frozen_data.contributions:
        key = str(contribution.get("projection_instance_key") or "")
        if key:
            mutable_contributions_by_key.setdefault(key, []).append(
                contribution
            )
    contributions_by_key = FrozenDict(
        {
            key: tuple(values)
            for key, values in mutable_contributions_by_key.items()
        }
    )

    # entry_by_key referencing the SAME frozen entry objects.
    entry_by_key = FrozenDict(
        {
            str(entry.get("projection_instance_key") or ""): entry
            for entry in frozen_data.entries
            if str(entry.get("projection_instance_key") or "")
        }
    )

    return ProjectionIndexes(
        entry_by_key=entry_by_key,
        contributions_by_key=contributions_by_key,
    )


def assemble_day_projection(
    frozen_data: FrozenProjectionData,
    indexes: ProjectionIndexes,
    source_version: ProjectionSourceVersion,
    *,
    report_date: str | None = None,
) -> DayProjection:
    """Assemble the final :class:`DayProjection` from frozen data + indexes.

    Pure function: no SQLite, no cache, no telemetry, no module state.
    ``report_date`` defaults to ``frozen_data.start_date``.
    """

    resolved_report_date = (
        report_date if report_date is not None else frozen_data.start_date
    )

    return DayProjection(
        report_date=resolved_report_date,
        source_version=source_version,
        entries=frozen_data.entries,
        contributions=frozen_data.contributions,
        operation_diagnostics=frozen_data.operation_diagnostics,
        snapshot_revision=frozen_data.snapshot_revision,
        entry_by_key=indexes.entry_by_key,
        contributions_by_key=indexes.contributions_by_key,
    )


def materialize_day_projection(
    computation: ProjectionComputation,
    source_version: ProjectionSourceVersion,
    *,
    report_date: str | None = None,
) -> DayProjection:
    """Materialize a compact, recursively-immutable :class:`DayProjection`.

    Pure function: no SQLite, no cross-request cache, no module-level state.
    ``report_date`` defaults to ``computation.start_date``.

    Contributions are frozen exactly once and referenced by both
    ``contributions`` and ``contributions_by_key`` (same objects, no
    duplicate freeze). Compact entries have ``_projection_contributions``
    stripped before freezing; page paths use ``contributions_by_key``.
    Both this materializer and the full snapshot materializer depend on
    the same :class:`ProjectionComputation` from
    :mod:`report_projection_builder` — neither duplicates business rules.

    This public entry point composes the three pure steps
    (:func:`freeze_projection_data`, :func:`build_projection_indexes`,
    :func:`assemble_day_projection`) without per-step timing.  The
    Builder path (:func:`_build_day_projection`) calls the steps
    directly so each stage is measured independently.
    """
    frozen_data = freeze_projection_data(computation)
    indexes = build_projection_indexes(frozen_data)
    return assemble_day_projection(
        frozen_data,
        indexes,
        source_version,
        report_date=report_date,
    )


def get_day_projection(report_date: str) -> DayProjection:
    """Return the immutable day projection for ``report_date``.

    This is the single entry point for page-read paths. It checks the
    request-level cache (inside a page_read_scope), the cross-request
    date slot cache, and builds a new projection if needed.

    Mutation paths must NOT use this function — they should call
    :func:`build_visible_snapshot` with their transaction connection.
    """
    context = current_page_read_context()
    if context is not None:
        return _get_via_page_context(context, report_date)
    return _get_via_standalone(report_date)


def _get_via_page_context(context, report_date: str) -> DayProjection:
    """Read path inside a page_read_scope — uses context's connection."""
    source_version = ProjectionSourceVersion(
        database_key=context.database_key,
        report_date=report_date,
        report_structure_generation=int(
            context.report_generations.get(
                DataGenerationNamespace.REPORT_STRUCTURE, 0
            )
        ),
        database_replacement_epoch=int(
            context.report_generations.get(
                DataGenerationNamespace.DATABASE_REPLACEMENT, 0
            )
        ),
        projection_schema_version=PROJECTION_SCHEMA_VERSION,
    )

    # 1. Request-level cache (frozen generations → always valid if present).
    cached_request = context.day_projection_cache.get(report_date)
    if cached_request is not None:
        record_cache_hit(True)
        return cached_request

    # 2. Cross-request cache.
    cached_cross = _cross_request_get(context.database_key, report_date, source_version)
    if cached_cross is not None:
        context.day_projection_cache[report_date] = cached_cross
        record_cache_hit(True)
        return cached_cross

    # 3. Single-flight build (handles cross-request cache publishing).
    projection = _single_flight_build(
        context.database_key,
        report_date,
        source_version,
        builder=lambda: _build_day_projection(context.conn, report_date, source_version),
    )
    context.day_projection_cache[report_date] = projection
    return projection


def _get_via_standalone(report_date: str) -> DayProjection:
    """Read path outside a page_read_scope — opens a short-lived connection."""
    database_key = get_db_key()
    source_version = get_projection_source_version(report_date)

    cached_cross = _cross_request_get(database_key, report_date, source_version)
    if cached_cross is not None:
        record_cache_hit(True)
        return cached_cross

    def builder() -> DayProjection:
        with get_connection() as conn:
            conn.execute("BEGIN")
            try:
                result = _build_day_projection(conn, report_date, source_version)
                conn.commit()
                return result
            except Exception:
                conn.rollback()
                raise

    return _single_flight_build(database_key, report_date, source_version, builder)


def _single_flight_build(
    database_key: str,
    report_date: str,
    source_version: ProjectionSourceVersion,
    builder,
) -> DayProjection:
    """Ensure only one thread builds a given (db, date, version) triple.

    Uses a :class:`concurrent.futures.Future` for result coordination.
    The builder publishes to the cross-request cache only if the cache
    epoch hasn't changed since the build started.  Waiters wait with a
    bounded timeout; on timeout :class:`ProjectionWaitTimeout` is raised
    but the builder continues running for other waiters.

    Waiter lifecycle contract:

    * ``waiter_count`` counts waiters that have joined an in-flight build
      but have not yet exited.  It is incremented exactly once (under the
      state lock) when a waiter joins the Future, and decremented exactly
      once in the single ``finally`` exit path (success, timeout, or
      owner-exception).
    * The waiter captures a reference to the specific ``_InFlight`` entry
      it joined (``joined_inflight``).  The decrement targets that exact
      object — never ``_in_flight.get(flight_key)`` — so a cache-epoch
      change that replaces the dict entry cannot cause a cross-entry
      decrement or underflow.
    * The timeout diagnostic snapshot is read from ``joined_inflight``
      *before* the decrement and includes the timing-out waiter in the
      count (it has not been decremented yet).
    * ``waiter_count`` must never go negative.  An underflow indicates a
      state-machine bug and raises :class:`AssertionError` rather than
      being silently clamped.
    """
    flight_key = (database_key, report_date, source_version.token())

    with _state_lock:
        current_epoch = _cache_epoch
        existing = _in_flight.get(flight_key)
        if existing is not None and existing.epoch == current_epoch:
            # Join an in-flight build from the same epoch.  Capture the
            # specific entry reference so the finally decrement targets
            # exactly the object we incremented — not whatever sits at
            # flight_key after a possible epoch change.
            future = existing.future
            existing.waiter_count += 1
            joined_inflight: _InFlight | None = existing
            builder_started_at = existing.started_at_monotonic
            is_builder = False
        else:
            # Start a new build.  If a stale entry from a previous epoch
            # exists it is overwritten — the old builder will check epoch
            # before publishing and won't touch the new entry's future.
            future = concurrent.futures.Future()
            _in_flight[flight_key] = _InFlight(
                future=future,
                epoch=current_epoch,
            )
            joined_inflight = None
            is_builder = True

    if not is_builder:
        try:
            return future.result(timeout=_PROJECTION_WAIT_TIMEOUT)
        except concurrent.futures.TimeoutError:
            # Snapshot diagnostics BEFORE the single decrement in
            # finally.  The count includes the current (timing-out)
            # waiter because it has not been decremented yet.
            with _state_lock:
                current_waiters = (
                    joined_inflight.waiter_count
                    if joined_inflight is not None
                    else 0
                )
                total_in_flight = len(_in_flight)
                build_epoch = current_epoch
                elapsed = time.monotonic() - builder_started_at
            raise ProjectionWaitTimeout(
                report_date=report_date,
                source_version_token=source_version.token(),
                build_epoch=build_epoch,
                timeout_seconds=_PROJECTION_WAIT_TIMEOUT,
                builder_elapsed_seconds=elapsed,
                waiter_count=current_waiters,
                total_in_flight_count=total_in_flight,
            )
        finally:
            # Single decrement path for ALL waiter exits (success,
            # timeout, owner-exception).  Targets the exact entry the
            # waiter joined so an epoch change cannot contaminate a
            # different entry's count.
            with _state_lock:
                if joined_inflight is not None:
                    if joined_inflight.waiter_count <= 0:
                        raise AssertionError(
                            f"waiter_count underflow for {flight_key}: "
                            f"count={joined_inflight.waiter_count} "
                            f"(expected >= 1 before waiter exit)"
                        )
                    joined_inflight.waiter_count -= 1

    # Builder path — runs outside the lock so different dates can build
    # in parallel.
    try:
        projection = builder()
        # Publish to cross-request cache only if epoch hasn't changed.
        _cross_request_put(
            database_key,
            report_date,
            projection,
            build_epoch=current_epoch,
        )
        future.set_result(projection)
        return projection
    except BaseException as exc:
        future.set_exception(exc)
        raise
    finally:
        with _state_lock:
            # Only remove if the entry is still ours (same epoch).  If a
            # newer build replaced it we leave the new entry alone.
            entry = _in_flight.get(flight_key)
            if entry is not None and entry.epoch == current_epoch:
                _in_flight.pop(flight_key, None)


def clear_cache() -> None:
    """Clear the cross-request cache and invalidate in-flight entries.

    Increments the cache epoch so that builds started before this call
    do not publish results into the new cache.  Old builders and their
    waiters still complete normally — they are not cancelled.  New
    requests after this call start fresh builds in the new epoch.
    """
    global _cache_epoch
    with _state_lock:
        _cache_epoch += 1
        _cache.clear()
    # In-flight entries are NOT cleared.  Old builders will check epoch
    # before publishing and won't pollute the new cache.  Their futures
    # are still resolved so waiters are never permanently blocked.


def cache_size() -> int:
    """Return the number of cached date slots (for testing)."""
    with _state_lock:
        return len(_cache)


def cached_dates() -> tuple[str, ...]:
    """Return the cached report dates (for testing)."""
    with _state_lock:
        return tuple(key[1] for key in _cache)


def in_flight_count() -> int:
    """Return the number of in-flight builds (for testing)."""
    with _state_lock:
        return len(_in_flight)


def get_waiter_count(
    database_key: str,
    report_date: str,
    source_version_token: str,
) -> int:
    """Return the waiter count for a specific in-flight entry (for testing).

    Allows tests to deterministically wait for all waiters to join an
    in-flight build instead of using fixed sleep-based settling.
    Returns 0 if no in-flight entry exists for the given key.
    """
    flight_key = (database_key, report_date, source_version_token)
    with _state_lock:
        entry = _in_flight.get(flight_key)
        return entry.waiter_count if entry is not None else 0


def set_wait_timeout(seconds: float) -> None:
    """Override the single-flight wait timeout (for testing)."""
    global _PROJECTION_WAIT_TIMEOUT
    _PROJECTION_WAIT_TIMEOUT = max(0.001, float(seconds))


def get_wait_timeout() -> float:
    return _PROJECTION_WAIT_TIMEOUT


__all__ = [
    "DayProjection",
    "ProjectionWaitTimeout",
    "cached_dates",
    "cache_size",
    "clear_cache",
    "get_day_projection",
    "get_wait_timeout",
    "get_waiter_count",
    "in_flight_count",
    "materialize_day_projection",
    "set_wait_timeout",
]
