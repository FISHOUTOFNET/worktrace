"""The single, read-only canonical report projection query.

This module is the materializer for the full :class:`ReportProjectionSnapshot`
used by mutation, export, and debug paths. The projection business computation
itself lives in :mod:`report_projection_builder` (the single public owner);
this module freezes the builder's :class:`ProjectionComputation` into a
recursively-immutable snapshot and exposes the page-read helpers that fall
back to a full snapshot when called outside a :func:`page_read_scope`.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from typing import Any

from ..data_generation_repository import (
    DataGenerationNamespace,
    DataGenerationRepository,
)
from ..db import get_connection, get_db_key
from . import project_lifecycle_policy
from .page_read_context import current_page_read_context
from .projection_performance import record_cache_hit
from .report_projection_builder import compute_projection
from .report_projection_model import ReportProjectionSnapshot, thaw_value
from .report_revision_service import PROJECTION_SCHEMA_VERSION
from .report_session_projection_service import (
    _attach_detail_revision,
    public_session_dto,
)

_FULL_SNAPSHOT_CACHE_MAX_SLOTS = 2
_FULL_SNAPSHOT_CACHE_LOCK = threading.Lock()
_FULL_SNAPSHOT_CACHE: OrderedDict[
    tuple[str, str, str, int, int, int], ReportProjectionSnapshot
] = OrderedDict()


def _snapshot_cache_key(
    database_key: str,
    start_date: str,
    end_date: str,
    report_generation: int,
    replacement_epoch: int,
) -> tuple[str, str, str, int, int, int]:
    return (
        str(database_key),
        str(start_date),
        str(end_date),
        int(report_generation),
        int(replacement_epoch),
        int(PROJECTION_SCHEMA_VERSION),
    )


def _cross_request_snapshot_get(
    key: tuple[str, str, str, int, int, int],
) -> ReportProjectionSnapshot | None:
    with _FULL_SNAPSHOT_CACHE_LOCK:
        snapshot = _FULL_SNAPSHOT_CACHE.get(key)
        if snapshot is None:
            return None
        _FULL_SNAPSHOT_CACHE.move_to_end(key)
        return snapshot


def _cross_request_snapshot_put(
    key: tuple[str, str, str, int, int, int],
    snapshot: ReportProjectionSnapshot,
) -> None:
    with _FULL_SNAPSHOT_CACHE_LOCK:
        _FULL_SNAPSHOT_CACHE[key] = snapshot
        _FULL_SNAPSHOT_CACHE.move_to_end(key)
        while len(_FULL_SNAPSHOT_CACHE) > _FULL_SNAPSHOT_CACHE_MAX_SLOTS:
            _FULL_SNAPSHOT_CACHE.popitem(last=False)


def clear_full_snapshot_cache() -> None:
    """Test/maintenance hook; generation keys handle ordinary invalidation."""

    with _FULL_SNAPSHOT_CACHE_LOCK:
        _FULL_SNAPSHOT_CACHE.clear()


def build_visible_snapshot(
    start_date: str,
    end_date: str,
    *,
    conn=None,
) -> ReportProjectionSnapshot:
    """Build a deterministic snapshot without modifying persistent state.

    Caller-owned mutation transactions deliberately bypass all caches by
    passing ``conn=``. Read-only range callers reuse up to two immutable full
    snapshots while the report/database generation tuple is unchanged.
    """

    if conn is not None:
        return _build_snapshot(conn, start_date, end_date)

    context = current_page_read_context()
    request_key = (str(start_date), str(end_date))
    if context is not None:
        cached = context.snapshot_cache.get(request_key)
        if cached is not None:
            record_cache_hit(True)
            return cached
        cache_key = _snapshot_cache_key(
            context.database_key,
            start_date,
            end_date,
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
        )
        cached = _cross_request_snapshot_get(cache_key)
        if cached is not None:
            record_cache_hit(True)
            context.snapshot_cache[request_key] = cached
            return cached
        result = _build_snapshot(context.conn, start_date, end_date)
        context.snapshot_cache[request_key] = result
        _cross_request_snapshot_put(cache_key, result)
        return result

    with get_connection() as read_conn:
        read_conn.execute("BEGIN")
        try:
            cache_key = _snapshot_cache_key(
                get_db_key(),
                start_date,
                end_date,
                DataGenerationRepository.get(
                    read_conn,
                    DataGenerationNamespace.REPORT_STRUCTURE,
                ),
                DataGenerationRepository.get(
                    read_conn,
                    DataGenerationNamespace.DATABASE_REPLACEMENT,
                ),
            )
            cached = _cross_request_snapshot_get(cache_key)
            if cached is not None:
                record_cache_hit(True)
                read_conn.commit()
                return cached
            result = _build_snapshot(read_conn, start_date, end_date)
            read_conn.commit()
        except Exception:
            read_conn.rollback()
            raise
    _cross_request_snapshot_put(cache_key, result)
    return result


def get_report_sessions_by_date(date: str) -> list[dict]:
    return get_report_sessions_by_range(date, date)


def get_visible_report_sessions_by_date(date: str) -> list[dict]:
    return get_report_sessions_by_date(date)


def get_visible_report_sessions_for_operations_by_date(date: str) -> list[dict]:
    return get_report_sessions_for_operations(date, date)


def get_report_sessions_by_range(start_date: str, end_date: str) -> list[dict]:
    return [
        public_session_dto(session)
        for session in get_report_sessions_for_operations(start_date, end_date)
    ]


def get_report_sessions_for_operations(
    start_date: str,
    end_date: str,
) -> list[dict]:
    projected = [
        _mutable_record(session)
        for session in build_visible_snapshot(start_date, end_date).final_sessions
        if project_lifecycle_policy.final_session_is_reportable(session)
    ]
    for session in projected:
        _attach_detail_revision(session)
    return projected


def get_projected_activity_contributions_by_range(
    start_date: str,
    end_date: str,
) -> list[dict]:
    return [
        _mutable_record(item)
        for item in build_visible_snapshot(start_date, end_date).final_contributions
    ]


def _mutable_record(value) -> dict[str, Any]:
    result = thaw_value(value)
    if not isinstance(result, dict):
        raise TypeError("canonical record must thaw to dict")
    return result


def _build_snapshot(conn, start_date: str, end_date: str) -> ReportProjectionSnapshot:
    """Materialize a full ReportProjectionSnapshot from the shared computation.

    The computation runs once via :func:`compute_projection` in
    :mod:`report_projection_builder`; this wrapper freezes all record
    collections (including base_sessions and the mutually exclusive subsets)
    into the recursively-immutable snapshot required by mutation, export,
    and debug paths. Page-read paths that only need the compact
    :class:`DayProjection` must call the provider instead so the full freeze
    is skipped.
    """
    comp = compute_projection(conn, start_date, end_date)
    return ReportProjectionSnapshot(
        start_date=comp.start_date,
        end_date=comp.end_date,
        base_sessions=tuple(comp.base_sessions),
        final_entries=comp.final_entries,
        final_sessions=comp.final_sessions,
        standalone_status_entries=comp.standalone_status_entries,
        final_contributions=comp.final_contributions,
        operation_diagnostics=comp.operation_diagnostics,
        snapshot_revision=comp.snapshot_revision,
    )


__all__ = [
    "ReportProjectionSnapshot",
    "build_visible_snapshot",
    "clear_full_snapshot_cache",
    "get_projected_activity_contributions_by_range",
    "get_report_sessions_by_date",
    "get_report_sessions_by_range",
    "get_report_sessions_for_operations",
    "get_visible_report_sessions_by_date",
    "get_visible_report_sessions_for_operations_by_date",
]
