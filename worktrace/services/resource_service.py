from __future__ import annotations

from ..db import dict_rows, get_connection, now_str
from ..resource_patterns import infer_resource_identity


def infer_or_create_resource(activity: dict) -> dict:
    identity = infer_resource_identity(
        activity.get("app_name"),
        activity.get("process_name"),
        activity.get("window_title"),
        activity.get("file_path_hint"),
    )
    ts = now_str()
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM resource WHERE canonical_key = ?",
            (identity.canonical_key,),
        ).fetchone()
        if row:
            conn.execute(
                """
                UPDATE resource
                SET display_name = ?,
                    app_name = COALESCE(?, app_name),
                    process_name = COALESCE(?, process_name),
                    title_hint = COALESCE(?, title_hint),
                    full_path = COALESCE(?, full_path),
                    parent_dir = COALESCE(?, parent_dir),
                    file_stem = COALESCE(?, file_stem),
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    identity.display_name,
                    identity.app_name,
                    identity.process_name,
                    identity.title_hint,
                    identity.full_path,
                    identity.parent_dir,
                    identity.file_stem,
                    ts,
                    int(row["id"]),
                ),
            )
            row = conn.execute("SELECT * FROM resource WHERE id = ?", (row["id"],)).fetchone()
            return dict(row)
        cur = conn.execute(
            """
            INSERT INTO resource(
                resource_role, resource_type, display_name, canonical_key,
                app_name, process_name, title_hint, full_path, parent_dir, file_stem,
                default_project_id, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)
            """,
            (
                identity.resource_role,
                identity.resource_type,
                identity.display_name,
                identity.canonical_key,
                identity.app_name,
                identity.process_name,
                identity.title_hint,
                identity.full_path,
                identity.parent_dir,
                identity.file_stem,
                ts,
                ts,
            ),
        )
        row = conn.execute("SELECT * FROM resource WHERE id = ?", (cur.lastrowid,)).fetchone()
    return dict(row)


def refresh_activity_resource(activity_id: int) -> dict:
    with get_connection() as conn:
        activity = conn.execute("SELECT * FROM activity_log WHERE id = ?", (activity_id,)).fetchone()
        if not activity:
            raise ValueError(f"activity not found: {activity_id}")
    resource = infer_or_create_resource(dict(activity))
    with get_connection() as conn:
        conn.execute(
            "UPDATE activity_log SET resource_id = ?, updated_at = ? WHERE id = ?",
            (resource["id"], now_str(), activity_id),
        )
    return resource


def ensure_activity_resource(activity_id: int) -> dict:
    with get_connection() as conn:
        activity = conn.execute("SELECT * FROM activity_log WHERE id = ?", (activity_id,)).fetchone()
        if not activity:
            raise ValueError(f"activity not found: {activity_id}")
        if activity["resource_id"]:
            row = conn.execute("SELECT * FROM resource WHERE id = ?", (activity["resource_id"],)).fetchone()
            if row:
                return dict(row)

    return refresh_activity_resource(activity_id)


def backfill_missing_resources() -> None:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id FROM activity_log WHERE resource_id IS NULL ORDER BY id"
        ).fetchall()
    for row in rows:
        ensure_activity_resource(int(row["id"]))


def is_anchor_resource(resource: dict) -> bool:
    return resource.get("resource_role") == "anchor"


def is_auxiliary_resource(resource: dict) -> bool:
    return resource.get("resource_role") == "auxiliary"


def get_resource(resource_id: int) -> dict | None:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM resource WHERE id = ?", (resource_id,)).fetchone()
    return dict(row) if row else None


def list_resources() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM resource ORDER BY display_name COLLATE NOCASE").fetchall()
    return dict_rows(rows)
