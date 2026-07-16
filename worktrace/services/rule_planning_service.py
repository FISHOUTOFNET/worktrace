"""Public, read-only planning kernel for rule history mutations."""

from __future__ import annotations

from typing import Any, Iterable

from ..constants import STATUS_NORMAL
from ..formatters import format_safe_display_name
from ..path_utils import is_path_under_folder, looks_like_anchor_file_path
from . import folder_index_service, project_lifecycle_policy
from .project_inference_service import keyword_pattern_matches

FOLDER_RULE_CONFIDENCE = 85
KEYWORD_RULE_CONFIDENCE = 80


def resolve_rule(conn, rule_type: str, rule_id: int) -> dict | None:
    if rule_type == "folder":
        row = conn.execute(
            """
            SELECT fpr.id, fpr.folder_path, fpr.project_id, fpr.recursive,
                   fpr.enabled, fpr.updated_at,
                   p.name AS project_name, p.enabled AS project_enabled,
                   p.is_archived AS project_archived,
                   p.is_deleted AS project_deleted
            FROM folder_project_rule fpr
            LEFT JOIN project p ON p.id = fpr.project_id
            WHERE fpr.id = ?
            """,
            (int(rule_id),),
        ).fetchone()
    else:
        row = conn.execute(
            """
            SELECT pr.id, pr.pattern, pr.project_id, pr.enabled, pr.updated_at,
                   p.name AS project_name, p.enabled AS project_enabled,
                   p.is_archived AS project_archived,
                   p.is_deleted AS project_deleted
            FROM project_rule pr
            LEFT JOIN project p ON p.id = pr.project_id
            WHERE pr.id = ? AND pr.rule_type = 'keyword'
            """,
            (int(rule_id),),
        ).fetchone()
    return dict(row) if row else None


def project_available(rule: dict) -> bool:
    return project_lifecycle_policy.project_available_for_inference(
        {
            "name": rule.get("project_name"),
            "enabled": rule.get("project_enabled"),
            "is_archived": rule.get("project_archived"),
            "is_deleted": rule.get("project_deleted"),
        }
    )


def rule_summary(
    rule: dict,
    rule_type: str,
    *,
    available: bool,
) -> dict[str, Any]:
    return {
        "kind": rule_type,
        "id": int(rule.get("id") or 0),
        "enabled": bool(int(rule.get("enabled") or 0)),
        "project_id": int(rule.get("project_id") or 0),
        "project_name": str(rule.get("project_name") or ""),
        "target": str(
            rule.get("folder_path")
            if rule_type == "folder"
            else rule.get("pattern")
            or ""
        ),
        "project_available": bool(available),
        "version": str(rule.get("updated_at") or ""),
    }


def load_candidate_activities(
    conn,
    *,
    after_id: int = 0,
    cutoff_id: int | None = None,
    limit: int | None = None,
) -> list[dict]:
    cutoff_clause = "AND a.id <= ?" if cutoff_id is not None else ""
    limit_clause = "LIMIT ?" if limit is not None else ""
    params: list[int] = [int(after_id)]
    if cutoff_id is not None:
        params.append(int(cutoff_id))
    if limit is not None:
        params.append(max(0, int(limit)))
    rows = conn.execute(
        f"""
        SELECT
            a.id, a.start_time, a.end_time, a.duration_seconds,
            a.window_title, a.file_path_hint, a.status,
            a.is_deleted, a.is_hidden, a.app_name, a.process_name,
            ar.path_hint AS resource_path_hint,
            ar.is_anchor AS resource_is_anchor,
            ar.display_name AS resource_display_name,
            ar.resource_kind, ar.resource_subtype,
            ar.app_name AS resource_app_name,
            ar.process_name AS resource_process_name,
            ar.window_title AS resource_window_title,
            ar.uri_host AS resource_uri_host,
            apa.project_id AS assignment_project_id,
            apa.source AS assignment_source,
            apa.is_manual AS assignment_is_manual,
            apa.source_rule_type AS assignment_source_rule_type,
            apa.source_rule_id AS assignment_source_rule_id,
            curr.name AS current_project_name
        FROM activity_log a
        LEFT JOIN activity_resource ar ON ar.activity_id = a.id
        LEFT JOIN activity_project_assignment apa ON apa.activity_id = a.id
        LEFT JOIN project curr ON curr.id = apa.project_id
        WHERE a.id > ?
          {cutoff_clause}
        ORDER BY a.id
        {limit_clause}
        """,
        params,
    ).fetchall()
    activities = [dict(row) for row in rows]
    _attach_clipboard_texts(conn, activities)
    return activities


def classify_activities(
    conn,
    activities: Iterable[dict],
    rule: dict,
    rule_type: str,
) -> dict[str, Any]:
    target_project_id = int(rule.get("project_id") or 0)
    expected_source = "folder_rule" if rule_type == "folder" else "keyword_rule"
    counts = zero_counts()
    updates: list[dict] = []
    for activity in activities:
        if int(activity.get("is_deleted") or 0):
            counts["deleted_skipped_count"] += 1
            continue
        if int(activity.get("is_hidden") or 0):
            counts["hidden_skipped_count"] += 1
            continue
        if activity.get("end_time") is None:
            counts["in_progress_skipped_count"] += 1
            continue
        if str(activity.get("status") or "") != STATUS_NORMAL:
            counts["non_normal_skipped_count"] += 1
            continue
        if int(activity.get("assignment_is_manual") or 0):
            counts["manual_skipped_count"] += 1
            continue
        counts["eligible_count"] += 1
        if not activity_matches_rule(conn, activity, rule, rule_type):
            continue
        counts["matched_count"] += 1
        already_target = (
            int(activity.get("assignment_project_id") or 0) == target_project_id
            and str(activity.get("assignment_source") or "") == expected_source
            and str(activity.get("assignment_source_rule_type") or "") == rule_type
            and int(activity.get("assignment_source_rule_id") or 0)
            == int(rule.get("id") or 0)
        )
        if already_target:
            counts["already_target_count"] += 1
            continue
        updates.append(activity)
    counts["would_update_count"] = len(updates)
    counts["would_update"] = updates
    return counts


def activity_matches_rule(
    conn,
    activity: dict,
    rule: dict,
    rule_type: str,
) -> bool:
    if rule_type == "folder":
        folder = str(rule.get("folder_path") or "")
        recursive = bool(int(rule.get("recursive") or 0))
        for key in ("resource_path_hint", "file_path_hint"):
            path = str(activity.get(key) or "").strip()
            if path and looks_like_anchor_file_path(path):
                return is_path_under_folder(path, folder, recursive)
        file_name = activity_file_name(activity)
        if not file_name:
            return False
        candidates = folder_index_service.lookup_indexed_paths_for_file_name(
            file_name,
            str(activity.get("start_time") or "") or None,
            include_excluded=False,
            request_refresh_on_miss=False,
            conn=conn,
        )
        return any(
            int(item.get("folder_rule_id") or 0) == int(rule.get("id") or 0)
            for item in candidates
        )
    pattern = str(rule.get("pattern") or "").strip().casefold()
    if not pattern:
        return False
    resource = {
        "display_name": activity.get("resource_display_name"),
        "resource_kind": activity.get("resource_kind"),
        "resource_subtype": activity.get("resource_subtype"),
        "app_name": activity.get("resource_app_name"),
        "process_name": activity.get("resource_process_name"),
        "window_title": activity.get("resource_window_title"),
        "path_hint": activity.get("resource_path_hint"),
        "uri_host": activity.get("resource_uri_host"),
    }
    return keyword_pattern_matches(
        pattern,
        activity,
        resource,
        str(activity.get("clipboard_text") or ""),
    )


def sample_rows(
    activities: list[dict],
    rule: dict,
    rule_type: str,
    limit: int,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for activity in activities[: max(0, int(limit))]:
        result.append(
            {
                "activity_id": int(activity.get("id") or 0),
                "start_time": str(activity.get("start_time") or ""),
                "end_time": str(activity.get("end_time") or ""),
                "duration_seconds": int(activity.get("duration_seconds") or 0),
                "resource_name": format_safe_display_name(
                    {
                        "resource_display_name": activity.get(
                            "resource_display_name"
                        ),
                        "app_name": activity.get("app_name"),
                        "process_name": activity.get("process_name"),
                    }
                ),
                "current_project_name": str(
                    activity.get("current_project_name") or ""
                ),
                "target_project_name": str(rule.get("project_name") or ""),
                "match_source": rule_type + "_rule",
            }
        )
    return result


def zero_counts() -> dict[str, int]:
    return {
        "matched_count": 0,
        "eligible_count": 0,
        "would_update_count": 0,
        "already_target_count": 0,
        "manual_skipped_count": 0,
        "hidden_skipped_count": 0,
        "deleted_skipped_count": 0,
        "in_progress_skipped_count": 0,
        "non_normal_skipped_count": 0,
    }


def activity_file_name(activity: dict) -> str | None:
    from ..resources.title_parsing import extract_file_name_from_title

    for value in (
        activity.get("resource_display_name"),
        activity.get("activity_display_name"),
        activity.get("window_title"),
    ):
        value = extract_file_name_from_title(str(value or ""))
        if value:
            return value
    return None


def _attach_clipboard_texts(conn, activities: list[dict]) -> None:
    ids = [int(item.get("id") or 0) for item in activities]
    if not ids:
        return
    texts: dict[int, list[str]] = {}
    for offset in range(0, len(ids), 800):
        chunk = ids[offset : offset + 800]
        placeholders = ",".join("?" for _ in chunk)
        rows = conn.execute(
            f"""
            SELECT activity_id, copied_text
            FROM activity_clipboard_event
            WHERE activity_id IN ({placeholders})
            ORDER BY activity_id, copied_at, id
            """,
            chunk,
        ).fetchall()
        for row in rows:
            texts.setdefault(int(row["activity_id"]), []).append(
                str(row["copied_text"] or "")
            )
    for activity in activities:
        activity["clipboard_text"] = "\n".join(
            value
            for value in texts.get(int(activity.get("id") or 0), [])
            if value
        )


__all__ = [
    "FOLDER_RULE_CONFIDENCE",
    "KEYWORD_RULE_CONFIDENCE",
    "activity_file_name",
    "activity_matches_rule",
    "classify_activities",
    "load_candidate_activities",
    "project_available",
    "resolve_rule",
    "rule_summary",
    "sample_rows",
    "zero_counts",
]
