from __future__ import annotations

from ..db import dict_rows, get_connection, now_str


def record_boundary(occurred_at: str | None = None, reason: str = "unknown") -> None:
    ts = now_str()
    at = occurred_at or ts
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO session_boundary(occurred_at, reason, created_at)
            VALUES (?, ?, ?)
            """,
            (at, reason, ts),
        )


def latest_boundary_time() -> str | None:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT occurred_at
            FROM session_boundary
            ORDER BY occurred_at DESC, id DESC
            LIMIT 1
            """
        ).fetchone()
    return str(row["occurred_at"]) if row else None


def list_boundaries(start_time: str, end_time: str) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM session_boundary
            WHERE occurred_at >= ? AND occurred_at <= ?
            ORDER BY occurred_at ASC, id ASC
            """,
            (start_time, end_time),
        ).fetchall()
    return dict_rows(rows)


def has_boundary_between(start_time: str, end_time: str) -> bool:
    if not start_time or not end_time or start_time > end_time:
        return False
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT 1
            FROM session_boundary
            WHERE occurred_at >= ? AND occurred_at <= ?
            LIMIT 1
            """,
            (start_time, end_time),
        ).fetchone()
    return row is not None
