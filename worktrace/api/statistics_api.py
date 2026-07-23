"""Statistics facade for the UI.

Wraps ``statistics_service`` for summary totals and per-project statistics
used by the Overview and Statistics pages. Display DTO shaping is owned here,
not by the WebView bridge.
"""

from __future__ import annotations

from typing import Any

from ..formatters import format_duration
from ..services import statistics_service


class StatisticsSummaryError(ValueError):
    """Raised by the read-only statistics/export summary for known user-facing failures.

    The ``code`` attribute is a stable token the WebView bridge maps to a
    Chinese message, so internal fields, ids, SQL, and tracebacks never
    enter bridge responses.
    """

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def get_summary(
    start_date: str,
    end_date: str,
) -> dict[str, Any]:
    return statistics_service.get_summary(start_date, end_date)


def get_project_stats(
    start_date: str,
    end_date: str,
) -> list[dict[str, Any]]:
    return statistics_service.get_project_stats(start_date, end_date)


def get_uncategorized_duration(start_date: str, end_date: str) -> int:
    return statistics_service.get_uncategorized_duration(start_date, end_date)


def get_statistics_export_summary(
    date_from: str, date_to: str, project_id: str | int | None = None
) -> dict[str, Any]:
    """Return the canonical read-only statistics and export-preview facts."""

    try:
        return statistics_service.get_statistics_export_summary(date_from, date_to, project_id)
    except StatisticsSummaryError:
        raise
    except ValueError as exc:
        code = str(exc)
        if code in ("invalid_date", "invalid_range", "range_too_large", "invalid_project"):
            raise StatisticsSummaryError(code)
        raise StatisticsSummaryError("operation_failed")
    except Exception:
        raise StatisticsSummaryError("operation_failed")


def get_statistics_export_view_model(
    date_from: str,
    date_to: str,
    project_id: str | int | None = None,
) -> dict[str, Any]:
    """Return the complete bridge-facing Statistics display envelope."""

    summary = get_statistics_export_summary(date_from, date_to, project_id)
    revision = str(summary.get("ticket_revision") or "")
    return {
        "summary": _statistics_summary_payload(summary),
        "export_ticket": {
            "date_from": str(summary.get("date_from") or date_from),
            "date_to": str(summary.get("date_to") or date_to),
            "revision": revision,
            "project_id": str(summary.get("project_id") or ""),
        },
    }


def format_export_duration(duration_seconds: int) -> str:
    """Format an export result at the API boundary."""

    return format_duration(int(duration_seconds or 0))


def _group_payload(group: dict[str, Any]) -> dict[str, Any]:
    seconds = int(group.get("duration_seconds") or 0)
    return {
        "key": str(group.get("key") or ""),
        "display_name": str(group.get("display_name") or ""),
        "duration_seconds": seconds,
        "duration": format_duration(seconds),
        "activity_count": int(group.get("activity_count") or 0),
        "percentage": float(group.get("percentage") or 0.0),
    }


def _statistics_summary_payload(summary: dict[str, Any]) -> dict[str, Any]:
    by_project = [
        _group_payload(group) for group in (summary.get("by_project") or [])
    ]
    by_app = [_group_payload(group) for group in (summary.get("by_app") or [])]
    by_status = [
        _group_payload(group) for group in (summary.get("by_status") or [])
    ]
    total_seconds = int(summary.get("total_duration_seconds") or 0)
    project_seconds = int(summary.get("project_duration_seconds") or 0)
    preview = summary.get("export_preview") or {}
    preview_seconds = int(preview.get("included_duration_seconds") or 0)
    return {
        "date_from": str(summary.get("date_from") or ""),
        "date_to": str(summary.get("date_to") or ""),
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
            "included_activity_count": int(
                preview.get("included_activity_count") or 0
            ),
            "session_count": int(preview.get("session_count") or 0),
            "export_row_count": int(preview.get("export_row_count") or 0),
            "included_duration_seconds": preview_seconds,
            "included_duration": format_duration(preview_seconds),
            "available_formats": list(preview.get("available_formats") or []),
            "export_actions_enabled": bool(
                preview.get("export_actions_enabled")
            ),
        },
    }


__all__ = [
    "StatisticsSummaryError",
    "format_export_duration",
    "get_project_stats",
    "get_statistics_export_summary",
    "get_statistics_export_view_model",
    "get_summary",
    "get_uncategorized_duration",
]
