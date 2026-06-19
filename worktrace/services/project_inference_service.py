from __future__ import annotations

import ntpath
import re

from ..constants import STATUS_NORMAL
from ..db import get_connection, now_str
from . import folder_rule_service
from .resource_service import ensure_activity_resource

GENERIC_FILE_PROJECT_NAMES = {
    "desktop",
    "downloads",
    "documents",
    "document",
    "wps cloud files",
    "my documents",
    "我的文档",
    "下载",
    "桌面",
    "文档",
}


def assign_project_for_activity(activity_id: int) -> dict:
    resource = ensure_activity_resource(activity_id)
    with get_connection() as conn:
        activity = conn.execute("SELECT * FROM activity_log WHERE id = ?", (activity_id,)).fetchone()
        if not activity:
            raise ValueError(f"activity not found: {activity_id}")

        existing = conn.execute(
            "SELECT * FROM activity_project_assignment WHERE activity_id = ?",
            (activity_id,),
        ).fetchone()
        if int(activity["manual_override"] or 0) or (existing and int(existing["is_manual"] or 0)):
            project_id = activity["project_id"] if activity["project_id"] is not None else existing["project_id"]
            if project_id is None:
                project_id = _get_uncategorized_project_id(conn)
            _upsert_assignment(conn, activity_id, project_id, "manual", 100, True)
            _sync_activity_project(conn, activity_id, project_id, auto_classified=False)
            return _assignment_dict(conn, activity_id)

        if activity["status"] != STATUS_NORMAL:
            project_id = _get_uncategorized_project_id(conn)
            _upsert_assignment(conn, activity_id, project_id, "uncategorized", 0, False)
            _sync_activity_project(conn, activity_id, project_id, auto_classified=False)
            return _assignment_dict(conn, activity_id)

        if resource["resource_role"] == "anchor":
            project_id, source, confidence = _infer_anchor_project(conn, dict(activity), resource)
        else:
            project_id = _get_uncategorized_project_id(conn)
            source = "uncategorized"
            confidence = 0

        _upsert_assignment(conn, activity_id, project_id, source, confidence, False)
        _sync_activity_project(
            conn,
            activity_id,
            project_id,
            auto_classified=source in {"anchor_resource_default", "anchor_keyword", "folder_rule"},
        )
        return _assignment_dict(conn, activity_id)


def backfill_missing_assignments() -> None:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id
            FROM activity_log
            WHERE is_deleted = 0
              AND NOT EXISTS (
                  SELECT 1 FROM activity_project_assignment apa
                  WHERE apa.activity_id = activity_log.id
              )
            ORDER BY id
            """
        ).fetchall()
    for row in rows:
        assign_project_for_activity(int(row["id"]))


def process_new_activity(activity_id: int) -> dict:
    return assign_project_for_activity(activity_id)


def _infer_anchor_project(conn, activity: dict, resource: dict) -> tuple[int, str, int]:
    if resource.get("default_project_id"):
        return int(resource["default_project_id"]), "anchor_resource_default", 90

    if (
        resource.get("resource_role") == "anchor"
        and resource.get("resource_type") == "file"
        and (resource.get("full_path") or resource.get("parent_dir"))
    ):
        rule = folder_rule_service.find_matching_folder_rule(
            resource.get("full_path") or resource.get("parent_dir") or ""
        )
        if rule:
            return int(rule["project_id"]), "folder_rule", 85

    text = " ".join(
        [
            str(resource.get("display_name") or ""),
            str(resource.get("title_hint") or ""),
            str(activity.get("window_title") or ""),
        ]
    ).casefold()
    rows = conn.execute(
        """
        SELECT project_id, pattern
        FROM project_rule
        WHERE enabled = 1 AND rule_type = 'keyword'
        ORDER BY created_at, id
        """
    ).fetchall()
    for row in rows:
        pattern = (row["pattern"] or "").strip().casefold()
        if pattern and pattern in text:
            return int(row["project_id"]), "anchor_keyword", 80

    fallback_name = candidate_project_name_for_file_resource(resource)
    if fallback_name:
        project_id = _get_or_create_project_in_conn(conn, fallback_name)
        conn.execute(
            """
            UPDATE resource
            SET default_project_id = ?, updated_at = ?
            WHERE id = ?
            """,
            (project_id, now_str(), resource["id"]),
        )
        return project_id, "anchor_resource_default", 70

    return _get_uncategorized_project_id(conn), "uncategorized", 0


def candidate_project_name_for_file_resource(resource: dict) -> str | None:
    if resource.get("resource_role") != "anchor" or resource.get("resource_type") != "file":
        return None
    parent_dir = str(resource.get("parent_dir") or "").strip()
    file_stem = str(resource.get("file_stem") or "").strip()
    parent_name = ntpath.basename(parent_dir.rstrip("\\/")) if parent_dir else ""
    parent_candidate = _clean_project_candidate(parent_name)
    file_candidate = _clean_project_candidate(file_stem)
    if parent_candidate and parent_candidate.casefold() not in GENERIC_FILE_PROJECT_NAMES:
        return parent_candidate
    return file_candidate


def _clean_project_candidate(value: str | None) -> str | None:
    cleaned = str(value or "").strip()
    if not cleaned:
        return None
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .-_")
    if len(cleaned) < 2:
        return None
    if cleaned.casefold() in {"untitled", "new file", "新建", "临时", "temp", "tmp"}:
        return None
    limit = 40 if any("\u4e00" <= ch <= "\u9fff" for ch in cleaned) else 80
    if len(cleaned) > limit:
        cleaned = cleaned[:limit].rstrip()
    return cleaned or None


def _get_or_create_project_in_conn(conn, name: str) -> int:
    row = conn.execute("SELECT id FROM project WHERE name = ?", (name,)).fetchone()
    if row:
        return int(row["id"])
    ts = now_str()
    cur = conn.execute(
        """
        INSERT INTO project(name, description, default_billable, is_archived, created_at, updated_at)
        VALUES (?, '', 1, 0, ?, ?)
        """,
        (name, ts, ts),
    )
    return int(cur.lastrowid)


def _upsert_assignment(conn, activity_id: int, project_id: int, source: str, confidence: int, is_manual: bool) -> None:
    ts = now_str()
    row = conn.execute(
        "SELECT project_id, source, confidence, is_manual FROM activity_project_assignment WHERE activity_id = ?",
        (activity_id,),
    ).fetchone()
    if row and (
        row["project_id"] == project_id
        and row["source"] == source
        and int(row["confidence"]) == confidence
        and int(row["is_manual"]) == int(is_manual)
    ):
        return
    conn.execute(
        """
        INSERT INTO activity_project_assignment(
            activity_id, project_id, confidence, source, is_manual, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(activity_id) DO UPDATE SET
            project_id = excluded.project_id,
            confidence = excluded.confidence,
            source = excluded.source,
            is_manual = excluded.is_manual,
            updated_at = excluded.updated_at
        """,
        (activity_id, project_id, confidence, source, int(is_manual), ts, ts),
    )


def _sync_activity_project(conn, activity_id: int, project_id: int, auto_classified: bool) -> None:
    row = conn.execute(
        "SELECT project_id, auto_classified FROM activity_log WHERE id = ?",
        (activity_id,),
    ).fetchone()
    if row and row["project_id"] == project_id and int(row["auto_classified"] or 0) == int(auto_classified):
        return
    conn.execute(
        """
        UPDATE activity_log
        SET project_id = ?, auto_classified = ?, updated_at = ?
        WHERE id = ?
        """,
        (project_id, int(auto_classified), now_str(), activity_id),
    )


def _assignment_dict(conn, activity_id: int) -> dict:
    row = conn.execute(
        "SELECT * FROM activity_project_assignment WHERE activity_id = ?",
        (activity_id,),
    ).fetchone()
    return dict(row) if row else {}


def _get_uncategorized_project_id(conn) -> int:
    from ..constants import UNCATEGORIZED_PROJECT

    row = conn.execute("SELECT id FROM project WHERE name = ?", (UNCATEGORIZED_PROJECT,)).fetchone()
    if row:
        return int(row["id"])
    ts = now_str()
    cur = conn.execute(
        """
        INSERT INTO project(name, description, default_billable, is_archived, created_at, updated_at)
        VALUES (?, '', 1, 0, ?, ?)
        """,
        (UNCATEGORIZED_PROJECT, ts, ts),
    )
    return int(cur.lastrowid)
