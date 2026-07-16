"""Stable report revisions for refresh and export boundaries."""

from __future__ import annotations

import threading
from datetime import date as date_type, timedelta
from typing import Any

from ..db import get_connection, get_db_key
from ..report_structure_generation import current_generation
from .page_read_context import current_page_read_context
from .report_projection_identity import stable_json_hash

_STRUCTURE_CACHE_LOCK = threading.Lock()
_STRUCTURE_REVISION_CACHE: dict[tuple[str, str], tuple[int, str]] = {}


def clear_report_structure_revision_cache(database_key: str | None = None) -> None:
    """Drop cached hashes, normally after tests or explicit DB reconfiguration."""

    with _STRUCTURE_CACHE_LOCK:
        if database_key is None:
            _STRUCTURE_REVISION_CACHE.clear()
            return
        key = str(database_key)
        for cache_key in list(_STRUCTURE_REVISION_CACHE):
            if cache_key[0] == key:
                _STRUCTURE_REVISION_CACHE.pop(cache_key, None)


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
    """Return the single structural revision used by pages and heartbeat.

    Transaction-bound callers receive an immediate hash of their uncommitted
    view. Page requests reuse the request-level read transaction. Ordinary
    refresh callers reuse a cached hash until a structural write transaction
    publishes a new generation. Natural open-row duration ticks do not publish
    that generation.
    """

    date_type.fromisoformat(report_date)
    if conn is not None:
        return _build_report_structure_revision(report_date, conn)

    page_context = current_page_read_context()
    if page_context is not None:
        return _build_report_structure_revision(report_date, page_context.conn)

    database_key = get_db_key()
    generation = current_generation(database_key)
    cache_key = (database_key, report_date)
    with _STRUCTURE_CACHE_LOCK:
        cached = _STRUCTURE_REVISION_CACHE.get(cache_key)
    if cached is not None and cached[0] == generation:
        return cached[1]

    with get_connection() as own_conn:
        own_conn.execute("BEGIN")
        try:
            value = _build_report_structure_revision(report_date, own_conn)
            own_conn.commit()
        except Exception:
            own_conn.rollback()
            raise

    generation_after = current_generation(database_key)
    if generation_after == generation:
        with _STRUCTURE_CACHE_LOCK:
            _STRUCTURE_REVISION_CACHE[cache_key] = (generation, value)
    return value


def export_revision(date_from: str, date_to: str, records) -> str:
    """Revision of the exact closed, display-safe export record set."""

    return stable_json_hash(
        {
            "range": [date_from, date_to],
            "records": [dict(record) for record in records],
        }
    )


__all__ = [
    "clear_report_structure_revision_cache",
    "export_revision",
    "get_report_structure_revision",
]
