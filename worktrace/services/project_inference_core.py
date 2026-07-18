from __future__ import annotations

import logging
import ntpath
import re
import threading
from collections.abc import Iterable
from dataclasses import dataclass

from ..constants import STATUS_NORMAL, UNCATEGORIZED_PROJECT
from ..data_generation_repository import DataGenerationNamespace
from ..db import get_connection, get_db_key
from ..domain_unit_of_work import DomainUnitOfWork
from ..generation_clock import generation
from ..path_utils import has_auto_project_extension
from . import (
    assignment_command_service,
    clipboard_fact_query_service,
    folder_index_query_service,
    folder_rule_service,
    project_lifecycle_policy,
)
from .system_project_service import require_uncategorized_project_id

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
_KEYWORD_RULE_CACHE_LOCK = threading.RLock()
_KEYWORD_RULE_CACHE_DATABASE_KEY: str | None = None
_KEYWORD_RULE_CACHE_GENERATION: int | None = None
_KEYWORD_RULE_CACHE: list[dict] | None = None


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
    """Test/reconfiguration hook; catalog writes invalidate by generation."""

    global _KEYWORD_RULE_CACHE_DATABASE_KEY
    global _KEYWORD_RULE_CACHE_GENERATION
    global _KEYWORD_RULE_CACHE
    with _KEYWORD_RULE_CACHE_LOCK:
        _KEYWORD_RULE_CACHE_DATABASE_KEY = None
        _KEYWORD_RULE_CACHE_GENERATION = None
        _KEYWORD_RULE_CACHE = None


def _load_enabled_keyword_rules(conn) -> list[dict]:
    rows = conn.execute(
        """
        SELECT pr.id, pr.project_id, pr.pattern,
               p.name AS project_name, p.enabled AS project_enabled,
               p.is_archived AS project_is_archived,
               p.is_deleted AS project_is_deleted
        FROM project_rule pr
        JOIN project p ON p.id = pr.project_id
        WHERE pr.enabled = 1
          AND pr.rule_type = 'keyword'
          AND pr.created_by = 'user'
        ORDER BY pr.created_at, pr.id
        """
    ).fetchall()
    return [
        {
            "id": int(row["id"]),
            "project_id": int(row["project_id"]),
            "pattern": str(row["pattern"] or "").strip().casefold(),
        }
        for row in rows
        if project_lifecycle_policy.project_available_for_inference(
            {
                "name": row["project_name"],
                "enabled": row["project_enabled"],
                "is_archived": row["project_is_archived"],
                "is_deleted": row["project_is_deleted"],
            }
        )
    ]


def _enabled_keyword_rules(conn=None) -> list[dict]:
    if conn is not None:
        return [dict(row) for row in _load_enabled_keyword_rules(conn)]

    global _KEYWORD_RULE_CACHE_DATABASE_KEY
    global _KEYWORD_RULE_CACHE_GENERATION
    global _KEYWORD_RULE_CACHE
    while True:
        database_key = get_db_key()
        current_generation = generation(DataGenerationNamespace.CLASSIFICATION_CATALOG)
        with _KEYWORD_RULE_CACHE_LOCK:
            if (
                _KEYWORD_RULE_CACHE_DATABASE_KEY == database_key
                and _KEYWORD_RULE_CACHE_GENERATION == current_generation
                and _KEYWORD_RULE_CACHE is not None
            ):
                return [dict(row) for row in _KEYWORD_RULE_CACHE]
        with get_connection() as read_conn:
            rules = _load_enabled_keyword_rules(read_conn)
        if generation(DataGenerationNamespace.CLASSIFICATION_CATALOG) != current_generation:
            continue
        with _KEYWORD_RULE_CACHE_LOCK:
            _KEYWORD_RULE_CACHE_DATABASE_KEY = database_key
            _KEYWORD_RULE_CACHE_GENERATION = current_generation
            _KEYWORD_RULE_CACHE = [dict(row) for row in rules]
        return [dict(row) for row in rules]


def assign_project_for_activity(activity_id: int) -> dict:
    """Infer and persist one assignment through the canonical command owner."""

    with DomainUnitOfWork((DataGenerationNamespace.REPORT_STRUCTURE,)) as uow:
        result, changed = _assign_project_for_activity_in_transaction(
            uow.connection,
            int(activity_id),
        )
        if changed:
            uow.mark_changed()
        return result


def assign_project_for_activity_in_transaction(
    conn,
    activity_id: int,
    *,
    exclude_rule: tuple[str, int] | None = None,
) -> dict:
    """Assign one activity inside a caller-owned transaction."""

    result, _changed = _assign_project_for_activity_in_transaction(
        conn,
        int(activity_id),
        exclude_rule=exclude_rule,
    )
    return result


def _assign_project_for_activity_in_transaction(
    conn,
    activity_id: int,
    *,
    exclude_rule: tuple[str, int] | None = None,
) -> tuple[dict, bool]:
    activity = conn.execute(
        "SELECT * FROM activity_log WHERE id = ?",
        (int(activity_id),),
    ).fetchone()
    if activity is None:
        raise ValueError(f"activity not found: {activity_id}")
    activity_dict = dict(activity)

    existing = conn.execute(
        "SELECT * FROM activity_project_assignment WHERE activity_id = ?",
        (int(activity_id),),
    ).fetchone()
    if existing is not None and int(existing["is_manual"] or 0):
        return _assignment_dict(conn, activity_id), False
    if existing is not None and str(existing["source"] or "") == "midnight_anchor":
        return _assignment_dict(conn, activity_id), False

    uncategorized_id = require_uncategorized_project_id(conn)
    if str(activity["status"] or "") != STATUS_NORMAL:
        changed = assignment_command_service.upsert_assignment(
            conn,
            activity_id=activity_id,
            project_id=uncategorized_id,
            source="uncategorized",
            confidence=0,
        )
        return _assignment_dict(conn, activity_id), changed

    resource = _resource_for_activity(conn, activity_id)
    decision = _infer_project_resource_first(
        conn,
        activity_dict,
        resource,
        exclude_rule=exclude_rule,
    )
    changed = assignment_command_service.upsert_assignment(
        conn,
        activity_id=activity_id,
        project_id=decision.project_id,
        source=decision.source,
        confidence=decision.confidence,
        suggested_project_name=decision.suggested_project_name,
        source_rule_type=decision.source_rule_type,
        source_rule_id=decision.source_rule_id,
    )
    return _assignment_dict(conn, activity_id), changed


def process_new_activity(activity_id: int) -> dict:
    """Apply automatic rules only to closed, visible, durable activities."""

    with get_connection() as conn:
        activity = conn.execute(
            "SELECT is_hidden, is_deleted, end_time FROM activity_log WHERE id = ?",
            (int(activity_id),),
        ).fetchone()
        if activity is None:
            raise ValueError(f"activity not found: {activity_id}")
        if int(activity["is_hidden"] or 0) or int(activity["is_deleted"] or 0):
            return _assignment_dict(conn, activity_id)
        if activity["end_time"] is None:
            return _assignment_dict(conn, activity_id)
    return assign_project_for_activity(activity_id)


def process_pending_inference_jobs(
    limit: int = 100,
    *,
    activity_ids: Iterable[int] | None = None,
) -> int:
    """Consume durable jobs through the acyclic bounded worker boundary."""

    from .activity_inference_job_service import process_pending_inference_jobs as consume

    return consume(
        assign_project_for_activity_in_transaction,
        limit=max(0, int(limit)),
        activity_ids=activity_ids,
    )


def retry_pending_inference(limit: int = 100) -> int:
    """Consume a bounded set of durable inference jobs."""

    return process_pending_inference_jobs(limit=max(0, int(limit)))


_OPEN_ROW_UNCLASSIFIED_SOURCES = {"uncategorized", "suggested_project_name"}


def sync_persisted_open_activity_project(activity_id: int) -> dict:
    """Converge an eligible open row without exposing inference to display code."""

    with get_connection() as conn:
        activity = conn.execute(
            """
            SELECT is_hidden, is_deleted, end_time, status
            FROM activity_log
            WHERE id = ?
            """,
            (int(activity_id),),
        ).fetchone()
        if activity is None:
            return {}
        if int(activity["is_hidden"] or 0) or int(activity["is_deleted"] or 0):
            return _assignment_dict(conn, activity_id)
        if activity["end_time"] is not None or activity["status"] != STATUS_NORMAL:
            return _assignment_dict(conn, activity_id)
        existing = conn.execute(
            "SELECT source, is_manual FROM activity_project_assignment WHERE activity_id = ?",
            (int(activity_id),),
        ).fetchone()
        if existing is not None and int(existing["is_manual"] or 0):
            return _assignment_dict(conn, activity_id)
        source = str(existing["source"] or "") if existing is not None else ""
        if source and source not in _OPEN_ROW_UNCLASSIFIED_SOURCES:
            return _assignment_dict(conn, activity_id)
    return assign_project_for_activity(activity_id)


def _resource_for_activity(conn, activity_id: int) -> dict:
    """Load the durable resource fact; historic inference never synthesizes it."""

    row = conn.execute(
        "SELECT * FROM activity_resource WHERE activity_id = ?",
        (int(activity_id),),
    ).fetchone()
    if row is None or not str(row["identity_key"] or "").strip():
        raise ValueError("data_repair_required")
    return dict(row)


def _safe_classification_text(
    activity: dict,
    resource: dict,
    clipboard_text: str = "",
) -> str:
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
    if not pattern_casefold:
        return False
    return pattern_casefold in _safe_classification_text(
        activity,
        resource,
        clipboard_text,
    )


def candidate_project_name_for_resource(resource: dict) -> str | None:
    is_anchor = bool(resource.get("is_anchor"))
    path_hint = str(resource.get("path_hint") or "").strip()
    resource_kind = str(resource.get("resource_kind") or "")
    resource_subtype = str(resource.get("resource_subtype") or "")
    if not is_anchor or resource_kind in {"browser_tab", "email"}:
        return None

    if path_hint:
        parent_dir = ntpath.dirname(path_hint.rstrip("\\/"))
        if parent_dir and (
            has_auto_project_extension(path_hint)
            or (resource_kind == "ide_file" and resource_subtype == "code_file")
        ):
            candidate = _clean_project_candidate(
                ntpath.basename(parent_dir.rstrip("\\/"))
            )
            if candidate and candidate.casefold() not in GENERIC_FILE_PROJECT_NAMES:
                return candidate

    if resource_kind == "ide_file" and resource_subtype == "ide_workspace":
        return _clean_project_candidate(str(resource.get("display_name") or ""))
    return None


def _infer_project_resource_first(
    conn,
    activity: dict,
    resource: dict,
    *,
    exclude_rule: tuple[str, int] | None = None,
) -> ProjectAssignmentDecision:
    path_hint = str(resource.get("path_hint") or "").strip()
    is_anchor = bool(resource.get("is_anchor"))
    display_name = str(resource.get("display_name") or "")
    excluded_folder_id = (
        int(exclude_rule[1])
        if exclude_rule is not None and exclude_rule[0] == "folder"
        else None
    )

    if path_hint:
        for target in (
            path_hint,
            ntpath.dirname(path_hint.rstrip("\\/")),
        ):
            if not target:
                continue
            rule = folder_rule_service.find_matching_folder_rule(
                target,
                exclude_rule_id=excluded_folder_id,
                conn=conn,
            )
            if rule:
                return ProjectAssignmentDecision(
                    int(rule["project_id"]),
                    "folder_rule",
                    85,
                    source_rule_type="folder",
                    source_rule_id=int(rule["id"]),
                )

    if not path_hint and is_anchor and display_name:
        rule = folder_index_query_service.find_matching_folder_rule_for_file_name(
            display_name,
            str(activity.get("start_time") or "") or None,
            conn=conn,
        )
        if rule and exclude_rule != ("folder", int(rule["id"])):
            return ProjectAssignmentDecision(
                int(rule["project_id"]),
                "folder_rule",
                85,
                source_rule_type="folder",
                source_rule_id=int(rule["id"]),
            )

    clipboard_text = ""
    activity_id = activity.get("id")
    if activity_id:
        clipboard_text = clipboard_fact_query_service.clipboard_text_for_activity(
            conn,
            int(activity_id),
        )
    classification_text = _safe_classification_text(
        activity,
        resource,
        clipboard_text,
    )
    for rule in _enabled_keyword_rules(conn):
        pattern = str(rule["pattern"] or "")
        if (
            pattern
            and pattern in classification_text
            and exclude_rule != ("keyword", int(rule["id"]))
        ):
            return ProjectAssignmentDecision(
                int(rule["project_id"]),
                "keyword_rule",
                80,
                source_rule_type="keyword",
                source_rule_id=int(rule["id"]),
            )

    uncategorized_id = require_uncategorized_project_id(conn)
    if is_anchor:
        fallback_name = candidate_project_name_for_resource(resource)
        if fallback_name:
            return ProjectAssignmentDecision(
                uncategorized_id,
                "suggested_project_name",
                40,
                fallback_name,
            )
    return ProjectAssignmentDecision(uncategorized_id, "uncategorized", 0)


def candidate_project_name_for_activity(
    activity: dict,
    resource: dict | None = None,
) -> str | None:
    label = candidate_project_label_for_activity(activity, resource)
    if label is None:
        return None
    return str(label.get("name") or "").strip() or None


def candidate_project_label_for_activity(
    activity: dict,
    resource: dict | None = None,
) -> dict | None:
    """Return a display-safe candidate label without writing any durable fact."""

    activity_dict = dict(activity or {})
    if not activity_dict:
        return None
    with get_connection() as conn:
        activity_id = activity_dict.get("id")
        if activity_id:
            resolved_resource = _resource_for_activity(conn, int(activity_id))
        else:
            resolved_resource = resource or _resource_from_activity_dict(activity_dict)
        decision = _infer_project_resource_first(conn, activity_dict, resolved_resource)
        uncategorized_id = require_uncategorized_project_id(conn)
        if decision.source == "suggested_project_name":
            return {
                "id": None,
                "name": str(decision.suggested_project_name or "").strip(),
                "description": "",
                "source": "suggested_project_name",
                "is_uncategorized": False,
                "is_suggested_project": True,
            }
        if int(decision.project_id) == uncategorized_id:
            return {
                "id": None,
                "name": UNCATEGORIZED_PROJECT,
                "description": "",
                "source": "uncategorized",
                "is_uncategorized": True,
                "is_suggested_project": False,
            }
        row = conn.execute(
            "SELECT name, description FROM project WHERE id = ?",
            (int(decision.project_id),),
        ).fetchone()
        return {
            "id": int(decision.project_id),
            "name": str(row["name"] or "") if row else "",
            "description": str(row["description"] or "") if row else "",
            "source": decision.source,
            "is_uncategorized": False,
            "is_suggested_project": False,
        }


def _resource_from_activity_dict(activity: dict) -> dict:
    """Detect an ephemeral resource only for a non-persisted live candidate."""

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
    if cleaned.casefold() in {
        "untitled",
        "new file",
        "新建",
        "临时",
        "temp",
        "tmp",
    }:
        return None
    limit = 40 if any("\u4e00" <= char <= "\u9fff" for char in cleaned) else 80
    if len(cleaned) > limit:
        cleaned = cleaned[:limit].rstrip()
    return cleaned or None


def _assignment_dict(conn, activity_id: int) -> dict:
    row = conn.execute(
        "SELECT * FROM activity_project_assignment WHERE activity_id = ?",
        (int(activity_id),),
    ).fetchone()
    return dict(row) if row else {}


def get_assignment_for_activity(activity_id: int) -> dict:
    with get_connection() as conn:
        return _assignment_dict(conn, activity_id)


__all__ = [
    "ProjectAssignmentDecision",
    "assign_project_for_activity",
    "assign_project_for_activity_in_transaction",
    "candidate_project_label_for_activity",
    "candidate_project_name_for_activity",
    "candidate_project_name_for_resource",
    "get_assignment_for_activity",
    "invalidate_keyword_rule_cache",
    "keyword_pattern_matches",
    "process_new_activity",
    "process_pending_inference_jobs",
    "retry_pending_inference",
    "sync_persisted_open_activity_project",
]
