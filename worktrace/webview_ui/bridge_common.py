"""Shared bridge helpers used by multiple bridge mixin modules.

Holds the common validation, payload-building, and display-safe helpers
shared by the page-level mixins (``bridge_overview.py``,
``bridge_timeline.py``, ``bridge_statistics.py``, ``bridge_settings.py``,
``bridge_dialogs.py``). Lives outside ``bridge.py`` so the mixins can
import it without reverse-importing ``bridge.py`` (which would create a
circular dependency).

Boundary rules (enforced by ``tests/test_ui_backend_boundary.py``):

- This module may import ``worktrace.api``, ``worktrace.constants``,
  ``worktrace.formatters``, and stdlib only. It must NOT import
  ``worktrace.services``, ``worktrace.db``, ``worktrace.collector``,
  ``worktrace.security``, ``worktrace.runtime``, or ``worktrace.config``.
- Helpers return JSON-serializable dicts/lists/scalars only.
- Helpers never log window titles, file paths, notes, or copied text.
- The generic error payload and date/datetime regexes live here so every
  mixin uses the same constants.
"""

from __future__ import annotations

import re
from typing import Any

from ..api import view_model_api
from ..formatters import format_duration, format_safe_display_name

# The generic bridge-level error payload. Every mixin method that catches
# an unexpected exception returns ``dict(_GENERIC_ERROR)`` so the frontend
# always sees ``{"ok": false, "error": "操作失败"}``.
_GENERIC_ERROR: dict[str, Any] = {"ok": False, "error": "操作失败"}

# Maximum number of recent activities returned by ``get_recent_activities``.
_RECENT_LIMIT: int = 20

# Lightweight ``YYYY-MM-DD`` shape check at the bridge layer. The API layer
# performs the full ``date.fromisoformat`` validation; this guard just gives
# the user a clearer "日期无效" message instead of the generic "操作失败"
# when the date string is obviously malformed.
_DATE_SHAPE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Lightweight ``YYYY-MM-DD HH:MM:SS`` shape check at the bridge layer. The
# API layer performs the full ``datetime.strptime`` validation; this guard
# gives the user a clearer "时间无效" message for obviously malformed input.
_DATETIME_SHAPE_RE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")


def _coerce_activity_ids(activity_ids: list[int]) -> list[int] | None:
    """Validate and normalize the ``activity_ids`` argument from JS.

    Returns a deduplicated list of positive ints, or ``None`` if the input
    is not a usable list of positive integers. This is a bridge-level guard
    so the API layer always receives clean ints; the API layer performs the
    deeper existence checks. ``bool`` values are rejected explicitly so
    ``True``/``False`` are not coerced to ``1``/``0``.
    """
    if not isinstance(activity_ids, list) or not activity_ids:
        return None
    ids: list[int] = []
    seen: set[int] = set()
    for raw in activity_ids:
        if isinstance(raw, bool):
            return None
        try:
            value = int(raw)
        except (TypeError, ValueError):
            return None
        if value <= 0:
            return None
        if value in seen:
            continue
        seen.add(value)
        ids.append(value)
    return ids if ids else None


def _validate_datetime_inputs(start_time: str, end_time: str) -> str | None:
    """Bridge-level guard for ``start_time`` / ``end_time`` inputs.

    Returns ``None`` if both values pass the lightweight shape check, or a
    Chinese error message string otherwise. The API layer performs the full
    ``datetime.strptime`` validation and the ``start < end`` ordering check;
    this guard just gives the user a clearer ``"时间无效"`` message for
    obviously malformed input (non-strings, empty, wrong shape).
    """
    if not isinstance(start_time, str) or not isinstance(end_time, str):
        return "时间无效"
    if not start_time or not end_time:
        return "时间无效"
    if not _DATETIME_SHAPE_RE.match(start_time) or not _DATETIME_SHAPE_RE.match(end_time):
        return "时间无效"
    return None


def _validate_split_time_input(split_time: str) -> str | None:
    """Bridge-level guard for the ``split_time`` input.

    Returns ``None`` if the value passes the lightweight shape check, or a
    Chinese error message string otherwise. The API layer performs the full
    ``datetime.strptime`` validation and the strict range check; this guard
    just gives the user a clearer ``"拆分时间无效"`` message for obviously
    malformed input (non-string, empty, wrong shape).
    """
    if not isinstance(split_time, str) or not split_time:
        return "拆分时间无效"
    if not _DATETIME_SHAPE_RE.match(split_time):
        return "拆分时间无效"
    return None


def _safe_resource_display_name(row: dict[str, Any]) -> str:
    """Return a display-safe resource name for a Timeline detail row.

    Delegates to the shared ``formatters.format_safe_display_name`` helper
    so the Timeline detail rows and the CSV export use the same
    display-safe fallback chain (``resource_display_name`` →
    ``activity_display_name`` → ``app_name`` → ``process_name`` → ``未知``)
    without the bridge reverse-depending on the export service.

    The raw ``window_title`` column is **deliberately skipped** because it
    can contain full file paths, URLs, or email subjects. ``file_path_hint``
    and ``note`` are also skipped. If all safe fields are empty the row
    falls back to ``"未知"`` rather than leaking sensitive metadata.
    """
    return format_safe_display_name(row)


def _snapshot_summary(snapshot: dict[str, Any] | None) -> dict[str, Any]:
    """Build a non-sensitive current-activity summary from the snapshot.

    Thin delegate to the unified live-display model
    (``view_model_api.build_current_activity_summary``). Only display-name,
    project, elapsed, and state are returned. Window titles, paths, and
    notes are never included.

    The unified payload also carries ``elapsed_seconds`` (raw integer
    seconds), ``is_paused``, ``status``, ``is_persisted``,
    ``project_name``, ``persisted_activity_id``, ``live_state``,
    ``is_in_progress``, ``is_virtual_live``, ``live_display_key``,
    ``resource_name``, ``app_name``, ``start_time``, ``end_time``,
    ``activity_id``, ``source``, ``is_uncategorized`` and
    ``is_classified`` so Overview / Recent / Timeline can apply a single
    live-projection decision without re-reading the raw snapshot.
    """
    return view_model_api.build_current_activity_summary(snapshot)


def _statistics_summary_payload(summary: dict[str, Any]) -> dict[str, Any]:
    """Build the display-safe statistics summary for JS.

    The service already returns a display-safe dict; this helper adds
    pre-formatted duration strings (matching the Timeline bridge convention)
    so the frontend can render without a second bridge round-trip. Only
    aggregated numbers and display names are surfaced — raw ``window_title``,
    ``file_path_hint``, ``full_path``, ``clipboard``, ``note``, SQL, and
    tracebacks are never present.
    """
    by_project = [
        {
            "key": str(group.get("key") or ""),
            "display_name": str(group.get("display_name") or ""),
            "duration_seconds": int(group.get("duration_seconds") or 0),
            "duration": format_duration(group.get("duration_seconds") or 0),
            "activity_count": int(group.get("activity_count") or 0),
            "percentage": float(group.get("percentage") or 0.0),
        }
        for group in (summary.get("by_project") or [])
    ]
    by_app = [
        {
            "key": str(group.get("key") or ""),
            "display_name": str(group.get("display_name") or ""),
            "duration_seconds": int(group.get("duration_seconds") or 0),
            "duration": format_duration(group.get("duration_seconds") or 0),
            "activity_count": int(group.get("activity_count") or 0),
            "percentage": float(group.get("percentage") or 0.0),
        }
        for group in (summary.get("by_app") or [])
    ]
    by_status = [
        {
            "key": str(group.get("key") or ""),
            "display_name": str(group.get("display_name") or ""),
            "duration_seconds": int(group.get("duration_seconds") or 0),
            "duration": format_duration(group.get("duration_seconds") or 0),
            "activity_count": int(group.get("activity_count") or 0),
            "percentage": float(group.get("percentage") or 0.0),
        }
        for group in (summary.get("by_status") or [])
    ]
    total_seconds = int(summary.get("total_duration_seconds") or 0)
    preview = summary.get("export_preview") or {}
    return {
        "date_from": str(summary.get("date_from") or ""),
        "date_to": str(summary.get("date_to") or ""),
        "total_duration_seconds": total_seconds,
        "total_duration": format_duration(total_seconds),
        "activity_count": int(summary.get("activity_count") or 0),
        "project_count": int(summary.get("project_count") or 0),
        "app_count": int(summary.get("app_count") or 0),
        "by_project": by_project,
        "by_app": by_app,
        "by_status": by_status,
        "export_preview": {
            "date_from": str(preview.get("date_from") or ""),
            "date_to": str(preview.get("date_to") or ""),
            "included_activity_count": int(preview.get("included_activity_count") or 0),
            "included_duration_seconds": int(preview.get("included_duration_seconds") or 0),
            "included_duration": format_duration(preview.get("included_duration_seconds") or 0),
            "available_formats": list(preview.get("available_formats") or []),
            "export_actions_enabled": bool(preview.get("export_actions_enabled")),
        },
    }


__all__ = [
    "_DATETIME_SHAPE_RE",
    "_DATE_SHAPE_RE",
    "_GENERIC_ERROR",
    "_RECENT_LIMIT",
    "_coerce_activity_ids",
    "_safe_resource_display_name",
    "_snapshot_summary",
    "_statistics_summary_payload",
    "_validate_datetime_inputs",
    "_validate_split_time_input",
]
