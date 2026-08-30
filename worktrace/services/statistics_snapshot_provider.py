"""Compact, bounded caches for the interactive Statistics read model.

Interactive Statistics never retains a full ``ReportProjectionSnapshot``. Durable
summaries are looked up before range materialization; cache misses build a compact
range projection from the canonical ``compute_projection`` business owner. Range
slots use stable identities and validate source versions so one range cannot retain
multiple generation copies.
"""

from __future__ import annotations

import concurrent.futures
import threading
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Mapping

from ..data_generation_repository import DataGenerationNamespace
from .page_read_context import current_page_read_context, page_read_scope
from .report_revision_service import PROJECTION_SCHEMA_VERSION
from .statistics_range_projection import (
    StatisticsRangeProjection,
    StatisticsRangeSourceVersion,
    materialize_statistics_range_projection,
)
from .statistics_scope_policy import normalize_statistics_project_scope

if TYPE_CHECKING:
    from .statistics_projection import StatisticsSummaryProjection


_MAX_RANGE_SLOTS = 2
_MAX_SUMMARY_SLOTS = 32
_RANGE_WAIT_TIMEOUT_SECONDS = 30.0


@dataclass
class _RangeCacheEntry:
    projection: StatisticsRangeProjection
    last_used: float


@dataclass
class _SummaryCacheEntry:
    source_version: StatisticsRangeSourceVersion
    projection: "StatisticsSummaryProjection"
    last_used: float


@dataclass
class _InFlight:
    future: concurrent.futures.Future
    epoch: int
    started_at_monotonic: float = field(default_factory=time.monotonic)


@dataclass(frozen=True)
class StatisticsDurableRead:
    """Durable summary plus the compact range built for this miss, if any."""

    summary: "StatisticsSummaryProjection"
    range_projection: StatisticsRangeProjection | None


_STATE_LOCK = threading.Lock()
_RANGE_CACHE: dict[tuple[str, str, str], _RangeCacheEntry] = {}
_SUMMARY_CACHE: dict[tuple[str, str, str, str], _SummaryCacheEntry] = {}
_IN_FLIGHT: dict[tuple[str, str, str, str], _InFlight] = {}
_CACHE_EPOCH = 0
_LRU_COUNTER = 0.0


def _next_lru() -> float:
    global _LRU_COUNTER
    _LRU_COUNTER += 1.0
    return _LRU_COUNTER


def _source_version(context) -> StatisticsRangeSourceVersion:
    return StatisticsRangeSourceVersion(
        database_key=str(context.database_key),
        report_structure_generation=int(
            context.report_generations.get(
                DataGenerationNamespace.REPORT_STRUCTURE,
                0,
            )
        ),
        database_replacement_epoch=int(
            context.report_generations.get(
                DataGenerationNamespace.DATABASE_REPLACEMENT,
                0,
            )
        ),
        projection_schema_version=int(PROJECTION_SCHEMA_VERSION),
    )


def _range_key(context, start_date: str, end_date: str) -> tuple[str, str, str]:
    return str(context.database_key), str(start_date), str(end_date)


def _summary_key(
    context,
    start_date: str,
    end_date: str,
    normalized_scope: str,
) -> tuple[str, str, str, str]:
    return (
        str(context.database_key),
        str(start_date),
        str(end_date),
        str(normalized_scope or ""),
    )


def _evict_range_if_needed() -> None:
    while len(_RANGE_CACHE) > _MAX_RANGE_SLOTS:
        oldest = min(_RANGE_CACHE, key=lambda key: _RANGE_CACHE[key].last_used)
        _RANGE_CACHE.pop(oldest, None)


def _evict_summary_if_needed() -> None:
    while len(_SUMMARY_CACHE) > _MAX_SUMMARY_SLOTS:
        oldest = min(_SUMMARY_CACHE, key=lambda key: _SUMMARY_CACHE[key].last_used)
        _SUMMARY_CACHE.pop(oldest, None)


def _get_cached_range(
    key: tuple[str, str, str],
    expected_version: StatisticsRangeSourceVersion,
) -> StatisticsRangeProjection | None:
    with _STATE_LOCK:
        entry = _RANGE_CACHE.get(key)
        if entry is None:
            return None
        if entry.projection.source_version != expected_version:
            _RANGE_CACHE.pop(key, None)
            return None
        entry.last_used = _next_lru()
        return entry.projection


def _put_cached_range(
    key: tuple[str, str, str],
    projection: StatisticsRangeProjection,
    *,
    build_epoch: int,
) -> None:
    with _STATE_LOCK:
        if _CACHE_EPOCH != build_epoch:
            return
        _RANGE_CACHE[key] = _RangeCacheEntry(
            projection=projection,
            last_used=_next_lru(),
        )
        _evict_range_if_needed()


def _get_cached_summary(
    key: tuple[str, str, str, str],
    expected_version: StatisticsRangeSourceVersion,
) -> "StatisticsSummaryProjection" | None:
    with _STATE_LOCK:
        entry = _SUMMARY_CACHE.get(key)
        if entry is None:
            return None
        if entry.source_version != expected_version:
            _SUMMARY_CACHE.pop(key, None)
            return None
        entry.last_used = _next_lru()
        return entry.projection


def _put_cached_summary(
    key: tuple[str, str, str, str],
    source_version: StatisticsRangeSourceVersion,
    projection: "StatisticsSummaryProjection",
) -> None:
    with _STATE_LOCK:
        _SUMMARY_CACHE[key] = _SummaryCacheEntry(
            source_version=source_version,
            projection=projection,
            last_used=_next_lru(),
        )
        _evict_summary_if_needed()


def _build_range_projection(
    context,
    start_date: str,
    end_date: str,
    source_version: StatisticsRangeSourceVersion,
) -> StatisticsRangeProjection:
    # Import the module rather than the symbol so existing performance tests and
    # diagnostics can instrument the canonical compute owner.
    from . import report_projection_snapshot_service

    computation = report_projection_snapshot_service.compute_projection(
        context.conn,
        start_date,
        end_date,
    )
    return materialize_statistics_range_projection(
        computation,
        source_version,
        start_date=start_date,
        end_date=end_date,
    )


def _get_range_with_context(
    context,
    start_date: str,
    end_date: str,
    source_version: StatisticsRangeSourceVersion,
) -> StatisticsRangeProjection:
    if bool(context.needs_full_refresh):
        return _build_range_projection(
            context,
            start_date,
            end_date,
            source_version,
        )

    key = _range_key(context, start_date, end_date)
    cached = _get_cached_range(key, source_version)
    if cached is not None:
        return cached

    flight_key = (*key, source_version.token())
    with _STATE_LOCK:
        current_epoch = _CACHE_EPOCH
        existing = _IN_FLIGHT.get(flight_key)
        if existing is None or existing.epoch != current_epoch:
            future: concurrent.futures.Future = concurrent.futures.Future()
            _IN_FLIGHT[flight_key] = _InFlight(
                future=future,
                epoch=current_epoch,
            )
            is_builder = True
        else:
            future = existing.future
            is_builder = False

    if not is_builder:
        return future.result(timeout=_RANGE_WAIT_TIMEOUT_SECONDS)

    try:
        projection = _build_range_projection(
            context,
            start_date,
            end_date,
            source_version,
        )
        _put_cached_range(
            key,
            projection,
            build_epoch=current_epoch,
        )
        future.set_result(projection)
        return projection
    except BaseException as exc:
        future.set_exception(exc)
        raise
    finally:
        with _STATE_LOCK:
            current = _IN_FLIGHT.get(flight_key)
            if current is not None and current.epoch == current_epoch:
                _IN_FLIGHT.pop(flight_key, None)


def get_statistics_range_projection(
    start_date: str,
    end_date: str,
) -> StatisticsRangeProjection:
    """Return the compact durable projection for one Statistics range."""

    context = current_page_read_context()
    if context is None:
        with page_read_scope():
            return get_statistics_range_projection(start_date, end_date)

    source_version = _source_version(context)
    return _get_range_with_context(
        context,
        start_date,
        end_date,
        source_version,
    )


def get_statistics_durable_read(
    start_date: str,
    end_date: str,
    project_id: str | int | None = None,
) -> StatisticsDurableRead:
    """Return a durable summary, checking the small summary cache first."""

    context = current_page_read_context()
    if context is None:
        with page_read_scope():
            return get_statistics_durable_read(
                start_date,
                end_date,
                project_id,
            )

    from . import statistics_projection

    normalized_scope = normalize_statistics_project_scope(project_id)
    source_version = _source_version(context)
    summary_key = _summary_key(
        context,
        start_date,
        end_date,
        normalized_scope,
    )

    if not bool(context.needs_full_refresh):
        cached_summary = _get_cached_summary(summary_key, source_version)
        if cached_summary is not None:
            return StatisticsDurableRead(
                summary=cached_summary,
                range_projection=None,
            )

    range_projection = _get_range_with_context(
        context,
        start_date,
        end_date,
        source_version,
    )
    summary = statistics_projection.build_statistics_summary_projection(
        range_projection,
        project_id=project_id,
    )
    if not bool(context.needs_full_refresh):
        _put_cached_summary(
            summary_key,
            source_version,
            summary,
        )
    return StatisticsDurableRead(
        summary=summary,
        range_projection=range_projection,
    )


def get_statistics_durable_summary(
    start_date: str,
    end_date: str,
    project_id: str | int | None = None,
) -> "StatisticsSummaryProjection":
    return get_statistics_durable_read(
        start_date,
        end_date,
        project_id,
    ).summary


def get_statistics_base_snapshot(
    start_date: str,
    end_date: str,
) -> StatisticsRangeProjection:
    """Compatibility alias: Statistics base reads are now compact projections."""

    return get_statistics_range_projection(start_date, end_date)


def get_statistics_summary_projection(
    snapshot,
    project_id: str | int | None = None,
    *,
    live_runtime_snapshot: Mapping[str, Any] | None = None,
) -> "StatisticsSummaryProjection":
    """Compatibility helper for callers that already own an exact snapshot."""

    from .statistics_projection import build_statistics_summary_projection

    return build_statistics_summary_projection(
        snapshot,
        project_id=project_id,
        live_runtime_snapshot=live_runtime_snapshot,
    )


def clear_statistics_snapshot_cache() -> None:
    """Clear Statistics caches and prevent pre-clear builds from publishing."""

    global _CACHE_EPOCH
    with _STATE_LOCK:
        _CACHE_EPOCH += 1
        _RANGE_CACHE.clear()
        _SUMMARY_CACHE.clear()


def statistics_range_cache_size() -> int:
    with _STATE_LOCK:
        return len(_RANGE_CACHE)


def statistics_summary_cache_size() -> int:
    with _STATE_LOCK:
        return len(_SUMMARY_CACHE)


def cached_statistics_ranges() -> tuple[tuple[str, str], ...]:
    with _STATE_LOCK:
        return tuple(
            (key[1], key[2])
            for key in _RANGE_CACHE
        )


__all__ = [
    "StatisticsDurableRead",
    "cached_statistics_ranges",
    "clear_statistics_snapshot_cache",
    "get_statistics_base_snapshot",
    "get_statistics_durable_read",
    "get_statistics_durable_summary",
    "get_statistics_range_projection",
    "get_statistics_summary_projection",
    "statistics_range_cache_size",
    "statistics_summary_cache_size",
]
