from __future__ import annotations

import ntpath
import re
import time
from dataclasses import dataclass

from ..constants import EXCLUDED_PROJECT, RULE_CACHE_TTL_SECONDS, STATUS_NORMAL, UNCATEGORIZED_PROJECT
from ..db import get_connection, get_db_path, now_str
from ..path_utils import has_auto_project_extension, looks_like_local_file_path
from . import clipboard_service, folder_index_service, folder_rule_service

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
_KEYWORD_RULE_CACHE_TTL_SECONDS = RULE_CACHE_TTL_SECONDS
_KEYWORD_RULE_CACHE: dict[str, tuple[float, list[dict]]] = {}


@dataclass(frozen=True)
class ProjectAssignmentDecision:
    """The complete, persistable result of automatic project inference."""

    project_id: int
    source: str
    confidence: int
    suggested_project_name: str | None = None
    source_rule_type: str | None = None
    source_rule_id: int | None = None


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
                SELECT pr.id, pr.project_id, pr.pattern
                FROM project_rule pr
                JOIN project p ON p.id = pr.project_id
                WHERE pr.enabled = 1
                  AND pr.rule_type = 'keyword'
                  AND pr.created_by = 'user'
                  AND p.enabled = 1
                  AND p.is_archived = 0
                  AND p.name <> ?
                ORDER BY pr.created_at, pr.id
                """,
                (EXCLUDED_PROJECT,),
            ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT pr.id, pr.project_id, pr.pattern
            FROM project_rule pr
            JOIN project p ON p.id = pr.project_id
            WHERE pr.enabled = 1
              AND pr.rule_type = 'keyword'
              AND pr.created_by = 'user'
              AND p.enabled = 1
              AND p.is_archived = 0
              AND p.name <> ?
            ORDER BY pr.created_at, pr.id
            """,
            (EXCLUDED_PROJECT,),
        ).fetchall()
    rules = [{"id": int(row["id"]), "project_id": int(row["project_id"]), "pattern": (row["pattern"] or "").strip().casefold()} for row in rows]
    _KEYWORD_RULE_CACHE[cache_key] = (now + _KEYWORD_RULE_CACHE_TTL_SECONDS, rules)
    return [dict(row) for row in rules]


def assign_project_for_activity(activity_id: int) -> dict:
    with get_connection() as conn:
        activity = conn.execute("SELECT * FROM activity_log WHERE id = ?", (activity_id,)).fetchone()
        if not activity:
            raise ValueError(f"activity not found: {activity_id}")
        activity_dict = dict(activity)

        existing = conn.execute(
            "SELECT * FROM activity_project_assignment WHERE activity_id = ?",
            (activity_id,),
        ).fetchone()
        if existing and int(existing["is_manual"] or 0):
            project_id = existing["project_id"] if existing["project_id"] is not None else _get_uncategorized_project_id(conn)
            return _assignment_dict(conn, activity_id)

        if existing and existing["source"] == "midnight_anchor":
            return _assignment_dict(conn, activity_id)

        if activity["status"] != STATUS_NORMAL:
            project_id = _get_uncategorized_project_id(conn)
            _upsert_assignment(conn, activity_id, project_id, "uncategorized", 0, False, None)
            return _assignment_dict(conn, activity_id)

        resource = _resource_for_activity(conn, activity_id, activity_dict)
        decision = _infer_project_resource_first(conn, activity_dict, resource)

        _upsert_assignment(
            conn, activity_id, decision.project_id, decision.source,
            decision.confidence, False, decision.suggested_project_name,
            decision.source_rule_type, decision.source_rule_id,
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
    """Automatic-rules entry point called by ``finalize_created_activity``.

    Applies skip guards for hidden / deleted / in-progress activities
    before delegating to ``assign_project_for_activity``, so the
    automatic-rules contract only touches closed, visible, non-deleted
    activities. The general ``assign_project_for_activity`` function
    still handles manual reclassification, rule application, and backfill
    when explicitly requested by the caller.
    """
    with get_connection() as conn:
        activity = conn.execute(
            "SELECT is_hidden, is_deleted, end_time FROM activity_log WHERE id = ?",
            (activity_id,),
        ).fetchone()
        if not activity:
            raise ValueError(f"activity not found: {activity_id}")
        if int(activity["is_hidden"] or 0) or int(activity["is_deleted"] or 0):
            return _assignment_dict(conn, activity_id)
        if activity["end_time"] is None:
            return _assignment_dict(conn, activity_id)
    return assign_project_for_activity(activity_id)


# Sources marking the open row as still uncategorized (eligible for
# re-inference). Concrete automatic sources (folder_rule / keyword_rule /
# midnight_anchor) and manual sources are excluded so open-row sync doesn't
# flap an already-concrete assignment mid-activity.
_OPEN_ROW_UNCLASSIFIED_SOURCES = {"uncategorized", "suggested_project_name"}


def sync_persisted_open_activity_project(activity_id: int) -> dict:
    """Converge an open persisted row's project assignment before display.

    Purpose: ensure an open persisted row's project attribution matches the
    current resource-first inference before it is displayed.

    Conditions (all must hold; otherwise the helper is a no-op): the
    activity exists, ``end_time IS NULL``, ``status == STATUS_NORMAL``,
    ``is_deleted = 0``, ``is_hidden = 0``, the
    assignment is not manual, and the current assignment source is still
    effectively uncategorized.

    Behavior: delegates to the existing resource-first inference
    (``assign_project_for_activity``). It does NOT re-implement folder /
    keyword / suggested-project logic and does NOT create projects.

    Returns the current or updated assignment dict; ``{}`` when the
    activity is missing.
    """
    with get_connection() as conn:
        activity = conn.execute(
            """
            SELECT is_hidden, is_deleted, end_time, status
            FROM activity_log
            WHERE id = ?
            """,
            (activity_id,),
        ).fetchone()
        if not activity:
            return {}
        if int(activity["is_hidden"] or 0) or int(activity["is_deleted"] or 0):
            return _assignment_dict(conn, activity_id)
        if activity["end_time"] is not None:
            return _assignment_dict(conn, activity_id)
        if activity["status"] != STATUS_NORMAL:
            return _assignment_dict(conn, activity_id)
        existing = conn.execute(
            "SELECT source, is_manual FROM activity_project_assignment WHERE activity_id = ?",
            (activity_id,),
        ).fetchone()
        if existing and int(existing["is_manual"] or 0):
            return _assignment_dict(conn, activity_id)
        source = str(existing["source"] or "") if existing else ""
        if source and source not in _OPEN_ROW_UNCLASSIFIED_SOURCES:
            return _assignment_dict(conn, activity_id)
    return assign_project_for_activity(activity_id)


# Resource-first inference

def _resource_for_activity(conn, activity_id: int, activity: dict) -> dict:
    """Return resource dict for activity, preferring activity_resource table."""
    row = conn.execute(
        "SELECT * FROM activity_resource WHERE activity_id = ?",
        (activity_id,),
    ).fetchone()
    if row:
        return dict(row)
    from ..resources.resource_identity import infer_resource_for_activity
    resource = infer_resource_for_activity(activity)
    return {
        "resource_kind": resource.resource_kind,
        "resource_subtype": resource.resource_subtype,
        "display_name": resource.display_name,
        "identity_key": resource.identity_key,
        "is_anchor": int(resource.is_anchor),
        "app_name": resource.app_name,
        "process_name": resource.process_name,
        "window_title": resource.window_title,
        "path_hint": resource.path_hint,
        "uri_host": resource.uri_host,
    }


def _safe_classification_text(activity: dict, resource: dict, clipboard_text: str = "") -> str:
    """Build safe text for keyword matching from resource and activity fields."""
    parts = [
        str(resource.get("display_name") or ""),
        str(resource.get("resource_kind") or ""),
        str(resource.get("resource_subtype") or ""),
        str(resource.get("app_name") or ""),
        str(resource.get("process_name") or ""),
        str(resource.get("window_title") or ""),
        str(resource.get("path_hint") or ""),
        str(resource.get("uri_host") or ""),
        str(activity.get("window_title") or ""),
        str(activity.get("file_path_hint") or ""),
        clipboard_text,
    ]
    return " ".join(parts).casefold()


def keyword_pattern_matches(
    pattern_casefold: str,
    activity: dict,
    resource: dict,
    clipboard_text: str = "",
) -> bool:
    """Return True if a casefolded keyword pattern matches the activity's
    safe classification text via substring containment.

    Reuses ``_safe_classification_text`` so there is a single keyword
    text-building code path shared with ``_infer_project_resource_first``.
    ``_infer_project_resource_first`` instead of a second divergent matcher.
    The built text may include clipboard content and must NEVER be returned
    to an API / bridge / frontend payload — callers only use the boolean
    result. ``pattern_casefold`` must already be casefolded and stripped by
    the caller (matching how ``_enabled_keyword_rules`` normalizes patterns).
    """
    if not pattern_casefold:
        return False
    text = _safe_classification_text(activity, resource, clipboard_text)
    return pattern_casefold in text


def candidate_project_name_for_resource(resource: dict) -> str | None:
    """Generate a candidate project name from a resource dict."""
    is_anchor = bool(resource.get("is_anchor"))
    path_hint = str(resource.get("path_hint") or "").strip()
    resource_kind = str(resource.get("resource_kind") or "")
    resource_subtype = str(resource.get("resource_subtype") or "")

    if not is_anchor:
        return None

    # For browser/email, don't auto-generate parent folder suggestions
    if resource_kind in ("browser_tab", "email"):
        return None

    if path_hint:
        parent_dir = ntpath.dirname(path_hint.rstrip("\\/"))
        if parent_dir:
            # For anchor file extensions, always suggest parent folder
            if has_auto_project_extension(path_hint):
                parent_name = ntpath.basename(parent_dir.rstrip("\\/"))
                parent_candidate = _clean_project_candidate(parent_name)
                if parent_candidate and parent_candidate.casefold() not in GENERIC_FILE_PROJECT_NAMES:
                    return parent_candidate
            # For IDE code files, suggest parent folder even if not in ANCHOR_FILE_EXTENSIONS
            if resource_kind == "ide_file" and resource_subtype == "code_file":
                parent_name = ntpath.basename(parent_dir.rstrip("\\/"))
                parent_candidate = _clean_project_candidate(parent_name)
                if parent_candidate and parent_candidate.casefold() not in GENERIC_FILE_PROJECT_NAMES:
                    return parent_candidate

    # For IDE workspace (no code file), use workspace name as project name
    if resource_kind == "ide_file" and resource_subtype == "ide_workspace":
        display = str(resource.get("display_name") or "")
        if display:
            candidate = _clean_project_candidate(display)
            if candidate:
                return candidate

    return None


def _infer_project_resource_first(
    conn,
    activity: dict,
    resource: dict,
    *,
    exclude_rule: tuple[str, int] | None = None,
) -> ProjectAssignmentDecision:
    """Infer project using resource-first priority."""
    path_hint = str(resource.get("path_hint") or "").strip()
    is_anchor = bool(resource.get("is_anchor"))
    display_name = str(resource.get("display_name") or "")

    # 3. folder/file rule for local path
    if path_hint:
        excluded_folder_id = exclude_rule[1] if exclude_rule and exclude_rule[0] == "folder" else None
        rule = folder_rule_service.find_matching_folder_rule(path_hint, exclude_rule_id=excluded_folder_id)
        if rule:
            return ProjectAssignmentDecision(int(rule["project_id"]), "folder_rule", 85, source_rule_type="folder", source_rule_id=int(rule["id"]))
        # Also try parent directory
        parent_dir = ntpath.dirname(path_hint.rstrip("\\/"))
        if parent_dir:
            rule = folder_rule_service.find_matching_folder_rule(parent_dir, exclude_rule_id=excluded_folder_id)
            if rule:
                return ProjectAssignmentDecision(int(rule["project_id"]), "folder_rule", 85, source_rule_type="folder", source_rule_id=int(rule["id"]))

    # If no path_hint but anchor file with display_name, try folder index
    if not path_hint and is_anchor and display_name:
        rule = folder_index_service.find_matching_folder_rule_for_file_name(
            display_name,
            str(activity.get("start_time") or "") or None,
        )
        if rule and exclude_rule != ("folder", int(rule["id"])):
            return ProjectAssignmentDecision(int(rule["project_id"]), "folder_rule", 85, source_rule_type="folder", source_rule_id=int(rule["id"]))


    # 5. keyword rule against safe classification text
    clipboard_text = ""
    activity_id = activity.get("id")
    if activity_id:
        clipboard_text = clipboard_service.clipboard_text_for_activity(conn, int(activity_id))
    text = _safe_classification_text(activity, resource, clipboard_text)
    for row in _enabled_keyword_rules(conn):
        pattern = row["pattern"]
        if pattern and pattern in text and exclude_rule != ("keyword", int(row["id"])):
            return ProjectAssignmentDecision(int(row["project_id"]), "keyword_rule", 80, source_rule_type="keyword", source_rule_id=int(row["id"]))

    # 6. suggested project name from parent folder/workspace
    if is_anchor:
        fallback_name = candidate_project_name_for_resource(resource)
        if fallback_name:
            return ProjectAssignmentDecision(_get_uncategorized_project_id(conn), "suggested_project_name", 40, fallback_name)

    return ProjectAssignmentDecision(_get_uncategorized_project_id(conn), "uncategorized", 0)


def candidate_project_name_for_activity(
    activity: dict,
    resource: dict | None = None,
) -> str | None:
    """Return the display project name that automatic inference would use without writing to DB."""
    label = candidate_project_label_for_activity(activity, resource)
    if label is None:
        return None
    name = str(label.get("name") or "").strip()
    return name or None


def candidate_project_label_for_activity(
    activity: dict,
    resource: dict | None = None,
) -> dict | None:
    """Return a display-safe candidate project *label* for an activity."""
    activity_dict = dict(activity or {})
    if not activity_dict:
        return None
    with get_connection() as conn:
        activity_id = activity_dict.get("id")
        if activity_id:
            resolved_resource = _resource_for_activity(conn, int(activity_id), activity_dict)
        else:
            resolved_resource = resource or _resource_from_activity_dict(activity_dict)
        decision = _infer_project_resource_first(
            conn, activity_dict, resolved_resource
        )
        uncategorized_id = _get_uncategorized_project_id(conn)
        is_uncategorized = int(decision.project_id) == int(uncategorized_id)
        if decision.source == "suggested_project_name":
            return {
                "id": None,
                "name": str(decision.suggested_project_name or "").strip(),
                "description": "",
                "source": "suggested_project_name",
                "is_uncategorized": False,
                "is_suggested_project": True,
            }
        if is_uncategorized:
            return {
                "id": None,
                "name": UNCATEGORIZED_PROJECT,
                "description": "",
                "source": "uncategorized",
                "is_uncategorized": True,
                "is_suggested_project": False,
            }
        row = conn.execute(
            "SELECT name, description FROM project WHERE id = ?", (decision.project_id,)
        ).fetchone()
        name = str(row["name"]) if row and row["name"] else ""
        description = str(row["description"]) if row and row["description"] else ""
        return {
            "id": int(decision.project_id),
            "name": name,
            "description": description,
            "source": decision.source,
            "is_uncategorized": False,
            "is_suggested_project": False,
        }


def _resource_from_activity_dict(activity: dict) -> dict:
    """Build a resource dict from an activity dict using resource-first detection."""
    from ..resources.resource_identity import infer_resource_for_activity
    resource = infer_resource_for_activity(activity)
    return {
        "resource_kind": resource.resource_kind,
        "resource_subtype": resource.resource_subtype,
        "display_name": resource.display_name,
        "identity_key": resource.identity_key,
        "is_anchor": int(resource.is_anchor),
        "app_name": resource.app_name,
        "process_name": resource.process_name,
        "window_title": resource.window_title,
        "path_hint": resource.path_hint,
        "uri_host": resource.uri_host,
    }


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
    source_rule_type: str | None = None,
    source_rule_id: int | None = None,
) -> None:
    if source not in {"folder_rule", "keyword_rule"}:
        source_rule_type = None
        source_rule_id = None
    ts = now_str()
    row = conn.execute(
        """
        SELECT project_id, source, confidence, is_manual, suggested_project_name,
               source_rule_type, source_rule_id
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
        and (row["source_rule_type"] or None) == source_rule_type
        and (row["source_rule_id"] or None) == source_rule_id
    ):
        return
    conn.execute(
        """
        INSERT INTO activity_project_assignment(
            activity_id, project_id, confidence, source, is_manual, suggested_project_name,
            source_rule_type, source_rule_id, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(activity_id) DO UPDATE SET
            project_id = excluded.project_id,
            confidence = excluded.confidence,
            source = excluded.source,
            is_manual = excluded.is_manual,
            suggested_project_name = excluded.suggested_project_name,
            source_rule_type = excluded.source_rule_type,
            source_rule_id = excluded.source_rule_id,
            updated_at = excluded.updated_at
        """,
        (activity_id, project_id, confidence, source, int(is_manual), suggested_project_name,
         source_rule_type, source_rule_id, ts, ts),
    )


def _sync_activity_project(conn, activity_id: int, project_id: int, auto_classified: bool) -> None:
    return


def _assignment_dict(conn, activity_id: int) -> dict:
    row = conn.execute(
        "SELECT * FROM activity_project_assignment WHERE activity_id = ?",
        (activity_id,),
    ).fetchone()
    return dict(row) if row else {}


def get_assignment_for_activity(activity_id: int) -> dict:
    """Return the current ``activity_project_assignment`` row for an activity.

    Public conn-less accessor used by display layers (e.g.
    ``live_display_service._display_project_name``) to read the
    ``suggested_project_name`` / ``source`` / ``is_manual`` fields without
    re-implementing the SQL. Returns ``{}`` when no assignment row exists.
    """
    with get_connection() as conn:
        return _assignment_dict(conn, activity_id)


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
