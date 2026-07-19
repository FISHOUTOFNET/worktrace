from __future__ import annotations

import hashlib
import json
from typing import Any

from ..constants import UNCATEGORIZED_PROJECT
from .project_attribution_policy import is_official_project_source


def resolve_official_anchor_project(anchor: dict[str, Any] | None) -> dict[str, Any]:
    """Project an anchor only from facts already attached by its repository."""

    row = dict(anchor or {})
    source = str(row.get("assignment_source") or "")
    project_id = int(row.get("effective_project_id") or 0)
    project_name = str(row.get("effective_project_name") or "").strip()
    official = bool(
        project_id > 0
        and project_name
        and is_official_project_source(source)
    )
    if not official:
        project_id = 0
        project_name = UNCATEGORIZED_PROJECT
    project_description = (
        str(row.get("effective_project_description") or "") if official else ""
    )
    return {
        "project_id": project_id,
        "project_name": project_name,
        "project_description": project_description,
        "display_project": {
            "id": project_id if official else None,
            "name": project_name,
            "description": project_description,
            "source": source if official else "uncategorized",
            "is_uncategorized": not official,
            "is_suggested_project": False,
        },
        "is_uncategorized": not official,
        "is_classified": official,
    }


def _aggregate_clock(source: dict[str, Any], base_seconds: int) -> dict[str, Any]:
    return {
        "sampled_at_epoch_ms": int(source["sampled_at_epoch_ms"]),
        "started_at_epoch_ms": int(source["started_at_epoch_ms"]),
        "elapsed_seconds_at_sample": int(source["elapsed_seconds_at_sample"]),
        "aggregate_base_seconds": max(0, int(base_seconds)),
        "duration_semantic": "aggregate_live",
        "is_live": True,
        "live_state": "persisted_open",
        "display_span_id": str(source["display_span_id"]),
        "stable_live_key_hash": str(source["stable_live_key_hash"]),
    }


def _row_live_clock(row: dict[str, Any]) -> dict[str, Any] | None:
    clock = row.get("live_clock")
    if not isinstance(clock, dict):
        return None
    if (
        clock.get("is_live") is True
        and clock.get("live_state") == "persisted_open"
        and clock.get("duration_semantic") == "aggregate_live"
    ):
        return clock
    return None


def build_kpi_live_targets(
    rows: list[dict[str, Any]],
    live_clock: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Build exact aggregate clocks for KPI rows from verified row clocks."""

    del live_clock
    live_rows = [(row, _row_live_clock(row)) for row in rows]
    live_rows = [(row, clock) for row, clock in live_rows if clock is not None]
    source_clock = live_rows[0][1] if live_rows else None

    total_seconds = sum(int(row.get("duration_seconds") or 0) for row in rows)
    classified_seconds = sum(
        int(row.get("duration_seconds") or 0)
        for row in rows
        if bool(row.get("is_classified"))
    )
    uncategorized_seconds = sum(
        int(row.get("duration_seconds") or 0)
        for row in rows
        if bool(row.get("is_uncategorized"))
    )
    active_elapsed = (
        int(source_clock["elapsed_seconds_at_sample"])
        if source_clock is not None
        else 0
    )

    def target(enabled: bool, seconds: int) -> dict[str, Any]:
        if not enabled or source_clock is None:
            return {"enabled": False, "live_clock": None}
        return {
            "enabled": True,
            "live_clock": _aggregate_clock(
                source_clock,
                max(0, int(seconds) - active_elapsed),
            ),
        }

    return {
        "today_total_seconds": target(bool(live_rows), total_seconds),
        "classified_seconds": target(
            any(bool(row.get("is_classified")) for row, _clock in live_rows),
            classified_seconds,
        ),
        "uncategorized_seconds": target(
            any(bool(row.get("is_uncategorized")) for row, _clock in live_rows),
            uncategorized_seconds,
        ),
    }


def build_revision_parts(
    model: dict[str, Any],
    marker: dict[str, Any],
    *,
    snapshot_status: str,
    collector_status: str,
    user_paused: bool,
    today: str,
    report_date: str,
) -> dict[str, str]:
    live_clock = model.get("live_clock") or {}
    current_activity = model.get("current_activity") or {}
    live_clock_input = {
        "sampled_at_epoch_ms": int(live_clock.get("sampled_at_epoch_ms") or 0),
        "started_at_epoch_ms": int(live_clock.get("started_at_epoch_ms") or 0),
        "elapsed_seconds_at_sample": int(
            live_clock.get("elapsed_seconds_at_sample") or 0
        ),
        "aggregate_base_seconds": int(
            live_clock.get("aggregate_base_seconds") or 0
        ),
        "duration_semantic": str(live_clock.get("duration_semantic") or ""),
        "display_span_id": str(live_clock.get("display_span_id") or ""),
        "stable_live_key_hash": str(
            live_clock.get("stable_live_key_hash") or ""
        ),
        "status": snapshot_status,
        "live_state": str(live_clock.get("live_state") or ""),
        "is_live": bool(live_clock.get("is_live")),
        "collector_status": collector_status,
        "user_paused": bool(user_paused),
        "today": today,
        "report_date": report_date,
    }
    display_policy = live_clock.get("display_policy") or {}
    display_projection_input = {
        "display_structural_signature": str(
            model.get("display_structural_signature") or ""
        ),
        "display_policy": {
            "display_session_kind": str(
                display_policy.get("display_session_kind") or ""
            ),
            "base_policy": str(display_policy.get("base_policy") or ""),
            "materialize_recent": bool(display_policy.get("materialize_recent")),
            "materialize_timeline": bool(
                display_policy.get("materialize_timeline")
            ),
            "materialize_details": bool(
                display_policy.get("materialize_details")
            ),
            "status_only_reason": str(
                display_policy.get("status_only_reason") or ""
            ),
            "base_policy_reason": str(
                display_policy.get("base_policy_reason") or ""
            ),
        },
        "current_display_project": _project_revision_identity(
            current_activity.get("display_project")
        ),
    }
    return {
        "live_revision": _hash(live_clock_input),
        "page_revision": _hash([marker, display_projection_input]),
    }


def _hash(value: Any) -> str:
    return hashlib.sha1(
        json.dumps(value, sort_keys=True, ensure_ascii=True).encode("utf-8")
    ).hexdigest()


def _project_revision_identity(project: Any) -> dict[str, Any]:
    if not isinstance(project, dict):
        return {}
    return {
        "id": project.get("id"),
        "name": str(project.get("name") or ""),
        "description": str(project.get("description") or ""),
        "source": str(project.get("source") or ""),
        "is_uncategorized": bool(project.get("is_uncategorized")),
        "is_suggested_project": bool(project.get("is_suggested_project")),
    }
