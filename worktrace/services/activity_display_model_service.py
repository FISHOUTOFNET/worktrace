"""Unified Activity Display Model — sole owner of live display semantics.

Reads ``current_activity_snapshot`` once and produces a single JSON-safe
display model. The ONLY place that decides: live-eligibility; the refined
``live_state`` (``none`` / ``virtual_pending`` / ``absorbed_pending`` /
``persisted_open`` / ``paused`` / ``idle`` / ``excluded`` / ``error``);
stable live identity; display span identity; live clock anchor; ``<30s``
pending absorption (display-only projection — NEVER writes the DB);
visibility of live rows in recent / timeline / details.

Short-activity contract (DO NOT collapse these stages): Running
``absorbed_pending`` display projection (``<30s`` pending RUNNING,
unpersisted snapshot) projects pending elapsed onto the previous confirmed
normal activity's DB row — DISPLAY-ONLY, NEVER writes the DB. Finished
short-activity merge is COLLECTOR-OWNED persistence behavior
(``_merge_or_pend_short_seconds`` real DB write, ``pending_short_seconds``
pend, or drop at session boundary) — NOT the display model's responsibility.

Boundary: lives in ``worktrace.services``; imports low-level helpers from
``live_display_service`` plus ``activity_service``, ``timeline_service``,
``settings_service``, ``live_time_service`` and stdlib only. MUST NOT be imported by
``worktrace.webview_ui.*`` directly. JSON-serializable only; raw
``window_title`` / ``file_path_hint`` / ``note`` / ``clipboard`` / SQL /
tracebacks / paths / passphrases NEVER surfaced.
"""


from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
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
from . import activity_service, timeline_service
from .activity_continuity_service import can_absorb_short_pending
from .live_display_service import (
    _display_resource_name,
    _snapshot_display_project_fields,
    _stable_live_key,
    _stable_live_key_hash,
    build_current_activity_summary,
    classify_live_state,
)
from .live_time_service import (
    safe_int,
    snapshot_elapsed_seconds,
    snapshot_extra_seconds,
    snapshot_persisted_id,
)
from .runtime_activity_state_service import validate_pending_short_carry
from .settings_service import get_setting


# Sentinel activity id used when no real DB row backs a display span.
_VIRTUAL_ACTIVITY_ID = 0

# Disable-reason text for live rows still in progress / pending confirmation.
_LIVE_EDIT_DISABLE_REASON = "当前活动尚未进入历史，暂不能编辑"

CURRENT_LIVE = "current_live"
AGGREGATE_LIVE = "aggregate_live"
STATIC_CLOSED = "static_closed"

ROW_KIND_CURRENT_ACTIVITY_HEADER = "current_activity_header"
ROW_KIND_ACTIVITY_DETAIL_ROW = "activity_detail_row"
ROW_KIND_PROJECT_SESSION_ROW = "project_session_row"
ROW_KIND_RECENT_PROJECT_SESSION_ROW = "recent_project_session_row"
ROW_KIND_KPI_TOTAL = "kpi_total"
ROW_KIND_HISTORICAL_CLOSED_ROW = "historical_closed_row"

_CURRENT_LIVE_ROW_KINDS = {
    ROW_KIND_CURRENT_ACTIVITY_HEADER,
    ROW_KIND_ACTIVITY_DETAIL_ROW,
}
_AGGREGATE_LIVE_ROW_KINDS = {
    ROW_KIND_PROJECT_SESSION_ROW,
    ROW_KIND_RECENT_PROJECT_SESSION_ROW,
    ROW_KIND_KPI_TOTAL,
}
_DISPLAY_ROW_KINDS = (
    ROW_KIND_CURRENT_ACTIVITY_HEADER,
    ROW_KIND_ACTIVITY_DETAIL_ROW,
    ROW_KIND_PROJECT_SESSION_ROW,
    ROW_KIND_RECENT_PROJECT_SESSION_ROW,
    ROW_KIND_KPI_TOTAL,
    ROW_KIND_HISTORICAL_CLOSED_ROW,
)


@dataclass(frozen=True)
class DisplaySessionPolicy:
    display_session_kind: str
    base_policy: str
    aggregate_base_seconds: int
    current_base_seconds: int
    project_duration_live: bool
    current_duration_live: bool
    materialize_recent: bool
    materialize_timeline: bool
    materialize_details: bool
    status_only_reason: str
    base_policy_reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# Sentinel for ``build_activity_display_model(snapshot=...)``: distinguishes
# "not passed" from "explicitly passed ``None``". A passed snapshot MUST
# NOT trigger an internal re-read of ``current_activity_snapshot``.
_UNSET = object()


def _build_suppressed_live_clock() -> dict[str, Any]:
    """Build a fully-suppressed live clock for historical dates.

    On ``report_date != today`` the page-scoped live clock MUST NOT carry
    any tickable field: no ``display_span_id``, no ``live_started_at_epoch_ms``,
    no ``carry_seconds``, ``is_live`` / ``is_project_duration_live`` both
    ``False``. This prevents the frontend ticker from registering an active
    project-duration live clock on a historical Timeline / Details / Recent
    page and prevents the current open row's live seconds from polluting
    the historical total.
    """
    return {
        "display_span_id": "",
        "stable_live_key": "",
        "stable_live_key_hash": "",
        "live_state": "none",
        "live_started_at_epoch_ms": 0,
        "carry_seconds": 0,
        "duration_semantic": STATIC_CLOSED,
        "current_live_seconds_at_sample": 0,
        "current_live_base_seconds": 0,
        "aggregate_duration_seconds_at_sample": 0,
        "aggregate_display_base_seconds": 0,
        "display_base_seconds": 0,
        "duration_seconds_at_sample": 0,
        "active_elapsed_at_sample": 0,
        "current_elapsed_at_sample": 0,
        "is_live": False,
        "is_project_duration_live": False,
        "current_duration_live": False,
        "project_duration_live": False,
        "display_session_kind": "suppressed",
        "base_policy": "suppressed",
        "status_only_reason": "historical_date",
        "base_policy_reason": "historical_date",
        "display_policy": DisplaySessionPolicy(
            display_session_kind="suppressed",
            base_policy="suppressed",
            aggregate_base_seconds=0,
            current_base_seconds=0,
            project_duration_live=False,
            current_duration_live=False,
            materialize_recent=False,
            materialize_timeline=False,
            materialize_details=False,
            status_only_reason="historical_date",
            base_policy_reason="historical_date",
        ).to_dict(),
    }


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
    return can_absorb_short_pending(row, pending_start_time)


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
      previous confirmed normal activity to absorb into. It produces a
      display-only span for Current / Recent / Timeline / Details.
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


def _current_resource_identity_hash(snapshot: dict[str, Any] | None) -> str:
    """Hash current resource identity + start_time for UI continuity.

    The raw resource identity may contain a path, so only the digest is
    surfaced. Including start_time lets a window/resource switch reset the
    current activity display while virtual_pending -> persisted_open for the
    same resource remains continuous.
    """
    if not snapshot:
        return ""
    resource_identity = (
        snapshot.get("resource_identity_key")
        or snapshot.get("activity_identity_key")
        or snapshot.get("resource_display_name")
        or snapshot.get("activity_display_name")
        or snapshot.get("app_name")
        or snapshot.get("process_name")
        or ""
    )
    parts = [
        str(resource_identity or ""),
        str(snapshot.get("start_time") or ""),
        str(snapshot.get("status") or ""),
    ]
    key = "|".join(parts)
    if not key.strip("|"):
        return ""
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]


def _status_only_reason_for_state(display_live_state: str) -> str:
    if display_live_state in ("paused", "idle", "excluded", "error"):
        return display_live_state
    return ""


def _build_display_session_policy(
    snapshot: dict[str, Any] | None,
    report_date: str,
    today: str,
    base_state: str,
    anchor: dict[str, Any] | None,
    display_live_state: str,
    summary: dict[str, Any],
) -> DisplaySessionPolicy:
    """Central Display Session Boundary Policy.

    This is the only place that decides whether aggregate live duration can
    use a static base. Natural elapsed seconds are intentionally excluded
    from the policy identity; only structural base eligibility belongs here.
    """
    if not snapshot:
        return DisplaySessionPolicy(
            display_session_kind="none",
            base_policy="suppressed",
            aggregate_base_seconds=0,
            current_base_seconds=0,
            project_duration_live=False,
            current_duration_live=False,
            materialize_recent=False,
            materialize_timeline=False,
            materialize_details=False,
            status_only_reason="",
            base_policy_reason="no_snapshot",
        )

    if report_date != today:
        return DisplaySessionPolicy(
            display_session_kind="suppressed",
            base_policy="suppressed",
            aggregate_base_seconds=0,
            current_base_seconds=0,
            project_duration_live=False,
            current_duration_live=False,
            materialize_recent=False,
            materialize_timeline=False,
            materialize_details=False,
            status_only_reason="historical_date",
            base_policy_reason="historical_date",
        )

    status = _snapshot_status_safe(snapshot)
    live_started_at = int(summary.get("live_started_at_epoch_ms") or 0)
    if display_live_state in ("paused", "idle", "excluded", "error") or status != STATUS_NORMAL:
        reason = _status_only_reason_for_state(display_live_state) or status or display_live_state
        current_duration_live = display_live_state != "paused" and live_started_at > 0
        return DisplaySessionPolicy(
            display_session_kind="status_only",
            base_policy="suppressed",
            aggregate_base_seconds=0,
            current_base_seconds=0,
            project_duration_live=False,
            current_duration_live=current_duration_live,
            materialize_recent=False,
            materialize_timeline=False,
            materialize_details=False,
            status_only_reason=reason,
            base_policy_reason="status_not_project_live",
        )

    if display_live_state == "absorbed_pending" and anchor:
        return DisplaySessionPolicy(
            display_session_kind="absorbed_pending",
            base_policy="absorbed_anchor",
            aggregate_base_seconds=safe_int(anchor.get("duration_seconds")) + snapshot_extra_seconds(snapshot),
            current_base_seconds=0,
            project_duration_live=True,
            current_duration_live=live_started_at > 0,
            materialize_recent=True,
            materialize_timeline=True,
            materialize_details=True,
            status_only_reason="",
            base_policy_reason="valid_absorbed_anchor",
        )

    if display_live_state == "persisted_open":
        return DisplaySessionPolicy(
            display_session_kind="persisted_open",
            base_policy="persisted_extra",
            aggregate_base_seconds=snapshot_extra_seconds(snapshot),
            current_base_seconds=0,
            project_duration_live=True,
            current_duration_live=live_started_at > 0,
            materialize_recent=True,
            materialize_timeline=True,
            materialize_details=True,
            status_only_reason="",
            base_policy_reason="persisted_open_extra",
        )

    if display_live_state == "virtual_pending":
        carry = validate_pending_short_carry(
            current_start_time=str(snapshot.get("start_time") or ""),
            current_status=status,
        )
        if carry.get("valid"):
            return DisplaySessionPolicy(
                display_session_kind="continuous_virtual",
                base_policy="validated_pending_carry",
                aggregate_base_seconds=int(carry.get("seconds") or 0),
                current_base_seconds=0,
                project_duration_live=True,
                current_duration_live=live_started_at > 0,
                materialize_recent=True,
                materialize_timeline=True,
                materialize_details=True,
                status_only_reason="",
                base_policy_reason="validated_pending_carry",
            )
        return DisplaySessionPolicy(
            display_session_kind="fresh_virtual",
            base_policy="zero",
            aggregate_base_seconds=0,
            current_base_seconds=0,
            project_duration_live=True,
            current_duration_live=live_started_at > 0,
            materialize_recent=True,
            materialize_timeline=True,
            materialize_details=True,
            status_only_reason="",
            base_policy_reason=str(carry.get("reason") or "no_valid_pending_carry"),
        )

    return DisplaySessionPolicy(
        display_session_kind="none" if base_state == "none" else "suppressed",
        base_policy="suppressed",
        aggregate_base_seconds=0,
        current_base_seconds=0,
        project_duration_live=False,
        current_duration_live=False,
        materialize_recent=False,
        materialize_timeline=False,
        materialize_details=False,
        status_only_reason="",
        base_policy_reason="not_live_projectable",
    )


def _build_project_live_clock(
    snapshot: dict[str, Any] | None,
    display_live_state: str,
    anchor: dict[str, Any] | None,
    summary: dict[str, Any],
    policy: DisplaySessionPolicy,
    report_date: str,
    today: str,
) -> dict[str, Any]:
    """Build the project/history projection live-clock block.

    Project/history formula: ``display_base_seconds + current_active_elapsed``.
    The dynamic portion is the current resource elapsed source sampled from
    the same snapshot, not the project duration reverse-engineered as a
    current activity duration.

    Invariants at sample time ``T0``: ``duration_seconds_at_sample ==
    display_base_seconds + current_elapsed_at_sample``; rows/KPIs add only
    the heartbeat delta after render.

    Carry per state is decided only by ``DisplaySessionPolicy``.
    """
    stable_key = _stable_live_key(snapshot)
    stable_hash = _stable_live_key_hash(snapshot)
    display_span_id = ("span:" + stable_hash) if stable_hash else ""
    live_started_at = int(summary.get("live_started_at_epoch_ms") or 0)
    current_elapsed_at_sample = int(snapshot_elapsed_seconds(snapshot))
    display_base_seconds = int(policy.aggregate_base_seconds)
    carry_seconds = int(policy.aggregate_base_seconds)
    duration_at_sample = display_base_seconds + current_elapsed_at_sample
    is_project_duration_live = bool(policy.project_duration_live)
    is_current_duration_live = bool(policy.current_duration_live and live_started_at > 0)

    current_live_seconds_at_sample = int(current_elapsed_at_sample)
    current_live_base_seconds = 0
    aggregate_display_base_seconds = int(display_base_seconds)
    aggregate_duration_seconds_at_sample = int(duration_at_sample)

    return {
        "display_span_id": display_span_id,
        "stable_live_key": stable_key,
        "stable_live_key_hash": stable_hash,
        "live_state": display_live_state,
        "live_started_at_epoch_ms": live_started_at,
        "carry_seconds": int(carry_seconds),
        "duration_semantic": AGGREGATE_LIVE if is_project_duration_live else STATIC_CLOSED,
        "current_live_seconds_at_sample": current_live_seconds_at_sample,
        "current_live_base_seconds": current_live_base_seconds,
        "aggregate_duration_seconds_at_sample": aggregate_duration_seconds_at_sample,
        "aggregate_display_base_seconds": aggregate_display_base_seconds,
        "display_base_seconds": int(display_base_seconds),
        "duration_seconds_at_sample": int(duration_at_sample),
        "active_elapsed_at_sample": int(current_elapsed_at_sample),
        "current_elapsed_at_sample": int(current_elapsed_at_sample),
        "project_duration_live": bool(is_project_duration_live),
        "current_duration_live": bool(is_current_duration_live),
        "is_live": bool(is_project_duration_live or is_current_duration_live),
        "is_project_duration_live": bool(is_project_duration_live),
        "display_session_kind": policy.display_session_kind,
        "base_policy": policy.base_policy,
        "status_only_reason": policy.status_only_reason,
        "base_policy_reason": policy.base_policy_reason,
        "display_policy": policy.to_dict(),
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
    so the user knows what they are currently looking at. Its primary
    duration is the current resource elapsed source. Absorbed/project display
    projection remains in ``live_clock`` for Recent / Timeline / Details.
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
            "display_span_id": "",
            "live_clock": live_clock,
            "current_activity_display_span_id": "",
            "display_base_seconds": 0,
            "duration_semantic": CURRENT_LIVE,
            "current_live_seconds_at_sample": 0,
            "current_live_base_seconds": 0,
            "aggregate_duration_seconds_at_sample": 0,
            "aggregate_display_base_seconds": 0,
            "display_session_kind": "none",
            "base_policy": "suppressed",
            "status_only_reason": "",
            "base_policy_reason": "no_snapshot",
        }

    # Start from the existing summary and override live clock / elapsed fields.
    display = dict(summary)
    display["live_clock"] = live_clock
    display["display_span_id"] = live_clock.get("display_span_id") or ""
    identity_hash = _current_resource_identity_hash(snapshot)
    display["current_activity_display_span_id"] = ("current:" + identity_hash) if identity_hash else ""
    display["current_resource_identity_hash"] = identity_hash
    display["live_state"] = display_live_state
    display["live_started_at_epoch_ms"] = int(
        live_clock.get("live_started_at_epoch_ms") or 0
    )
    display["carry_seconds"] = 0
    display["display_base_seconds"] = 0
    display["duration_semantic"] = CURRENT_LIVE
    current_elapsed = int(snapshot_elapsed_seconds(snapshot))
    display["resource_elapsed_seconds"] = current_elapsed
    display["elapsed_seconds"] = current_elapsed
    display["duration_seconds_at_sample"] = display["elapsed_seconds"]
    display["current_live_seconds_at_sample"] = current_elapsed
    display["current_live_base_seconds"] = 0
    display["aggregate_duration_seconds_at_sample"] = int(
        live_clock.get("aggregate_duration_seconds_at_sample")
        or current_elapsed
    )
    display["aggregate_display_base_seconds"] = int(
        live_clock.get("aggregate_display_base_seconds")
        or live_clock.get("display_base_seconds")
        or 0
    )
    display["display_session_kind"] = str(live_clock.get("display_session_kind") or "")
    display["base_policy"] = str(live_clock.get("base_policy") or "")
    display["status_only_reason"] = str(live_clock.get("status_only_reason") or "")
    display["base_policy_reason"] = str(live_clock.get("base_policy_reason") or "")

    display["is_virtual_live"] = display_live_state == "virtual_pending"
    display["is_in_progress"] = display_live_state == "persisted_open"
    display["is_absorbed_pending"] = display_live_state == "absorbed_pending"
    display["source"] = _source_for_state(display_live_state, snapshot)

    from ..formatters import format_duration

    display_seconds = int(display.get("elapsed_seconds") or 0)
    if display.get("display"):
        parts = str(display.get("display") or "").split("｜")
        if len(parts) >= 3:
            parts[2] = format_duration(display_seconds)
            display["display"] = "｜".join(parts)

    # Absorbed_pending: KPI project attribution MUST come from the anchor DB row.
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
        from .live_display_service import _display_resource_name as _resource_name
        resource_name = _resource_name(snapshot)
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
    return display


def _signature_project_dict(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    return {
        "id": value.get("id"),
        "name": str(value.get("name") or ""),
        "source": str(value.get("source") or ""),
    }


def _build_display_structural_signature(
    snapshot: dict[str, Any] | None,
    display_live_state: str,
    anchor: dict[str, Any] | None,
    live_clock: dict[str, Any],
    current_activity: dict[str, Any],
    report_date: str,
    today: str,
    is_today: bool,
) -> str:
    project_transition = current_activity.get("project_transition") or {}
    signature_payload = {
        "current_activity_stable_key": str(
            current_activity.get("stable_live_key") or _stable_live_key(snapshot)
        ),
        "display_live_state": display_live_state,
        "is_persisted": bool(snapshot and snapshot.get("is_persisted")),
        "persisted_activity_id": int(snapshot_persisted_id(snapshot) or 0) if snapshot else 0,
        "display_project": _signature_project_dict(current_activity.get("display_project")),
        "candidate_project": _signature_project_dict(current_activity.get("candidate_project")),
        "project_transition": {
            "pending": bool(project_transition.get("pending")),
            "from_project_id": project_transition.get("from_project_id"),
            "to_project_id": project_transition.get("to_project_id"),
        },
        "project_live_span": {
            "display_span_id": str(live_clock.get("display_span_id") or ""),
            "anchor_activity_id": int(anchor.get("id") or 0) if anchor else 0,
            "materialize_recent": bool(
                (live_clock.get("display_policy") or {}).get("materialize_recent")
            ),
            "materialize_timeline": bool(
                (live_clock.get("display_policy") or {}).get("materialize_timeline")
            ),
            "materialize_details": bool(
                (live_clock.get("display_policy") or {}).get("materialize_details")
            ),
        },
        "base_policy": {
            "display_session_kind": str(live_clock.get("display_session_kind") or ""),
            "base_policy": str(live_clock.get("base_policy") or ""),
            "status_only_reason": str(live_clock.get("status_only_reason") or ""),
            "base_policy_reason": str(live_clock.get("base_policy_reason") or ""),
        },
        "current_activity_display_span_id": str(
            current_activity.get("current_activity_display_span_id") or ""
        ),
        "report_date": report_date,
        "today": today,
        "is_today": bool(is_today),
    }
    return json.dumps(signature_payload, sort_keys=True, ensure_ascii=False)


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
    current_live_seconds = int(
        live_clock.get("current_live_seconds_at_sample")
        or live_clock.get("current_elapsed_at_sample")
        or 0
    )
    aggregate_duration = int(
        live_clock.get("aggregate_duration_seconds_at_sample")
        or live_clock.get("duration_seconds_at_sample")
        or current_live_seconds
    )
    aggregate_base = int(
        live_clock.get("aggregate_display_base_seconds")
        or live_clock.get("display_base_seconds")
        or 0
    )
    policy = live_clock.get("display_policy") or {}
    # Anchor base seconds exists only for absorbed_pending, where the display
    # projection is explicitly anchored to a closed row. Persisted-open rows
    # derive static bases from row structural fields during row-kind projection.
    live_anchor_base_seconds = 0

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
        live_anchor_base_seconds = safe_int(anchor.get("duration_seconds"))
    else:
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
        "duration_semantic": "",
        "duration": format_duration(aggregate_duration),
        "duration_seconds": aggregate_duration,
        "duration_seconds_at_sample": aggregate_duration,
        "current_live_seconds_at_sample": current_live_seconds,
        "current_live_base_seconds": 0,
        "aggregate_duration_seconds_at_sample": aggregate_duration,
        "aggregate_display_base_seconds": aggregate_base,
        "display_base_seconds": aggregate_base,
        "live_clock": live_clock,
        "project_id": int(project_id),
        "project_name": project_name,
        "project_description": project_description,
        "resource_name": _display_resource_name(snapshot) if snapshot else "",
        "is_current": True,
        "is_live": bool(live_clock.get("is_live")),
        "project_duration_live": bool(live_clock.get("project_duration_live", live_clock.get("is_project_duration_live"))),
        "current_duration_live": bool(live_clock.get("current_duration_live")),
        "display_session_kind": str(live_clock.get("display_session_kind") or ""),
        "base_policy": str(live_clock.get("base_policy") or ""),
        "status_only_reason": str(live_clock.get("status_only_reason") or ""),
        "base_policy_reason": str(live_clock.get("base_policy_reason") or ""),
        "is_virtual": bool(is_virtual),
        "is_persisted": bool(is_persisted),
        "is_absorbed_pending": bool(is_absorbed),
        "is_visible_in_current": True,
        "is_visible_in_recent": bool(policy.get("materialize_recent")),
        "is_visible_in_timeline": bool(policy.get("materialize_timeline")),
        "is_visible_in_details": bool(policy.get("materialize_details")),
        "is_display_only": display_live_state in ("virtual_pending", "absorbed_pending"),
        "display_only": display_live_state in ("virtual_pending", "absorbed_pending"),
        "editable": False,
        "exportable": False,
        "edit_disabled": True,
        "disable_reason": _LIVE_EDIT_DISABLE_REASON,
        "display_project": project_fields["display_project"] if display_live_state != "absorbed_pending" else None,
        "candidate_project": project_fields["candidate_project"] if display_live_state != "absorbed_pending" else None,
        "project_transition": project_fields["project_transition"] if display_live_state != "absorbed_pending" else None,
        "project_transition_pending": bool(project_fields["project_transition_pending"]) if display_live_state != "absorbed_pending" else False,
        "live_anchor_activity_id": int(anchor_id),
        "live_anchor_base_seconds": int(live_anchor_base_seconds),
        "is_uncategorized": bool(project_fields["is_uncategorized"]),
        "is_classified": bool(project_fields["is_classified"]),
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
        "duration_semantic": str(live_clock.get("duration_semantic") or ""),
        "current_live_seconds_at_sample": int(live_clock.get("current_live_seconds_at_sample") or 0),
        "current_live_base_seconds": int(live_clock.get("current_live_base_seconds") or 0),
        "aggregate_duration_seconds_at_sample": int(live_clock.get("aggregate_duration_seconds_at_sample") or 0),
        "aggregate_display_base_seconds": int(live_clock.get("aggregate_display_base_seconds") or 0),
        "display_base_seconds": int(live_clock.get("display_base_seconds") or 0),
        "duration_seconds_at_sample": int(live_clock.get("duration_seconds_at_sample") or 0),
        "active_elapsed_at_sample": int(live_clock.get("active_elapsed_at_sample") or 0),
        "current_elapsed_at_sample": int(live_clock.get("current_elapsed_at_sample") or 0),
        "is_live": bool(live_clock.get("is_live")),
        "is_project_duration_live": bool(live_clock.get("is_project_duration_live")),
        "project_duration_live": bool(live_clock.get("project_duration_live", live_clock.get("is_project_duration_live"))),
        "current_duration_live": bool(live_clock.get("current_duration_live")),
        "display_session_kind": str(live_clock.get("display_session_kind") or ""),
        "base_policy": str(live_clock.get("base_policy") or ""),
        "status_only_reason": str(live_clock.get("status_only_reason") or ""),
        "base_policy_reason": str(live_clock.get("base_policy_reason") or ""),
    }


def _current_active_elapsed_at_sample(live_clock: dict[str, Any]) -> int:
    return int(
        live_clock.get("current_elapsed_at_sample")
        or live_clock.get("active_elapsed_at_sample")
        or 0
    )


def _snapshot_extra_base_for_span(span: dict[str, Any], live_clock: dict[str, Any]) -> int:
    return int(
        live_clock.get("display_base_seconds")
        or span.get("display_base_seconds")
        or 0
    )


def _static_base_for_live_row(
    row: dict[str, Any],
    span: dict[str, Any],
    live_clock: dict[str, Any],
    state: str,
) -> int:
    if state != "persisted_open":
        return int(live_clock.get("display_base_seconds") or 0)

    anchor_id = int(span.get("anchor_activity_id") or 0)
    snapshot_extra_base = _snapshot_extra_base_for_span(span, live_clock)
    row_id = int(row.get("activity_id") or row.get("id") or 0)
    open_activity_id = int(row.get("open_activity_id") or 0)
    activity_ids = row.get("activity_ids")

    if row_id == anchor_id:
        return snapshot_extra_base

    if open_activity_id == anchor_id and "closed_duration_seconds" in row:
        return int(row.get("closed_duration_seconds") or 0) + snapshot_extra_base

    if isinstance(activity_ids, list) and anchor_id in {int(aid) for aid in activity_ids if aid}:
        row["live_contract_reason"] = "missing_closed_static_base"
        return snapshot_extra_base

    return snapshot_extra_base


def _duration_semantic_for_row_kind(row_kind: str) -> str:
    if row_kind in _CURRENT_LIVE_ROW_KINDS:
        return CURRENT_LIVE
    if row_kind in _AGGREGATE_LIVE_ROW_KINDS:
        return AGGREGATE_LIVE
    if row_kind == ROW_KIND_HISTORICAL_CLOSED_ROW:
        return STATIC_CLOSED
    raise ValueError(f"unknown live display row_kind: {row_kind!r}")


def apply_live_span_to_row(
    row: dict[str, Any],
    span: dict[str, Any] | None,
    *,
    row_kind: str,
) -> dict[str, Any]:
    """Project the unified live span onto a DB row payload by display row kind.

    Row matches when its ``activity_id`` / ``id`` / ``first_activity_id`` /
    ``activity_ids`` contains ``span.anchor_activity_id``.

    ``row_kind`` is the Projection Surface Contract. Current header/detail
    rows display only the current resource/window elapsed with base 0.
    Recent/Timeline/KPI rows display aggregate totals as
    ``static base + current elapsed``. Session rows keep their session
    ``start_time``; only current/detail surfaces may use the current activity
    start as their display ``start_time``.

    Mutates and returns ``row``; unchanged when ``span`` is ``None`` or no match.
    """
    semantic = _duration_semantic_for_row_kind(row_kind)
    if semantic == STATIC_CLOSED:
        row["duration_semantic"] = STATIC_CLOSED
        row["live_delta_eligible"] = False
        return row
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
    state = str(span.get("live_state") or "")
    if row_kind == ROW_KIND_ACTIVITY_DETAIL_ROW and state == "absorbed_pending":
        return row

    row.update(_live_clock_fields(live_clock))
    current_live_seconds = int(
        live_clock.get("current_live_seconds_at_sample")
        or live_clock.get("current_elapsed_at_sample")
        or 0
    )
    aggregate_duration = int(
        live_clock.get("aggregate_duration_seconds_at_sample")
        or live_clock.get("duration_seconds_at_sample")
        or current_live_seconds
    )
    aggregate_base = int(
        live_clock.get("aggregate_display_base_seconds")
        or live_clock.get("display_base_seconds")
        or 0
    )
    # Preserve the row's raw duration before any live projection.
    if "raw_duration_seconds" not in row:
        row["raw_duration_seconds"] = int(row.get("duration_seconds") or 0)
    row_raw = int(row.get("raw_duration_seconds") or 0)
    from ..formatters import format_duration

    if state == "absorbed_pending":
        anchor_base = int(span.get("live_anchor_base_seconds") or 0)
        pending_extra_base = max(
            0,
            int(
                live_clock.get("aggregate_display_base_seconds")
                or live_clock.get("display_base_seconds")
                or 0
            ) - anchor_base,
        )
        aggregate_base = row_raw + pending_extra_base
        aggregate_duration = aggregate_base + current_live_seconds
    elif state == "persisted_open":
        aggregate_base = _static_base_for_live_row(row, span, live_clock, state)
        aggregate_duration = aggregate_base + current_live_seconds
    else:
        aggregate_base = int(
            live_clock.get("aggregate_display_base_seconds")
            or live_clock.get("display_base_seconds")
            or 0
        )
        aggregate_duration = aggregate_base + current_live_seconds

    row["current_live_seconds_at_sample"] = int(current_live_seconds)
    row["current_live_base_seconds"] = 0
    row["aggregate_duration_seconds_at_sample"] = int(aggregate_duration)
    row["aggregate_display_base_seconds"] = int(aggregate_base)
    row["current_activity_start_time"] = str(span.get("start_time") or "")
    row["open_activity_start_time"] = str(span.get("start_time") or "")

    if semantic == CURRENT_LIVE:
        row["duration_semantic"] = CURRENT_LIVE
        row["duration_seconds"] = int(current_live_seconds)
        row["duration"] = format_duration(current_live_seconds)
        row["display_base_seconds"] = 0
        row["live_base_seconds"] = 0
        row["duration_seconds_at_sample"] = int(current_live_seconds)
    else:
        row["duration_semantic"] = AGGREGATE_LIVE
        row["duration_seconds"] = int(aggregate_duration)
        row["duration"] = format_duration(aggregate_duration)
        row["display_base_seconds"] = int(aggregate_base)
        row["live_base_seconds"] = int(aggregate_base)
        row["duration_seconds_at_sample"] = int(aggregate_duration)
    row["live_delta_eligible"] = True
    row["is_live_projected"] = True
    row["is_in_progress"] = True
    row["is_virtual_live"] = False
    row["is_absorbed_pending"] = state == "absorbed_pending"
    row["edit_disabled"] = True
    row["disable_reason"] = _LIVE_EDIT_DISABLE_REASON

    if state == "persisted_open":
        row["project_id"] = int(span.get("project_id") or 0)
        row["project_name"] = str(span.get("project_name") or "未归类")
        row["project_description"] = str(span.get("project_description") or "")
        row["display_project"] = span.get("display_project")
        row["candidate_project"] = span.get("candidate_project")
        row["project_transition"] = span.get("project_transition")
        row["project_transition_pending"] = bool(span.get("project_transition_pending"))
        # Classification (Section 四): prefer span flags over project_id check.
        span_uncategorized = span.get("is_uncategorized")
        span_classified = span.get("is_classified")
        if span_uncategorized is not None:
            row["is_uncategorized"] = bool(span_uncategorized)
            row["is_classified"] = bool(span_classified) if span_classified is not None else (not bool(span_uncategorized))
        else:
            project_name_str = str(row.get("project_name") or "")
            if project_name_str == UNCATEGORIZED_PROJECT:
                row["is_uncategorized"] = True
                row["is_classified"] = False
            else:
                row["is_uncategorized"] = not bool(row.get("project_id"))
                row["is_classified"] = bool(row.get("project_id"))
        row["source"] = "db"
        if row_kind in _CURRENT_LIVE_ROW_KINDS:
            row["start_time"] = str(span.get("start_time") or row.get("start_time") or "")
        row["live_anchor_activity_id"] = int(span.get("live_anchor_activity_id") or 0)
        row["live_anchor_base_seconds"] = int(span.get("live_anchor_base_seconds") or 0)
    elif state == "absorbed_pending":
        row["source"] = "absorbed_pending"
    return row


# Main entry point


def build_activity_display_model(
    report_date: str | None = None,
    today: str | None = None,
    snapshot: Any = _UNSET,
    include_absorb_anchor: bool = True,
) -> dict[str, Any]:
    """Build the unified Activity Display Model from a single snapshot.

    The ONLY function page ViewModels should call for live-display
    semantics. Returns a JSON-safe model with ``live_clock`` /
    ``current_activity`` / ``display_spans``. The model NEVER writes the
    DB — running ``absorbed_pending`` projection is display-only; the
    finished ``<30s`` short-activity merge is collector-owned persistence
    in :mod:`worktrace.collector.auto_activity_recorder`.
    Snapshot injection (single-sample contract): callers that already read
    ``current_activity_snapshot`` (e.g. refresh-state ViewModel, which also
    feeds ``compute_refresh_revision``) MUST pass it via ``snapshot``.
    ``_UNSET`` (default) reads internally; ``None`` / ``dict`` MUST NOT
    re-read the setting. Historical-date suppression (``report_date !=
    today``): page-scoped ``live_clock`` is fully suppressed,
    ``display_spans == []``, and ALL live states collapse to ``"none"``
    so the ticker cannot register an active project-duration live clock
    on a historical page.
    """
    if snapshot is _UNSET:
        snapshot = _get_current_activity_snapshot()
    today = today or timeline_service.get_default_report_date()
    report_date = report_date or today
    is_today = report_date == today

    base_state = classify_live_state(snapshot)
    # On historical dates, ALL live states collapse to "none" so a tickable
    # clock cannot pollute the historical page; ``live_clock`` is suppressed.
    if not is_today:
        display_live_state = "none"
    elif not include_absorb_anchor and base_state == "virtual":
        display_live_state = "virtual_pending"
    else:
        display_live_state = classify_display_live_state(snapshot, report_date, today)

    anchor: dict[str, Any] | None = None
    if include_absorb_anchor and display_live_state == "absorbed_pending":
        anchor = _find_absorb_anchor(snapshot, today or "")

    summary = build_current_activity_summary(
        snapshot, report_date=report_date, today=today
    )
    policy = _build_display_session_policy(
        snapshot,
        report_date,
        today or "",
        base_state,
        anchor,
        display_live_state,
        summary,
    )
    if not is_today:
        live_clock = _build_suppressed_live_clock()
    else:
        live_clock = _build_project_live_clock(
            snapshot, display_live_state, anchor, summary, policy, report_date, today or ""
        )
    display_spans: list[dict[str, Any]] = []
    if is_today and (
        policy.materialize_recent
        or policy.materialize_timeline
        or policy.materialize_details
    ):
        display_spans.append(
            _build_display_span(
                snapshot, display_live_state, anchor, live_clock, summary, report_date, today or ""
            )
        )

    current_activity = _build_current_activity_display(
        snapshot, display_live_state, anchor, summary, live_clock
    )
    display_structural_signature = _build_display_structural_signature(
        snapshot,
        display_live_state,
        anchor,
        live_clock,
        current_activity,
        report_date,
        today or "",
        is_today,
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
        "display_structural_signature": display_structural_signature,
        "display_policy": policy.to_dict(),
    }


def build_live_runtime_model(
    snapshot: dict[str, Any] | None,
    report_date: str | None = None,
    today: str | None = None,
) -> dict[str, Any]:
    """Build the sole live runtime/display model from one sampled snapshot."""
    return build_activity_display_model(
        report_date=report_date,
        today=today,
        snapshot=snapshot,
    )


def get_live_span(model: dict[str, Any]) -> dict[str, Any] | None:
    """Return the single live display span from a display model, or ``None``."""
    spans = model.get("display_spans") or []
    return spans[0] if spans else None


__all__ = [
    "AGGREGATE_LIVE",
    "CURRENT_LIVE",
    "ROW_KIND_ACTIVITY_DETAIL_ROW",
    "ROW_KIND_CURRENT_ACTIVITY_HEADER",
    "ROW_KIND_HISTORICAL_CLOSED_ROW",
    "ROW_KIND_KPI_TOTAL",
    "ROW_KIND_PROJECT_SESSION_ROW",
    "ROW_KIND_RECENT_PROJECT_SESSION_ROW",
    "STATIC_CLOSED",
    "apply_live_span_to_row",
    "build_activity_display_model",
    "build_live_runtime_model",
    "classify_display_live_state",
    "get_live_span",
]
