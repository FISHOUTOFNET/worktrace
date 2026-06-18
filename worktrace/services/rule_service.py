from __future__ import annotations

from ..db import dict_rows, get_connection, now_str
from .activity_service import get_activity


def create_rule(keyword: str, project_id: int) -> int:
    keyword = keyword.strip()
    if not keyword:
        raise ValueError("keyword is required")
    ts = now_str()
    with get_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO rule(keyword, project_id, enabled, created_at, updated_at)
            VALUES (?, ?, 1, ?, ?)
            """,
            (keyword, project_id, ts, ts),
        )
        return int(cur.lastrowid)


def list_rules() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT r.*, p.name AS project_name
            FROM rule r
            LEFT JOIN project p ON p.id = r.project_id
            ORDER BY r.created_at, r.id
            """
        ).fetchall()
    return dict_rows(rows)


def _matching_project_id(activity: dict) -> int | None:
    text = " ".join(
        [
            activity.get("window_title") or "",
            activity.get("app_name") or "",
            activity.get("process_name") or "",
        ]
    ).lower()
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM rule WHERE enabled = 1 ORDER BY created_at, id"
        ).fetchall()
    for row in rows:
        if row["keyword"].lower() in text:
            return int(row["project_id"])
    return None


def apply_rules_to_activity(activity_id: int) -> None:
    activity = get_activity(activity_id)
    if not activity or int(activity.get("manual_override") or 0):
        return
    project_id = _matching_project_id(activity)
    if project_id is None:
        return
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE activity_log
            SET project_id = ?, auto_classified = 1, updated_at = ?
            WHERE id = ? AND manual_override = 0
            """,
            (project_id, now_str(), activity_id),
        )


def apply_rules_to_unclassified() -> None:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id FROM activity_log WHERE manual_override = 0 AND is_deleted = 0"
        ).fetchall()
    for row in rows:
        apply_rules_to_activity(int(row["id"]))
