"""Shared display-safe helpers for WebView bridge mixins."""

from __future__ import annotations

import re
from typing import Any

from ..api import view_model_api
from ..formatters import format_duration, format_safe_display_name

_GENERIC_ERROR: dict[str, Any] = {"ok": False, "error": "操作失败"}
_RECENT_LIMIT = 20
_DATE_SHAPE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _safe_resource_display_name(row: dict[str, Any]) -> str:
    return format_safe_display_name(row)


def _snapshot_summary(snapshot: dict[str, Any] | None) -> dict[str, Any]:
    return view_model_api.build_current_activity_summary(snapshot)


def _group_payload(group: dict[str, Any], *, project: bool = False) -> dict[str, Any]:
    payload = {
        "key": str(group.get("key") or ""),
        "display_name": str(group.get("display_name") or ""),
        "duration_seconds": int(group.get("duration_seconds") or 0),
        "duration": format_duration(group.get("duration_seconds") or 0),
        "activity_count": int(group.get("activity_count") or 0),
        "percentage": float(group.get("percentage") or 0.0),
    }
    if project:
        payload["is_concrete_project"] = bool(group.get("is_concrete_project"))
    return payload


def _statistics_summary_payload(summary: dict[str, Any]) -> dict[str, Any]:
    by_project = [
        _group_payload(group, project=True)
        for group in (summary.get("by_project") or [])
    ]
    by_app = [_group_payload(group) for group in (summary.get("by_app") or [])]
    by_status = [
        _group_payload(group) for group in (summary.get("by_status") or [])
    ]
    total_seconds = int(summary.get("total_duration_seconds") or 0)
    project_seconds = int(summary.get("project_duration_seconds") or 0)
    preview = summary.get("export_preview") or {}
    export_revision = str(summary.get("export_revision") or "")
    return {
        "date_from": str(summary.get("date_from") or ""),
        "date_to": str(summary.get("date_to") or ""),
        "snapshot_revision": str(summary.get("snapshot_revision") or ""),
        "export_revision": export_revision,
        "total_duration_seconds": total_seconds,
        "total_duration": format_duration(total_seconds),
        "project_duration_seconds": project_seconds,
        "project_duration": format_duration(project_seconds),
        "activity_count": int(summary.get("activity_count") or 0),
        "session_count": int(summary.get("session_count") or 0),
        "export_row_count": int(summary.get("export_row_count") or 0),
        "project_count": int(summary.get("project_count") or 0),
        "app_count": int(summary.get("app_count") or 0),
        "by_project": by_project,
        "by_app": by_app,
        "by_status": by_status,
        "export_preview": {
            "date_from": str(preview.get("date_from") or ""),
            "date_to": str(preview.get("date_to") or ""),
            "snapshot_revision": str(preview.get("snapshot_revision") or ""),
            "export_revision": str(
                preview.get("export_revision") or export_revision
            ),
            "included_activity_count": int(
                preview.get("included_activity_count") or 0
            ),
            "session_count": int(preview.get("session_count") or 0),
            "export_row_count": int(preview.get("export_row_count") or 0),
            "included_duration_seconds": int(
                preview.get("included_duration_seconds") or 0
            ),
            "included_duration": format_duration(
                preview.get("included_duration_seconds") or 0
            ),
            "available_formats": list(preview.get("available_formats") or []),
            "export_actions_enabled": bool(
                preview.get("export_actions_enabled")
            ),
        },
    }


__all__ = [
    "_DATE_SHAPE_RE",
    "_GENERIC_ERROR",
    "_RECENT_LIMIT",
    "_safe_resource_display_name",
    "_snapshot_summary",
    "_statistics_summary_payload",
]
