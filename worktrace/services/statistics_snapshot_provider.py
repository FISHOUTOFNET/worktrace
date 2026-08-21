"""Bounded cross-request caches for the interactive Statistics read model.

The generic full-snapshot owner intentionally remains request-scoped. Statistics
repeatedly asks for the same date range and project scopes, so this module keeps
small generation-keyed caches for both the durable range snapshot and the much
smaller derived summary projection. Mutation/export/debug paths retain their
existing canonical projection semantics.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from typing import TYPE_CHECKING, Any, Mapping

from ..data_generation_repository import DataGenerationNamespace
from .page_read_context import current_page_read_context
from .report_projection_model import ReportProjectionSnapshot
from .report_projection_snapshot_service import build_visible_snapshot
from .report_revision_service import PROJECTION_SCHEMA_VERSION
from .statistics_scope_policy import normalize_statistics_project_scope

if TYPE_CHECKING:
    from .statistics_projection import StatisticsSummaryProjection

_MAX_SLOTS = 4
_MAX_SUMMARY_SLOTS = 32
_CACHE_LOCK = threading.Lock()
_SNAPSHOT_CACHE: OrderedDict[
    tuple[str, str, str, int, int, int], ReportProjectionSnapshot
] = OrderedDict()
_SUMMARY_CACHE: OrderedDict[
    tuple[str, str, str, int, int, int, str, str], Any
] = OrderedDict()


def _generation_value(context, namespace: DataGenerationNamespace) -> int:
    if context is None:
        return 0
    return int(context.report_generations.get(namespace, 0))


def _snapshot_cache_key(context, start_date: str, end_date: str):
    return (
        str(context.database_key),
        str(start_date),
        str(end_date),
        _generation_value(context, DataGenerationNamespace.REPORT_STRUCTURE),
        _generation_value(context, DataGenerationNamespace.DATABASE_REPLACEMENT),
        int(PROJECTION_SCHEMA_VERSION),
    )


def _summary_cache_key(
    context,
    snapshot: ReportProjectionSnapshot,
    normalized_scope: str,
):
    return (
        str(context.database_key) if context is not None else "",
        str(snapshot.start_date),
        str(snapshot.end_date),
        _generation_value(context, DataGenerationNamespace.REPORT_STRUCTURE),
        _generation_value(context, DataGenerationNamespace.DATABASE_REPLACEMENT),
        int(PROJECTION_SCHEMA_VERSION),
        str(snapshot.snapshot_revision or ""),
        str(normalized_scope or ""),
    )


def _get_snapshot(key):
    with _CACHE_LOCK:
        snapshot = _SNAPSHOT_CACHE.get(key)
        if snapshot is None:
            return None
        _SNAPSHOT_CACHE.move_to_end(key)
        return snapshot


def _put_snapshot(key, snapshot: ReportProjectionSnapshot) -> None:
    with _CACHE_LOCK:
        _SNAPSHOT_CACHE[key] = snapshot
        _SNAPSHOT_CACHE.move_to_end(key)
        while len(_SNAPSHOT_CACHE) > _MAX_SLOTS:
            _SNAPSHOT_CACHE.popitem(last=False)


def _get_summary(key):
    with _CACHE_LOCK:
        projection = _SUMMARY_CACHE.get(key)
        if projection is None:
            return None
        _SUMMARY_CACHE.move_to_end(key)
        return projection


def _put_summary(key, projection: "StatisticsSummaryProjection") -> None:
    with _CACHE_LOCK:
        _SUMMARY_CACHE[key] = projection
        _SUMMARY_CACHE.move_to_end(key)
        while len(_SUMMARY_CACHE) > _MAX_SUMMARY_SLOTS:
            _SUMMARY_CACHE.popitem(last=False)


def get_statistics_base_snapshot(
    start_date: str,
    end_date: str,
) -> ReportProjectionSnapshot:
    """Return a reusable durable range snapshot for realtime Statistics only."""

    context = current_page_read_context()
    if context is None or bool(context.needs_full_refresh):
        return build_visible_snapshot(start_date, end_date)

    key = _snapshot_cache_key(context, start_date, end_date)
    cached = _get_snapshot(key)
    if cached is not None:
        return cached

    snapshot = build_visible_snapshot(start_date, end_date)
    _put_snapshot(key, snapshot)
    return snapshot


def get_statistics_summary_projection(
    snapshot: ReportProjectionSnapshot,
    project_id: str | int | None = None,
    *,
    live_runtime_snapshot: Mapping[str, Any] | None = None,
) -> "StatisticsSummaryProjection":
    """Return a cached summary projection for one exact snapshot and scope.

    The snapshot revision keeps live/as-of samples exact: ticking snapshots get
    distinct keys, while historical and otherwise stable scopes avoid repeating
    the same Python aggregation work when the UI revisits them.
    """

    from .statistics_projection import build_statistics_summary_projection

    normalized_scope = normalize_statistics_project_scope(project_id)
    context = current_page_read_context()
    if context is None or bool(context.needs_full_refresh):
        return build_statistics_summary_projection(
            snapshot,
            project_id=project_id,
            live_runtime_snapshot=live_runtime_snapshot,
        )

    key = _summary_cache_key(context, snapshot, normalized_scope)
    cached = _get_summary(key)
    if cached is not None:
        return cached

    projection = build_statistics_summary_projection(
        snapshot,
        project_id=project_id,
        live_runtime_snapshot=live_runtime_snapshot,
    )
    _put_summary(key, projection)
    return projection


def clear_statistics_snapshot_cache() -> None:
    """Test/maintenance hook; ordinary invalidation is generation/revision keyed."""

    with _CACHE_LOCK:
        _SNAPSHOT_CACHE.clear()
        _SUMMARY_CACHE.clear()


__all__ = [
    "clear_statistics_snapshot_cache",
    "get_statistics_base_snapshot",
    "get_statistics_summary_projection",
]
