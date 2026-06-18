from __future__ import annotations

from ..db import dict_rows, get_connection, now_str
from ..path_utils import (
    is_path_under_folder,
    looks_like_anchor_file_path,
    normalize_folder_key,
    normalize_path_key,
)


def create_or_update_folder_rule(folder_path: str, project_id: int, recursive: bool = True) -> int:
    folder = (folder_path or "").strip()
    if not folder:
        raise ValueError("folder path is required")
    key = normalize_folder_key(folder)
    if not key:
        raise ValueError("folder path is required")
    ts = now_str()
    with get_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO folder_project_rule(
                folder_path, normalized_folder_key, project_id, recursive, enabled, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, 1, ?, ?)
            ON CONFLICT(normalized_folder_key) DO UPDATE SET
                folder_path = excluded.folder_path,
                project_id = excluded.project_id,
                recursive = excluded.recursive,
                enabled = 1,
                updated_at = excluded.updated_at
            """,
            (folder, key, project_id, int(recursive), ts, ts),
        )
        row = conn.execute(
            "SELECT id FROM folder_project_rule WHERE normalized_folder_key = ?",
            (key,),
        ).fetchone()
    return int(row["id"] if row else cur.lastrowid)


def delete_folder_rule(rule_id: int) -> None:
    with get_connection() as conn:
        conn.execute("DELETE FROM folder_project_rule WHERE id = ?", (rule_id,))


def set_folder_rule_enabled(rule_id: int, enabled: bool) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE folder_project_rule SET enabled = ?, updated_at = ? WHERE id = ?",
            (int(enabled), now_str(), rule_id),
        )


def list_folder_rules() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT fpr.*, p.name AS project_name
            FROM folder_project_rule fpr
            LEFT JOIN project p ON p.id = fpr.project_id
            ORDER BY fpr.folder_path COLLATE NOCASE, fpr.id
            """
        ).fetchall()
    return dict_rows(rows)


def find_matching_folder_rule(path_or_parent_dir: str) -> dict | None:
    target = (path_or_parent_dir or "").strip()
    if not target:
        return None
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT fpr.*, p.name AS project_name
            FROM folder_project_rule fpr
            LEFT JOIN project p ON p.id = fpr.project_id
            WHERE fpr.enabled = 1
            """
        ).fetchall()
    matches = [dict(row) for row in rows if _target_matches_rule(target, dict(row))]
    if not matches:
        return None
    return max(matches, key=lambda row: len(row["normalized_folder_key"] or ""))


def preview_folder_rule_conflicts(folder_path: str, project_id: int) -> dict:
    folder = (folder_path or "").strip()
    with get_connection() as conn:
        activity_rows = dict_rows(conn.execute(
            """
            SELECT
                a.id,
                a.manual_override,
                a.is_confirmed,
                COALESCE(apa.project_id, a.project_id) AS effective_project_id,
                COALESCE(apa.is_manual, 0) AS is_manual,
                r.full_path,
                r.parent_dir
            FROM activity_log a
            JOIN resource r ON r.id = a.resource_id
            LEFT JOIN activity_project_assignment apa ON apa.activity_id = a.id
            WHERE a.is_deleted = 0
              AND r.resource_role = 'anchor'
              AND r.resource_type = 'file'
            """
        ).fetchall())

        rules = dict_rows(conn.execute("SELECT * FROM folder_project_rule").fetchall())
        resources = dict_rows(
            conn.execute(
                """
                SELECT id, default_project_id, full_path, parent_dir
                FROM resource
                WHERE resource_role = 'anchor' AND resource_type = 'file'
                """
            ).fetchall()
        )
    child_count = sum(
        1
        for rule in rules
        if int(rule["project_id"]) != int(project_id)
        and is_path_under_folder(rule["folder_path"], folder, recursive=True)
    )
    file_default_count = sum(
        1
        for resource in resources
        if resource.get("default_project_id")
        and int(resource["default_project_id"]) != int(project_id)
        and _resource_matches_folder(resource, folder)
    )
    matching_activities = [
        row for row in activity_rows if _resource_matches_folder(row, folder)
    ]
    return {
        "child_folder_rule_conflicts": child_count,
        "file_default_project_conflicts": file_default_count,
        "other_project_activity_count": sum(
            1
            for row in matching_activities
            if row.get("effective_project_id") is not None
            and int(row["effective_project_id"]) != int(project_id)
        ),
        "manual_or_confirmed_activity_count": sum(
            1
            for row in matching_activities
            if int(row.get("manual_override") or 0)
            or int(row.get("is_confirmed") or 0)
            or int(row.get("is_manual") or 0)
        ),
    }


def backfill_folder_rule(rule_id: int, mode: str = "safe") -> dict:
    if mode != "safe":
        raise ValueError("only safe backfill is supported")
    with get_connection() as conn:
        rule = conn.execute("SELECT * FROM folder_project_rule WHERE id = ?", (rule_id,)).fetchone()
        if not rule:
            raise ValueError(f"folder rule not found: {rule_id}")
        rows = conn.execute(
            """
            SELECT a.id
            FROM activity_log a
            JOIN resource r ON r.id = a.resource_id
            LEFT JOIN activity_project_assignment apa ON apa.activity_id = a.id
            WHERE a.is_deleted = 0
              AND a.manual_override = 0
              AND a.is_confirmed = 0
              AND COALESCE(apa.is_manual, 0) = 0
              AND r.resource_role = 'anchor'
              AND r.resource_type = 'file'
            """
        ).fetchall()
        activity_ids = []
        for row in rows:
            resource = conn.execute(
                """
                SELECT full_path, parent_dir
                FROM resource
                WHERE id = (SELECT resource_id FROM activity_log WHERE id = ?)
                """,
                (row["id"],),
            ).fetchone()
            if resource and _resource_matches_folder(dict(resource), rule["folder_path"], bool(rule["recursive"])):
                activity_ids.append(int(row["id"]))

        ts = now_str()
        for activity_id in activity_ids:
            conn.execute(
                """
                UPDATE activity_log
                SET project_id = ?, auto_classified = 1, updated_at = ?
                WHERE id = ?
                """,
                (rule["project_id"], ts, activity_id),
            )
            conn.execute(
                """
                INSERT INTO activity_project_assignment(
                    activity_id, project_id, confidence, source, is_manual, created_at, updated_at
                )
                VALUES (?, ?, 85, 'folder_rule', 0, ?, ?)
                ON CONFLICT(activity_id) DO UPDATE SET
                    project_id = excluded.project_id,
                    confidence = excluded.confidence,
                    source = excluded.source,
                    is_manual = excluded.is_manual,
                    updated_at = excluded.updated_at
                """,
                (activity_id, rule["project_id"], ts, ts),
            )
    return {"updated_activity_count": len(activity_ids), "mode": mode}


def _resource_matches_folder(resource: dict, folder_path: str, recursive: bool = True) -> bool:
    full_path = resource.get("full_path") or ""
    parent_dir = resource.get("parent_dir") or ""
    if full_path:
        return is_path_under_folder(full_path, folder_path, recursive)
    if not parent_dir:
        return False
    if normalize_folder_key(parent_dir) == normalize_folder_key(folder_path):
        return True
    return bool(recursive and is_path_under_folder(parent_dir, folder_path, True))


def _target_matches_rule(target: str, rule: dict) -> bool:
    folder_path = rule["folder_path"]
    recursive = bool(rule["recursive"])
    if normalize_path_key(target) == normalize_folder_key(folder_path):
        return True
    if looks_like_anchor_file_path(target):
        return is_path_under_folder(target, folder_path, recursive)
    return bool(recursive and is_path_under_folder(target, folder_path, True))
