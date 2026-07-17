from __future__ import annotations

import hashlib
import json
from typing import Any

from ..constants import UNCATEGORIZED_PROJECT
from .project_attribution_policy import is_official_project_source


def resolve_official_anchor_project(anchor: dict[str, Any] | None) -> dict[str, Any]:
    """Project an anchor only from facts already attached by its repository."""

    row = dict(anchor or {})
    source = str(row.get("assignment_source") or "")
    project_id = int(row.get("effective_project_id") or 0)
    project_name = str(row.get("effective_project_name") or "").strip()
    official = bool(
        project_id > 0
        and project_name
        and is_official_project_source(source)
    )
    if not official:
        project_id = 0
        project_name = UNCATEGORIZED_PROJECT
    project_description = (
        str(row.get("effective_project_description") or "") if official else ""
    )
    return {
        "project_id": project_id,
        "project_name": project_name,
        "project_description": project_description,
        "display_project": {
            "id": project_id if official else None,
            "name": project_name,
            "description": project_description,
            "source": source if official else "uncategorized",
            "is_uncategorized": not official,
            "is_suggested_project": False,
        },
        "is_uncategorized": not official,
        "is_classified": official,
    }


def build_kpi_live_targets(
    rows: list[dict[str, Any]],
    live_clock: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    active_elapsed = int(
        live_clock.get("current_elapsed_at_sample")
        or live_clock.get("active_elapsed_at_sample")
        or 0
    )
    live_projects = bool(
        live_clock.get("is_live")
        and (
            live_clock.get("project_duration_live") is True
            or live_clock.get("is_project_duration_live") is True
        )
    )
    live_span_id = str(live_clock.get("display_span_id") or "")
    live_rows = [
        row
        for row in rows
        if live_projects
        and live_span_id
        and row.get("live_delta_eligible") is True
        and str(row.get("display_span_id") or "") == live_span_id
    ]

    total_seconds = sum(int(row.get("duration_seconds") or 0) for row in rows)
    classified_seconds = sum(
        int(row.get("duration_seconds") or 0)
        for row in rows
        if bool(row.get("is_classified"))
    )
    uncategorized_seconds = sum(
        int(row.get("duration_seconds") or 0)
        for row in rows
        if bool(row.get("is_uncategorized"))
    )

    total_enabled = bool(live_rows)
    classified_enabled = any(bool(row.get("is_classified")) for row in live_rows)
    uncategorized_enabled = any(bool(row.get("is_uncategorized")) for row in live_rows)

    def target(enabled: bool, seconds: int) -> dict[str, Any]:
        return {
            "enabled": bool(enabled),
            "base_seconds": max(0, int(seconds) - active_elapsed) if enabled else 0,
        }

    return {
        "today_total_seconds": target(total_enabled, total_seconds),
        "classified_seconds": target(classified_enabled, classified_seconds),
        "uncategorized_seconds": target(uncategorized_enabled, uncategorized_seconds),
    }


def build_revision_parts(
    model: dict[str, Any],
    marker: dict[str, Any],
    *,
    snapshot_status: str,
    collector_status: str,
    user_paused: bool,
    today: str,
    report_date: str,
) -> dict[str, str]:
    live_clock = model.get("live_clock") or {}
    current_activity = model.get("current_activity") or {}
    live_clock_input = {
        "stable_live_key_hash": str(live_clock.get("stable_live_key_hash") or ""),
        "display_span_id": str(live_clock.get("display_span_id") or ""),
        "current_activity_display_span_id": str(
            current_activity.get("current_activity_display_span_id") or ""
        ),
        "current_resource_identity_hash": str(
            current_activity.get("current_resource_identity_hash") or ""
        ),
        "live_started_at_epoch_ms": int(live_clock.get("live_started_at_epoch_ms") or 0),
        "status": snapshot_status,
        "live_state": str(live_clock.get("live_state") or ""),
        "is_live": bool(live_clock.get("is_live")),
        "project_duration_live": bool(
            live_clock.get("project_duration_live", live_clock.get("is_project_duration_live"))
        ),
        "current_duration_live": bool(live_clock.get("current_duration_live")),
        "collector_status": collector_status,
        "user_paused": bool(user_paused),
        "today": today,
        "report_date": report_date,
    }
    display_policy = live_clock.get("display_policy") or {}
    display_projection_input = {
        "display_structural_signature": str(model.get("display_structural_signature") or ""),
        "display_policy": {
            "display_session_kind": str(display_policy.get("display_session_kind") or ""),
            "base_policy": str(display_policy.get("base_policy") or ""),
            "project_duration_live": bool(display_policy.get("project_duration_live")),
            "current_duration_live": bool(display_policy.get("current_duration_live")),
            "materialize_recent": bool(display_policy.get("materialize_recent")),
            "materialize_timeline": bool(display_policy.get("materialize_timeline")),
            "materialize_details": bool(display_policy.get("materialize_details")),
            "status_only_reason": str(display_policy.get("status_only_reason") or ""),
            "base_policy_reason": str(display_policy.get("base_policy_reason") or ""),
        },
        "current_display_project": _project_revision_identity(
            current_activity.get("display_project")
        ),
    }
    return {
        "live_revision": _hash(live_clock_input),
        "page_revision": _hash([marker, display_projection_input]),
    }


def _hash(value: Any) -> str:
    return hashlib.sha1(
        json.dumps(value, sort_keys=True, ensure_ascii=True).encode("utf-8")
    ).hexdigest()


def _project_revision_identity(project: Any) -> dict[str, Any]:
    if not isinstance(project, dict):
        return {}
    return {
        "id": project.get("id"),
        "name": str(project.get("name") or ""),
        "description": str(project.get("description") or ""),
        "source": str(project.get("source") or ""),
        "is_uncategorized": bool(project.get("is_uncategorized")),
        "is_suggested_project": bool(project.get("is_suggested_project")),
    }
