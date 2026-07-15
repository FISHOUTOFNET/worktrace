"""ViewModel API facade — sole bridge-facing entry for page display payloads.

This boundary owns request-scoped canonical snapshot reuse and the small set of
cross-page canonical metadata that must not be reinterpreted independently by
Overview, Timeline, Statistics, or heartbeat consumers.
"""

from __future__ import annotations

from typing import Any

from ..services import view_model_service
from ..services.live_display_service import build_current_activity_summary
from ..services.report_projection_identity import stable_json_hash
from ..services.report_projection_snapshot_service import (
    build_visible_snapshot,
    snapshot_read_scope,
)
from ..services.timeline_service import get_default_report_date


def _entry_duration(entry: dict[str, Any]) -> int:
    return max(0, int(entry.get("duration_seconds") or 0))


def _apply_canonical_overview_metrics(
    payload: dict[str, Any], report_date: str
) -> dict[str, Any]:
    snapshot = build_visible_snapshot(report_date, report_date)
    entries = [dict(item) for item in snapshot.final_entries]
    contributions = [dict(item) for item in snapshot.final_contributions]

    total_seconds = sum(_entry_duration(item) for item in entries)
    classified_seconds = sum(
        max(0, int(item.get("duration_seconds") or 0))
        for item in contributions
        if bool(item.get("is_report_project"))
    )
    uncategorized_seconds = sum(
        max(0, int(item.get("duration_seconds") or 0))
        for item in contributions
        if bool(item.get("is_report_uncategorized"))
    )
    concrete_projects = {
        int(item.get("project_id") or 0)
        for item in contributions
        if bool(item.get("is_report_project"))
        and int(item.get("project_id") or 0) > 0
        and not bool(item.get("project_is_deleted"))
    }

    payload["today_total_seconds"] = total_seconds
    payload["classified_seconds"] = classified_seconds
    payload["uncategorized_seconds"] = uncategorized_seconds
    payload["project_count"] = len(concrete_projects)
    overview = payload.get("overview")
    if isinstance(overview, dict):
        overview["today_total_seconds"] = total_seconds
        overview["classified_seconds"] = classified_seconds
        overview["uncategorized_seconds"] = uncategorized_seconds
        overview["project_count"] = len(concrete_projects)
    return payload


def get_overview_view_model(today: str | None = None) -> dict[str, Any]:
    report_date = today or get_default_report_date()
    with snapshot_read_scope():
        payload = view_model_service.get_overview_view_model(report_date)
        return _apply_canonical_overview_metrics(payload, report_date)


def get_timeline_view_model(report_date: str | None = None) -> dict[str, Any]:
    with snapshot_read_scope():
        return view_model_service.get_timeline_view_model(report_date)


def get_session_activity_summary_view_model(
    *,
    report_date: str | None = None,
    projection_instance_key: str,
    expected_projection_revision: str | None = None,
) -> dict[str, Any]:
    with snapshot_read_scope():
        return view_model_service.get_session_activity_summary_view_model(
            report_date=report_date,
            projection_instance_key=projection_instance_key,
            expected_projection_revision=expected_projection_revision,
        )


def get_refresh_state_view_model(report_date: str | None = None) -> dict[str, Any]:
    scoped_date = report_date or get_default_report_date()
    with snapshot_read_scope():
        payload = view_model_service.get_refresh_state_view_model(scoped_date)
        snapshot = build_visible_snapshot(scoped_date, scoped_date)
        structure_revision = str(
            getattr(snapshot, "structure_revision", snapshot.snapshot_revision)
        )
        live_revision = str(payload.get("live_revision") or "")
        payload["structure_revision"] = structure_revision
        payload["page_revision"] = stable_json_hash(
            [structure_revision, live_revision]
        )
        return payload


__all__ = [
    "build_current_activity_summary",
    "get_overview_view_model",
    "get_refresh_state_view_model",
    "get_session_activity_summary_view_model",
    "get_timeline_view_model",
]
