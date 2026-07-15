"""Rule impact preview + safe single-rule backfill service."""

from __future__ import annotations

from typing import Any

from ..constants import STATUS_NORMAL
from ..db import get_connection, now_str
from ..formatters import format_safe_display_name
from . import clipboard_service, folder_index_service, folder_rule_service
from . import project_lifecycle_policy
from .project_inference_service import keyword_pattern_matches

MAX_RULE_BACKFILL_ACTIVITIES = 100
DEFAULT_SAMPLE_LIMIT = 20

_FOLDER_RULE_CONFIDENCE = 85
_KEYWORD_RULE_CONFIDENCE = 80

ERR_NOT_FOUND = "not_found"
ERR_RULE_DISABLED = "rule_disabled"
ERR_PROJECT_NOT_AVAILABLE = "project_not_available"
ERR_TOO_MANY_MATCHES = "too_many_matches"
ERR_OPERATION_FAILED = "operation_failed"


class RuleImpactError(Exception):
    """Stable rule-impact error. ``code`` is one of the ``ERR_*`` literals."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _resolve_folder_rule(conn, rule_id: int) -> dict | None:
    row = conn.execute(
        """
        SELECT fpr.id, fpr.folder_path, fpr.project_id, fpr.recursive, fpr.enabled,
               p.name AS project_name, p.enabled AS project_enabled,
               p.is_archived AS project_archived,
               p.is_deleted AS project_deleted
        FROM folder_project_rule fpr
        LEFT JOIN project p ON p.id = fpr.project_id
        WHERE fpr.id = ?
        """,
        (int(rule_id),),
    ).fetchone()
    return dict(row) if row else None


def _resolve_keyword_rule(conn, rule_id: int) -> dict | None:
    row = conn.execute(
        """
        SELECT pr.id, pr.pattern, pr.project_id, pr.enabled,
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


def _project_available(rule: dict) -> bool:
    return project_lifecycle_policy.project_available_for_inference(
        {
            "name": rule.get("project_name"),
            "enabled": rule.get("project_enabled"),
            "is_archived": rule.get("project_archived"),
            "is_deleted": rule.get("project_deleted"),
        }
    )


def _rule_target(rule: dict, rule_type: str) -> str:
    if rule_type == "folder":
        return str(rule.get("folder_path") or "")
    return str(rule.get("pattern") or "")


def _rule_summary(
    rule: dict,
    rule_type: str,
    *,
    project_available: bool,
) -> dict[str, Any]:
    return {
        "kind": rule_type,
        "id": int(rule.get("id") or 0),
        "enabled": bool(int(rule.get("enabled") or 0)),
        "project_id": int(rule.get("project_id") or 0),
        "project_name": str(rule.get("project_name") or ""),
        "target": _rule_target(rule, rule_type),
        "project_available": bool(project_available),
    }


_ACTIVITY_SQL = """
SELECT
    a.id, a.start_time, a.end_time, a.duration_seconds,
    a.window_title, a.file_path_hint, a.status, a.is_deleted, a.is_hidden,
    a.app_name, a.process_name,
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
ORDER BY a.id
"""


def _fetch_activities(conn) -> list[dict]:
    return [dict(row) for row in conn.execute(_ACTIVITY_SQL).fetchall()]


def _activity_matches_folder_read_only(activity: dict, rule: dict, conn) -> bool:
    """Match a folder rule without starting index-maintenance writes.

    Direct path matching is attempted first. Title-only matching may consult an
    already-ready folder index through the caller's transaction, but an index
    miss never requests a refresh from inside that transaction.
    """

    if folder_rule_service._activity_matches_folder(
        activity,
        str(rule.get("folder_path") or ""),
        bool(int(rule.get("recursive") or 0)),
    ):
        return True

    file_name = folder_index_service._activity_file_name(activity)
    if not file_name:
        return False
    candidates = folder_index_service.lookup_indexed_paths_for_file_name(
        file_name,
        str(activity.get("start_time") or "") or None,
        include_excluded=False,
        request_refresh_on_miss=False,
        conn=conn,
    )
    if not candidates:
        return False

    matched_project_ids: set[int] = set()
    for candidate in candidates:
        matched_rule = folder_rule_service.find_matching_folder_rule(
            str(candidate.get("file_path") or ""),
            conn=conn,
        )
        if matched_rule:
            matched_project_ids.add(int(matched_rule["project_id"]))
    if len(matched_project_ids) > 1:
        return False
    return any(
        int(candidate.get("folder_rule_id") or 0) == int(rule.get("id") or 0)
        for candidate in candidates
    )


def _activity_matches(activity: dict, rule: dict, rule_type: str, conn) -> bool:
    if rule_type == "folder":
        return _activity_matches_folder_read_only(activity, rule, conn)

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
    clipboard_text = clipboard_service.clipboard_text_for_activity(
        conn,
        int(activity.get("id") or 0),
    )
    return keyword_pattern_matches(pattern, activity, resource, clipboard_text)


def _classify_activities(
    activities: list[dict],
    rule: dict,
    rule_type: str,
    conn,
) -> dict:
    target_project_id = int(rule.get("project_id") or 0)
    expected_source = "folder_rule" if rule_type == "folder" else "keyword_rule"
    counts = {
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
    would_update: list[dict] = []
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
        if not _activity_matches(activity, rule, rule_type, conn):
            continue
        counts["matched_count"] += 1
        effective_project_id = int(activity.get("assignment_project_id") or 0)
        already_target = (
            effective_project_id == target_project_id
            and str(activity.get("assignment_source") or "") == expected_source
            and str(activity.get("assignment_source_rule_type") or "") == rule_type
            and int(activity.get("assignment_source_rule_id") or 0)
            == int(rule.get("id") or 0)
        )
        if already_target:
            counts["already_target_count"] += 1
            continue
        counts["would_update_count"] += 1
        would_update.append(activity)
    counts["would_update"] = would_update
    return counts


def _sample_row(activity: dict, rule: dict, rule_type: str) -> dict[str, Any]:
    resource_name = format_safe_display_name(
        {
            "resource_display_name": activity.get("resource_display_name"),
            "app_name": activity.get("app_name"),
            "process_name": activity.get("process_name"),
        }
    )
    return {
        "activity_id": int(activity.get("id") or 0),
        "start_time": str(activity.get("start_time") or ""),
        "end_time": str(activity.get("end_time") or ""),
        "duration_seconds": int(activity.get("duration_seconds") or 0),
        "resource_name": resource_name,
        "current_project_name": str(activity.get("current_project_name") or ""),
        "target_project_name": str(rule.get("project_name") or ""),
        "match_source": rule_type + "_rule",
    }


def _sample_rows(
    would_update: list[dict],
    rule: dict,
    rule_type: str,
    limit: int,
) -> list[dict]:
    if limit <= 0:
        return []
    return [
        _sample_row(activity, rule, rule_type)
        for activity in would_update[:limit]
    ]


def preview_rule_impact(
    rule_type: str,
    rule_id: int,
    sample_limit: int = DEFAULT_SAMPLE_LIMIT,
) -> dict[str, Any]:
    if not isinstance(rule_type, str) or rule_type not in {"folder", "keyword"}:
        raise RuleImpactError(ERR_NOT_FOUND)
    if type(rule_id) is not int or rule_id <= 0:
        raise RuleImpactError(ERR_NOT_FOUND)
    with get_connection() as conn:
        rule = (
            _resolve_folder_rule(conn, rule_id)
            if rule_type == "folder"
            else _resolve_keyword_rule(conn, rule_id)
        )
        if not rule:
            raise RuleImpactError(ERR_NOT_FOUND)
        project_avail = _project_available(rule)
        rule_summary = _rule_summary(
            rule,
            rule_type,
            project_available=project_avail,
        )
        if not int(rule.get("enabled") or 0) or not project_avail:
            return {
                "rule": rule_summary,
                "counts": {
                    "matched_count": 0,
                    "eligible_count": 0,
                    "would_update_count": 0,
                    "already_target_count": 0,
                    "manual_skipped_count": 0,
                    "hidden_skipped_count": 0,
                    "deleted_skipped_count": 0,
                    "in_progress_skipped_count": 0,
                    "non_normal_skipped_count": 0,
                },
                "samples": [],
            }
        activities = _fetch_activities(conn)
        classified = _classify_activities(activities, rule, rule_type, conn)
        samples = _sample_rows(
            classified["would_update"],
            rule,
            rule_type,
            int(sample_limit),
        )
        return {
            "rule": rule_summary,
            "counts": {
                "matched_count": classified["matched_count"],
                "eligible_count": classified["eligible_count"],
                "would_update_count": classified["would_update_count"],
                "already_target_count": classified["already_target_count"],
                "manual_skipped_count": classified["manual_skipped_count"],
                "hidden_skipped_count": classified["hidden_skipped_count"],
                "deleted_skipped_count": classified["deleted_skipped_count"],
                "in_progress_skipped_count": classified[
                    "in_progress_skipped_count"
                ],
                "non_normal_skipped_count": classified["non_normal_skipped_count"],
            },
            "samples": samples,
        }


def backfill_rule_impact(
    rule_type: str,
    rule_id: int,
    max_updates: int = MAX_RULE_BACKFILL_ACTIVITIES,
) -> dict[str, Any]:
    if not isinstance(rule_type, str) or rule_type not in {"folder", "keyword"}:
        raise RuleImpactError(ERR_NOT_FOUND)
    if type(rule_id) is not int or rule_id <= 0:
        raise RuleImpactError(ERR_NOT_FOUND)
    source = "folder_rule" if rule_type == "folder" else "keyword_rule"
    confidence = (
        _FOLDER_RULE_CONFIDENCE
        if rule_type == "folder"
        else _KEYWORD_RULE_CONFIDENCE
    )
    with get_connection() as conn:
        rule = (
            _resolve_folder_rule(conn, rule_id)
            if rule_type == "folder"
            else _resolve_keyword_rule(conn, rule_id)
        )
        if not rule:
            raise RuleImpactError(ERR_NOT_FOUND)
        if not int(rule.get("enabled") or 0):
            raise RuleImpactError(ERR_RULE_DISABLED)
        if not _project_available(rule):
            raise RuleImpactError(ERR_PROJECT_NOT_AVAILABLE)
        project_id = int(rule.get("project_id") or 0)
        activities = _fetch_activities(conn)
        classified = _classify_activities(activities, rule, rule_type, conn)
        would_update = classified["would_update"]
        would_update_count = classified["would_update_count"]
        if would_update_count > int(max_updates):
            raise RuleImpactError(ERR_TOO_MANY_MATCHES)
        ts = now_str()
        for activity in would_update:
            activity_id = int(activity.get("id") or 0)
            cursor = conn.execute(
                """
                INSERT INTO activity_project_assignment(
                    activity_id, project_id, confidence, source, is_manual,
                    suggested_project_name, source_rule_type, source_rule_id,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, 0, NULL, ?, ?, ?, ?)
                ON CONFLICT(activity_id) DO UPDATE SET
                    project_id = excluded.project_id,
                    confidence = excluded.confidence,
                    source = excluded.source,
                    is_manual = 0,
                    suggested_project_name = NULL,
                    source_rule_type = excluded.source_rule_type,
                    source_rule_id = excluded.source_rule_id,
                    updated_at = excluded.updated_at
                WHERE activity_project_assignment.is_manual = 0
                """,
                (
                    activity_id,
                    project_id,
                    confidence,
                    source,
                    rule_type,
                    rule_id,
                    ts,
                    ts,
                ),
            )
            if cursor.rowcount != 1:
                raise RuleImpactError(ERR_OPERATION_FAILED)
        return {
            "rule": _rule_summary(rule, rule_type, project_available=True),
            "updated_count": len(would_update),
            "matched_count": classified["matched_count"],
            "eligible_count": classified["eligible_count"],
            "would_update_count": would_update_count,
            "skipped_count": (
                classified["manual_skipped_count"]
                + classified["hidden_skipped_count"]
                + classified["deleted_skipped_count"]
                + classified["in_progress_skipped_count"]
                + classified["non_normal_skipped_count"]
                + classified["already_target_count"]
            ),
            "already_target_count": classified["already_target_count"],
            "manual_skipped_count": classified["manual_skipped_count"],
            "hidden_skipped_count": classified["hidden_skipped_count"],
            "deleted_skipped_count": classified["deleted_skipped_count"],
            "in_progress_skipped_count": classified["in_progress_skipped_count"],
            "non_normal_skipped_count": classified["non_normal_skipped_count"],
            "too_many_matches": False,
        }


__all__ = [
    "DEFAULT_SAMPLE_LIMIT",
    "ERR_NOT_FOUND",
    "ERR_OPERATION_FAILED",
    "ERR_PROJECT_NOT_AVAILABLE",
    "ERR_RULE_DISABLED",
    "ERR_TOO_MANY_MATCHES",
    "MAX_RULE_BACKFILL_ACTIVITIES",
    "RuleImpactError",
    "backfill_rule_impact",
    "preview_rule_impact",
]
