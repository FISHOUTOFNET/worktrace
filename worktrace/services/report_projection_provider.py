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
  is built by at most one thread; others wait for the result.
* **Transaction bypass** — mutation paths that pass ``conn=`` bypass
  the provider entirely and use :func:`build_visible_snapshot` directly.
* **Compact storage** — entries and contributions are stored exactly
  once; indexes reference the same immutable objects.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Mapping

from ..data_generation_repository import DataGenerationNamespace
from ..db import get_connection, get_db_key
from .page_read_context import current_page_read_context
from .projection_performance import record_cache_hit
from .report_projection_model import OperationDiagnostic
from .report_projection_snapshot_service import _build_snapshot
from .report_revision_service import (
    PROJECTION_SCHEMA_VERSION,
    ProjectionSourceVersion,
    get_projection_source_version,
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


class _SingleFlightResult:
    """Result holder for single-flight coordination."""

    __slots__ = ("_event", "_projection", "_exception")

    def __init__(self) -> None:
        self._event = threading.Event()
        self._projection: DayProjection | None = None
        self._exception: BaseException | None = None

    def set_result(self, projection: DayProjection) -> None:
        self._projection = projection
        self._event.set()

    def set_exception(self, exc: BaseException) -> None:
        self._exception = exc
        self._event.set()

    def wait(self, timeout: float | None = None) -> DayProjection:
        self._event.wait(timeout=timeout)
        if self._exception is not None:
            raise self._exception
        assert self._projection is not None
        return self._projection


_MAX_SLOTS = 3
_cache_lock = threading.Lock()
_cache: dict[tuple[str, str], _CacheEntry] = {}
_in_flight_lock = threading.Lock()
_in_flight: dict[tuple[str, str, str], _SingleFlightResult] = {}
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
    with _cache_lock:
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
) -> None:
    with _cache_lock:
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
    """Build a compact DayProjection from the canonical snapshot builder."""
    snapshot = _build_snapshot(conn, report_date, report_date)
    entries = snapshot.final_entries
    contributions = snapshot.final_contributions

    entry_by_key: dict[str, Mapping[str, Any]] = {}
    for entry in entries:
        key = str(entry.get("projection_instance_key") or "")
        if key:
            entry_by_key[key] = entry

    contributions_by_key: dict[str, tuple[Mapping[str, Any], ...]] = {}
    for contribution in contributions:
        key = str(contribution.get("projection_instance_key") or "")
        if key:
            contributions_by_key.setdefault(key, ())
            contributions_by_key[key] = (
                *contributions_by_key[key],
                contribution,
            )

    # _build_snapshot already called record_counts with the real counts.
    return DayProjection(
        report_date=report_date,
        source_version=source_version,
        entries=entries,
        contributions=contributions,
        operation_diagnostics=snapshot.operation_diagnostics,
        snapshot_revision=snapshot.snapshot_revision,
        entry_by_key=entry_by_key,
        contributions_by_key=contributions_by_key,
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

    # 3. Single-flight build.
    projection = _single_flight_build(
        context.database_key,
        report_date,
        source_version,
        builder=lambda: _build_day_projection(context.conn, report_date, source_version),
    )
    context.day_projection_cache[report_date] = projection
    _cross_request_put(context.database_key, report_date, projection)
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

    projection = _single_flight_build(database_key, report_date, source_version, builder)
    _cross_request_put(database_key, report_date, projection)
    return projection


def _single_flight_build(
    database_key: str,
    report_date: str,
    source_version: ProjectionSourceVersion,
    builder,
) -> DayProjection:
    """Ensure only one thread builds a given (db, date, version) triple."""
    flight_key = (database_key, report_date, source_version.token())

    with _in_flight_lock:
        existing = _in_flight.get(flight_key)
        if existing is not None:
            is_builder = False
        else:
            existing = _SingleFlightResult()
            _in_flight[flight_key] = existing
            is_builder = True

    if not is_builder:
        return existing.wait()

    try:
        projection = builder()
        existing.set_result(projection)
        return projection
    except BaseException as exc:
        existing.set_exception(exc)
        raise
    finally:
        with _in_flight_lock:
            _in_flight.pop(flight_key, None)


def clear_cache() -> None:
    """Clear the cross-request cache. Safe to call at any time.

    The cache is not the source of truth — clearing it just means the
    next read will rebuild from SQLite + runtime state.
    """
    with _cache_lock:
        _cache.clear()
    with _in_flight_lock:
        # Cancel any in-flight builds by propagating an exception.
        for result in _in_flight.values():
            result.set_exception(RuntimeError("cache cleared during build"))
        _in_flight.clear()


def cache_size() -> int:
    """Return the number of cached date slots (for testing)."""
    with _cache_lock:
        return len(_cache)


def cached_dates() -> tuple[str, ...]:
    """Return the cached report dates (for testing)."""
    with _cache_lock:
        return tuple(key[1] for key in _cache)


__all__ = [
    "DayProjection",
    "cached_dates",
    "cache_size",
    "clear_cache",
    "get_day_projection",
]
