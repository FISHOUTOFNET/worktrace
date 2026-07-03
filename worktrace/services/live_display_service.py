"""Low-level display-safe helpers and legacy-compatible helper provider.

This module is NOT the page live-display model owner. The page live
display model owner is
:mod:`worktrace.services.activity_display_model_service`, which is the
sole place that decides live-eligibility, the refined ``live_state``
(``virtual_pending`` / ``absorbed_pending`` / ``persisted_open``), the
display span identity, and visibility of live rows in recent / timeline /
details.

This module retains only low-level pure helpers used by
``activity_display_model_service`` and the bridge: display-safe field
extraction, stable live identity (``_stable_live_key`` /
``_stable_live_key_hash``), live-clock anchor, current-activity summary
(``build_current_activity_summary``), refresh-revision computation
(``compute_refresh_revision``), short-activity carry integration, and
legacy-compatible row-contract helpers (``build_live_row_contract`` /
``apply_live_row_contract``) kept as private/internal helpers for tests
and legacy callers. Page ViewModels must use
``activity_display_model_service.apply_live_span_to_row`` instead.

Display projection is purely a UI overlay. It NEVER writes the DB, NEVER
changes the 30-second collector persistence threshold, and NEVER persists
a <30s activity early. This service returns display-safe
JSON-serializable payloads only — raw ``window_title``,
``file_path_hint``, ``note``, ``clipboard`` and any traceback / SQL are
NEVER surfaced. The bridge layer reaches it through
``worktrace.api.live_display_api``.
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
from . import activity_service, timeline_service
from .live_time_service import (
    safe_int,
    snapshot_elapsed_seconds,
    snapshot_extra_seconds,
    snapshot_persisted_id,
    snapshot_seconds_for_date_range,
    snapshot_start_time,
    sync_short_activity_carry,
)
from .settings_service import get_setting


# Constants

# Maximum look-back for the open-row live-duration recompute. Prevents a
# stale snapshot start_time from producing an absurd 100-hour live value
# when the wall clock has drifted (e.g. system sleep).
_MAX_LIVE_DURATION_SECONDS = 36 * 60 * 60

# Stable disable-reason text surfaced on virtual session / detail rows so
# the frontend can show a tooltip explaining why edit / split / merge /
# hide / delete / restore are disabled.
_VIRTUAL_EDIT_DISABLE_REASON = "当前活动尚未进入历史，暂不能编辑"

# Sentinel activity id used for virtual (display-only) rows. Real DB rows
# always carry a positive int id; ``0`` / ``None`` is reserved for virtual.
_VIRTUAL_ACTIVITY_ID = 0


# Live-state classification


def _snapshot_status(snapshot: dict[str, Any] | None) -> str:
    if not snapshot:
        return ""
    return str(snapshot.get("status") or "")


def classify_live_state(snapshot: dict[str, Any] | None) -> str:
    """Return the unified live-state label for a snapshot.

    Returns one of:

    - ``"none"``         — no snapshot / no elapsed seconds.
    - ``"virtual"``      — normal, not persisted, no persisted_activity_id;
                            eligible for virtual live display.
    - ``"persisted_open"`` — normal, persisted with a real open DB row.
    - ``"paused"``       — status == paused.
    - ``"idle"``         — status == idle.
    - ``"excluded"``     — status == excluded.
    - ``"error"``        — status == error.

    Only ``"virtual"`` and ``"persisted_open"`` are eligible to increment
    the normal project live duration. ``"paused"`` / ``"idle"`` /
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
    elapsed = _snapshot_total_seconds(snapshot)
    if elapsed <= 0:
        return "none"
    if bool(snapshot.get("is_persisted")) or snapshot_persisted_id(snapshot):
        return "persisted_open"
    return "virtual"


def is_live_eligible_for_normal(
    snapshot: dict[str, Any] | None,
    report_date: str | None,
    today: str | None,
) -> bool:
    """Return ``True`` iff the snapshot should drive the *normal* live
    display (virtual session / virtual detail / recent live item /
    Overview KPI increment).

    Eligibility (all must hold):

    - snapshot exists;
    - snapshot ``status == "normal"`` (excludes idle / paused / excluded /
      error);
    - elapsed + extra seconds > 0;
    - report_date == today (historical dates are not projected).

    Persisted-open rows are ALSO eligible: they need the same continuous
    live increment, just sourced from the real DB row instead of a virtual
    row. The caller distinguishes the two via ``classify_live_state``.
    """
    if not snapshot:
        return False
    if _snapshot_status(snapshot) != STATUS_NORMAL:
        return False
    if _snapshot_total_seconds(snapshot) <= 0:
        return False
    if not report_date or not today:
        return False
    return report_date == today


def _snapshot_total_seconds(snapshot: dict[str, Any] | None) -> int:
    if not snapshot:
        return 0
    return snapshot_elapsed_seconds(snapshot) + snapshot_extra_seconds(snapshot)


# Display-safe field extraction


def _display_resource_name(snapshot: dict[str, Any] | None) -> str:
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


def _display_app_name(snapshot: dict[str, Any] | None) -> str:
    if not snapshot:
        return ""
    return str(snapshot.get("app_name") or "").strip()


def _snapshot_display_project_dict(snapshot: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return the display-safe ``display_project`` dict from a snapshot.

    Reads the structured ``display_project`` block written by the
    project-ownership state machine. Returns ``None`` when the snapshot
    has no structured block (callers fall back to ``_display_project_name``).
    """
    if not snapshot:
        return None
    dp = snapshot.get("display_project")
    if isinstance(dp, dict) and dp:
        return dp
    return None


def _display_project_name(snapshot: dict[str, Any] | None) -> str:
    """Return the unified display project name for a snapshot."""
    if not snapshot:
        return UNCATEGORIZED_PROJECT
    dp = _snapshot_display_project_dict(snapshot)
    if dp:
        name = str(dp.get("name") or "").strip()
        if name:
            return name
    persisted_id = snapshot_persisted_id(snapshot)
    if persisted_id:
        try:
            row = activity_service.get_activity(int(persisted_id))
        except Exception:
            row = None
        if row:
            db_name = str(row.get("project_name") or "").strip()
            if db_name and db_name != UNCATEGORIZED_PROJECT:
                return db_name
            try:
                from .project_inference_service import get_assignment_for_activity

                assignment = get_assignment_for_activity(int(persisted_id))
            except Exception:
                assignment = {}
            suggested = str(assignment.get("suggested_project_name") or "").strip()
            if suggested:
                return suggested
    name = str(snapshot.get("inferred_project_name") or "").strip()
    return name if name else UNCATEGORIZED_PROJECT


def _display_project_description(snapshot: dict[str, Any] | None) -> str:
    """Return the display project description for a snapshot.

    Reads the structured ``display_project.description`` block when
    present. Otherwise resolves the display project name (which falls
    back to ``inferred_project_name`` when no structured block exists)
    and looks up the concrete project's description by name. Returns
    ``""`` for uncategorized / suggested-project candidates (no concrete
    project row).
    """
    if not snapshot:
        return ""
    dp = _snapshot_display_project_dict(snapshot)
    if dp:
        return str(dp.get("description") or "")
    # No structured display_project block — resolve the display name and look
    # up the concrete project's description by name, mirroring
    # _display_project_name so description stays consistent with the name.
    dp_name = _display_project_name(snapshot)
    if dp_name and dp_name != UNCATEGORIZED_PROJECT:
        from . import project_service

        existing = project_service.get_project_by_name(dp_name)
        if existing:
            return str(existing.get("description") or "")
    return ""


def _stable_live_key(snapshot: dict[str, Any] | None) -> str:
    """Build a STABLE live identity for the current activity.

    Unlike ``_live_display_key``, this key does NOT include
    ``is_persisted`` / ``persisted_activity_id`` / ``inferred_project_name``
    so it remains the same when the activity transitions from virtual
    (unpersisted) to persisted_open. The frontend ticker uses this key as
    the continuity anchor so the duration display does not reset when the
    30-second persistence threshold is crossed.

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


def _stable_live_key_hash(snapshot: dict[str, Any] | None) -> str:
    """Return a short hash of the stable_live_key for use in UI ids."""
    key = _stable_live_key(snapshot)
    if not key:
        return ""
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]


def _start_time_epoch_ms(snapshot: dict[str, Any] | None) -> int:
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


def _live_display_key(snapshot: dict[str, Any] | None) -> str:
    """Build a display-safe live-display identity for the current activity.

    The key is constructed ONLY from sanitized display fields
    (``resource_display_name`` / ``activity_display_name`` / ``app_name`` /
    ``process_name`` / ``inferred_project_name`` / ``start_time`` /
    ``status`` / ``is_persisted`` / ``persisted_activity_id``). Raw
    ``window_title``, ``file_path_hint``, ``note`` and ``clipboard`` are
    NEVER included.

    The returned value is used as the JS-side ``live_display_key`` so the
    ticker can decide when a continuity-key reset is allowed (e.g. activity
    switched, status switched, persisted state switched). It is also part
    of ``refresh_revision`` so a structural identity change triggers a
    heavy refresh.
    """
    if not snapshot:
        return ""
    parts = [
        str(snapshot.get("resource_display_name") or ""),
        str(snapshot.get("activity_display_name") or ""),
        str(snapshot.get("app_name") or ""),
        str(snapshot.get("process_name") or ""),
        str(snapshot.get("inferred_project_name") or ""),
        str(snapshot.get("start_time") or ""),
        str(snapshot.get("status") or ""),
        "1" if bool(snapshot.get("is_persisted")) else "0",
        str(int(snapshot.get("persisted_activity_id") or 0)),
    ]
    return "|".join(parts)


# Short-activity carry integration


def _read_pending_short_seconds() -> int:
    """Read the pending_short_seconds setting (carry-over from sub-30s
    short activities that have not yet been persisted).

    The collector writes this value whenever a normal short activity ends
    without crossing the 30-second persistence threshold. The unified
    live-display carry seconds must include it so the UI does not lose seconds
    between short activities and then suddenly jump when the next
    activity persists.
    """
    raw = get_setting("pending_short_seconds", "") or ""
    if not raw:
        return 0
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return 0
    return max(0, value)


def _read_short_activity_carry() -> dict[str, Any] | None:
    """Read the serialized short-activity carry state (if any).

    The collector writes a JSON object describing the carry-over context
    so the unified live-display carry seconds can incorporate consecutive
    short activities that belong to the same logical session.
    """
    import json

    raw = get_setting("short_activity_carry", "") or ""
    if not raw:
        return None
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    return value if isinstance(value, dict) else None


def short_activity_carry_seconds(
    snapshot: dict[str, Any] | None,
    report_date: str | None,
) -> int:
    """Return the carry-over seconds that should be added to the unified
    live-display carry seconds.

    The carry seconds represent consecutive short activities (<30s each)
    that have not been persisted individually but should still contribute
    to the current normal live display so the UI does not first lose
    seconds and then suddenly jump when the next activity crosses the
    persistence threshold.
    does not first lose seconds and then suddenly jump when the next
    activity crosses the persistence threshold.

    Returns ``0`` when:

    - the snapshot is None / not normal / not unconfirmed;
    - there is no carry state;
    - the carry's anchor activity id is no longer visible in the
      report date's activity ids.
    """
    if not snapshot or _snapshot_status(snapshot) != STATUS_NORMAL:
        return 0
    if bool(snapshot.get("is_persisted")) or snapshot_persisted_id(snapshot):
        return 0
    carry = _read_short_activity_carry()
    if not carry:
        # Fall back to the simple pending_short_seconds accumulator when
        # no structured carry state exists. This covers the common case
        # of a single short activity ending below the threshold.
        return _read_pending_short_seconds()
    # Use the existing helper to compute the carry duration against the
    # current report date's activity ids. The helper returns ``None`` when
    # the carry's anchor activity is no longer visible, in which case we
    # fall back to the pending accumulator.
    try:
        if report_date:
            activity_ids = [
                int(a.get("id") or 0)
                for a in activity_service.get_activities_by_date(report_date)
                if int(a.get("id") or 0) > 0
            ]
            base_duration = 0
            anchor_id = safe_int(carry.get("activity_id"))
            if anchor_id and anchor_id in activity_ids:
                # The anchor activity's stored duration is the confirmed
                # base; carry.completed_seconds holds subsequent short
                # activities that have already ended.
                anchor = activity_service.get_activity(anchor_id)
                if anchor:
                    base_duration = safe_int(anchor.get("duration_seconds"))
            duration = _short_activity_carry_duration_helper(
                carry, activity_ids, base_duration, report_date, snapshot
            )
            if duration is not None:
                return max(0, duration)
    except Exception:
        pass
    return _read_pending_short_seconds()


def _short_activity_carry_duration_helper(
    carry: dict[str, Any] | None,
    activity_ids: list[int],
    base_duration_seconds: int,
    report_date: str,
    snapshot: dict[str, Any] | None,
) -> int | None:
    """Thin wrapper around ``live_time_service.short_activity_carry_duration``
    so the import boundary is explicit.
    unified live-display code path (no longer dead code).
    """
    from .live_time_service import short_activity_carry_duration

    return short_activity_carry_duration(
        carry,
        activity_ids,
        base_duration_seconds,
        report_date,
        snapshot,
    )


def sync_carry_state(
    previous_snapshot: dict[str, Any] | None,
    snapshot: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Sync the short-activity carry state when the snapshot changes.

    Wraps ``live_time_service.sync_short_activity_carry`` so the unified
    live-display model can advance the carry state alongside the snapshot
    without each consumer re-implementing the signature-comparison logic.
    """
    carry = _read_short_activity_carry()
    return sync_short_activity_carry(carry, previous_snapshot, snapshot)


# Unified live-display payload builders


def build_current_activity_summary(
    snapshot: dict[str, Any] | None,
    report_date: str | None = None,
    today: str | None = None,
) -> dict[str, Any]:
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
                "threshold_seconds": 30,
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
    # is_in_progress is True only when the snapshot represents a real
    # persisted open DB row. Virtual (unpersisted) rows carry
    # ``is_virtual_live = True`` instead so the frontend can distinguish
    # the two rendering paths.
    is_in_progress = live_state == "persisted_open"
    is_virtual_live = live_state == "virtual"
    is_uncategorized = (
        not project_name or project_name == UNCATEGORIZED_PROJECT
    )
    # The carry seconds are added to the elapsed seconds so the UI does
    # not lose seconds between consecutive short activities. Only applies
    # to virtual (unpersisted) snapshots; persisted_open rows already
    # have the carry folded into their stored duration.
    carry_seconds = 0
    if is_virtual_live:
        carry_seconds = short_activity_carry_seconds(snapshot, report_date)
    display_seconds = elapsed_seconds + carry_seconds
    # Project ownership fields. The snapshot carries a structured
    # display_project / candidate_project / project_transition block from
    # the ownership state machine, surfaced verbatim (display-safe) so the
    # frontend can render the 30s pending indicator without the raw snapshot.
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
    project_transition_dict = snapshot.get("project_transition") if snapshot else None
    if not isinstance(project_transition_dict, dict):
        project_transition_dict = {
            "pending": False,
            "started_at": "",
            "elapsed_seconds": 0,
            "threshold_seconds": 30,
            "from_project_id": None,
            "to_project_id": None,
        }
    project_transition_pending = bool(project_transition_dict.get("pending"))
    # Unified live clock: the frontend computes display_seconds =
    # carry_seconds + floor((Date.now() - live_started_at_epoch_ms) / 1000)
    # so the current activity doesn't jump across refreshes. start_time is
    # the stable anchor; both fields come from the SAME snapshot sample.
    live_started_at_epoch_ms = _start_time_epoch_ms(snapshot)
    from ..formatters import format_duration

    state_label = "已进入历史" if is_persisted else "暂不入历史"
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
        "source": "db" if is_in_progress else ("snapshot" if is_virtual_live else "none"),
        "is_uncategorized": bool(is_uncategorized),
        "is_classified": not bool(is_uncategorized),
        # Project ownership fields (display-safe).
        "project_description": project_description,
        "display_project": display_project_dict,
        "candidate_project": candidate_project_dict,
        "project_transition": project_transition_dict,
        "project_transition_pending": project_transition_pending,
    }


def _virtual_session_id(snapshot: dict[str, Any] | None) -> str:
    """Return the stable virtual session id for a snapshot.

    The id is ``"virtual-live:<stable_live_key_hash>"`` so the same logical
    activity keeps the same id across the virtual → persisted_open
    transition (the persisted row uses its real DB id, but the stable hash
    lets the frontend continuity key survive the transition). When the
    snapshot is empty the ``"virtual-live"`` sentinel is returned so
    callers can still detect "no virtual session".
    """
    h = _stable_live_key_hash(snapshot)
    if not h:
        return "virtual-live"
    return "virtual-live:" + h


def _snapshot_display_project_fields(snapshot: dict[str, Any] | None) -> dict[str, Any]:
    """Return the full set of display-facing project fields from a snapshot.

    Centralizes project-field extraction so virtual session, virtual
    detail, persisted_open overlay, and the live row contract all share
    the SAME source of truth for project attribution.
    pending transition the fields come from the snapshot's
    ``display_project`` block (the inherited last-confirmed project), NOT
    from the DB row's candidate assignment.

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
    project_transition_dict = snapshot.get("project_transition") if snapshot else None
    if not isinstance(project_transition_dict, dict):
        project_transition_dict = {
            "pending": False,
            "started_at": "",
            "elapsed_seconds": 0,
            "threshold_seconds": 30,
            "from_project_id": None,
            "to_project_id": None,
        }
    dp_id = display_project_dict.get("id")
    # DB fallback only when the snapshot has NO structured display_project block
    # (e.g. persisted_open with only inferred_project_name). When display_project
    # explicitly declares id=None + is_uncategorized=True (candidate pending),
    # honor it: do NOT pull project_id from the DB row (candidate must not override).
    if dp_id is None and snapshot_dp is None:
        persisted_id = snapshot_persisted_id(snapshot) if snapshot else None
        if persisted_id:
            try:
                row = activity_service.get_activity(int(persisted_id))
            except Exception:
                row = None
            if row:
                dp_id = row.get("project_id")
    return {
        "project_id": int(dp_id) if dp_id is not None else 0,
        "project_name": project_name,
        "project_description": project_description,
        "display_project": display_project_dict,
        "candidate_project": candidate_project_dict,
        "project_transition": project_transition_dict,
        "project_transition_pending": bool(project_transition_dict.get("pending")),
        "is_uncategorized": bool(is_uncategorized),
        "is_classified": not bool(is_uncategorized),
        "status": _snapshot_status(snapshot),
        "start_time": str(snapshot.get("start_time") or "") if snapshot else "",
    }


def _build_virtual_session(
    snapshot: dict[str, Any] | None,
    report_date: str,
    today: str,
) -> dict[str, Any] | None:
    """LEGACY private helper: build a display-only virtual session for an
    unpersisted normal snapshot.

    Retained ONLY for the legacy ``build_live_row_contract`` path and
    contract tests. Page ViewModels must use
    ``activity_display_model_service.apply_live_span_to_row`` instead.
    A ``<30s`` pending snapshot is no longer injected as a virtual row
    in Recent / Timeline / Details.

    Returns ``None`` when the snapshot is not eligible (not normal,
    persisted, no elapsed seconds, or historical date). The virtual
    session is display-only: ``activity_id=0``, ``is_virtual=True``,
    ``source="snapshot"``, all edit buttons disabled. The DB is NEVER
    written. ``session_id`` is ``"virtual-live:<stable_live_key_hash>"``
    so the frontend continuity key survives the virtual → persisted_open
    transition.
    """
    if not is_live_eligible_for_normal(snapshot, report_date, today):
        return None
    if classify_live_state(snapshot) != "virtual":
        return None
    from ..formatters import format_duration

    elapsed = _snapshot_total_seconds(snapshot)
    carry = short_activity_carry_seconds(snapshot, report_date)
    duration_seconds = elapsed + carry
    project_name = _display_project_name(snapshot)
    project_description = _display_project_description(snapshot)
    start_time = str(snapshot.get("start_time") or "")
    project_fields = _snapshot_display_project_fields(snapshot)
    return {
        "session_id": _virtual_session_id(snapshot),
        "project_name": project_name,
        "project_description": project_description,
        "project_id": project_fields["project_id"],
        "start_time": start_time,
        "end_time": None,
        "duration": format_duration(duration_seconds),
        "duration_seconds": int(duration_seconds),
        "status": "进行中",
        "event_count": 1,
        "is_uncategorized": project_fields["is_uncategorized"],
        "is_classified": project_fields["is_classified"],
        "is_in_progress": True,
        "is_live_projected": False,
        "is_virtual": True,
        "is_virtual_live": True,
        "live_state": "virtual",
        "source": "snapshot",
        "activity_ids": [],
        "first_activity_id": None,
        "session_note": "",
        "live_display_key": _live_display_key(snapshot),
        "stable_live_key": _stable_live_key(snapshot),
        "stable_live_key_hash": _stable_live_key_hash(snapshot),
        # Unified live clock fields so the frontend ticker can
        # compute ``display_seconds = carry_seconds + floor((Date.now() -
        # live_started_at_epoch_ms) / 1000)`` from a single stable anchor.
        "live_started_at_epoch_ms": _start_time_epoch_ms(snapshot),
        "carry_seconds": int(carry),
        "edit_disabled": True,
        "disable_reason": _VIRTUAL_EDIT_DISABLE_REASON,
        # Display-facing project fields.
        # display_project block (project ownership).
        "display_project": project_fields["display_project"],
        "candidate_project": project_fields["candidate_project"],
        "project_transition": project_fields["project_transition"],
        "project_transition_pending": project_fields["project_transition_pending"],
    }


def _build_virtual_detail_row(
    snapshot: dict[str, Any] | None,
    report_date: str,
    today: str,
) -> dict[str, Any] | None:
    """LEGACY private helper: build a display-only virtual detail row for
    an unpersisted normal snapshot.

    This helper is retained ONLY for the legacy ``build_live_row_contract``
    row-contract path and contract tests. Page ViewModels must NOT call it
    — they use ``activity_display_model_service.apply_live_span_to_row``
    instead. A ``<30s`` pending snapshot is no longer injected as a
    virtual row in Recent / Timeline / Details.

    Returns ``None`` when the snapshot is not eligible for virtual live
    display. The row is display-only: ``activity_id`` is ``0``,
    ``is_virtual`` is ``True``, ``source`` is ``"snapshot"``, and every
    edit / split / merge / hide / delete / restore button must be
    disabled.
    """
    if not is_live_eligible_for_normal(snapshot, report_date, today):
        return None
    if classify_live_state(snapshot) != "virtual":
        return None
    from ..formatters import format_duration, format_resource_type

    elapsed = _snapshot_total_seconds(snapshot)
    carry = short_activity_carry_seconds(snapshot, report_date)
    duration_seconds = elapsed + carry
    project_name = _display_project_name(snapshot)
    project_description = _display_project_description(snapshot)
    resource_name = _display_resource_name(snapshot)
    app_name = _display_app_name(snapshot)
    start_time = str(snapshot.get("start_time") or "")
    resource_kind = str(snapshot.get("resource_kind") or "")
    resource_subtype = str(snapshot.get("resource_subtype") or "")
    project_fields = _snapshot_display_project_fields(snapshot)
    return {
        "activity_id": _VIRTUAL_ACTIVITY_ID,
        "start_time": start_time,
        "end_time": None,
        "duration": format_duration(duration_seconds),
        "duration_seconds": int(duration_seconds),
        "app_name": app_name,
        "resource_type": format_resource_type(resource_kind, resource_subtype),
        "resource_name": resource_name,
        "project_name": project_name,
        "project_description": project_description,
        "project_id": project_fields["project_id"],
        "status": STATUS_NORMAL,
        "is_in_progress": True,
        "is_virtual": True,
        "is_virtual_live": True,
        "live_state": "virtual",
        "source": "snapshot",
        "live_display_key": _live_display_key(snapshot),
        "stable_live_key": _stable_live_key(snapshot),
        "stable_live_key_hash": _stable_live_key_hash(snapshot),
        # Unified live clock fields.
        "live_started_at_epoch_ms": _start_time_epoch_ms(snapshot),
        "carry_seconds": int(carry),
        "edit_disabled": True,
        "disable_reason": _VIRTUAL_EDIT_DISABLE_REASON,
        # Display-facing project fields.
        # display_project block (project ownership).
        "is_uncategorized": project_fields["is_uncategorized"],
        "is_classified": project_fields["is_classified"],
        "display_project": project_fields["display_project"],
        "candidate_project": project_fields["candidate_project"],
        "project_transition": project_fields["project_transition"],
        "project_transition_pending": project_fields["project_transition_pending"],
    }


def persisted_open_live_seconds(
    snapshot: dict[str, Any] | None,
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


def build_persisted_open_overlay(
    snapshot: dict[str, Any] | None,
    report_date: str,
    today: str,
) -> dict[str, Any] | None:
    """Return the persisted-open live overlay metadata for bridge consumers.

    When the snapshot is persisted_open AND the report date is today, this
    returns a dict carrying the unified live clock fields AND the
    display-facing project fields so the bridge can apply BOTH the live
    clock increment and the ``display_project`` overlay to the matching
    real DB session/detail row.

    Returns ``None`` when not applicable.
    """
    if not is_live_eligible_for_normal(snapshot, report_date, today):
        return None
    if classify_live_state(snapshot) != "persisted_open":
        return None
    persisted_id = snapshot_persisted_id(snapshot) or 0
    if persisted_id <= 0:
        return None
    # Unified live clock: persisted_open live seconds are anchored on the
    # row's start_time so the frontend computes display_seconds =
    # carry_seconds + floor((Date.now() - live_started_at_epoch_ms) / 1000).
    # For persisted_open rows carry_seconds is 0 (already in stored duration).
    live_started_at_epoch_ms = _start_time_epoch_ms(snapshot)
    # Display-facing project fields from the snapshot's display_project
    # block (override the DB row's assignment during the 30-second pending
    # window so the live UI shows the inherited display project, not the
    # candidate).
    project_fields = _snapshot_display_project_fields(snapshot)
    return {
        "persisted_activity_id": int(persisted_id),
        "live_seconds": int(_snapshot_total_seconds(snapshot)),
        "live_display_key": _live_display_key(snapshot),
        "stable_live_key": _stable_live_key(snapshot),
        "stable_live_key_hash": _stable_live_key_hash(snapshot),
        "live_started_at_epoch_ms": int(live_started_at_epoch_ms or 0),
        "carry_seconds": 0,
        # Display-facing project fields.
        "project_id": project_fields["project_id"],
        "project_name": project_fields["project_name"],
        "project_description": project_fields["project_description"],
        "display_project": project_fields["display_project"],
        "candidate_project": project_fields["candidate_project"],
        "project_transition": project_fields["project_transition"],
        "project_transition_pending": project_fields["project_transition_pending"],
        "is_uncategorized": project_fields["is_uncategorized"],
        "is_classified": project_fields["is_classified"],
        "status": project_fields["status"],
        "start_time": project_fields["start_time"],
    }


# Unified refresh-revision computation


def compute_refresh_revision(
    snapshot: dict[str, Any] | None,
    collector_status: str,
    user_paused: bool,
    today: str,
    report_date: str | None = None,
) -> tuple[str, dict[str, Any]]:
    """Compute the unified refresh-revision signature."""
    if report_date is None:
        report_date = today
    # Current snapshot structural identity (display-safe).
    current_activity_key = _live_display_key(snapshot)
    current_status = _snapshot_status(snapshot)
    is_persisted = bool(snapshot and snapshot.get("is_persisted"))
    persisted_id = int(snapshot_persisted_id(snapshot) or 0) if snapshot else 0
    inferred_project = ""
    if snapshot:
        inferred_project = str(snapshot.get("inferred_project_name") or "")
    # Carry / pending state.
    pending_short_seconds = _read_pending_short_seconds()
    carry_signature = ""
    carry = _read_short_activity_carry()
    if carry:
        carry_signature = "{0}|{1}|{2}".format(
            safe_int(carry.get("activity_id")),
            safe_int(carry.get("base_seconds")),
            safe_int(carry.get("completed_seconds")),
        )
    latest_id = 0
    latest_updated_at = ""
    latest_kind = ""
    structural_signature = ""
    row_count = 0
    try:
        rows = activity_service.get_activities_by_date(report_date)
        row_count = len(rows)
        # Hash each row's structural fields. Using a per-row signature keeps
        # the overall string length bounded and avoids field-order ambiguity,
        # including the fields most likely to change on a user edit.
        row_signatures: list[str] = []
        for row in rows:
            row_id = int(row.get("id") or 0)
            if row_id > latest_id:
                latest_id = row_id
                latest_updated_at = str(row.get("updated_at") or "")
                latest_kind = "{0}|{1}|{2}|{3}|{4}".format(
                    str(row.get("status") or ""),
                    str(row.get("project_name") or ""),
                    "1" if row.get("end_time") is None else "0",
                    str(row.get("is_deleted") or 0),
                    str(row.get("is_hidden") or 0),
                )
            sig = "|".join(
                [
                    str(row.get("id") or 0),
                    str(row.get("start_time") or ""),
                    "1" if row.get("end_time") is None else "0",
                    str(row.get("end_time") or ""),
                    str(row.get("status") or ""),
                    str(row.get("project_id") or 0),
                    str(row.get("source") or ""),
                    str(row.get("is_deleted") or 0),
                    str(row.get("is_hidden") or 0),
                    str(row.get("note") or ""),
                    str(row.get("app_name") or ""),
                    str(row.get("process_name") or ""),
                    str(row.get("file_path_hint") or ""),
                    str(row.get("manual_override") or 0),
                    str(row.get("auto_classified") or 0),
                ]
            )
            row_signatures.append(sig)
        # The structural signature is the hash of all row signatures +
        # the row count. This way, any single row's structural change
        # (including a new/removed row) changes the overall revision,
        # but a duration-only write does not.
        structural_signature = hashlib.sha1(
            ("#".join(row_signatures) + "|count=" + str(row_count)).encode("utf-8")
        ).hexdigest()
    except Exception:
        pass
    revision_input = "|".join(
        [
            current_activity_key,
            current_status,
            "1" if is_persisted else "0",
            str(persisted_id),
            inferred_project,
            collector_status,
            "1" if user_paused else "0",
            today,
            str(pending_short_seconds),
            carry_signature,
            # Structural signature so a duration-only ``updated_at`` bump
            # does not trigger a heavy refresh.
            # duration-only ``updated_at`` bump no longer triggers a
            # heavy refresh.
            structural_signature,
            str(row_count),
            str(latest_id),
        ]
    )
    revision = hashlib.sha1(revision_input.encode("utf-8")).hexdigest()
    debug_inputs = {
        "current_activity_key": current_activity_key,
        "current_status": current_status,
        "is_persisted": is_persisted,
        "persisted_id": persisted_id,
        "inferred_project": inferred_project,
        "collector_status": collector_status,
        "user_paused": user_paused,
        "today": today,
        "pending_short_seconds": pending_short_seconds,
        "carry_signature": carry_signature,
        "structural_signature": structural_signature,
        "row_count": row_count,
        "latest_id": latest_id,
        # Kept for debug visibility only — NOT part of revision_input.
        "latest_updated_at": latest_updated_at,
        "latest_kind": latest_kind,
    }
    return revision, debug_inputs


# Live-row contract helpers

LIVE_ROW_CONTRACT_FIELDS = (
    "live_state",
    "stable_live_key",
    "stable_live_key_hash",
    "live_display_key",
    "live_started_at_epoch_ms",
    "carry_seconds",
    "duration_seconds",
    "is_virtual_live",
    "is_in_progress",
    "is_live_projected",
    "edit_disabled",
    "disable_reason",
    "source",
    # Display-facing project fields.
    # display_project block for BOTH virtual and persisted_open rows.
    "project_id",
    "project_name",
    "project_description",
    "display_project",
    "candidate_project",
    "project_transition",
    "project_transition_pending",
    "is_uncategorized",
    "is_classified",
    "status",
    "start_time",
)


def apply_persisted_open_overlay_to_row(
    row: dict[str, Any],
    overlay: dict[str, Any] | None,
) -> dict[str, Any]:
    """Merge persisted-open live overlay fields into a DB row payload."""
    if not overlay:
        return row
    persisted_id = int(overlay.get("persisted_activity_id") or 0)
    if persisted_id <= 0:
        return row
    # Match detail rows (activity_id / id) and session rows
    # (first_activity_id / activity_ids). A session row matches when the
    # persisted_open activity is one of its activities — typically the
    # in-progress last activity.
    row_id = int(row.get("activity_id") or row.get("id") or 0)
    first_activity_id = int(row.get("first_activity_id") or 0)
    activity_ids = row.get("activity_ids")
    matches = row_id == persisted_id or first_activity_id == persisted_id
    if not matches and isinstance(activity_ids, list):
        matches = persisted_id in {
            int(aid) for aid in activity_ids if aid
        }
    if not matches:
        return row
    # Unified live clock fields.
    row["live_state"] = "persisted_open"
    row["stable_live_key"] = str(overlay.get("stable_live_key") or "")
    row["stable_live_key_hash"] = str(overlay.get("stable_live_key_hash") or "")
    row["live_display_key"] = str(overlay.get("live_display_key") or "")
    row["live_started_at_epoch_ms"] = int(overlay.get("live_started_at_epoch_ms") or 0)
    row["carry_seconds"] = int(overlay.get("carry_seconds") or 0)
    # Mark the row as a live projected persisted-open row.
    row["is_virtual_live"] = False
    row["is_in_progress"] = True
    row["is_live_projected"] = True
    # Display-facing project fields. ``candidate_project`` is surfaced as
    # a separate field and does NOT override ``project_name``.
    # project during the 30-second pending window. candidate_project is
    # surfaced as a separate field but does NOT override project_name.
    row["project_id"] = int(overlay.get("project_id") or 0)
    row["project_name"] = str(overlay.get("project_name") or "未归类")
    row["project_description"] = str(overlay.get("project_description") or "")
    row["display_project"] = overlay.get("display_project")
    row["candidate_project"] = overlay.get("candidate_project")
    row["project_transition"] = overlay.get("project_transition")
    row["project_transition_pending"] = bool(overlay.get("project_transition_pending"))
    row["is_uncategorized"] = bool(overlay.get("is_uncategorized"))
    row["is_classified"] = bool(overlay.get("is_classified"))
    row["status"] = str(overlay.get("status") or "")
    row["start_time"] = str(overlay.get("start_time") or "")
    # Persisted_open rows are NOT editable (the activity is still in
    # progress). The frontend uses these to disable edit / split / merge /
    # hide / delete / restore controls.
    row["edit_disabled"] = True
    row["disable_reason"] = _VIRTUAL_EDIT_DISABLE_REASON
    row["source"] = "db"
    return row


def build_live_row_contract(
    snapshot: dict[str, Any] | None,
    row: dict[str, Any] | None,
    row_kind: str,
    report_date: str,
    today: str,
) -> dict[str, Any]:
    """LEGACY live-row contract builder.

    Page ViewModels must use
    ``activity_display_model_service.apply_live_span_to_row`` instead.
    Retained only for contract tests and legacy callers.

    ``row_kind`` is one of ``"virtual_session"``, ``"virtual_detail"``,
    ``"persisted_open"``, or ``"current"``. Returns a dict with all
    :data:`LIVE_ROW_CONTRACT_FIELDS` populated from the snapshot and/or
    the DB row. Virtual rows use the private ``_build_virtual_session`` /
    ``_build_virtual_detail_row`` helpers; persisted_open uses
    :func:`build_persisted_open_overlay`; current uses
    :func:`build_current_activity_summary`.

    Returns an empty dict when the row is not live-eligible (closed
    historical rows, non-normal statuses on past dates, etc.).
    """
    if row_kind == "persisted_open":
        overlay = build_persisted_open_overlay(snapshot, report_date, today)
        if not overlay:
            return {}
        return {
            "live_state": "persisted_open",
            "stable_live_key": str(overlay.get("stable_live_key") or ""),
            "stable_live_key_hash": str(overlay.get("stable_live_key_hash") or ""),
            "live_display_key": str(overlay.get("live_display_key") or ""),
            "live_started_at_epoch_ms": int(overlay.get("live_started_at_epoch_ms") or 0),
            "carry_seconds": int(overlay.get("carry_seconds") or 0),
            "duration_seconds": int(row.get("duration_seconds") or 0) if row else 0,
            "is_virtual_live": False,
            "is_in_progress": True,
            "is_live_projected": True,
            "edit_disabled": True,
            "disable_reason": _VIRTUAL_EDIT_DISABLE_REASON,
            "source": "db",
            # Display-facing project fields from the overlay.
            "project_id": int(overlay.get("project_id") or 0),
            "project_name": str(overlay.get("project_name") or "未归类"),
            "project_description": str(overlay.get("project_description") or ""),
            "display_project": overlay.get("display_project"),
            "candidate_project": overlay.get("candidate_project"),
            "project_transition": overlay.get("project_transition"),
            "project_transition_pending": bool(overlay.get("project_transition_pending")),
            "is_uncategorized": bool(overlay.get("is_uncategorized")),
            "is_classified": bool(overlay.get("is_classified")),
            "status": str(overlay.get("status") or ""),
            "start_time": str(overlay.get("start_time") or ""),
        }
    if row_kind == "virtual_session":
        virtual = _build_virtual_session(snapshot, report_date, today)
        if not virtual:
            return {}
        return _contract_from_virtual(virtual)
    if row_kind == "virtual_detail":
        virtual = _build_virtual_detail_row(snapshot, report_date, today)
        if not virtual:
            return {}
        return _contract_from_virtual(virtual)
    if row_kind == "current":
        summary = build_current_activity_summary(snapshot, report_date, today)
        if not summary:
            return {}
        return {
            "live_state": str(summary.get("live_state") or ""),
            "stable_live_key": str(summary.get("stable_live_key") or ""),
            "stable_live_key_hash": str(summary.get("stable_live_key_hash") or ""),
            "live_display_key": str(summary.get("live_display_key") or ""),
            "live_started_at_epoch_ms": int(summary.get("live_started_at_epoch_ms") or 0),
            "carry_seconds": int(summary.get("carry_seconds") or 0),
            "duration_seconds": int(summary.get("duration_seconds") or 0),
            "is_virtual_live": bool(summary.get("is_virtual_live")),
            "is_in_progress": bool(summary.get("is_in_progress")),
            "is_live_projected": bool(summary.get("is_live_projected")),
            "edit_disabled": bool(summary.get("edit_disabled")),
            "disable_reason": str(summary.get("disable_reason") or ""),
            "source": str(summary.get("source") or ""),
            # Display-facing project fields from the summary.
            "project_id": int(summary.get("project_id") or 0) if summary.get("project_id") else 0,
            "project_name": str(summary.get("project_name") or ""),
            "project_description": str(summary.get("project_description") or ""),
            "display_project": summary.get("display_project"),
            "candidate_project": summary.get("candidate_project"),
            "project_transition": summary.get("project_transition"),
            "project_transition_pending": bool(summary.get("project_transition_pending")),
            "is_uncategorized": bool(summary.get("is_uncategorized")),
            "is_classified": bool(summary.get("is_classified")),
            "status": str(summary.get("status") or ""),
            "start_time": str(summary.get("start_time") or ""),
        }
    return {}


def _contract_from_virtual(virtual: dict[str, Any]) -> dict[str, Any]:
    return {
        "live_state": str(virtual.get("live_state") or "virtual"),
        "stable_live_key": str(virtual.get("stable_live_key") or ""),
        "stable_live_key_hash": str(virtual.get("stable_live_key_hash") or ""),
        "live_display_key": str(virtual.get("live_display_key") or ""),
        "live_started_at_epoch_ms": int(virtual.get("live_started_at_epoch_ms") or 0),
        "carry_seconds": int(virtual.get("carry_seconds") or 0),
        "duration_seconds": int(virtual.get("duration_seconds") or 0),
        "is_virtual_live": True,
        "is_in_progress": True,
        "is_live_projected": bool(virtual.get("is_live_projected")),
        "edit_disabled": bool(virtual.get("edit_disabled")),
        "disable_reason": str(virtual.get("disable_reason") or ""),
        "source": str(virtual.get("source") or "snapshot"),
        # Display-facing project fields from the virtual builder.
        "project_id": int(virtual.get("project_id") or 0),
        "project_name": str(virtual.get("project_name") or "未归类"),
        "project_description": str(virtual.get("project_description") or ""),
        "display_project": virtual.get("display_project"),
        "candidate_project": virtual.get("candidate_project"),
        "project_transition": virtual.get("project_transition"),
        "project_transition_pending": bool(virtual.get("project_transition_pending")),
        "is_uncategorized": bool(virtual.get("is_uncategorized")),
        "is_classified": bool(virtual.get("is_classified")),
        "status": str(virtual.get("status") or ""),
        "start_time": str(virtual.get("start_time") or ""),
    }


def apply_live_row_contract(
    row: dict[str, Any],
    contract: dict[str, Any],
) -> dict[str, Any]:
    """Merge a live-row contract into a bridge row payload.

    Mutates and returns ``row``. When ``contract`` is empty, the row is
    unchanged. Only :data:`LIVE_ROW_CONTRACT_FIELDS` are merged; no raw
    fields (window_title / file_path_hint / note / clipboard) are ever
    introduced.
    """
    if not contract:
        return row
    for field in LIVE_ROW_CONTRACT_FIELDS:
        if field in contract:
            row[field] = contract[field]
    return row


def assert_live_row_contract(row: dict[str, Any]) -> None:
    """Assert that ``row`` carries every :data:`LIVE_ROW_CONTRACT_FIELDS`.

    Used by contract tests to verify that both virtual and persisted_open
    rows exposed to the frontend carry the complete set of display-safe
    live fields. Raises ``AssertionError`` with the missing field names.
    """
    missing = [f for f in LIVE_ROW_CONTRACT_FIELDS if f not in row]
    if missing:
        raise AssertionError(
            "live row contract missing fields: " + ", ".join(missing)
        )


# Unified live projection (single source of truth for live UI)


def build_live_projection(
    snapshot: dict[str, Any] | None,
    report_date: str | None = None,
    today: str | None = None,
) -> dict[str, Any]:
    """Build the unified live projection — the single source of truth for"""
    summary = build_current_activity_summary(snapshot, report_date=report_date, today=today)
    return {
        "resource_name": str(summary.get("resource_name") or ""),
        "app_name": str(summary.get("app_name") or ""),
        "display_project": summary.get("display_project"),
        "candidate_project": summary.get("candidate_project"),
        "project_transition": summary.get("project_transition"),
        "project_transition_pending": bool(summary.get("project_transition_pending")),
        "duration_seconds": int(summary.get("elapsed_seconds") or 0),
        "live_started_at_epoch_ms": int(summary.get("live_started_at_epoch_ms") or 0),
        "carry_seconds": int(summary.get("carry_seconds") or 0),
        "stable_live_key": str(summary.get("stable_live_key") or ""),
        "stable_live_key_hash": str(summary.get("stable_live_key_hash") or ""),
        "live_state": str(summary.get("live_state") or "none"),
        "is_virtual_live": bool(summary.get("is_virtual_live")),
        "is_in_progress": bool(summary.get("is_in_progress")),
        "persisted_activity_id": int(summary.get("persisted_activity_id") or 0),
        "activity_id": summary.get("activity_id"),
        "source": str(summary.get("source") or "none"),
        # Both virtual (unpersisted) and persisted_open (real open DB row)
        # are still in-progress activities and MUST be edit-disabled. The
        # frontend uses these to disable edit / split / merge / hide /
        # delete / restore controls.
        "edit_disabled": bool(
            summary.get("is_virtual_live") or summary.get("is_in_progress")
        ),
        "disable_reason": (
            _VIRTUAL_EDIT_DISABLE_REASON
            if (
                summary.get("is_virtual_live")
                or summary.get("is_in_progress")
            )
            else ""
        ),
        # Convenience: the display project name + description for
        # consumers that only need the label.
        "project_name": str(summary.get("project_name") or ""),
        "project_description": str(summary.get("project_description") or ""),
        "is_uncategorized": bool(summary.get("is_uncategorized")),
        "is_classified": bool(summary.get("is_classified")),
        "status": str(summary.get("status") or ""),
        "start_time": str(summary.get("start_time") or ""),
    }


__all__ = [
    "LIVE_ROW_CONTRACT_FIELDS",
    "apply_live_row_contract",
    "assert_live_row_contract",
    "build_current_activity_summary",
    "build_live_projection",
    "build_live_row_contract",
    "short_activity_carry_seconds",
    "classify_live_state",
    "compute_refresh_revision",
    "is_live_eligible_for_normal",
    "persisted_open_live_seconds",
    "stable_live_key",
    "stable_live_key_hash",
    "sync_carry_state",
    "virtual_session_id",
]


# Public aliases for the stable live-identity helpers

# These aliases expose the underscore-prefixed helpers through the public
# namespace so the bridge layer (via ``live_display_api``) can read the stable
# live identity without reaching into the private helpers directly. The
# private helpers remain the single source of truth.

stable_live_key = _stable_live_key
stable_live_key_hash = _stable_live_key_hash
virtual_session_id = _virtual_session_id
