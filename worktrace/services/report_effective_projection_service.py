"""Verified request-local report structure over the durable projection."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .live_time_service import snapshot_seconds_for_date_range
from .report_projection_builder import (
    ProjectionComputation,
    VerifiedOpenProjectionOverride,
    compute_effective_read_projection,
)


_MUTATION_CAPABILITIES = (
    "can_hide",
    "can_copy",
    "can_hide_activity",
    "can_merge_previous",
    "can_merge_next",
    "can_split",
)


def build_effective_read_computation(
    context,
    report_date: str,
    durable_entries: Sequence[Mapping[str, Any]],
) -> ProjectionComputation | None:
    """Build as-of topology only from the PageReadContext verified owner."""

    if (
        context is None
        or not bool(context.runtime_consistent)
        or not bool(context.collection_live_eligible)
    ):
        return None
    open_activity_id = context.verified_open_activity_id
    if open_activity_id is None or int(open_activity_id) <= 0:
        return None
    runtime_snapshot = context.runtime_sample.snapshot
    if not isinstance(runtime_snapshot, Mapping):
        return None
    try:
        runtime_activity_id = int(
            runtime_snapshot.get("persisted_activity_id") or 0
        )
        elapsed_seconds = max(
            0,
            int(runtime_snapshot.get("elapsed_seconds") or 0),
        )
    except (TypeError, ValueError):
        return None
    if runtime_activity_id != int(open_activity_id):
        return None
    if snapshot_seconds_for_date_range(
        runtime_snapshot,
        report_date,
        report_date,
    ) <= 0:
        return None

    computation = compute_effective_read_projection(
        context.conn,
        report_date,
        report_date,
        VerifiedOpenProjectionOverride(
            activity_id=int(open_activity_id),
            duration_seconds=elapsed_seconds,
        ),
    )
    _mark_provisional_entries(computation, durable_entries)
    return computation


def _mark_provisional_entries(
    computation: ProjectionComputation,
    durable_entries: Sequence[Mapping[str, Any]],
) -> None:
    durable_keys = {
        str(entry.get("projection_instance_key") or "")
        for entry in durable_entries
    }
    seen: set[int] = set()
    for collection in (
        computation.final_entries,
        computation.final_sessions,
    ):
        for entry in collection:
            if id(entry) in seen:
                continue
            seen.add(id(entry))
            if str(entry.get("row_kind") or "project_session") != "project_session":
                continue
            key = str(entry.get("projection_instance_key") or "")
            provisional = bool(entry.get("is_in_progress")) or key not in durable_keys
            if not provisional:
                continue
            entry["read_provisional"] = True
            entry["editable"] = False
            entry["edit_disabled"] = True
            for capability in _MUTATION_CAPABILITIES:
                entry[capability] = False


__all__ = ["build_effective_read_computation"]
