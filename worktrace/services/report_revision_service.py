"""Stable report revisions for refresh and export boundaries.

This module defines three revision concepts that must not be conflated:

* :class:`ProjectionSourceVersion` — a cheap O(1) token derived from durable
  generation counters and the database replacement epoch. It is the sole
  cache-validity and heartbeat structure signal for page read paths.

* ``snapshot_revision`` (built inside :mod:`report_projection_snapshot_service`)
  — a content hash of the complete projection output. It is computed once
  during projection build and used for mutation receipts and export
  consistency. It is NOT recomputed for cache lookups.

* ``projection_revision`` (per-session, from
  :mod:`report_projection_identity`) — a per-session identity used for
  optimistic write admission on merge/split/copy/edit.

The heavyweight content hash (:func:`_build_report_structure_revision`) is
retained only for transaction-bound callers that need to hash an uncommitted
view. Page and heartbeat paths use the source-version token exclusively.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import date as date_type, timedelta
from typing import Any

from ..data_generation_repository import (
    DataGenerationNamespace,
    DataGenerationRepository,
)
from ..db import get_connection, get_db_key
from .page_read_context import current_page_read_context
from .projection_performance import record_source_version
from .report_projection_identity import stable_json_hash

# Bump this when the projection algorithm changes shape (new fields, different
# sorting, different context attribution rules, etc.). All cached day
# projections are invalidated when this changes.
PROJECTION_SCHEMA_VERSION = 1

_STRUCTURE_CACHE_LOCK = threading.Lock()
_STRUCTURE_REVISION_CACHE: dict[
    tuple[str, str],
    tuple[tuple[int, int], str],
] = {}
_STRUCTURE_GENERATION_NAMESPACES = (
    DataGenerationNamespace.REPORT_STRUCTURE,
    DataGenerationNamespace.DATABASE_REPLACEMENT,
)


@dataclass(frozen=True)
class ProjectionSourceVersion:
    """Cheap O(1) cache-validity token for day-level projections.

    Composed entirely from durable generation counters and the database
    replacement epoch — never from scanning activity rows. Two projections
    for the same ``(database_key, report_date)`` are interchangeable iff
    their source versions are equal.

    Future extension point: add ``report_day_generation`` when date-level
    generation is introduced (currently a global ``REPORT_STRUCTURE``
    counter is used, which conservatively invalidates all dates on any
    structural change).
    """

    database_key: str
    report_date: str
    report_structure_generation: int
    database_replacement_epoch: int
    projection_schema_version: int

    def token(self) -> str:
        """Stable hash token suitable for use as ``structure_revision``."""

        return stable_json_hash(
            {
                "db": self.database_key,
                "date": self.report_date,
                "gen": self.report_structure_generation,
                "epoch": self.database_replacement_epoch,
                "schema": self.projection_schema_version,
            }
        )


def get_projection_source_version(report_date: str) -> ProjectionSourceVersion:
    """Read the current source version for ``report_date`` in O(1).

    Inside a :func:`page_read_scope` the generations are reused from the
    request context (already captured). Outside, a lightweight SELECT from
    ``data_generation_state`` is used — no activity/resource/clipboard scan.
    """

    page_context = current_page_read_context()
    if page_context is not None:
        return ProjectionSourceVersion(
            database_key=page_context.database_key,
            report_date=report_date,
            report_structure_generation=int(
                page_context.report_generations.get(
                    DataGenerationNamespace.REPORT_STRUCTURE, 0
                )
            ),
            database_replacement_epoch=int(
                page_context.report_generations.get(
                    DataGenerationNamespace.DATABASE_REPLACEMENT, 0
                )
            ),
            projection_schema_version=PROJECTION_SCHEMA_VERSION,
        )

    with get_connection() as conn:
        generations = DataGenerationRepository.get_many(
            conn,
            _STRUCTURE_GENERATION_NAMESPACES,
        )
    return ProjectionSourceVersion(
        database_key=get_db_key(),
        report_date=report_date,
        report_structure_generation=int(
            generations.get(DataGenerationNamespace.REPORT_STRUCTURE, 0)
        ),
        database_replacement_epoch=int(
            generations.get(DataGenerationNamespace.DATABASE_REPLACEMENT, 0)
        ),
        projection_schema_version=PROJECTION_SCHEMA_VERSION,
    )


def clear_report_structure_revision_cache(database_key: str | None = None) -> None:
    """No-op retained for backward compatibility.

    The source-version token is O(1) and needs no cache. The heavyweight
    content-hash cache (:data:`_STRUCTURE_REVISION_CACHE`) is kept only for
    the transaction path and is cleared here for test isolation.
    """

    with _STRUCTURE_CACHE_LOCK:
        if database_key is None:
            _STRUCTURE_REVISION_CACHE.clear()
            return
        key = str(database_key)
        for cache_key in list(_STRUCTURE_REVISION_CACHE):
            if cache_key[0] == key:
                _STRUCTURE_REVISION_CACHE.pop(cache_key, None)


def _read_durable_generations(connection) -> tuple[int, int]:
    values = DataGenerationRepository.get_many(
        connection,
        _STRUCTURE_GENERATION_NAMESPACES,
    )
    return tuple(values[namespace] for namespace in _STRUCTURE_GENERATION_NAMESPACES)


def _build_report_structure_revision(
    report_date: str,
    connection,
) -> str:
    day = date_type.fromisoformat(report_date)
    load_start = f"{(day - timedelta(days=1)).isoformat()} 00:00:00"
    load_end = f"{(day + timedelta(days=2)).isoformat()} 00:00:00"

    activities = [
        dict(row)
        for row in connection.execute(
            """
            SELECT
                a.id, a.start_time, a.end_time, a.status, a.source,
                a.app_name, a.process_name, a.window_title, a.file_path_hint,
                a.is_hidden, a.is_deleted,
                apa.project_id, apa.source AS assignment_source,
                apa.is_manual, apa.source_rule_type, apa.source_rule_id,
                apa.updated_at AS assignment_updated_at,
                p.name AS project_name,
                p.description AS project_description,
                p.enabled AS project_enabled,
                p.is_archived AS project_archived,
                p.is_deleted AS project_deleted,
                p.updated_at AS project_updated_at
            FROM activity_log a
            LEFT JOIN activity_project_assignment apa ON apa.activity_id = a.id
            LEFT JOIN project p ON p.id = apa.project_id
            WHERE (a.start_time >= ? OR a.end_time IS NULL OR a.end_time >= ?)
              AND (a.end_time IS NULL OR a.start_time <= ?)
            ORDER BY a.start_time, a.id
            """,
            (load_start, load_start, load_end),
        ).fetchall()
    ]
    activity_ids = [int(row["id"]) for row in activities]
    resources: list[dict[str, Any]] = []
    clipboard: list[dict[str, Any]] = []
    if activity_ids:
        placeholders = ",".join("?" for _ in activity_ids)
        resources = [
            dict(row)
            for row in connection.execute(
                f"""
                SELECT activity_id, resource_kind, resource_subtype,
                       display_name, identity_key, is_anchor, confidence,
                       source, app_name, process_name, window_title,
                       path_hint, path_key, uri_scheme, uri_host, uri_hint,
                       metadata_json
                FROM activity_resource
                WHERE activity_id IN ({placeholders})
                ORDER BY activity_id, id
                """,
                activity_ids,
            ).fetchall()
        ]
        clipboard = [
            dict(row)
            for row in connection.execute(
                f"""
                SELECT id, activity_id, copied_at
                FROM activity_clipboard_event
                WHERE activity_id IN ({placeholders})
                ORDER BY activity_id, copied_at, id
                """,
                activity_ids,
            ).fetchall()
        ]
    boundaries = [
        dict(row)
        for row in connection.execute(
            """
            SELECT occurred_at, reason
            FROM session_boundary
            WHERE occurred_at >= ? AND occurred_at <= ?
            ORDER BY occurred_at, id
            """,
            (load_start, load_end),
        ).fetchall()
    ]
    operations = [
        dict(row)
        for row in connection.execute(
            """
            SELECT id, sequence, operation_type, source_instance_key,
                   source_expected_revision, target_instance_key,
                   target_expected_revision, direction,
                   undo_of_operation_id, payload_json
            FROM report_session_operation
            WHERE report_date = ?
            ORDER BY sequence, id
            """,
            (report_date,),
        ).fetchall()
    ]
    operation_ids = [int(row["id"]) for row in operations]
    members: list[dict[str, Any]] = []
    if operation_ids:
        placeholders = ",".join("?" for _ in operation_ids)
        members = [
            dict(row)
            for row in connection.execute(
                f"""
                SELECT operation_id, role, activity_id, report_date,
                       slice_start_time, display_order
                FROM report_session_operation_member
                WHERE operation_id IN ({placeholders})
                ORDER BY operation_id, role, display_order, activity_id
                """,
                operation_ids,
            ).fetchall()
        ]
    settings = {
        str(row["key"]): str(row["value"] or "")
        for row in connection.execute(
            """
            SELECT key, value FROM settings
            WHERE key IN (
                'context_carry_minutes',
                'unrecorded_gap_boundary_seconds'
            )
            ORDER BY key
            """
        ).fetchall()
    }
    return stable_json_hash(
        {
            "report_date": report_date,
            "activities": activities,
            "resources": resources,
            "clipboard": clipboard,
            "boundaries": boundaries,
            "operations": operations,
            "operation_members": members,
            "settings": settings,
        }
    )


def get_report_structure_revision(report_date: str, *, conn=None) -> str:
    """Return the structural revision used by pages and heartbeat.

    Page and heartbeat paths receive the cheap :class:`ProjectionSourceVersion`
    token — an O(1) value derived from durable generation counters, never
    from scanning activity rows. Transaction-bound callers (``conn`` provided)
    receive the heavyweight content hash of their uncommitted view, which is
    needed for write-admission tests that must see uncommitted state.
    """

    date_type.fromisoformat(report_date)
    if conn is not None:
        return _build_report_structure_revision(report_date, conn)

    source_version = get_projection_source_version(report_date)
    token = source_version.token()
    record_source_version(token)
    return token


def export_revision(date_from: str, date_to: str, records) -> str:
    """Revision of the exact closed, display-safe export record set."""

    return stable_json_hash(
        {
            "range": [date_from, date_to],
            "records": [dict(record) for record in records],
        }
    )


__all__ = [
    "PROJECTION_SCHEMA_VERSION",
    "ProjectionSourceVersion",
    "clear_report_structure_revision_cache",
    "export_revision",
    "get_projection_source_version",
    "get_report_structure_revision",
]
