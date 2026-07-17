from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from ..db import dict_rows, get_connection
from ..time_utils import end_of_day, start_of_day


def fetch_report_activities_between(
    start_time: str,
    end_time: str,
    *,
    include_excluded: bool,
    conn=None,
) -> list[dict[str, Any]]:
    where = [
        "a.is_deleted = 0",
        "a.is_hidden = 0",
        "a.start_time < ?",
        "COALESCE(a.end_time, a.start_time) >= ?",
    ]
    params: list[Any] = [end_time, start_time]
    if not include_excluded:
        where.append("a.status <> 'excluded'")
    sql = f"""
        SELECT
            a.*,
            apa.project_id AS project_id,
            apa.source AS assignment_source,
            apa.is_manual AS is_manual,
            apa.confidence AS assignment_confidence,
            apa.suggested_project_name,
            apa.source_rule_type,
            apa.source_rule_id,
            p.name AS project_name,
            p.description AS project_description,
            p.enabled AS project_enabled,
            p.is_archived AS project_is_archived,
            p.is_deleted AS project_is_deleted,
            ar.resource_kind,
            ar.resource_subtype,
            ar.display_name AS resource_display_name,
            ar.identity_key AS resource_identity_key,
            ar.is_anchor AS resource_is_anchor,
            ar.path_hint AS resource_path_hint,
            ar.uri_host AS resource_uri_host
        FROM activity_log a
        LEFT JOIN activity_project_assignment apa ON apa.activity_id = a.id
        LEFT JOIN project p ON p.id = apa.project_id
        LEFT JOIN activity_resource ar ON ar.activity_id = a.id
        WHERE {' AND '.join(where)}
        ORDER BY a.start_time, a.id
    """
    if conn is None:
        with get_connection() as own_conn:
            return dict_rows(own_conn.execute(sql, params).fetchall())
    return dict_rows(conn.execute(sql, params).fetchall())


def fetch_report_activities_for_dates(
    dates: Iterable[str],
    *,
    include_excluded: bool,
    conn=None,
) -> list[dict[str, Any]]:
    normalized = sorted({str(value) for value in dates if value})
    if not normalized:
        return []
    return fetch_report_activities_between(
        start_of_day(normalized[0]),
        end_of_day(normalized[-1]),
        include_excluded=include_excluded,
        conn=conn,
    )


def get_activity_structure_markers(
    dates: Iterable[str],
    *,
    conn=None,
) -> dict[str, str]:
    normalized = sorted({str(value) for value in dates if value})
    if not normalized:
        return {}
    placeholders = ",".join("?" for _ in normalized)
    sql = (
        "SELECT date, structure_marker FROM daily_report_marker "
        f"WHERE date IN ({placeholders})"
    )
    if conn is None:
        with get_connection() as own_conn:
            rows = own_conn.execute(sql, normalized).fetchall()
    else:
        rows = conn.execute(sql, normalized).fetchall()
    return {
        str(row["date"]): str(row["structure_marker"] or "")
        for row in rows
    }


__all__ = [
    "fetch_report_activities_between",
    "fetch_report_activities_for_dates",
    "get_activity_structure_markers",
]
