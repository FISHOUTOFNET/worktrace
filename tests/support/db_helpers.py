from __future__ import annotations

from typing import Any

from worktrace.db import dict_rows, get_connection, now_str


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
    row = fetch_one("SELECT * FROM activity_log WHERE id = ?", (activity_id,))
    assignment = assignment_row(activity_id)
    if row and assignment:
        row["project_id"] = assignment.get("project_id")
        row["manual_override"] = int(assignment.get("is_manual") or 0)
        row["auto_classified"] = 1 if assignment.get("source") in {"keyword_rule", "folder_rule"} else 0
    return row


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


def assign_activity_project(activity_id: int, project_id: int, *, manual: bool = True) -> None:
    ts = now_str()
    source = "manual" if manual else "anchor_context"
    confidence = 100 if manual else 60
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO activity_project_assignment(
                activity_id, project_id, confidence, source, is_manual,
                suggested_project_name, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, NULL, ?, ?)
            ON CONFLICT(activity_id) DO UPDATE SET
                project_id = excluded.project_id,
                confidence = excluded.confidence,
                source = excluded.source,
                is_manual = excluded.is_manual,
                suggested_project_name = excluded.suggested_project_name,
                updated_at = excluded.updated_at
            """,
            (activity_id, project_id, confidence, source, int(manual), ts, ts),
        )


def set_activity_note(activity_id: int, note: str) -> None:
    return None
