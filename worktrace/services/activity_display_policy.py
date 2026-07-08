from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from ..constants import STATUS_NORMAL, UNCATEGORIZED_PROJECT
from ..contracts.live_display_contracts import (
    ActivitySnapshotContract,
    CurrentActivityContract,
    DisplaySessionPolicyContract,
)
from ..formatters import format_status_label
from . import (
    activity_continuity_service,
    activity_service,
    session_boundary_service,
)
from .activity_display_projection import resolve_official_anchor_project
from .live_display_service import classify_live_state
from .live_time_service import snapshot_extra_seconds


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
    borrowed_anchor_activity_id: int = 0
    borrowed_anchor_base_seconds: int = 0
    borrowed_anchor_project_id: int = 0
    borrowed_anchor_project_name: str = ""
    borrowed_anchor_project_description: str = ""

    def to_dict(self) -> DisplaySessionPolicyContract:
        return asdict(self)


def classify_display_live_state(
    snapshot: ActivitySnapshotContract | None,
    report_date: str | None,
    today: str | None,
) -> str:
    base = classify_live_state(snapshot)
    if base in ("paused", "idle", "excluded", "error"):
        return "status_only" if report_date and today and report_date == today else "none"
    if base != "virtual":
        return base
    if not report_date or not today or report_date != today:
        return "none"
    return "current_only_pending"


def status_only_reason_for_state(display_live_state: str) -> str:
    if display_live_state in ("paused", "idle", "excluded", "error"):
        return display_live_state
    return ""


def status_display_label(status: str) -> str:
    return "" if status == STATUS_NORMAL else format_status_label(status)


def build_status_display_item(
    snapshot: ActivitySnapshotContract | None,
    display_live_state: str,
    report_date: str,
    today: str,
) -> dict[str, Any] | None:
    if report_date != today:
        return None
    status = status_only_reason_for_state(display_live_state)
    if display_live_state == "status_only" and snapshot:
        status = str(snapshot.get("status") or status)
    if not status:
        return None
    display_status = status_display_label(status)
    return {
        "row_kind": "status_only",
        "status_code": status,
        "status_label": display_status,
        "display_status": display_status,
        "project_name": "—",
        "project_description": "",
        "start_time": str(snapshot.get("start_time") or "") if snapshot else "",
        "end_time": "",
        "duration": "00:00:00",
        "duration_seconds": 0,
        "duration_semantic": "static_status",
        "duration_seconds_at_sample": 0,
        "display_base_seconds": 0,
        "aggregate_display_base_seconds": 0,
        "current_live_base_seconds": 0,
        "current_live_seconds_at_sample": 0,
        "contributes_to_totals": False,
        "project_duration_live": False,
        "current_duration_live": False,
        "live_delta_eligible": False,
        "is_live": False,
        "is_project_duration_live": False,
        "is_in_progress": False,
        "is_live_projected": False,
        "is_virtual": False,
        "is_virtual_live": False,
        "display_span_id": "",
        "stable_live_key": "",
        "stable_live_key_hash": "",
        "live_started_at_epoch_ms": 0,
        "carry_seconds": 0,
        "exportable": False,
        "editable": False,
        "edit_disabled": True,
        "disable_reason": "系统状态行不可编辑",
        "source": "status_only",
    }


def anchor_project_fields(anchor: dict[str, Any] | None) -> dict[str, Any]:
    return resolve_official_anchor_project(anchor)


def resolve_borrowed_display_anchor(
    snapshot: ActivitySnapshotContract | None,
    report_date: str | None,
    today: str | None,
) -> dict[str, Any] | None:
    if not snapshot or not report_date or not today or report_date != today:
        return None
    if classify_live_state(snapshot) != "virtual":
        return None
    if str(snapshot.get("status") or "") != STATUS_NORMAL:
        return None
    latest_boundary = session_boundary_service.latest_boundary_time() or None
    anchor = activity_service.get_latest_closed_auto_normal_activity(
        after_time=latest_boundary
    )
    if not activity_continuity_service.can_absorb_short_pending(anchor, snapshot):
        return None
    return anchor


def build_display_session_policy(
    snapshot: ActivitySnapshotContract | None,
    report_date: str,
    today: str,
    base_state: str,
    anchor: dict[str, Any] | None,
    display_live_state: str,
    summary: CurrentActivityContract,
) -> DisplaySessionPolicy:
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

    status = str(snapshot.get("status") or "")
    live_started_at = int(summary.get("live_started_at_epoch_ms") or 0)
    if (
        display_live_state in ("paused", "idle", "excluded", "error", "status_only")
        or status != STATUS_NORMAL
    ):
        reason = status_only_reason_for_state(display_live_state) or status or display_live_state
        return DisplaySessionPolicy(
            display_session_kind="status_only",
            base_policy="suppressed",
            aggregate_base_seconds=0,
            current_base_seconds=0,
            project_duration_live=False,
            current_duration_live=False,
            materialize_recent=False,
            materialize_timeline=False,
            materialize_details=False,
            status_only_reason=reason,
            base_policy_reason="status_not_project_live",
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

    if display_live_state in ("borrowed_anchor_pending", "current_only_pending"):
        if anchor:
            anchor_base = int(anchor.get("duration_seconds") or 0)
            anchor_project = anchor_project_fields(anchor)
            return DisplaySessionPolicy(
                display_session_kind="borrowed_anchor_pending",
                base_policy="borrowed_anchor_static",
                aggregate_base_seconds=anchor_base,
                current_base_seconds=0,
                project_duration_live=True,
                current_duration_live=live_started_at > 0,
                materialize_recent=True,
                materialize_timeline=True,
                materialize_details=True,
                status_only_reason="",
                base_policy_reason="borrowed_anchor_pending",
                borrowed_anchor_activity_id=int(anchor.get("id") or 0),
                borrowed_anchor_base_seconds=anchor_base,
                borrowed_anchor_project_id=int(anchor_project["project_id"] or 0),
                borrowed_anchor_project_name=str(anchor_project["project_name"] or ""),
                borrowed_anchor_project_description=str(
                    anchor_project["project_description"] or ""
                ),
            )
        return DisplaySessionPolicy(
            display_session_kind="current_only_pending",
            base_policy="current_only_zero",
            aggregate_base_seconds=0,
            current_base_seconds=0,
            project_duration_live=False,
            current_duration_live=live_started_at > 0,
            materialize_recent=False,
            materialize_timeline=False,
            materialize_details=False,
            status_only_reason="",
            base_policy_reason="unanchored_pending_current_only",
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
