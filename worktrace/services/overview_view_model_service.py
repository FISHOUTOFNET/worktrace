"""Overview page ViewModel owner."""

from __future__ import annotations

from typing import Any

from ..formatters import format_duration
from . import view_model_service
from .page_view_model_common import apply_structure_revision
from .report_projection_snapshot_service import build_visible_snapshot


def get_overview_view_model(today: str | None = None) -> dict[str, Any]:
    payload = view_model_service.get_overview_view_model(today)
    scoped_today = str(payload.get("date") or today or "")
    snapshot = build_visible_snapshot(scoped_today, scoped_today)
    standalone = [
        dict(entry)
        for entry in snapshot.standalone_status_entries
        if not bool(entry.get("is_in_progress"))
    ]

    # Status-only excluded intervals contribute to canonical totals but are
    # intentionally absent from Recent. Timeline remains their anonymous view.
    payload["activities"] = list(payload.get("activities") or [])[:20]
    extra = sum(int(row.get("duration_seconds") or 0) for row in standalone)
    total = int(payload.get("today_total_seconds") or 0) + extra
    payload["today_total_seconds"] = total
    payload["today_total_base_seconds"] = int(
        payload.get("today_total_base_seconds") or 0
    ) + extra
    kpi_base = dict(payload.get("kpi_live_base") or {})
    kpi_base["today_total_seconds"] = int(
        kpi_base.get("today_total_seconds") or 0
    ) + extra
    payload["kpi_live_base"] = kpi_base

    concrete_projects = {
        int(row.get("report_project_id") or row.get("project_id") or 0)
        for row in snapshot.final_contributions
        if bool(row.get("is_report_project"))
        and int(row.get("report_project_id") or row.get("project_id") or 0) > 0
        and not bool(row.get("report_project_is_deleted"))
    }
    overview = dict(payload.get("overview") or {})
    overview.update(
        {
            "today_total_seconds": total,
            "total_duration": format_duration(total),
            "project_count": len(concrete_projects),
        }
    )
    payload["overview"] = overview
    apply_structure_revision(
        payload,
        report_date=scoped_today,
        today=scoped_today,
        snapshot=snapshot,
    )
    return payload


__all__ = ["get_overview_view_model"]
