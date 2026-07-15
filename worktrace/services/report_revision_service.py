"""Stable report revisions for refresh and export boundaries."""

from __future__ import annotations

from datetime import date as date_type, timedelta
from typing import Any

from ..db import get_connection
from .report_projection_identity import stable_json_hash


def get_report_structure_revision(report_date: str, *, conn=None) -> str:
    """Return a lightweight revision that excludes natural open-row duration.

    The revision tracks every durable fact that can change visible report
    structure or attribution. It deliberately omits ``duration_seconds`` so a
    collector tick does not request a full page reload.
    """

    day = date_type.fromisoformat(report_date)
    load_start = f"{(day - timedelta(days=1)).isoformat()} 00:00:00"
    load_end = f"{(day + timedelta(days=2)).isoformat()} 00:00:00"

    def _build(connection) -> str:
        activities = [
            dict(row)
            for row in connection.execute(
                """
                SELECT
                    a.id, a.start_time, a.end_time, a.status,
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
        clipboard: list[dict[str, Any]] = []
        if activity_ids:
            placeholders = ",".join("?" for _ in activity_ids)
            clipboard = [
                dict(row)
                for row in connection.execute(
                    f"""
                    SELECT id, activity_id, captured_at
                    FROM activity_clipboard_event
                    WHERE activity_id IN ({placeholders})
                    ORDER BY activity_id, captured_at, id
                    """,
                    activity_ids,
                ).fetchall()
            ]
        boundaries = [
            dict(row)
            for row in connection.execute(
                """
                SELECT occurred_at, boundary_type
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
                "clipboard": clipboard,
                "boundaries": boundaries,
                "operations": operations,
                "operation_members": members,
                "settings": settings,
            }
        )

    if conn is not None:
        return _build(conn)
    with get_connection() as own_conn:
        own_conn.execute("BEGIN")
        try:
            value = _build(own_conn)
            own_conn.commit()
            return value
        except Exception:
            own_conn.rollback()
            raise


def snapshot_structure_revision(snapshot) -> str:
    """Build the same semantic revision from an already-built snapshot."""

    entries = []
    for entry in snapshot.final_entries:
        in_progress = bool(entry.get("is_in_progress"))
        entries.append(
            {
                "key": str(entry.get("projection_instance_key") or ""),
                "kind": str(entry.get("row_kind") or "project_session"),
                "revision": (
                    {
                        "report_date": str(entry.get("report_date") or ""),
                        "members": list(entry.get("member_slices") or []),
                        "status": str(entry.get("status_code") or entry.get("status") or ""),
                        "project_id": int(entry.get("project_id") or 0),
                    }
                    if in_progress
                    else str(entry.get("projection_revision") or "")
                ),
                "in_progress": in_progress,
            }
        )
    return stable_json_hash(
        {
            "range": [snapshot.start_date, snapshot.end_date],
            "entries": entries,
            "diagnostics": [item.to_dict() for item in snapshot.operation_diagnostics],
        }
    )


def export_revision(date_from: str, date_to: str, records) -> str:
    """Revision of the exact closed, display-safe export record set."""

    return stable_json_hash(
        {
            "range": [date_from, date_to],
            "records": [dict(record) for record in records],
        }
    )


__all__ = [
    "export_revision",
    "get_report_structure_revision",
    "snapshot_structure_revision",
]
