from __future__ import annotations

from typing import Any

from ..constants import UNCATEGORIZED_PROJECT
from ..contracts.live_display_contracts import DisplaySpanContract, LiveClockContract
from ..formatters import format_duration
from .activity_display_span import LIVE_EDIT_DISABLE_REASON
from .activity_live_clock import AGGREGATE_LIVE, CURRENT_LIVE, STATIC_CLOSED

ROW_KIND_CURRENT_ACTIVITY_HEADER = "current_activity_header"
ROW_KIND_ACTIVITY_DETAIL_ROW = "activity_detail_row"
ROW_KIND_PROJECT_ACTIVITY_SUMMARY_ROW = "project_activity_summary_row"
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
    ROW_KIND_PROJECT_ACTIVITY_SUMMARY_ROW,
    ROW_KIND_KPI_TOTAL,
}
_REPORT_ROW_KINDS = {
    ROW_KIND_PROJECT_SESSION_ROW,
    ROW_KIND_RECENT_PROJECT_SESSION_ROW,
    ROW_KIND_ACTIVITY_DETAIL_ROW,
    ROW_KIND_PROJECT_ACTIVITY_SUMMARY_ROW,
}


def apply_live_span_to_row(
    row: dict[str, Any],
    span: DisplaySpanContract | None,
    *,
    row_kind: str,
) -> dict[str, Any]:
    semantic = _duration_semantic_for_row_kind(row_kind)
    if semantic == STATIC_CLOSED:
        row["duration_semantic"] = STATIC_CLOSED
        row["live_delta_eligible"] = False
        return row
    if not span:
        return row
    if row_kind == ROW_KIND_RECENT_PROJECT_SESSION_ROW and not span.get("is_visible_in_recent"):
        return row
    if row_kind == ROW_KIND_PROJECT_SESSION_ROW and not span.get("is_visible_in_timeline"):
        return row
    if row_kind == ROW_KIND_ACTIVITY_DETAIL_ROW and not span.get("is_visible_in_details"):
        return row
    if row_kind == ROW_KIND_PROJECT_ACTIVITY_SUMMARY_ROW and not span.get("is_visible_in_details"):
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
    if row_kind == ROW_KIND_ACTIVITY_DETAIL_ROW and state == "borrowed_anchor_pending":
        row["duration_semantic"] = STATIC_CLOSED
        row["live_delta_eligible"] = False
        return row
    row.update(_live_clock_fields(live_clock))
    current_live_seconds = int(
        live_clock.get("current_live_seconds_at_sample")
        or live_clock.get("current_elapsed_at_sample")
        or 0
    )
    aggregate_base = int(
        live_clock.get("aggregate_display_base_seconds")
        or live_clock.get("display_base_seconds")
        or 0
    )
    if "raw_duration_seconds" not in row:
        row["raw_duration_seconds"] = int(row.get("duration_seconds") or 0)

    if state == "persisted_open":
        aggregate_base = _static_base_for_live_row(row, span, live_clock, state)
        aggregate_duration = aggregate_base + current_live_seconds
    else:
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
    row["is_virtual_live"] = state == "borrowed_anchor_pending"
    row["edit_disabled"] = True
    row["editable"] = False
    row["exportable"] = False
    row["disable_reason"] = LIVE_EDIT_DISABLE_REASON

    if state == "borrowed_anchor_pending":
        row["source"] = "borrowed_anchor_pending"
        row["display_only"] = True
        row["is_display_only"] = True
        row["project_id"] = int(span.get("project_id") or 0)
        row["project_name"] = str(span.get("project_name") or UNCATEGORIZED_PROJECT)
        row["project_description"] = str(span.get("project_description") or "")
        row["live_anchor_activity_id"] = int(
            span.get("live_anchor_activity_id") or anchor_id
        )
        row["live_anchor_base_seconds"] = int(
            span.get("live_anchor_base_seconds") or aggregate_base
        )
        row["display_project"] = span.get("display_project")
        row["candidate_project"] = span.get("candidate_project")
        row["project_transition"] = span.get("project_transition")
        row["project_transition_pending"] = bool(span.get("project_transition_pending"))
        _copy_span_classification(row, span)
    elif state == "persisted_open":
        preserve_report_attribution = _should_preserve_report_attribution(row, row_kind)
        if not preserve_report_attribution:
            row["project_id"] = int(span.get("project_id") or 0)
            row["project_name"] = str(span.get("project_name") or UNCATEGORIZED_PROJECT)
            row["project_description"] = str(span.get("project_description") or "")
            row["display_project"] = span.get("display_project")
            row["candidate_project"] = span.get("candidate_project")
            row["project_transition"] = span.get("project_transition")
            row["project_transition_pending"] = bool(span.get("project_transition_pending"))
            if not _copy_span_classification(row, span):
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
    return row


def _live_clock_fields(live_clock: LiveClockContract) -> dict[str, Any]:
    return {
        "display_span_id": str(live_clock.get("display_span_id") or ""),
        "stable_live_key": str(live_clock.get("stable_live_key") or ""),
        "stable_live_key_hash": str(live_clock.get("stable_live_key_hash") or ""),
        "live_state": str(live_clock.get("live_state") or ""),
        "live_started_at_epoch_ms": int(live_clock.get("live_started_at_epoch_ms") or 0),
        "carry_seconds": int(live_clock.get("carry_seconds") or 0),
        "duration_semantic": str(live_clock.get("duration_semantic") or ""),
        "current_live_seconds_at_sample": int(
            live_clock.get("current_live_seconds_at_sample") or 0
        ),
        "current_live_base_seconds": int(live_clock.get("current_live_base_seconds") or 0),
        "aggregate_duration_seconds_at_sample": int(
            live_clock.get("aggregate_duration_seconds_at_sample") or 0
        ),
        "aggregate_display_base_seconds": int(
            live_clock.get("aggregate_display_base_seconds") or 0
        ),
        "display_base_seconds": int(live_clock.get("display_base_seconds") or 0),
        "duration_seconds_at_sample": int(live_clock.get("duration_seconds_at_sample") or 0),
        "active_elapsed_at_sample": int(live_clock.get("active_elapsed_at_sample") or 0),
        "current_elapsed_at_sample": int(live_clock.get("current_elapsed_at_sample") or 0),
        "is_live": bool(live_clock.get("is_live")),
        "is_project_duration_live": bool(live_clock.get("is_project_duration_live")),
        "project_duration_live": bool(
            live_clock.get("project_duration_live", live_clock.get("is_project_duration_live"))
        ),
        "current_duration_live": bool(live_clock.get("current_duration_live")),
        "display_session_kind": str(live_clock.get("display_session_kind") or ""),
        "base_policy": str(live_clock.get("base_policy") or ""),
        "status_only_reason": str(live_clock.get("status_only_reason") or ""),
        "base_policy_reason": str(live_clock.get("base_policy_reason") or ""),
    }


def _should_preserve_report_attribution(row: dict[str, Any], row_kind: str) -> bool:
    if row_kind not in _REPORT_ROW_KINDS:
        return False
    return (
        "is_report_project" in row
        or "is_report_classified" in row
        or "is_report_uncategorized" in row
        or "report_attribution_kind" in row
    )


def _static_base_for_live_row(
    row: dict[str, Any],
    span: DisplaySpanContract,
    live_clock: LiveClockContract,
    state: str,
) -> int:
    if state != "persisted_open":
        return int(live_clock.get("display_base_seconds") or 0)

    anchor_id = int(span.get("anchor_activity_id") or 0)
    snapshot_extra_base = int(
        live_clock.get("display_base_seconds")
        or span.get("display_base_seconds")
        or 0
    )
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


def _copy_span_classification(row: dict[str, Any], span: DisplaySpanContract) -> bool:
    span_uncategorized = span.get("is_uncategorized")
    span_classified = span.get("is_classified")
    if span_uncategorized is None:
        return False
    row["is_uncategorized"] = bool(span_uncategorized)
    row["is_classified"] = (
        bool(span_classified)
        if span_classified is not None
        else (not bool(span_uncategorized))
    )
    return True
