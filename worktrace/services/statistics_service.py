from __future__ import annotations

from ..constants import STATUS_EXCLUDED, STATUS_IDLE, STATUS_NORMAL, STATUS_PAUSED
from ..db import dict_rows, get_connection
from .project_service import get_or_create_uncategorized_project


def _range_bounds(start_date: str, end_date: str) -> tuple[str, str]:
    return f"{start_date} 00:00:00", f"{end_date} 23:59:59"


def _sum_duration(where: str, params: tuple = ()) -> int:
    with get_connection() as conn:
        row = conn.execute(
            f"SELECT COALESCE(SUM(duration_seconds), 0) AS total FROM activity_log WHERE {where}",
            params,
        ).fetchone()
    return int(row["total"] or 0)


def get_summary(start_date: str, end_date: str) -> dict:
    start, end = _range_bounds(start_date, end_date)
    base = "is_deleted = 0 AND is_hidden = 0 AND start_time BETWEEN ? AND ?"
    params = (start, end)
    total = _sum_duration(base, params)
    effective = _sum_duration(base + " AND status = ?", params + (STATUS_NORMAL,))
    idle = _sum_duration(base + " AND status = ?", params + (STATUS_IDLE,))
    paused = _sum_duration(base + " AND status = ?", params + (STATUS_PAUSED,))
    excluded = _sum_duration(base + " AND status = ?", params + (STATUS_EXCLUDED,))
    unconfirmed = _sum_duration(base + " AND is_confirmed = 0", params)
    uncategorized = get_uncategorized_duration(start_date, end_date)
    return {
        "total_duration": total,
        "effective_duration": effective,
        "idle_duration": idle,
        "paused_duration": paused,
        "excluded_duration": excluded,
        "uncategorized_duration": uncategorized,
        "unconfirmed_duration": unconfirmed,
        "unconfirmed_count": get_unconfirmed_count(start_date, end_date),
    }


def get_project_stats(start_date: str, end_date: str) -> list[dict]:
    start, end = _range_bounds(start_date, end_date)
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT
                COALESCE(p.name, '未归类') AS project,
                COALESCE(SUM(a.duration_seconds), 0) AS total_duration,
                COALESCE(SUM(CASE WHEN a.is_billable = 1 THEN a.duration_seconds ELSE 0 END), 0) AS billable_duration,
                COALESCE(SUM(CASE WHEN a.is_billable = 0 THEN a.duration_seconds ELSE 0 END), 0) AS non_billable_duration,
                COALESCE(SUM(CASE WHEN a.is_confirmed = 1 THEN a.duration_seconds ELSE 0 END), 0) AS confirmed_duration,
                COALESCE(SUM(CASE WHEN a.is_confirmed = 0 THEN a.duration_seconds ELSE 0 END), 0) AS unconfirmed_duration,
                COUNT(*) AS record_count
            FROM activity_log a
            LEFT JOIN project p ON p.id = a.project_id
            WHERE a.is_deleted = 0
              AND a.is_hidden = 0
              AND a.status = 'normal'
              AND a.start_time BETWEEN ? AND ?
            GROUP BY a.project_id, p.name
            ORDER BY total_duration DESC
            """,
            (start, end),
        ).fetchall()
    return dict_rows(rows)


def get_unconfirmed_count(start_date: str, end_date: str) -> int:
    start, end = _range_bounds(start_date, end_date)
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM activity_log
            WHERE is_deleted = 0 AND is_hidden = 0 AND is_confirmed = 0
              AND start_time BETWEEN ? AND ?
            """,
            (start, end),
        ).fetchone()
    return int(row["count"] or 0)


def get_uncategorized_duration(start_date: str, end_date: str) -> int:
    start, end = _range_bounds(start_date, end_date)
    uncategorized = get_or_create_uncategorized_project()
    return _sum_duration(
        "is_deleted = 0 AND is_hidden = 0 AND status = ? AND project_id = ? AND start_time BETWEEN ? AND ?",
        (STATUS_NORMAL, uncategorized, start, end),
    )
