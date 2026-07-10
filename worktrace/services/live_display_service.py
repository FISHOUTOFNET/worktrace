"""Low-level display-safe helpers for the unified Activity Display Model.

This module is NOT the page live-display model owner. The owner is
:mod:`worktrace.services.activity_display_model_service`, which solely
decides live-eligibility and ``live_state`` (``persisted_open`` for normal
activity),
display span identity, and visibility of live rows.

This module retains ONLY the low-level pure helpers used by
``activity_display_model_service`` and the bridge / settings layers:
display-safe field extraction, stable live identity
(``_stable_live_key`` / ``_stable_live_key_hash``), live-clock anchor,
current-activity summary (``build_current_activity_summary``),
refresh-revision computation (``compute_refresh_revision``), classification,
and the persisted-open live-seconds helper.

Display projection is purely a UI overlay. It NEVER writes the DB or changes
collector lifecycle. Returns display-safe JSON-serializable
payloads only — raw ``window_title``, ``file_path_hint``, ``note``,
``clipboard`` and any traceback / SQL are NEVER surfaced.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any

from ..constants import (
    STATUS_ERROR,
    STATUS_EXCLUDED,
    STATUS_IDLE,
    STATUS_NORMAL,
    STATUS_PAUSED,
    UNCATEGORIZED_PROJECT,
)
from ..contracts.live_display_contracts import (
    ActivitySnapshotContract,
    CurrentActivityContract,
)
from . import activity_service, timeline_service
from .live_time_service import (
    safe_int,
    snapshot_elapsed_seconds,
    snapshot_extra_seconds,
    snapshot_persisted_id,
    snapshot_seconds_for_date_range,
    snapshot_start_time,
)
from .project_attribution_policy import is_official_project_source
from .activity_display_projection import build_revision_parts
from .settings_service import get_setting


# Constants

# Maximum look-back for the open-row live-duration recompute. Prevents a
# stale snapshot start_time from producing an absurd 100-hour live value
# when the wall clock has drifted (e.g. system sleep).
_MAX_LIVE_DURATION_SECONDS = 36 * 60 * 60


# Live-state classification


def _snapshot_status(snapshot: ActivitySnapshotContract | None) -> str:
    if not snapshot:
        return ""
    return str(snapshot.get("status") or "")


def classify_live_state(snapshot: ActivitySnapshotContract | None) -> str:
    """Return the unified live-state label for a snapshot.

    Returns one of:

    - ``"none"``         — no snapshot / unsupported status.
    - ``"persisted_open"`` — normal, persisted with a real open DB row.
    - ``"paused"``       — status == paused.
    - ``"idle"``         — status == idle.
    - ``"excluded"``     — status == excluded.
    - ``"error"``        — status == error.

    Only ``"persisted_open"`` is eligible to increment the normal project
    live duration. ``"paused"`` / ``"idle"`` /
    ``"excluded"`` / ``"error"`` may still render a status line but MUST
    NOT contribute to normal project live duration.
    """
    if not snapshot:
        return "none"
    status = _snapshot_status(snapshot)
    if status == STATUS_PAUSED:
        return "paused"
    if status == STATUS_IDLE:
        return "idle"
    if status == STATUS_EXCLUDED:
        return "excluded"
    if status == STATUS_ERROR:
        return "error"
    if status != STATUS_NORMAL:
        return "none"
    if bool(snapshot.get("is_persisted")) or snapshot_persisted_id(snapshot):
        return "persisted_open"
    # A normal snapshot without its required persisted row is invalid.
    # Fail closed rather than creating a display-only activity.
    return "none"


def is_live_eligible_for_normal(
    snapshot: ActivitySnapshotContract | None,
    report_date: str | None,
    today: str | None,
) -> bool:
    """Return ``True`` iff the snapshot should drive the *normal* live
    display (current-activity area / Overview KPI increment / live span
    overlay onto a matching DB row).

    Eligibility (all must hold):

    - snapshot exists;
    - snapshot ``status == "normal"`` (excludes idle / paused / excluded /
      error);
    - report_date == today (historical dates are not projected).

    Normal snapshots are eligible only when backed by a persisted open row.
    """
    if not snapshot:
        return False
    if _snapshot_status(snapshot) != STATUS_NORMAL:
        return False
    if classify_live_state(snapshot) != "persisted_open":
        return False
    if not report_date or not today:
        return False
    return report_date == today


def _snapshot_total_seconds(snapshot: ActivitySnapshotContract | None) -> int:
    if not snapshot:
        return 0
    return snapshot_elapsed_seconds(snapshot) + snapshot_extra_seconds(snapshot)


# Display-safe field extraction


def _display_resource_name(snapshot: ActivitySnapshotContract | None) -> str:
    """Return a display-safe resource name from the snapshot.

    Falls back through ``resource_display_name`` →
    ``activity_display_name`` → ``app_name`` → ``process_name`` → ``未知``.
    Raw ``window_title`` / ``file_path_hint`` are NEVER surfaced.
    """
    if not snapshot:
        return "未知"
    name = (
        snapshot.get("resource_display_name")
        or snapshot.get("activity_display_name")
        or snapshot.get("app_name")
        or snapshot.get("process_name")
    )
    return str(name or "未知").strip() or "未知"


def _display_app_name(snapshot: ActivitySnapshotContract | None) -> str:
    if not snapshot:
        return ""
    return str(snapshot.get("app_name") or "").strip()


def _snapshot_display_project_dict(
    snapshot: ActivitySnapshotContract | None,
) -> dict[str, Any] | None:
    """Return the display-safe ``display_project`` dict from a snapshot.

    Reads the structured ``display_project`` block written by the
    project-ownership state machine. Returns ``None`` when the snapshot
    has no structured block; callers then resolve through the
    official-only ``_display_project_name`` policy.
    """
    if not snapshot:
        return None
    dp = snapshot.get("display_project")
    if isinstance(dp, dict) and dp:
        return dp
    return None


def _project_transition_for_display(snapshot: ActivitySnapshotContract | None) -> dict[str, Any]:
    """Return the compatibility-shaped, permanently non-pending transition.

    Old runtime snapshots may contain a pending confirmation window. It is
    deliberately ignored at the display boundary so stale state cannot
    resurrect project inheritance.
    """
    return {
        "pending": False,
        "started_at": "",
        "elapsed_seconds": 0,
        "threshold_seconds": 0,
        "from_project_id": None,
        "to_project_id": None,
    }


def _official_project_name_for_persisted_row(activity_id: int) -> str:
    """Return the official project name for a persisted open DB row, or ``""``.

    Checks the assignment source via ``project_attribution_policy``. Only
    official sources (``manual`` / ``keyword_rule`` / ``folder_rule``)
    surface the project name; suggested / context-derived / uncategorized
    return ``""`` so the caller falls back to ``UNCATEGORIZED_PROJECT``.
    """
    try:
        from .project_inference_service import get_assignment_for_activity

        assignment = get_assignment_for_activity(activity_id)
    except Exception:
        return ""
    if not assignment:
        return ""
    source = str(assignment.get("source") or "").strip()
    if not is_official_project_source(source):
        return ""
    project_id = assignment.get("project_id")
    if project_id is None:
        return ""
    from ..db import get_connection

    try:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT name FROM project WHERE id = ?", (int(project_id),)
            ).fetchone()
    except Exception:
        return ""
    name = str(row["name"]).strip() if row else ""
    return name if name and name != UNCATEGORIZED_PROJECT else ""


def _display_project_name(snapshot: ActivitySnapshotContract | None) -> str:
    """Return the unified display project name for a snapshot.

    The display project is sourced from the structured
    ``display_project`` block (written by the project-ownership state
    machine, which only places official labels there). When a persisted
    snapshot has no structured block, the DB row is checked via
    ``project_attribution_policy`` — only official sources surface a
    project name; suggested / context-derived / uncategorized all resolve
    to ``UNCATEGORIZED_PROJECT``. Snapshots without a structured block also
    stay uncategorized.
    """
    if not snapshot:
        return UNCATEGORIZED_PROJECT
    dp = _snapshot_display_project_dict(snapshot)
    if dp and is_official_project_source(str(dp.get("source") or "")):
        name = str(dp.get("name") or "").strip()
        if name:
            return name
    persisted_id = snapshot_persisted_id(snapshot)
    if persisted_id:
        official = _official_project_name_for_persisted_row(int(persisted_id))
        if official:
            return official
        # Persisted row has a non-official assignment source (suggested /
        # context-derived / uncategorized). Return uncategorized — do NOT
        # fall back to ``inferred_project_name`` which may carry the
        # suggested project name and leak it into the formal display.
        return UNCATEGORIZED_PROJECT
    # Incomplete snapshots stay uncategorized instead of leaking raw
    # inferred/candidate metadata into official display fields.
    return UNCATEGORIZED_PROJECT


def _display_project_description(snapshot: ActivitySnapshotContract | None) -> str:
    """Return the display project description for a snapshot.

    Reads the structured ``display_project.description`` block when
    present. Otherwise resolves the display project name (via the
    policy-aware ``_display_project_name``) and looks up the concrete
    project's description by name when the project is official. Returns
    ``""`` for uncategorized / suggested / context-derived projects.
    """
    if not snapshot:
        return ""
    dp = _snapshot_display_project_dict(snapshot)
    if dp and is_official_project_source(str(dp.get("source") or "")):
        return str(dp.get("description") or "")
    dp_name = _display_project_name(snapshot)
    if dp_name and dp_name != UNCATEGORIZED_PROJECT:
        from . import project_service

        existing = project_service.get_project_by_name(dp_name)
        if existing:
            return str(existing.get("description") or "")
    return ""


def _stable_live_key(snapshot: ActivitySnapshotContract | None) -> str:
    """Build a STABLE live identity for the current activity.

    Unlike ``_live_display_key``, this key does NOT include
    ``is_persisted`` / ``persisted_activity_id`` / ``inferred_project_name``
    so refreshes preserve one stable continuity anchor for the persisted open
    activity.

    The key is constructed ONLY from sanitized display fields
    (``resource_display_name`` / ``activity_display_name`` / ``app_name`` /
    ``process_name`` / ``start_time`` / ``status``). Raw ``window_title``,
    ``file_path_hint``, ``note`` and ``clipboard`` are NEVER included.
    """
    if not snapshot:
        return ""
    parts = [
        str(snapshot.get("resource_display_name") or ""),
        str(snapshot.get("activity_display_name") or ""),
        str(snapshot.get("app_name") or ""),
        str(snapshot.get("process_name") or ""),
        str(snapshot.get("start_time") or ""),
        str(snapshot.get("status") or ""),
    ]
    return "|".join(parts)


def _stable_live_key_hash(snapshot: ActivitySnapshotContract | None) -> str:
    """Return a short hash of the stable_live_key for use in UI ids."""
    key = _stable_live_key(snapshot)
    if not key:
        return ""
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]


def _start_time_epoch_ms(snapshot: ActivitySnapshotContract | None) -> int:
    """Convert the snapshot's ``start_time`` (``YYYY-MM-DD HH:MM:SS``) to
    epoch milliseconds.

    Returns ``0`` when the snapshot is missing or the start_time cannot
    be parsed. Used by the unified live clock so the frontend can compute
    ``display_seconds = carry_seconds + floor((Date.now() -
    live_started_at_epoch_ms) / 1000)`` from a single stable start-time
    anchor.
    """
    if not snapshot:
        return 0
    start_time = str(snapshot.get("start_time") or "")
    if not start_time:
        return 0
    try:
        dt = datetime.strptime(start_time, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return 0
    return int(dt.timestamp() * 1000)


def _live_display_key(snapshot: ActivitySnapshotContract | None) -> str:
    """Build a display-safe live-display identity for the current activity.

    The key is constructed ONLY from sanitized display fields
    (``resource_display_name`` / ``activity_display_name`` / ``app_name`` /
    ``process_name`` / ``start_time`` /
    ``status`` / ``is_persisted`` / ``persisted_activity_id``). Raw
    ``window_title``, ``file_path_hint``, ``note`` and ``clipboard`` are
    NEVER included.

    The returned value is used as the JS-side ``live_display_key`` so the
    ticker can decide when a continuity-key reset is allowed (e.g. activity
    switched, status switched, persisted state switched). Revision inputs are
    independently defined by ``build_revision_parts()``; candidate and
    suggested project metadata never participate in this continuity key.
    """
    if not snapshot:
        return ""
    parts = [
        str(snapshot.get("resource_display_name") or ""),
        str(snapshot.get("activity_display_name") or ""),
        str(snapshot.get("app_name") or ""),
        str(snapshot.get("process_name") or ""),
        str(snapshot.get("start_time") or ""),
        str(snapshot.get("status") or ""),
        "1" if bool(snapshot.get("is_persisted")) else "0",
        str(int(snapshot.get("persisted_activity_id") or 0)),
    ]
    return "|".join(parts)


# Unified live-display payload builders


def build_current_activity_summary(
    snapshot: ActivitySnapshotContract | None,
    report_date: str | None = None,
    today: str | None = None,
) -> CurrentActivityContract:
    """Build the unified current-activity summary consumed by Overview,
    Timeline header, and the heartbeat revision check.

    The payload is display-safe: no raw ``window_title``,
    ``file_path_hint``, ``note``, ``clipboard``, ``traceback``, or SQL.
    """
    if not snapshot:
        return {
            "active": False,
            "display": "无",
            "elapsed_seconds": 0,
            "resource_elapsed_seconds": 0,
            "is_paused": False,
            "status": "",
            "is_persisted": False,
            "project_name": "",
            "project_id": 0,
            "persisted_activity_id": 0,
            "live_state": "none",
            "is_in_progress": False,
            "is_virtual_live": False,
            "live_display_key": "",
            "stable_live_key": "",
            "stable_live_key_hash": "",
            "live_started_at_epoch_ms": 0,
            "carry_seconds": 0,
            "resource_name": "",
            "app_name": "",
            "start_time": "",
            "end_time": None,
            "activity_id": None,
            "source": "none",
            "is_uncategorized": True,
            "is_classified": False,
            "project_description": "",
            "display_project": None,
            "candidate_project": None,
            "project_transition": {
                "pending": False,
                "started_at": "",
                "elapsed_seconds": 0,
                "threshold_seconds": 0,
                "from_project_id": None,
                "to_project_id": None,
            },
            "project_transition_pending": False,
        }
    if today is None:
        today = timeline_service.get_default_report_date()
    if report_date is None:
        report_date = today
    live_state = classify_live_state(snapshot)
    elapsed_seconds = _snapshot_total_seconds(snapshot)
    project_name = _display_project_name(snapshot)
    project_description = _display_project_description(snapshot)
    resource_name = _display_resource_name(snapshot)
    app_name = _display_app_name(snapshot)
    start_time = str(snapshot.get("start_time") or "")
    status = _snapshot_status(snapshot)
    is_paused = status == STATUS_PAUSED
    is_persisted = bool(snapshot.get("is_persisted"))
    persisted_id = snapshot_persisted_id(snapshot) or 0
    # Normal activity must always represent a real persisted open DB row.
    is_in_progress = live_state == "persisted_open"
    is_virtual_live = False
    is_uncategorized = (
        not project_name or project_name == UNCATEGORIZED_PROJECT
    )
    carry_seconds = 0
    display_seconds = elapsed_seconds + carry_seconds
    # Project ownership fields surfaced verbatim (display-safe) from the
    # snapshot's structured display_project / candidate_project block.
    display_project_dict = _snapshot_display_project_dict(snapshot) or {
        "id": None,
        "name": project_name,
        "description": project_description,
        "source": "uncategorized",
        "is_uncategorized": is_uncategorized,
        "is_suggested_project": False,
    }
    candidate_project_dict = snapshot.get("candidate_project") if snapshot else None
    if not isinstance(candidate_project_dict, dict) or not candidate_project_dict:
        candidate_project_dict = display_project_dict
    project_transition_dict = _project_transition_for_display(snapshot)
    project_transition_pending = False
    # Unified live clock: the frontend computes display_seconds =
    # carry_seconds + floor((Date.now() - live_started_at_epoch_ms) / 1000)
    # so the current activity doesn't jump across refreshes. start_time is
    # the stable anchor; both fields come from the SAME snapshot sample.
    live_started_at_epoch_ms = _start_time_epoch_ms(snapshot)
    from ..formatters import format_duration

    state_label = "进行中" if is_persisted else "活动状态异常"
    if status == STATUS_IDLE:
        resource_name = "空闲中"
        state_label = "空闲"
    elif status == STATUS_PAUSED:
        state_label = "已暂停"
    elif status == STATUS_EXCLUDED:
        state_label = "已排除"
    elif status == STATUS_ERROR:
        state_label = "异常"
    display = f"{resource_name}｜{project_name}｜{format_duration(display_seconds)}｜{state_label}"
    dp_id = display_project_dict.get("id") if isinstance(display_project_dict, dict) else None
    return {
        "active": True,
        "display": display,
        "elapsed_seconds": int(display_seconds),
        "resource_elapsed_seconds": int(snapshot_elapsed_seconds(snapshot)),
        "is_paused": bool(is_paused),
        "status": status,
        "is_persisted": is_persisted,
        "project_name": project_name,
        "project_id": int(dp_id) if dp_id is not None else 0,
        "persisted_activity_id": int(persisted_id or 0),
        "live_state": live_state,
        "is_in_progress": bool(is_in_progress),
        "is_virtual_live": bool(is_virtual_live),
        "live_display_key": _live_display_key(snapshot),
        "stable_live_key": _stable_live_key(snapshot),
        "stable_live_key_hash": _stable_live_key_hash(snapshot),
        # Unified live clock fields. The frontend computes
        # ``carry_seconds + floor((Date.now() - live_started_at_epoch_ms) / 1000)``.
        "live_started_at_epoch_ms": int(live_started_at_epoch_ms or 0),
        "carry_seconds": int(carry_seconds),
        "resource_name": resource_name,
        "app_name": app_name,
        "start_time": start_time,
        "end_time": None,
        "activity_id": int(persisted_id or 0) or None,
        "source": "db" if is_in_progress else "none",
        "is_uncategorized": bool(is_uncategorized),
        "is_classified": not bool(is_uncategorized),
        # Project ownership fields (display-safe).
        "project_description": project_description,
        "display_project": display_project_dict,
        "candidate_project": candidate_project_dict,
        "project_transition": project_transition_dict,
        "project_transition_pending": project_transition_pending,
    }


def _snapshot_display_project_fields(
    snapshot: ActivitySnapshotContract | None,
) -> dict[str, Any]:
    """Return the full set of display-facing project fields from a snapshot.

    Centralizes project-field extraction so the unified Activity Display
    Model can apply the SAME source of truth for project attribution
    across the live span overlay and the current-activity summary. The
    snapshot display project is honored only when it has an official source.

    Returns a dict with: ``project_id``, ``project_name``,
    ``project_description``, ``display_project``, ``candidate_project``,
    ``project_transition``, ``project_transition_pending``,
    ``is_uncategorized``, ``is_classified``, ``status``, ``start_time``.
    """
    project_name = _display_project_name(snapshot)
    project_description = _display_project_description(snapshot)
    is_uncategorized = (
        not project_name or project_name == UNCATEGORIZED_PROJECT
    )
    snapshot_dp = _snapshot_display_project_dict(snapshot)
    display_project_dict = snapshot_dp or {
        "id": None,
        "name": project_name,
        "description": project_description,
        "source": "uncategorized",
        "is_uncategorized": is_uncategorized,
        "is_suggested_project": False,
    }
    candidate_project_dict = snapshot.get("candidate_project") if snapshot else None
    if not isinstance(candidate_project_dict, dict) or not candidate_project_dict:
        candidate_project_dict = display_project_dict
    project_transition_dict = _project_transition_for_display(snapshot)
    dp_id = display_project_dict.get("id")
    # DB fallback only when snapshot has no structured display_project block.
    # Assignment source is policy-checked: only official sources surface a project_id.
    if dp_id is None and snapshot_dp is None:
        persisted_id = snapshot_persisted_id(snapshot) if snapshot else None
        if persisted_id:
            official = _official_project_name_for_persisted_row(int(persisted_id))
            if official:
                # Re-fetch the id alongside the name to keep them consistent.
                try:
                    from .project_inference_service import get_assignment_for_activity

                    assignment = get_assignment_for_activity(int(persisted_id))
                    if assignment and is_official_project_source(
                        str(assignment.get("source") or "")
                    ):
                        dp_id = assignment.get("project_id")
                except Exception:
                    dp_id = None
    return {
        "project_id": int(dp_id) if dp_id is not None else 0,
        "project_name": project_name,
        "project_description": project_description,
        "display_project": display_project_dict,
        "candidate_project": candidate_project_dict,
        "project_transition": project_transition_dict,
        "project_transition_pending": False,
        "is_uncategorized": bool(is_uncategorized),
        "is_classified": not bool(is_uncategorized),
        "status": _snapshot_status(snapshot),
        "start_time": str(snapshot.get("start_time") or "") if snapshot else "",
    }


def persisted_open_live_seconds(
    snapshot: ActivitySnapshotContract | None,
    row: dict[str, Any] | None,
) -> int:
    """Return the live seconds for a persisted open DB row.

    Matches the snapshot's ``persisted_activity_id`` to the row's id and
    returns ``snapshot_elapsed + snapshot_extra``. Returns ``0`` when the
    snapshot / row mismatch or when no snapshot exists.
    """
    if not snapshot or not row:
        return 0
    try:
        row_id = int(row.get("id") or 0)
    except (TypeError, ValueError):
        return 0
    if row_id <= 0:
        return 0
    snapshot_id = snapshot_persisted_id(snapshot)
    if not snapshot_id or int(snapshot_id) != row_id:
        return 0
    return _snapshot_total_seconds(snapshot)


# Unified refresh-revision computation


def compute_refresh_revision(
    snapshot: ActivitySnapshotContract | None,
    collector_status: str,
    user_paused: bool,
    today: str,
    report_date: str | None = None,
    display_model: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any]]:
    """Compute split live/page revisions for the heartbeat path."""
    if report_date is None:
        report_date = today
    current_activity_key = _live_display_key(snapshot)
    current_status = _snapshot_status(snapshot)
    is_persisted = bool(snapshot and snapshot.get("is_persisted"))
    persisted_id = int(snapshot_persisted_id(snapshot) or 0) if snapshot else 0
    inferred_project = ""
    if snapshot:
        inferred_project = str(snapshot.get("inferred_project_name") or "")
    model = display_model or {}
    display_structural_signature = str(model.get("display_structural_signature") or "")
    marker: dict[str, Any] = {
        "row_count": 0,
        "visible_row_count": 0,
        "max_id": 0,
        "closed_max_updated_at": "",
        "max_updated_at": "",
        "open_row_count": 0,
        "open_max_id": 0,
        "open_max_updated_at": "",
        "open_end_time_presence": "",
        "hidden_count": 0,
        "deleted_count": 0,
    }
    try:
        marker = activity_service.get_activity_structure_marker_by_date(report_date)
    except Exception:
        pass
    revision_parts = build_revision_parts(
        model,
        marker,
        snapshot_status=current_status,
        collector_status=collector_status,
        user_paused=user_paused,
        today=today,
        report_date=report_date or "",
    )
    revision = revision_parts["refresh_revision"]
    debug_inputs = {
        "current_activity_key": current_activity_key,
        "current_status": current_status,
        "is_persisted": is_persisted,
        "persisted_id": persisted_id,
        "inferred_project": inferred_project,
        "collector_status": collector_status,
        "user_paused": user_paused,
        "today": today,
        "display_structural_signature": display_structural_signature,
        "structural_signature": revision_parts["page_structure_revision"],
        "live_clock_revision": revision_parts["live_clock_revision"],
        "live_state_revision": revision_parts["live_clock_revision"],
        "display_projection_revision": revision_parts["display_projection_revision"],
        "page_structure_revision": revision_parts["page_structure_revision"],
        "refresh_revision": revision,
        "activity_structure_marker": marker,
        "row_count": int(marker.get("row_count") or 0),
        "latest_id": int(marker.get("max_id") or 0),
        # Kept for debug visibility only — NOT part of live_state_revision.
        "latest_updated_at": str(marker.get("max_updated_at") or ""),
        "latest_kind": "",
    }
    return revision, debug_inputs


__all__ = [
    "build_current_activity_summary",
    "classify_live_state",
    "compute_refresh_revision",
    "is_live_eligible_for_normal",
    "persisted_open_live_seconds",
]
