from __future__ import annotations

import hashlib
import json
from typing import Any

from ..constants import UNCATEGORIZED_PROJECT
from . import project_service
from .project_attribution_policy import candidate_project_fields, official_project_fields


def resolve_official_anchor_project(anchor: dict[str, Any] | None) -> dict[str, Any]:
    uncategorized_id = project_service.get_or_create_uncategorized_project()
    if not anchor:
        return _anchor_project_from_official_fields(
            official_project_fields({}, uncategorized_id),
            candidate_project_fields({}, uncategorized_id),
        )
    row = _anchor_attribution_row(anchor)
    return _anchor_project_from_official_fields(
        official_project_fields(row, uncategorized_id),
        candidate_project_fields(row, uncategorized_id),
    )


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
    display_projection_input = {
        "display_structural_signature": str(model.get("display_structural_signature") or ""),
        "display_policy": model.get("display_policy") or {},
        "current_display_project": _project_revision_identity(
            current_activity.get("display_project")
        ),
        "current_candidate_project": _project_revision_identity(
            current_activity.get("candidate_project")
        ),
        "project_transition": _project_transition_revision_identity(
            current_activity.get("project_transition")
        ),
    }
    page_structure_revision = _hash(marker)
    live_clock_revision = _hash(live_clock_input)
    display_projection_revision = _hash(display_projection_input)
    return {
        "live_clock_revision": live_clock_revision,
        "display_projection_revision": display_projection_revision,
        "page_structure_revision": page_structure_revision,
        "refresh_revision": ":".join(
            [live_clock_revision, display_projection_revision, page_structure_revision]
        ),
    }


def _anchor_attribution_row(anchor: dict[str, Any]) -> dict[str, Any]:
    row = dict(anchor)
    activity_id = int(row.get("id") or row.get("activity_id") or 0)
    if not row.get("assignment_source") and activity_id > 0:
        try:
            from .project_inference_service import get_assignment_for_activity

            assignment = get_assignment_for_activity(activity_id)
        except Exception:
            assignment = {}
        if assignment:
            row["assignment_source"] = assignment.get("source")
            row["assignment_is_manual"] = assignment.get("is_manual")
            row["suggested_project_name"] = assignment.get("suggested_project_name")
            row["effective_project_id"] = assignment.get("project_id")
    effective_project_id = int(row.get("effective_project_id") or 0)
    if effective_project_id > 0 and not row.get("effective_project_name"):
        try:
            project = project_service.get_project(effective_project_id)
        except Exception:
            project = None
        if project:
            row["effective_project_name"] = project.get("name")
            row["effective_project_description"] = project.get("description")
    return row


def _anchor_project_from_official_fields(
    official: dict[str, Any],
    candidate: dict[str, Any],
) -> dict[str, Any]:
    project_id = int(official.get("display_project_id") or 0)
    project_name = str(official.get("display_project_name") or UNCATEGORIZED_PROJECT)
    project_description = str(official.get("display_project_description") or "")
    source = "uncategorized"
    if project_id > 0 and bool(official.get("is_official_project")):
        source = str(official.get("project_attribution_kind") or "official")
    return {
        "project_id": project_id if bool(official.get("is_official_project")) else 0,
        "project_name": project_name,
        "project_description": project_description,
        "display_project": {
            "id": project_id if bool(official.get("is_official_project")) else None,
            "name": project_name,
            "description": project_description,
            "source": source,
            "is_uncategorized": bool(official.get("is_uncategorized", True)),
            "is_suggested_project": False,
        },
        "candidate_project": candidate,
        "is_uncategorized": bool(official.get("is_uncategorized", True)),
        "is_classified": bool(official.get("is_classified")),
    }


def _hash(value: dict[str, Any]) -> str:
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


def _project_transition_revision_identity(transition: Any) -> dict[str, Any]:
    if not isinstance(transition, dict):
        return {}
    return {
        "pending": bool(transition.get("pending")),
        "from_project_id": transition.get("from_project_id"),
        "to_project_id": transition.get("to_project_id"),
    }

