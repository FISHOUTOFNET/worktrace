from __future__ import annotations

import time
from typing import Any

from ..constants import UNCATEGORIZED_PROJECT
from ..contracts.live_display_contracts import DisplaySpanContract, LiveClockContract
from ..formatters import format_duration
from .activity_display_span import LIVE_EDIT_DISABLE_REASON
from .activity_live_clock import AGGREGATE_LIVE, CURRENT_LIVE, STATIC_CLOSED
from .live_display_service import _stable_live_key_hash
from .page_read_context import current_page_read_context

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
_LIVE_CLOCK_KEYS = {
    "sampled_at_epoch_ms",
    "started_at_epoch_ms",
    "elapsed_seconds_at_sample",
    "aggregate_base_seconds",
    "duration_semantic",
    "is_live",
    "live_state",
    "display_span_id",
    "stable_live_key_hash",
}


def apply_live_span_to_row(
    row: dict[str, Any],
    span: DisplaySpanContract | None,
    *,
    row_kind: str,
) -> dict[str, Any]:
    """Attach one row-owned exact clock after the runtime/SQLite handshake."""

    semantic = _duration_semantic_for_row_kind(row_kind)
    if semantic == STATIC_CLOSED:
        return _fail_static(row)
    if not span or not _span_visible_for_row(span, row_kind):
        return _fail_static(row)

    context = current_page_read_context()
    if context is None or not context.runtime_consistent:
        return _fail_static(row)
    anchor_id = int(span.get("anchor_activity_id") or 0)
    if anchor_id <= 0 or context.verified_open_activity_id != anchor_id:
        return _fail_static(row)
    if not _row_contains_anchor(row, anchor_id):
        return _fail_static(row)

    row_id = int(row.get("activity_id") or row.get("id") or 0)
    if row_id == anchor_id and row.get("end_time") not in {None, ""}:
        return _fail_static(row)

    live_clock = span.get("live_clock")
    if not _valid_source_clock(live_clock):
        return _fail_static(row)
    runtime_snapshot = context.runtime_sample.snapshot
    if not isinstance(runtime_snapshot, dict):
        return _fail_static(row)
    if str(live_clock["stable_live_key_hash"]) != _stable_live_key_hash(
        runtime_snapshot
    ):
        return _fail_static(row)

    aggregate_base = _aggregate_base(row, row_kind)
    if aggregate_base is None:
        return _fail_static(row)
    elapsed = int(live_clock["elapsed_seconds_at_sample"])
    row_clock: LiveClockContract = {
        "sampled_at_epoch_ms": int(live_clock["sampled_at_epoch_ms"]),
        "started_at_epoch_ms": int(live_clock["started_at_epoch_ms"]),
        "elapsed_seconds_at_sample": elapsed,
        "aggregate_base_seconds": aggregate_base,
        "duration_semantic": semantic,
        "is_live": True,
        "live_state": "persisted_open",
        "display_span_id": str(live_clock["display_span_id"]),
        "stable_live_key_hash": str(live_clock["stable_live_key_hash"]),
    }
    duration_seconds = elapsed if semantic == CURRENT_LIVE else aggregate_base + elapsed
    row["live_clock"] = row_clock
    row["duration_seconds"] = int(duration_seconds)
    row["duration"] = format_duration(duration_seconds)
    row["is_in_progress"] = True
    row["edit_disabled"] = True
    row["editable"] = False
    row["exportable"] = False
    row["disable_reason"] = LIVE_EDIT_DISABLE_REASON

    if not _should_preserve_report_attribution(row, row_kind):
        row["project_id"] = int(span.get("project_id") or 0)
        row["project_name"] = str(
            span.get("project_name") or UNCATEGORIZED_PROJECT
        )
        row["project_description"] = str(span.get("project_description") or "")
        row["display_project"] = span.get("display_project")
        if not _copy_span_classification(row, span):
            row["is_uncategorized"] = not bool(row.get("project_id"))
            row["is_classified"] = bool(row.get("project_id"))
    row["source"] = "db"
    if row_kind in _CURRENT_LIVE_ROW_KINDS:
        row["start_time"] = str(span.get("start_time") or row.get("start_time") or "")
    return row


def _valid_source_clock(value: Any) -> bool:
    if not isinstance(value, dict) or set(value) != _LIVE_CLOCK_KEYS:
        return False
    integers = (
        value.get("sampled_at_epoch_ms"),
        value.get("started_at_epoch_ms"),
        value.get("elapsed_seconds_at_sample"),
        value.get("aggregate_base_seconds"),
    )
    return (
        all(type(item) is int and item >= 0 for item in integers)
        and value.get("duration_semantic") == CURRENT_LIVE
        and value.get("is_live") is True
        and value.get("live_state") == "persisted_open"
        and int(value.get("sampled_at_epoch_ms") or 0) > 0
        and int(value.get("started_at_epoch_ms") or 0) > 0
        and isinstance(value.get("display_span_id"), str)
        and bool(value.get("display_span_id"))
        and isinstance(value.get("stable_live_key_hash"), str)
        and bool(value.get("stable_live_key_hash"))
    )


def _span_visible_for_row(span: DisplaySpanContract, row_kind: str) -> bool:
    if row_kind == ROW_KIND_RECENT_PROJECT_SESSION_ROW:
        return bool(span.get("is_visible_in_recent"))
    if row_kind == ROW_KIND_PROJECT_SESSION_ROW:
        return bool(span.get("is_visible_in_timeline"))
    if row_kind in {
        ROW_KIND_ACTIVITY_DETAIL_ROW,
        ROW_KIND_PROJECT_ACTIVITY_SUMMARY_ROW,
    }:
        return bool(span.get("is_visible_in_details"))
    return True


def _row_contains_anchor(row: dict[str, Any], anchor_id: int) -> bool:
    direct_ids = {
        int(row.get("activity_id") or row.get("id") or 0),
        int(row.get("first_activity_id") or 0),
        int(row.get("open_activity_id") or 0),
    }
    if anchor_id in direct_ids:
        return True
    activity_ids = row.get("activity_ids")
    if not isinstance(activity_ids, list):
        return False
    return anchor_id in {int(value) for value in activity_ids if type(value) is int}


def _aggregate_base(row: dict[str, Any], row_kind: str) -> int | None:
    if row_kind in _CURRENT_LIVE_ROW_KINDS:
        return 0
    if row_kind not in _AGGREGATE_LIVE_ROW_KINDS:
        return None
    value = row.get("closed_duration_seconds")
    if type(value) is not int or value < 0:
        return None
    return value


def _fail_static(row: dict[str, Any]) -> dict[str, Any]:
    duration = max(0, int(row.get("duration_seconds") or 0))
    row["live_clock"] = {
        "sampled_at_epoch_ms": int(time.time() * 1000),
        "started_at_epoch_ms": 0,
        "elapsed_seconds_at_sample": duration,
        "aggregate_base_seconds": 0,
        "duration_semantic": STATIC_CLOSED,
        "is_live": False,
        "live_state": "none",
        "display_span_id": "",
        "stable_live_key_hash": "",
    }
    if row.get("end_time") not in {None, ""}:
        row["is_in_progress"] = False
    return row


def _should_preserve_report_attribution(row: dict[str, Any], row_kind: str) -> bool:
    if row_kind not in _REPORT_ROW_KINDS:
        return False
    return any(
        key in row
        for key in (
            "is_report_project",
            "is_report_classified",
            "is_report_uncategorized",
            "report_attribution_kind",
        )
    )


def _duration_semantic_for_row_kind(row_kind: str) -> str:
    if row_kind in _CURRENT_LIVE_ROW_KINDS:
        return CURRENT_LIVE
    if row_kind in _AGGREGATE_LIVE_ROW_KINDS:
        return AGGREGATE_LIVE
    if row_kind == ROW_KIND_HISTORICAL_CLOSED_ROW:
        return STATIC_CLOSED
    raise ValueError(f"unknown live display row_kind: {row_kind!r}")


def _copy_span_classification(
    row: dict[str, Any],
    span: DisplaySpanContract,
) -> bool:
    span_uncategorized = span.get("is_uncategorized")
    span_classified = span.get("is_classified")
    if span_uncategorized is None:
        return False
    row["is_uncategorized"] = bool(span_uncategorized)
    row["is_classified"] = (
        bool(span_classified)
        if span_classified is not None
        else not bool(span_uncategorized)
    )
    return True
