"""Narrow cross-request cache for Statistics durable range snapshots.

The generic full-snapshot owner intentionally remains request-scoped. Statistics
is the one interactive surface that repeatedly asks for the same date range
while only changing project scope, so it gets a small dedicated cache instead
of widening report projection cache semantics for mutation/export/debug paths.
"""

from __future__ import annotations

import threading
from collections import OrderedDict

from ..data_generation_repository import DataGenerationNamespace
from .page_read_context import current_page_read_context
from .report_projection_model import ReportProjectionSnapshot
from .report_projection_snapshot_service import build_visible_snapshot
from .report_revision_service import PROJECTION_SCHEMA_VERSION

_MAX_SLOTS = 4
_CACHE_LOCK = threading.Lock()
_CACHE: OrderedDict[
    tuple[str, str, str, int, int, int], ReportProjectionSnapshot
] = OrderedDict()


def _cache_key(context, start_date: str, end_date: str):
    return (
        str(context.database_key),
        str(start_date),
        str(end_date),
        int(
            context.report_generations.get(
                DataGenerationNamespace.REPORT_STRUCTURE,
                0,
            )
        ),
        int(
            context.report_generations.get(
                DataGenerationNamespace.DATABASE_REPLACEMENT,
                0,
            )
        ),
        int(PROJECTION_SCHEMA_VERSION),
    )


def _get(key):
    with _CACHE_LOCK:
        snapshot = _CACHE.get(key)
        if snapshot is None:
            return None
        _CACHE.move_to_end(key)
        return snapshot


def _put(key, snapshot: ReportProjectionSnapshot) -> None:
    with _CACHE_LOCK:
        _CACHE[key] = snapshot
        _CACHE.move_to_end(key)
        while len(_CACHE) > _MAX_SLOTS:
            _CACHE.popitem(last=False)


def get_statistics_base_snapshot(
    start_date: str,
    end_date: str,
) -> ReportProjectionSnapshot:
    """Return a reusable durable range snapshot for realtime Statistics only."""

    context = current_page_read_context()
    if context is None or bool(context.needs_full_refresh):
        return build_visible_snapshot(start_date, end_date)

    key = _cache_key(context, start_date, end_date)
    cached = _get(key)
    if cached is not None:
        return cached

    snapshot = build_visible_snapshot(start_date, end_date)
    _put(key, snapshot)
    return snapshot


def clear_statistics_snapshot_cache() -> None:
    """Test/maintenance hook; ordinary invalidation is generation-keyed."""

    with _CACHE_LOCK:
        _CACHE.clear()


__all__ = [
    "clear_statistics_snapshot_cache",
    "get_statistics_base_snapshot",
]
