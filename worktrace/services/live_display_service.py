"""Low-level display-safe helpers for the unified Activity Display Model.

This module is NOT the page live-display model owner. The owner is
:mod:`worktrace.services.activity_display_model_service`, which solely
decides live-eligibility, ``live_state``
(``virtual_pending`` / ``absorbed_pending`` / ``persisted_open``),
display span identity, and visibility of live rows.

This module retains ONLY the low-level pure helpers used by
``activity_display_model_service`` and the bridge / settings layers:
display-safe field extraction, stable live identity
(``_stable_live_key`` / ``_stable_live_key_hash``), live-clock anchor,
current-activity summary (``build_current_activity_summary``),
refresh-revision computation (``compute_refresh_revision``), the
production-maintained ``pending_short_seconds`` accumulator,
classification, and the persisted-open live-seconds helper.

The legacy structured ``short_activity_carry`` JSON mechanism was
REMOVED — no production writer existed. The production collector
maintains ``pending_short_seconds`` within a continuous recording session;
hard runtime boundaries clear it.

Display projection is purely a UI overlay. It NEVER writes the DB,
NEVER changes the 30-second collector persistence threshold, and NEVER
persists a <30s activity early. Returns display-safe JSON-serializable
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
from . import activity_service, timeline_service
from .live_time_service import (
    safe_int,
    snapshot_elapsed_seconds,
    snapshot_extra_seconds,
    snapshot_persisted_id,
    snapshot_seconds_for_date_range,
    snapshot_start_time,
)
from .settings_service import get_setting


# Constants

# Maximum look-back for the open-row live-duration recompute. Prevents a
# stale snapshot start_time from producing an absurd 100-hour live value
# when the wall clock has drifted (e.g. system sleep).
_MAX_LIVE_DURATION_SECONDS = 36 * 60 * 60


# Live-state classification


def _snapshot_status(snapshot: dict[str, Any] | None) -> str:
    if not snapshot:
        return ""
    return str(snapshot.get("status") or "")


def classify_live_state(snapshot: dict[str, Any] | None) -> str:
    """Return the unified live-state label for a snapshot.

    Returns one of:

    - ``"none"``         — no snapshot / unsupported status.
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
    if bool(snapshot.get("is_persisted")) or snapshot_persisted_id(snapshot):
        return "persisted_open"
    return "virtual"


def is_live_eligible_for_normal(
    snapshot: dict[str, Any] | None,
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

    Persisted-open rows are ALSO eligible: they need the same continuous
    live increment, just sourced from the real DB row instead of a
    virtual row. The caller distinguishes the two via ``classify_live_state``.
    """
    if not snapshot:
        return False
    if _snapshot_status(snapshot) != STATUS_NORMAL:
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
    """Read the ``pending_short_seconds`` setting (carry-over from
    sub-30s short activities that have not yet been persisted).

    The COLLECTOR writes this value whenever a normal short activity ends
    without crossing the 30-second persistence threshold, and resets it
    whenever a normal short activity merges into a persisted row. It is
    therefore the ONLY production-maintained carry source the display
    model should consult; the legacy structured ``short_activity_carry``
    JSON had no production writer and was removed.

    The unified live-display carry seconds include this value so the UI
    does not lose seconds between short activities and then suddenly jump
    when the next activity persists. Runtime boundary cleanup owns clearing
    stale carry on restart / pause / stop / midnight / import / reset.
    """
    raw = get_setting("pending_short_seconds", "") or ""
    if not raw:
        return 0
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return 0
    return max(0, value)


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
    # Carry seconds added to elapsed so the UI does not lose seconds
    # between consecutive short activities. Only applies to virtual
    # (unpersisted) snapshots; persisted_open rows already have carry
    # folded into their stored duration. Source: ``pending_short_seconds``.
    carry_seconds = 0
    if is_virtual_live:
        carry_seconds = _read_pending_short_seconds()
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


def _snapshot_display_project_fields(snapshot: dict[str, Any] | None) -> dict[str, Any]:
    """Return the full set of display-facing project fields from a snapshot.

    Centralizes project-field extraction so the unified Activity Display
    Model can apply the SAME source of truth for project attribution
    across the live span overlay and the current-activity summary. During
    the 30s pending transition the fields come from the snapshot's
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


# Unified refresh-revision computation


def compute_refresh_revision(
    snapshot: dict[str, Any] | None,
    collector_status: str,
    user_paused: bool,
    today: str,
    report_date: str | None = None,
    display_model: dict[str, Any] | None = None,
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
            str((display_model or {}).get("display_structural_signature") or ""),
            collector_status,
            "1" if user_paused else "0",
            today,
            str(report_date or ""),
            # Structural signature so a duration-only ``updated_at`` bump
            # does not trigger a heavy refresh.
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
        "pending_short_seconds": _read_pending_short_seconds(),
        "display_structural_signature": str(
            (display_model or {}).get("display_structural_signature") or ""
        ),
        "structural_signature": structural_signature,
        "row_count": row_count,
        "latest_id": latest_id,
        # Kept for debug visibility only — NOT part of revision_input.
        "latest_updated_at": latest_updated_at,
        "latest_kind": latest_kind,
    }
    return revision, debug_inputs


__all__ = [
    "build_current_activity_summary",
    "classify_live_state",
    "compute_refresh_revision",
    "is_live_eligible_for_normal",
    "persisted_open_live_seconds",
]
