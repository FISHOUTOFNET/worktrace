"""Unified Activity Display Model — sole owner of live display semantics.

Reads ``current_activity_snapshot`` once and produces a single JSON-safe
display model. The ONLY place that decides: live-eligibility; the refined
``live_state`` (``none`` / ``virtual_pending`` / ``absorbed_pending`` /
``persisted_open`` / ``paused`` / ``idle`` / ``excluded`` / ``error``);
stable live identity (``stable_live_key`` / ``stable_live_key_hash``);
display span identity (``display_span_id``); live clock anchor
(``live_started_at_epoch_ms`` / ``carry_seconds`` /
``duration_seconds_at_sample``); ``<30s`` pending absorption (display-only
projection onto the previous confirmed normal activity — NEVER writes the
DB); visibility of live rows in recent / timeline / details.

``<30s`` pending absorption: a normal unpersisted pending resource MUST NOT
create a new virtual row in Recent / Timeline / Details. If a previous
confirmed normal activity exists (absorb anchor), pending elapsed is added
as display-only projection onto that anchor's DB row (DB NEVER written).
Otherwise no live row is shown; only the current-activity area renders the
pending resource.

Boundary: lives in ``worktrace.services``; imports ``live_display_service``,
``activity_service``, ``timeline_service``, ``settings_service``,
``live_time_service`` and stdlib only. MUST NOT be imported by
``worktrace.webview_ui.*`` directly. JSON-serializable only; raw
``window_title`` / ``file_path_hint`` / ``note`` / ``clipboard`` / SQL /
tracebacks / paths / passphrases NEVER surfaced.
"""

from __future__ import annotations

import json
from typing import Any

from ..constants import (
    SOURCE_AUTO,
    STATUS_ERROR,
    STATUS_EXCLUDED,
    STATUS_IDLE,
    STATUS_NORMAL,
    STATUS_PAUSED,
)
from . import activity_service, live_display_service, timeline_service
from .live_display_service import (
    _display_app_name,
    _display_project_description,
    _display_project_name,
    _display_resource_name,
    _snapshot_display_project_fields,
    _snapshot_total_seconds,
    _start_time_epoch_ms,
    _stable_live_key,
    _stable_live_key_hash,
    build_current_activity_summary,
    build_live_projection,
    classify_live_state,
    is_live_eligible_for_normal,
    short_activity_carry_seconds,
)
from .live_time_service import (
    safe_int,
    snapshot_elapsed_seconds,
    snapshot_extra_seconds,
    snapshot_persisted_id,
)
from .settings_service import get_bool_setting, get_setting


# Sentinel activity id used when no real DB row backs a display span.
_VIRTUAL_ACTIVITY_ID = 0

# Disable-reason text surfaced on live rows that cannot be edited while
# the underlying activity is still in progress or pending confirmation.
_LIVE_EDIT_DISABLE_REASON = "当前活动尚未进入历史，暂不能编辑"


# Snapshot access helpers


def _get_current_activity_snapshot() -> dict[str, Any] | None:
    raw = get_setting("current_activity_snapshot", "") or ""
    if not raw:
        return None
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _read_short_activity_carry() -> dict[str, Any] | None:
    raw = get_setting("short_activity_carry", "") or ""
    if not raw:
        return None
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _carry_completed_seconds() -> int:
    carry = _read_short_activity_carry()
    if not carry:
        return 0
    return safe_int(carry.get("completed_seconds"))


# Absorption anchor resolution


def _find_absorb_anchor(
    snapshot: dict[str, Any] | None,
    today: str,
) -> dict[str, Any] | None:
    """Return the latest confirmed normal activity that the pending
    snapshot should absorb into (display-only), or ``None``.

    The anchor is resolved through two paths:

    1. The short-activity carry state's ``activity_id`` — when the
       collector has already linked the pending resource to a previous
       persisted activity via the carry mechanism, that anchor is the
       authoritative absorption target.
    2. A fallback scan of today's activities for the latest closed,
       non-deleted, non-hidden, auto, normal activity that sits before
       the pending snapshot's start time and is not separated from it by
       a session boundary.

    Returns ``None`` when no suitable anchor exists. The anchor is used
    ONLY for display projection; the DB is NEVER written.
    """
    if not snapshot or not today:
        return None
    start_time = str(snapshot.get("start_time") or "")
    carry = _read_short_activity_carry()
    if carry:
        anchor_id = safe_int(carry.get("activity_id"))
        if anchor_id > 0:
            try:
                row = activity_service.get_activity(anchor_id)
            except Exception:
                row = None
            if row and _is_absorbable_anchor(row, start_time):
                return row
    # Fallback: scan today's activities for the latest absorbable anchor.
    try:
        rows = activity_service.get_activities_by_date(today)
    except Exception:
        return None
    candidates: list[dict[str, Any]] = []
    for row in rows:
        if _is_absorbable_anchor(row, start_time):
            candidates.append(row)
    if not candidates:
        return None
    # Pick the latest by start_time.
    candidates.sort(key=lambda r: str(r.get("start_time") or ""), reverse=True)
    return candidates[0]


def _is_absorbable_anchor(row: dict[str, Any], pending_start_time: str) -> bool:
    """Return ``True`` when ``row`` is a valid absorption anchor for a
    pending snapshot starting at ``pending_start_time``.

    An anchor must be a closed (``end_time`` not null), non-deleted,
    non-hidden, auto-sourced, normal activity whose ``start_time`` is not
    after the pending snapshot's start time. Deleted / hidden / system /
    paused / idle / excluded / error rows are never anchors.
    """
    if int(row.get("is_deleted") or 0) or int(row.get("is_hidden") or 0):
        return False
    if str(row.get("source") or "") != SOURCE_AUTO:
        return False
    if str(row.get("status") or "") != STATUS_NORMAL:
        return False
    end_time = row.get("end_time")
    if end_time is None or str(end_time) == "":
        return False
    anchor_start = str(row.get("start_time") or "")
    if not anchor_start:
        return False
    if pending_start_time and anchor_start > pending_start_time:
        return False
    return True


# Display live-state classification


def classify_display_live_state(
    snapshot: dict[str, Any] | None,
    report_date: str | None,
    today: str | None,
) -> str:
    """Return the refined display live-state label.

    Extends :func:`live_display_service.classify_live_state` by splitting
    the legacy ``"virtual"`` state into:

    - ``"virtual_pending"`` — normal, unpersisted, ``<30s``, and no
      previous confirmed normal activity to absorb into. Only the
      current-activity area renders it; Recent / Timeline / Details show
      no live row.
    - ``"absorbed_pending"`` — normal, unpersisted, ``<30s``, and a
      previous confirmed normal activity exists. The pending elapsed is
      projected (display-only) onto that anchor's DB row.

    The other states (``none`` / ``persisted_open`` / ``paused`` /
    ``idle`` / ``excluded`` / ``error``) are passed through unchanged,
    except that a legacy ``"virtual"`` on a historical date collapses to
    ``"none"`` (no live projection for past dates).
    """
    base = classify_live_state(snapshot)
    if base != "virtual":
        return base
    if not report_date or not today or report_date != today:
        return "none"
    anchor = _find_absorb_anchor(snapshot, today)
    return "absorbed_pending" if anchor else "virtual_pending"


# Live-clock construction


def _build_live_clock(
    snapshot: dict[str, Any] | None,
    display_live_state: str,
    anchor: dict[str, Any] | None,
    summary: dict[str, Any],
    report_date: str,
    today: str,
) -> dict[str, Any]:
    """Build the single authoritative live-clock block.

    The frontend computes display seconds as::

        carry_seconds + floor((Date.now() - live_started_at_epoch_ms) / 1000)

    For ``absorbed_pending`` the carry is the anchor's stored duration
    plus any accumulated short-activity completed seconds, and the anchor
    epoch is the pending snapshot's start_time (so the floor term yields
    the pending elapsed). For ``persisted_open`` the carry is 0 (already
    folded into the stored duration). For ``virtual_pending`` the carry
    is the short-activity carry only.
    """
    stable_key = _stable_live_key(snapshot)
    stable_hash = _stable_live_key_hash(snapshot)
    display_span_id = ("span:" + stable_hash) if stable_hash else ""
    live_started_at = int(summary.get("live_started_at_epoch_ms") or 0)
    carry_seconds = int(summary.get("carry_seconds") or 0)
    duration_at_sample = int(summary.get("elapsed_seconds") or 0)

    if display_live_state == "absorbed_pending" and anchor:
        anchor_duration = safe_int(anchor.get("duration_seconds"))
        carry_seconds = anchor_duration + _carry_completed_seconds()
        duration_at_sample = carry_seconds + _snapshot_total_seconds(snapshot)
    elif display_live_state == "virtual_pending":
        # Carry is just the short-activity carry; duration is the pending
        # snapshot's own elapsed plus carry.
        carry_seconds = short_activity_carry_seconds(snapshot, report_date)
        duration_at_sample = _snapshot_total_seconds(snapshot) + carry_seconds
    elif display_live_state == "persisted_open":
        carry_seconds = 0
        duration_at_sample = _snapshot_total_seconds(snapshot)

    is_live = display_live_state in (
        "virtual_pending",
        "absorbed_pending",
        "persisted_open",
    )
    # is_project_duration_live: the KPI / project totals tick. Only
    # absorbed_pending (projects onto a real DB row) and persisted_open
    # (real DB row) tick the project duration. virtual_pending has no DB
    # row so it must not inflate any project total.
    is_project_duration_live = display_live_state in (
        "absorbed_pending",
        "persisted_open",
    )

    return {
        "display_span_id": display_span_id,
        "stable_live_key": stable_key,
        "stable_live_key_hash": stable_hash,
        "live_state": display_live_state,
        "live_started_at_epoch_ms": live_started_at,
        "carry_seconds": int(carry_seconds),
        "duration_seconds_at_sample": int(duration_at_sample),
        "is_live": bool(is_live),
        "is_project_duration_live": bool(is_project_duration_live),
    }


# Current-activity display


def _build_current_activity_display(
    snapshot: dict[str, Any] | None,
    display_live_state: str,
    anchor: dict[str, Any] | None,
    summary: dict[str, Any],
    live_clock: dict[str, Any],
) -> dict[str, Any]:
    """Build the current-activity display block.

    The current-activity area always renders the pending resource / window
    so the user knows what they are currently looking at. The duration and
    live clock come from the unified ``live_clock`` so current / recent /
    timeline / details share one clock.
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
            "display_span_id": "",
            "live_clock": live_clock,
        }

    # Start from the existing summary (display-safe fields) and override
    # the live clock / elapsed fields with the unified values.
    display = dict(summary)
    display["live_clock"] = live_clock
    display["display_span_id"] = live_clock.get("display_span_id") or ""
    display["live_state"] = display_live_state
    display["live_started_at_epoch_ms"] = int(live_clock.get("live_started_at_epoch_ms") or 0)
    display["carry_seconds"] = int(live_clock.get("carry_seconds") or 0)
    display["elapsed_seconds"] = int(live_clock.get("duration_seconds_at_sample") or 0)

    # is_virtual_live / is_in_progress reflect the refined display state.
    display["is_virtual_live"] = display_live_state == "virtual_pending"
    display["is_in_progress"] = display_live_state == "persisted_open"
    # absorbed_pending is neither virtual_live nor in_progress in the
    # legacy sense; mark it with live_state and a new is_absorbed_pending
    # flag so the frontend can render it correctly.
    display["is_absorbed_pending"] = display_live_state == "absorbed_pending"
    display["source"] = _source_for_state(display_live_state, snapshot)
    return display


def _source_for_state(state: str, snapshot: dict[str, Any] | None) -> str:
    if state == "persisted_open":
        return "db"
    if state in ("virtual_pending", "absorbed_pending"):
        return "snapshot"
    return "none"


# Display-span construction


def _build_display_span(
    snapshot: dict[str, Any] | None,
    display_live_state: str,
    anchor: dict[str, Any] | None,
    live_clock: dict[str, Any],
    summary: dict[str, Any],
    report_date: str,
    today: str,
) -> dict[str, Any]:
    """Build the single live display span (at most one per snapshot).

    The span carries the unified live clock plus the visibility flags
    that the page ViewModels consult to decide whether to inject / overlay
    a live row in Recent / Timeline / Details.
    """
    from ..formatters import format_duration

    anchor_id = 0
    activity_id = 0
    start_time = str(snapshot.get("start_time") or "") if snapshot else ""
    project_fields = _snapshot_display_project_fields(snapshot)
    duration_at_sample = int(live_clock.get("duration_seconds_at_sample") or 0)

    if display_live_state == "persisted_open":
        activity_id = int(snapshot_persisted_id(snapshot) or 0) if snapshot else 0
        anchor_id = activity_id
        source = "db"
        is_virtual = False
        is_persisted = True
        is_absorbed = False
        # persisted_open overlays project fields from the snapshot's
        # display_project block (project ownership pending window).
        project_name = project_fields["project_name"]
        project_description = project_fields["project_description"]
        project_id = project_fields["project_id"]
    elif display_live_state == "absorbed_pending" and anchor:
        anchor_id = int(anchor.get("id") or 0)
        activity_id = anchor_id
        source = "absorbed_pending"
        is_virtual = False
        is_persisted = False
        is_absorbed = True
        # absorbed_pending keeps the anchor DB row's project / resource
        # identity; only the live clock is projected. The project fields
        # come from the anchor, not the pending snapshot.
        project_name = str(anchor.get("project_name") or "未归类")
        project_description = str(anchor.get("project_description") or "")
        project_id = int(anchor.get("project_id") or 0)
        start_time = str(anchor.get("start_time") or start_time)
    else:
        # virtual_pending: no DB row, only current-activity area.
        source = "snapshot"
        is_virtual = True
        is_persisted = False
        is_absorbed = False
        project_name = project_fields["project_name"]
        project_description = project_fields["project_description"]
        project_id = project_fields["project_id"]

    return {
        "display_span_id": live_clock.get("display_span_id") or "",
        "activity_id": int(activity_id),
        "anchor_activity_id": int(anchor_id),
        "source": source,
        "live_state": display_live_state,
        "start_time": start_time,
        "end_time": "",
        "duration": format_duration(duration_at_sample),
        "duration_seconds": duration_at_sample,
        "duration_seconds_at_sample": duration_at_sample,
        "live_clock": live_clock,
        "project_id": int(project_id),
        "project_name": project_name,
        "project_description": project_description,
        "resource_name": _display_resource_name(snapshot) if snapshot else "",
        "is_current": True,
        "is_live": bool(live_clock.get("is_live")),
        "is_virtual": bool(is_virtual),
        "is_persisted": bool(is_persisted),
        "is_absorbed_pending": bool(is_absorbed),
        # Visibility: virtual_pending is ONLY visible in the current
        # activity area. absorbed_pending and persisted_open are visible
        # in recent / timeline / details because they project onto a real
        # DB row.
        "is_visible_in_current": True,
        "is_visible_in_recent": display_live_state in ("absorbed_pending", "persisted_open"),
        "is_visible_in_timeline": display_live_state in ("absorbed_pending", "persisted_open"),
        "is_visible_in_details": display_live_state in ("absorbed_pending", "persisted_open"),
        "edit_disabled": True,
        "disable_reason": _LIVE_EDIT_DISABLE_REASON,
        # Project-ownership fields (persisted_open surfaces the pending
        # transition; absorbed_pending keeps the anchor's fields).
        "display_project": project_fields["display_project"] if display_live_state != "absorbed_pending" else None,
        "candidate_project": project_fields["candidate_project"] if display_live_state != "absorbed_pending" else None,
        "project_transition": project_fields["project_transition"] if display_live_state != "absorbed_pending" else None,
        "project_transition_pending": bool(project_fields["project_transition_pending"]) if display_live_state != "absorbed_pending" else False,
    }


# Live-span overlay (applied to matching DB rows by the page ViewModels)


def _live_clock_fields(live_clock: dict[str, Any]) -> dict[str, Any]:
    """Return the subset of live-clock fields merged into every live row."""
    return {
        "display_span_id": str(live_clock.get("display_span_id") or ""),
        "stable_live_key": str(live_clock.get("stable_live_key") or ""),
        "stable_live_key_hash": str(live_clock.get("stable_live_key_hash") or ""),
        "live_state": str(live_clock.get("live_state") or ""),
        "live_started_at_epoch_ms": int(live_clock.get("live_started_at_epoch_ms") or 0),
        "carry_seconds": int(live_clock.get("carry_seconds") or 0),
        "duration_seconds_at_sample": int(live_clock.get("duration_seconds_at_sample") or 0),
        "is_live": bool(live_clock.get("is_live")),
        "is_project_duration_live": bool(live_clock.get("is_project_duration_live")),
    }


def apply_live_span_to_row(
    row: dict[str, Any],
    span: dict[str, Any] | None,
) -> dict[str, Any]:
    """Merge the unified live-span overlay into a DB row payload.

    The row matches the span when its ``activity_id`` / ``id`` /
    ``first_activity_id`` / ``activity_ids`` contains the span's
    ``anchor_activity_id``. For ``persisted_open`` the project fields are
    also overlaid (project-ownership pending window). For
    ``absorbed_pending`` ONLY the live clock fields are overlaid — the
    anchor row's project / resource identity is preserved.

    Mutates and returns ``row``. When ``span`` is ``None`` or the row does
    not match, the row is returned unchanged.
    """
    if not span:
        return row
    anchor_id = int(span.get("anchor_activity_id") or 0)
    if anchor_id <= 0:
        return row
    row_id = int(row.get("activity_id") or row.get("id") or 0)
    first_activity_id = int(row.get("first_activity_id") or 0)
    activity_ids = row.get("activity_ids")
    matches = row_id == anchor_id or first_activity_id == anchor_id
    if not matches and isinstance(activity_ids, list):
        matches = anchor_id in {int(aid) for aid in activity_ids if aid}
    if not matches:
        return row

    live_clock = span.get("live_clock") or {}
    row.update(_live_clock_fields(live_clock))
    state = str(span.get("live_state") or "")
    duration_at_sample = int(live_clock.get("duration_seconds_at_sample") or 0)
    carry = int(live_clock.get("carry_seconds") or 0)
    # Preserve the row's raw duration before any live projection so the
    # raw total stays accurate (display-only projection never writes DB).
    if "raw_duration_seconds" not in row:
        row["raw_duration_seconds"] = int(row.get("duration_seconds") or 0)
    row_raw = int(row.get("raw_duration_seconds") or row.get("duration_seconds") or 0)
    from ..formatters import format_duration

    if state == "absorbed_pending":
        # The pending projection at sample time =
        # duration_seconds_at_sample - carry_seconds. Add it on top of the
        # row's raw duration so the frontend ticker (which adds the
        # unified delta) lands on row_raw + pending_elapsed_now.
        pending_at_sample = max(0, duration_at_sample - carry)
        projected = row_raw + pending_at_sample
        row["duration_seconds"] = int(projected)
        row["duration"] = format_duration(projected)
    elif state == "persisted_open":
        # For a detail row (the persisted activity itself) the live value
        # IS the snapshot total. For a session / recent row the DB
        # duration already tracks the persisted row's stored duration, so
        # keep it and let the frontend add the unified delta.
        if row_id == anchor_id:
            row["duration_seconds"] = duration_at_sample
            row["duration"] = format_duration(duration_at_sample)
        else:
            row["duration_seconds"] = row_raw
            row["duration"] = format_duration(row_raw)
    else:
        row["duration_seconds"] = duration_at_sample
        row["duration"] = format_duration(duration_at_sample)
    row["is_live_projected"] = True
    row["is_in_progress"] = True
    row["is_virtual_live"] = False
    row["is_absorbed_pending"] = state == "absorbed_pending"
    row["edit_disabled"] = True
    row["disable_reason"] = _LIVE_EDIT_DISABLE_REASON

    if state == "persisted_open":
        # Persisted_open overlays project-ownership fields from the
        # snapshot's display_project block (mirrors the legacy
        # apply_persisted_open_overlay_to_row behaviour).
        row["project_id"] = int(span.get("project_id") or 0)
        row["project_name"] = str(span.get("project_name") or "未归类")
        row["project_description"] = str(span.get("project_description") or "")
        row["display_project"] = span.get("display_project")
        row["candidate_project"] = span.get("candidate_project")
        row["project_transition"] = span.get("project_transition")
        row["project_transition_pending"] = bool(span.get("project_transition_pending"))
        row["is_uncategorized"] = not bool(row.get("project_id"))
        row["is_classified"] = bool(row.get("project_id"))
        row["source"] = "db"
        row["start_time"] = str(span.get("start_time") or row.get("start_time") or "")
    elif state == "absorbed_pending":
        # Absorbed_pending keeps the anchor row's project / resource
        # identity; only the live clock is projected. ``source`` is
        # marked so the frontend can distinguish the projection.
        row["source"] = "absorbed_pending"
    return row


# Main entry point


def build_activity_display_model(
    report_date: str | None = None,
    today: str | None = None,
) -> dict[str, Any]:
    """Build the unified Activity Display Model from a single snapshot.

    This is the ONLY function the page ViewModels should call to obtain
    live-display semantics. It reads the snapshot once, classifies the
    live state, resolves the absorption anchor, and returns a JSON-safe
    model with the unified ``live_clock``, ``current_activity``, and
    ``display_spans``.

    The model NEVER writes the DB. Absorption is display-only.
    """
    snapshot = _get_current_activity_snapshot()
    today = today or timeline_service.get_default_report_date()
    report_date = report_date or today
    is_today = report_date == today

    base_state = classify_live_state(snapshot)
    # On historical dates, virtual / persisted_open live projection is
    # suppressed (no live rows injected). The DB rows still appear, but
    # without live overlay.
    if not is_today:
        display_live_state = "none" if base_state == "virtual" else base_state
    else:
        display_live_state = classify_display_live_state(snapshot, report_date, today)

    anchor: dict[str, Any] | None = None
    if display_live_state == "absorbed_pending":
        anchor = _find_absorb_anchor(snapshot, today or "")

    summary = build_current_activity_summary(
        snapshot, report_date=report_date, today=today
    )
    live_clock = _build_live_clock(
        snapshot, display_live_state, anchor, summary, report_date, today or ""
    )

    display_spans: list[dict[str, Any]] = []
    if is_today and display_live_state in ("absorbed_pending", "persisted_open"):
        display_spans.append(
            _build_display_span(
                snapshot, display_live_state, anchor, live_clock, summary, report_date, today or ""
            )
        )

    current_activity = _build_current_activity_display(
        snapshot, display_live_state, anchor, summary, live_clock
    )

    # Backwards-compatible live_projection / live_display aliases derived
    # from the same model so existing frontend code keeps working while
    # the new live_clock / activity_display_model fields are adopted.
    live_projection = build_live_projection(snapshot, report_date=report_date, today=today)
    live_projection["display_span_id"] = live_clock.get("display_span_id") or ""
    live_projection["live_state"] = display_live_state
    live_projection["live_started_at_epoch_ms"] = int(live_clock.get("live_started_at_epoch_ms") or 0)
    live_projection["carry_seconds"] = int(live_clock.get("carry_seconds") or 0)
    live_projection["duration_seconds"] = int(live_clock.get("duration_seconds_at_sample") or 0)

    sample_id = str(live_clock.get("stable_live_key_hash") or "")

    return {
        "ok": True,
        "date": report_date,
        "is_today": bool(is_today),
        "sample_id": sample_id,
        "live_clock": live_clock,
        "current_activity": current_activity,
        "display_spans": display_spans,
        "live_projection": live_projection,
        "live_display": current_activity,
    }


def get_live_span(model: dict[str, Any]) -> dict[str, Any] | None:
    """Return the single live display span from a display model, or ``None``."""
    spans = model.get("display_spans") or []
    return spans[0] if spans else None


__all__ = [
    "apply_live_span_to_row",
    "build_activity_display_model",
    "classify_display_live_state",
    "get_live_span",
]
