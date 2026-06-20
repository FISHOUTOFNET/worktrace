from __future__ import annotations

import ntpath
import re
import time

from ..constants import EXCLUDED_PROJECT, STATUS_NORMAL
from ..db import get_connection, get_db_path, now_str
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
_KEYWORD_RULE_CACHE_TTL_SECONDS = 5.0
_KEYWORD_RULE_CACHE: dict[str, tuple[float, list[dict]]] = {}


def invalidate_keyword_rule_cache() -> None:
    _KEYWORD_RULE_CACHE.pop(str(get_db_path().resolve()), None)


def _enabled_keyword_rules(conn=None) -> list[dict]:
    cache_key = str(get_db_path().resolve())
    now = time.monotonic()
    cached = _KEYWORD_RULE_CACHE.get(cache_key)
    if cached is not None and cached[0] >= now:
        return [dict(row) for row in cached[1]]
    if conn is None:
        with get_connection() as read_conn:
            rows = read_conn.execute(
                """
                SELECT pr.project_id, pr.pattern
                FROM project_rule pr
                JOIN project p ON p.id = pr.project_id
                WHERE pr.enabled = 1
                  AND pr.rule_type = 'keyword'
                  AND p.enabled = 1
                  AND p.name <> ?
                ORDER BY pr.created_at, pr.id
                """,
                (EXCLUDED_PROJECT,),
            ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT pr.project_id, pr.pattern
            FROM project_rule pr
            JOIN project p ON p.id = pr.project_id
            WHERE pr.enabled = 1
              AND pr.rule_type = 'keyword'
              AND p.enabled = 1
              AND p.name <> ?
            ORDER BY pr.created_at, pr.id
            """,
            (EXCLUDED_PROJECT,),
        ).fetchall()
    rules = [{"project_id": int(row["project_id"]), "pattern": (row["pattern"] or "").strip().casefold()} for row in rows]
    _KEYWORD_RULE_CACHE[cache_key] = (now + _KEYWORD_RULE_CACHE_TTL_SECONDS, rules)
    return [dict(row) for row in rules]


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
            _upsert_assignment(conn, activity_id, project_id, "manual", 100, True, None)
            _sync_activity_project(conn, activity_id, project_id, auto_classified=False)
            return _assignment_dict(conn, activity_id)

        if existing and existing["source"] == "midnight_anchor":
            project_id = existing["project_id"] if existing["project_id"] is not None else _get_uncategorized_project_id(conn)
            _sync_activity_project(conn, activity_id, project_id, auto_classified=True)
            return _assignment_dict(conn, activity_id)

        if activity["status"] != STATUS_NORMAL:
            project_id = _get_uncategorized_project_id(conn)
            _upsert_assignment(conn, activity_id, project_id, "uncategorized", 0, False, None)
            _sync_activity_project(conn, activity_id, project_id, auto_classified=False)
            return _assignment_dict(conn, activity_id)

        if resource["resource_role"] == "anchor":
            project_id, source, confidence, suggested_name = _infer_anchor_project(conn, dict(activity), resource)
        else:
            project_id = _get_uncategorized_project_id(conn)
            source = "uncategorized"
            confidence = 0
            suggested_name = None

        _upsert_assignment(conn, activity_id, project_id, source, confidence, False, suggested_name)
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


def _infer_anchor_project(conn, activity: dict, resource: dict) -> tuple[int, str, int, str | None]:
    if resource.get("default_project_id") and _project_can_auto_classify(conn, int(resource["default_project_id"])):
        return int(resource["default_project_id"]), "anchor_resource_default", 90, None

    if (
        resource.get("resource_role") == "anchor"
        and resource.get("resource_type") == "file"
        and (resource.get("full_path") or resource.get("parent_dir"))
    ):
        rule = folder_rule_service.find_matching_folder_rule(
            resource.get("full_path") or resource.get("parent_dir") or ""
        )
        if rule:
            return int(rule["project_id"]), "folder_rule", 85, None

    text = " ".join(
        [
            str(resource.get("display_name") or ""),
            str(resource.get("title_hint") or ""),
            str(activity.get("window_title") or ""),
        ]
    ).casefold()
    for row in _enabled_keyword_rules(conn):
        pattern = row["pattern"]
        if pattern and pattern in text:
            return int(row["project_id"]), "anchor_keyword", 80, None

    fallback_name = candidate_project_name_for_file_resource(resource)
    if fallback_name:
        return _get_uncategorized_project_id(conn), "suggested_project_name", 40, fallback_name

    return _get_uncategorized_project_id(conn), "uncategorized", 0, None


def _project_can_auto_classify(conn, project_id: int) -> bool:
    row = conn.execute(
        "SELECT name, enabled FROM project WHERE id = ?",
        (project_id,),
    ).fetchone()
    return bool(row and int(row["enabled"] or 0) and row["name"] != EXCLUDED_PROJECT)


def candidate_project_name_for_file_resource(resource: dict) -> str | None:
    if resource.get("resource_role") != "anchor" or resource.get("resource_type") != "file":
        return None
    parent_dir = str(resource.get("parent_dir") or "").strip()
    if not parent_dir:
        return None
    parent_name = ntpath.basename(parent_dir.rstrip("\\/")) if parent_dir else ""
    parent_candidate = _clean_project_candidate(parent_name)
    if parent_candidate and parent_candidate.casefold() not in GENERIC_FILE_PROJECT_NAMES:
        return parent_candidate
    return None


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


def _upsert_assignment(
    conn,
    activity_id: int,
    project_id: int,
    source: str,
    confidence: int,
    is_manual: bool,
    suggested_project_name: str | None,
) -> None:
    ts = now_str()
    row = conn.execute(
        """
        SELECT project_id, source, confidence, is_manual, suggested_project_name
        FROM activity_project_assignment
        WHERE activity_id = ?
        """,
        (activity_id,),
    ).fetchone()
    if row and (
        row["project_id"] == project_id
        and row["source"] == source
        and int(row["confidence"]) == confidence
        and int(row["is_manual"]) == int(is_manual)
        and (row["suggested_project_name"] or None) == (suggested_project_name or None)
    ):
        return
    conn.execute(
        """
        INSERT INTO activity_project_assignment(
            activity_id, project_id, confidence, source, is_manual, suggested_project_name, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(activity_id) DO UPDATE SET
            project_id = excluded.project_id,
            confidence = excluded.confidence,
            source = excluded.source,
            is_manual = excluded.is_manual,
            suggested_project_name = excluded.suggested_project_name,
            updated_at = excluded.updated_at
        """,
        (activity_id, project_id, confidence, source, int(is_manual), suggested_project_name, ts, ts),
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
        INSERT INTO project(name, description, is_archived, enabled, created_by, created_at, updated_at)
        VALUES (?, '', 0, 1, 'system', ?, ?)
        """,
        (UNCATEGORIZED_PROJECT, ts, ts),
    )
    return int(cur.lastrowid)
