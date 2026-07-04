from __future__ import annotations

from typing import Any

from worktrace.db import dict_rows, get_connection


def fetch_one(sql: str, params: tuple[Any, ...] = ()) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(sql, params).fetchone()
    return dict(row) if row else None


def fetch_all(sql: str, params: tuple[Any, ...] = ()) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(sql, params).fetchall()
    return dict_rows(rows)


def scalar(sql: str, params: tuple[Any, ...] = ()) -> Any:
    with get_connection() as conn:
        row = conn.execute(sql, params).fetchone()
    if row is None:
        return None
    return row[0]


def table_count(table_name: str) -> int:
    if not table_name.replace("_", "").isalnum():
        raise ValueError("invalid table name")
    return int(scalar(f"SELECT COUNT(*) FROM {table_name}") or 0)


def activity_row(activity_id: int) -> dict | None:
    return fetch_one("SELECT * FROM activity_log WHERE id = ?", (activity_id,))


def assignment_row(activity_id: int) -> dict | None:
    return fetch_one(
        "SELECT project_id, confidence, source, is_manual "
        "FROM activity_project_assignment WHERE activity_id = ?",
        (activity_id,),
    )


def resource_row(activity_id: int) -> dict | None:
    return fetch_one(
        "SELECT resource_kind, display_name, identity_key, path_hint "
        "FROM activity_resource WHERE activity_id = ?",
        (activity_id,),
    )
