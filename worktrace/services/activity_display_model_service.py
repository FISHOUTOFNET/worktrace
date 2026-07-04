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
    UNCATEGORIZED_PROJECT,
)
from . import activity_service, live_display_service, session_boundary_service, timeline_service
from .live_display_service import (
    _display_app_name,
    _display_project_description,
    _display_project_name,
    _display_resource_name,
    _read_pending_short_seconds,
    _snapshot_display_project_fields,
    _snapshot_total_seconds,
    _start_time_epoch_ms,
    _stable_live_key,
    _stable_live_key_hash,
    build_current_activity_summary,
    classify_live_state,
    is_live_eligible_for_normal,
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

# Disable-reason text for live rows still in progress / pending confirmation.
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


# Absorption anchor resolution


def _find_absorb_anchor(
    snapshot: dict[str, Any] | None,
    today: str,
) -> dict[str, Any] | None:
    """Return the latest confirmed normal activity the pending snapshot
    should absorb into (display-only), or ``None``.

    The anchor is the latest closed, non-deleted, non-hidden, auto,
    normal activity on ``today`` whose ``start_time`` and ``end_time``
    are both ``<= pending_start_time`` AND that is NOT separated from
    the pending snapshot by a session boundary (any recorded reason).
    The legacy short-activity-carry priority path was removed (no
    production writer); both paths collapse into a single scan through
    ``_is_absorbable_anchor()``. The anchor is used ONLY for display
    projection; the DB is NEVER written.
    """
    if not snapshot or not today:
        return None
    start_time = str(snapshot.get("start_time") or "")
    if not start_time:
        return None
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

    An anchor must satisfy ALL of: ``pending_start_time`` non-empty;
    row is non-deleted, non-hidden, auto, normal, CLOSED; both
    ``anchor.start_time`` and ``anchor.end_time`` are
    ``<= pending_start_time`` (overlap rejected); and no session
    boundary exists in ``[anchor.end_time, pending_start_time]`` (any
    recorded reason blocks absorption so a post-restart / post-stop /
    post-midnight ``<30s`` activity does not leak into the previous
    project).
    """
    if not pending_start_time:
        return False
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
    anchor_end = str(end_time)
    if not anchor_start:
        return False
    if anchor_start > pending_start_time:
        return False
    if anchor_end > pending_start_time:
        # Overlap / anomaly: anchor ended after pending start.
        return False
    if session_boundary_service.has_boundary_between(anchor_end, pending_start_time):
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

    Frontend formula: ``carry_seconds + floor((now - live_started_at_epoch_ms)/1000)``.
    Unified delta: ``max(0, live_span_seconds - duration_seconds_at_sample)``.

    Invariants at sample time ``T0``: ``duration_seconds_at_sample ==
    snapshot_elapsed + snapshot_extra``; ``live_span_seconds(T0) ==
    duration_seconds_at_sample``; ``live_span_seconds(T0 + 5s) ==
    duration_seconds_at_sample + 5``.

    Carry per state: ``absorbed_pending`` → anchor's
    ``duration_seconds`` (legacy structured carry add-on removed — no
    production writer); ``persisted_open`` → ``snapshot_extra_seconds``
    (preserves sub-30s pending folded into ``extra_seconds``);
    ``virtual_pending`` → ``pending_short_seconds`` (production
    collector-maintained accumulator; legacy structured carry removed).
    """
    stable_key = _stable_live_key(snapshot)
    stable_hash = _stable_live_key_hash(snapshot)
    display_span_id = ("span:" + stable_hash) if stable_hash else ""
    live_started_at = int(summary.get("live_started_at_epoch_ms") or 0)
    carry_seconds = int(summary.get("carry_seconds") or 0)
    duration_at_sample = int(summary.get("elapsed_seconds") or 0)

    if display_live_state == "absorbed_pending" and anchor:
        # carry = anchor's stored DB duration (no structured carry add-on).
        carry_seconds = safe_int(anchor.get("duration_seconds"))
        duration_at_sample = carry_seconds + _snapshot_total_seconds(snapshot)
    elif display_live_state == "virtual_pending":
        # carry = production-maintained pending_short_seconds only.
        carry_seconds = _read_pending_short_seconds()
        duration_at_sample = _snapshot_total_seconds(snapshot) + carry_seconds
    elif display_live_state == "persisted_open":
        # carry_seconds MUST equal snapshot_extra_seconds so the frontend
        # formula matches duration_seconds_at_sample at sample time.
        carry_seconds = snapshot_extra_seconds(snapshot)
        duration_at_sample = _snapshot_total_seconds(snapshot)

    is_live = display_live_state in (
        "virtual_pending",
        "absorbed_pending",
        "persisted_open",
    )
    # is_project_duration_live: only absorbed_pending and persisted_open
    # tick project totals (virtual_pending has no DB row).
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
    # absorbed_pending gets its own flag so the frontend can render it.
    display["is_absorbed_pending"] = display_live_state == "absorbed_pending"
    display["source"] = _source_for_state(display_live_state, snapshot)

    # Absorbed_pending consistency: KPI project attribution MUST come
    # from the anchor DB row (matches Recent / Timeline overlay).
    if display_live_state == "absorbed_pending" and anchor:
        anchor_project_id = int(anchor.get("project_id") or 0)
        anchor_project_name = str(anchor.get("project_name") or "未归类")
        anchor_project_description = str(anchor.get("project_description") or "")
        anchor_is_uncategorized = (
            not anchor_project_id or anchor_project_name == UNCATEGORIZED_PROJECT
        )
        display["project_id"] = anchor_project_id
        display["project_name"] = anchor_project_name
        display["project_description"] = anchor_project_description
        display["is_uncategorized"] = bool(anchor_is_uncategorized)
        display["is_classified"] = not bool(anchor_is_uncategorized)
        # The anchor's project is the source of truth; the snapshot's
        # pending candidate fields must NOT leak into current-activity.
        display["display_project"] = None
        display["candidate_project"] = None
        display["project_transition"] = {
            "pending": False,
            "started_at": "",
            "elapsed_seconds": 0,
            "threshold_seconds": 30,
            "from_project_id": None,
            "to_project_id": None,
        }
        display["project_transition_pending"] = False
        # Rebuild display text: project label from anchor, resource
        # name from snapshot (what the user is currently looking at).
        from ..formatters import format_duration
        from .live_display_service import _display_resource_name as _resource_name
        resource_name = _resource_name(snapshot)
        display_seconds = int(display.get("elapsed_seconds") or 0)
        state_label = "暂不入历史"
        status = _snapshot_status_safe(snapshot)
        if status == STATUS_IDLE:
            resource_name = "空闲中"
            state_label = "空闲"
        elif status == STATUS_PAUSED:
            state_label = "已暂停"
        elif status == STATUS_EXCLUDED:
            state_label = "已排除"
        elif status == STATUS_ERROR:
            state_label = "异常"
        display["display"] = (
            f"{resource_name}｜{anchor_project_name}｜"
            f"{format_duration(display_seconds)}｜{state_label}"
        )
        # resource_name / app_name still come from the snapshot.
    return display


def _snapshot_status_safe(snapshot: dict[str, Any] | None) -> str:
    if not snapshot:
        return ""
    return str(snapshot.get("status") or "")


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
        # persisted_open overlays project fields from snapshot's display_project.
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
        # absorbed_pending keeps the anchor DB row's identity.
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
        # Visibility: virtual_pending only in current-activity area;
        # absorbed_pending / persisted_open visible in lists (real DB row).
        "is_visible_in_current": True,
        "is_visible_in_recent": display_live_state in ("absorbed_pending", "persisted_open"),
        "is_visible_in_timeline": display_live_state in ("absorbed_pending", "persisted_open"),
        "is_visible_in_details": display_live_state in ("absorbed_pending", "persisted_open"),
        "edit_disabled": True,
        "disable_reason": _LIVE_EDIT_DISABLE_REASON,
        # Project-ownership fields (absorbed_pending keeps anchor's fields).
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

    Row matches when its ``activity_id`` / ``id`` / ``first_activity_id`` /
    ``activity_ids`` contains ``span.anchor_activity_id``. For
    ``persisted_open`` project fields are also overlaid; for
    ``absorbed_pending`` ONLY live clock fields are overlaid.

    Per-row base fields seeded on every matching row:
    - ``live_base_seconds`` — row's OWN display duration at sample time.
      Frontend renders ``live_base_seconds + live_delta`` so a session row
      (340s) and a detail row (240s) sharing the same span keep own bases.
    - ``duration_seconds_at_sample`` — live span's sample duration. Frontend
      computes ``live_delta = max(0, live_span_seconds - duration_seconds_at_sample)``.
    - ``live_delta_eligible`` — always ``True`` for matched live rows.

    Mutates and returns ``row``; unchanged when ``span`` is ``None`` or no match.
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
    # Preserve the row's raw duration before any live projection.
    if "raw_duration_seconds" not in row:
        row["raw_duration_seconds"] = int(row.get("duration_seconds") or 0)
    row_raw = int(row.get("raw_duration_seconds") or row.get("duration_seconds") or 0)
    from ..formatters import format_duration

    if state == "absorbed_pending":
        # Pending projection at sample time = duration_at_sample - carry.
        # Add it on top of row_raw so the frontend ticker lands on
        # row_raw + pending_elapsed_now.
        pending_at_sample = max(0, duration_at_sample - carry)
        projected = row_raw + pending_at_sample
        row["duration_seconds"] = int(projected)
        row["duration"] = format_duration(projected)
        row["live_base_seconds"] = int(projected)
    elif state == "persisted_open":
        # Detail row (the persisted activity itself) uses the snapshot
        # total; session / recent rows keep DB duration and let the
        # frontend add the unified delta.
        if row_id == anchor_id:
            row["duration_seconds"] = duration_at_sample
            row["duration"] = format_duration(duration_at_sample)
            row["live_base_seconds"] = int(duration_at_sample)
        else:
            row["duration_seconds"] = row_raw
            row["duration"] = format_duration(row_raw)
            row["live_base_seconds"] = int(row_raw)
    else:
        row["duration_seconds"] = duration_at_sample
        row["duration"] = format_duration(duration_at_sample)
        row["live_base_seconds"] = int(duration_at_sample)
    row["live_delta_eligible"] = True
    row["is_live_projected"] = True
    row["is_in_progress"] = True
    row["is_virtual_live"] = False
    row["is_absorbed_pending"] = state == "absorbed_pending"
    row["edit_disabled"] = True
    row["disable_reason"] = _LIVE_EDIT_DISABLE_REASON

    if state == "persisted_open":
        # Persisted_open overlays project-ownership fields from snapshot.
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
        # Absorbed_pending keeps the anchor row's identity; only live
        # clock is projected. ``source`` marks the projection.
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

    sample_id = str(live_clock.get("stable_live_key_hash") or "")

    return {
        "ok": True,
        "date": report_date,
        "is_today": bool(is_today),
        "sample_id": sample_id,
        "live_clock": live_clock,
        "current_activity": current_activity,
        "display_spans": display_spans,
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
