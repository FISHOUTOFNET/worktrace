from __future__ import annotations

from ..db import dict_rows, get_connection, now_str
from .session_boundary_policy import validate_hard_boundary_reason


def record_boundary(occurred_at: str | None = None, reason: str = "unknown") -> None:
    """Low-level test/data-repair helper.

    Production runtime paths must call ``record_hard_boundary`` so hard
    boundary reasons stay whitelisted and collector health cannot masquerade
    as a session boundary.
    """
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


def record_hard_boundary(occurred_at: str | None = None, reason: str = "unknown") -> None:
    record_boundary(occurred_at, validate_hard_boundary_reason(reason))


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


def list_boundaries(start_time: str, end_time: str, *, conn=None) -> list[dict]:
    if conn is not None:
        rows = conn.execute(
            """SELECT * FROM session_boundary WHERE occurred_at >= ? AND occurred_at <= ? ORDER BY occurred_at ASC, id ASC""",
            (start_time, end_time),
        ).fetchall()
        return dict_rows(rows)
    with get_connection() as read_conn:
        rows = read_conn.execute(
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
