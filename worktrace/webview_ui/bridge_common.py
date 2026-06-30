"""Shared bridge helpers used by multiple bridge mixin modules.

This module was split out of ``bridge.py`` so that the page-level mixins
(``bridge_overview.py``, ``bridge_timeline.py``, ``bridge_statistics.py``,
``bridge_settings.py``, ``bridge_dialogs.py``) can share common validation,
payload-building, and display-safe helpers without reverse-importing
``bridge.py`` (which would create a circular dependency).

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

from ..api import timeline_api
from ..constants import STATUS_NORMAL, UNCATEGORIZED_PROJECT
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

    Only display-name, project, elapsed, and state are returned. Window titles,
    paths, and notes are never included.

    Also returns ``elapsed_seconds`` (raw integer seconds) and ``is_paused``
    so the frontend 1-second ticker can increment the display without a bridge
    round-trip. ``elapsed_seconds`` is the snapshot's total live seconds
    (elapsed + extra) at the moment the backend built the snapshot; the ticker
    adds ``(now - snapshot_at)`` only when the activity is running (not
    paused / not idle).

    Phase 6H-followup: also returns the display-safe structural fields
    ``status``, ``is_persisted``, ``project_name`` and ``persisted_activity_id``
    so Overview / Recent / Timeline can apply a unified live-projection
    decision without re-reading the raw snapshot. No raw ``window_title``,
    ``file_path_hint``, ``note`` or ``clipboard`` field is surfaced.
    """
    if not snapshot:
        return {
            "active": False,
            "display": "无",
            "elapsed_seconds": 0,
            "is_paused": False,
            "status": "",
            "is_persisted": False,
            "project_name": "",
            "persisted_activity_id": 0,
        }
    name = (
        snapshot.get("resource_display_name")
        or snapshot.get("activity_display_name")
        or snapshot.get("app_name")
        or snapshot.get("process_name")
        or "未知"
    )
    project = snapshot.get("inferred_project_name") or "未归类"
    elapsed_seconds = (
        (timeline_api.get_snapshot_elapsed_seconds(snapshot) or 0)
        + (timeline_api.get_snapshot_extra_seconds(snapshot) or 0)
    )
    elapsed = format_duration(elapsed_seconds)
    state = "已进入历史" if snapshot.get("is_persisted") else "暂不入历史"
    is_paused = snapshot.get("status") == "paused"
    if snapshot.get("status") == "idle":
        name = "空闲中"
    persisted_id = timeline_api.get_snapshot_persisted_id(snapshot) or 0
    return {
        "active": True,
        "display": f"{name}｜{project}｜{elapsed}｜{state}",
        "elapsed_seconds": int(elapsed_seconds),
        "is_paused": bool(is_paused),
        "status": str(snapshot.get("status") or ""),
        "is_persisted": bool(snapshot.get("is_persisted")),
        "project_name": str(snapshot.get("inferred_project_name") or ""),
        "persisted_activity_id": int(persisted_id or 0),
    }


def _can_live_project_snapshot(
    snapshot: dict[str, Any] | None,
    report_date: str | None,
    today: str | None,
) -> bool:
    """Return ``True`` iff the current snapshot is eligible for display
    projection on the given report date.

    The unified projection contract (Phase 6H-followup). Recent, Timeline
    session list, and Timeline detail projection must all use this helper
    so they apply the same eligibility rule. Projection is purely a UI
    overlay; it never writes the DB or changes collector persistence
    logic. The 30-second short-activity buffer is preserved.

    Eligibility (all must hold):
    - snapshot exists;
    - snapshot ``status == "normal"`` (excludes idle / paused / excluded / error);
    - snapshot is not persisted;
    - ``persisted_activity_id`` is empty / 0;
    - elapsed + extra seconds > 0;
    - the report date equals today (historical dates are not projected).

    The function only reads the snapshot dict and the date strings; it does
    not import services / db / collector / runtime / config / security.
    """
    if not snapshot:
        return False
    if str(snapshot.get("status") or "") != STATUS_NORMAL:
        return False
    if bool(snapshot.get("is_persisted")):
        return False
    if timeline_api.get_snapshot_persisted_id(snapshot):
        return False
    elapsed = (
        (timeline_api.get_snapshot_elapsed_seconds(snapshot) or 0)
        + (timeline_api.get_snapshot_extra_seconds(snapshot) or 0)
    )
    if elapsed <= 0:
        return False
    if not report_date or not today:
        return False
    return report_date == today


def _snapshot_live_projected_seconds(snapshot: dict[str, Any] | None) -> int:
    """Return the snapshot's live projected seconds at the moment the
    backend built the payload. The frontend adds ``(now - snapshot_at)``
    on top of this baseline. Pure helper; does not read services / db.
    """
    if not snapshot:
        return 0
    return int(
        (timeline_api.get_snapshot_elapsed_seconds(snapshot) or 0)
        + (timeline_api.get_snapshot_extra_seconds(snapshot) or 0)
    )


def _find_live_projection_target(
    sessions: list[dict[str, Any]],
    snapshot: dict[str, Any] | None,
    report_date: str | None,
    today: str | None,
) -> tuple[int, int] | None:
    """Find the session index that should receive the live projection and
    the projection seconds to add.

    Returns ``(index, projected_seconds)`` or ``None`` when projection
    does not apply.

    Rules:
    - If the snapshot is not live-projectable (see ``_can_live_project_snapshot``)
      return ``None``.
    - If any session already has ``is_in_progress == True`` the real live
      session already carries the live duration; return ``None`` to avoid
      double counting.
    - Otherwise pick the most recent session whose ``status`` is
      ``STATUS_NORMAL`` (sessions are sorted by start_time DESC, so the
      first normal session encountered is the most recent). idle / paused /
      excluded / error / mixed sessions are skipped.
    - If no normal session exists, return ``None`` (no row to project onto).
    - The returned ``projected_seconds`` is the backend response-time
      baseline; the frontend may only add the wall-clock delta on top.

    Pure helper; does not read services / db. Idle / paused / excluded /
    error sessions never receive projection time.
    """
    if not _can_live_project_snapshot(snapshot, report_date, today):
        return None
    for s in sessions:
        if bool(s.get("is_in_progress")):
            return None
    projected_seconds = _snapshot_live_projected_seconds(snapshot)
    if projected_seconds <= 0:
        return None
    for i, s in enumerate(sessions):
        if str(s.get("status") or "") == STATUS_NORMAL:
            return (i, projected_seconds)
    return None


def _normalize_project_name(name: str | None) -> str:
    """Normalize a project name for projection-target matching. Empty or
    whitespace-only names map to ``UNCATEGORIZED_PROJECT`` so an unnamed
    current activity aligns with the ``未归类`` session row.
    """
    s = str(name or "").strip()
    return s if s else UNCATEGORIZED_PROJECT


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
    "_can_live_project_snapshot",
    "_coerce_activity_ids",
    "_find_live_projection_target",
    "_normalize_project_name",
    "_safe_resource_display_name",
    "_snapshot_live_projected_seconds",
    "_snapshot_summary",
    "_statistics_summary_payload",
    "_validate_datetime_inputs",
    "_validate_split_time_input",
]
