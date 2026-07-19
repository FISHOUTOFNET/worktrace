"""Canonical current-only live-runtime transport envelope."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Mapping

from ..data_generation_repository import (
    ALL_DATA_GENERATION_NAMESPACES,
    DataGenerationNamespace,
    DataGenerationRepository,
)
from ..db import get_connection
from .page_read_context import current_page_read_context

if TYPE_CHECKING:
    from ..runtime.app_runtime import AppRuntime

LIVE_RUNTIME_SCHEMA_VERSION = 2
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
_RUNTIME_ALIAS_FIELDS = frozenset(
    {
        "activity_display_model",
        "collection_status",
        "collector_status",
        "current_activity",
        "current_activity_display_span_id",
        "current_activity_elapsed_seconds",
        "current_activity_revision",
        "current_resource_identity_hash",
        "display_span_id",
        "live_clock",
        "live_revision",
        "page_revision",
        "paused",
        "sample_epoch_ms",
        "sample_id",
        "stable_live_key_hash",
        "status_display",
        "structure_revision",
    }
)
_LIVE_METADATA_FIELDS = frozenset(
    {
        "live_clock",
        "current_activity_display_span_id",
        "current_resource_identity_hash",
        "display_span_id",
        "stable_live_key",
        "stable_live_key_hash",
        "live_started_at_epoch_ms",
        "sample_epoch_ms",
        "duration_seconds_at_sample",
        "current_live_duration_seconds",
        "persisted_duration_seconds",
        "active_elapsed_at_sample",
        "current_elapsed_at_sample",
        "carry_seconds",
        "current_duration_live",
        "project_duration_live",
        "is_project_duration_live",
        "live_delta_eligible",
        "is_live_projected",
    }
)


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _generation_snapshot() -> dict[str, int]:
    context = current_page_read_context()
    if context is not None:
        values = context.report_generations
    else:
        with get_connection() as conn:
            values = DataGenerationRepository.get_many(
                conn,
                ALL_DATA_GENERATION_NAMESPACES,
            )
    return {namespace.value: int(values[namespace]) for namespace in values}


def _require_live_clock(payload: Mapping[str, Any]) -> dict[str, Any]:
    value = payload.get("live_clock")
    if not isinstance(value, Mapping):
        raise ValueError("live_clock_missing")
    clock = dict(value)
    if set(clock) != _LIVE_CLOCK_KEYS:
        raise ValueError("live_clock_invalid_keys")
    integer_fields = (
        "sampled_at_epoch_ms",
        "started_at_epoch_ms",
        "elapsed_seconds_at_sample",
        "aggregate_base_seconds",
    )
    if any(type(clock[field]) is not int or clock[field] < 0 for field in integer_fields):
        raise ValueError("live_clock_invalid_values")
    if (
        type(clock["is_live"]) is not bool
        or clock["duration_semantic"]
        not in {"current_live", "aggregate_live", "static_closed"}
        or clock["live_state"] not in {"persisted_open", "suppressed", "none"}
        or not isinstance(clock["display_span_id"], str)
        or not isinstance(clock["stable_live_key_hash"], str)
    ):
        raise ValueError("live_clock_invalid_values")
    if clock["is_live"]:
        if (
            clock["duration_semantic"] == "static_closed"
            or clock["live_state"] != "persisted_open"
            or clock["sampled_at_epoch_ms"] <= 0
            or clock["started_at_epoch_ms"] <= 0
            or not clock["display_span_id"]
            or not clock["stable_live_key_hash"]
        ):
            raise ValueError("live_clock_invalid_live_state")
    elif clock["duration_semantic"] != "static_closed":
        raise ValueError("live_clock_invalid_static_state")
    return clock


def _static_clock_from(clock: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "sampled_at_epoch_ms": int(clock["sampled_at_epoch_ms"]),
        "started_at_epoch_ms": 0,
        "elapsed_seconds_at_sample": 0,
        "aggregate_base_seconds": 0,
        "duration_semantic": "static_closed",
        "is_live": False,
        "live_state": "none",
        "display_span_id": "",
        "stable_live_key_hash": "",
    }


def _static_metadata(value: Any) -> dict[str, Any] | None:
    result = _mapping(value)
    if not result:
        return None
    for field in _LIVE_METADATA_FIELDS:
        result.pop(field, None)
    return result


def _project_payload(current_activity: Mapping[str, Any]) -> dict[str, Any] | None:
    project = _mapping(current_activity.get("display_project"))
    if not project:
        return None
    return {
        "id": project.get("id"),
        "name": str(project.get("name") or ""),
        "description": str(project.get("description") or ""),
        "source": str(project.get("source") or ""),
        "is_uncategorized": bool(project.get("is_uncategorized")),
        "is_suggested_project": bool(project.get("is_suggested_project")),
    }


def _recent_first_row(payload: Mapping[str, Any]) -> dict[str, Any] | None:
    activities = payload.get("activities")
    if isinstance(activities, list) and activities:
        return _static_metadata(activities[0])
    return None


def _runtime_workers(runtime: "AppRuntime") -> dict[str, dict[str, Any]]:
    snapshot = runtime.worker_registry_snapshot()
    return {
        str(name): status.to_dict()
        for name, status in sorted(snapshot.items())
    }


def build_live_runtime_envelope(
    payload: Mapping[str, Any],
    *,
    surface: str,
    runtime: "AppRuntime | None" = None,
    collector_status: Mapping[str, Any] | None = None,
    scope_report_date: str | None = None,
    live_report_date: str | None = None,
) -> dict[str, Any]:
    """Build the sole current-only runtime envelope with one exact LiveClock."""

    if runtime is None:
        raise ValueError("runtime_missing")
    collector = _mapping(collector_status)
    if not collector:
        raise ValueError("collector_status_missing")

    current_activity_source = _mapping(payload.get("current_activity"))
    current_activity = _static_metadata(current_activity_source)
    clock = _require_live_clock(payload)
    generations = _generation_snapshot()
    workers = _runtime_workers(runtime)
    phase = getattr(runtime, "phase", "unavailable")
    runtime_phase = str(getattr(phase, "value", phase) or "unavailable")
    scoped_date = str(
        scope_report_date or payload.get("report_date") or payload.get("date") or ""
    )
    live_date = str(live_report_date or payload.get("today") or scoped_date or "")
    if scoped_date and live_date and scoped_date != live_date:
        clock = _static_clock_from(clock)

    error_codes = sorted(
        {
            str(status.get("error_code") or "")
            for status in workers.values()
            if status.get("error_code")
        }
        | {
            str(collector.get("collector_last_failure_code") or "")
            if collector.get("collector_last_failure_code")
            else ""
        }
        - {""}
    )
    context = current_page_read_context()
    runtime_consistent = bool(context is None or context.runtime_consistent)
    needs_full_refresh = bool(context is not None and context.needs_full_refresh)

    return {
        "schema_version": LIVE_RUNTIME_SCHEMA_VERSION,
        "surface": str(surface or ""),
        "scope_report_date": scoped_date,
        "live_report_date": live_date,
        "snapshot": {
            "id": str(payload.get("sample_id") or ""),
            "revision": str(payload.get("live_revision") or ""),
        },
        "current_activity": current_activity,
        "recent_first_row": _recent_first_row(payload),
        "clock": clock,
        "current_project": _project_payload(current_activity_source),
        "collector": collector,
        "runtime_phase": runtime_phase,
        "workers": workers,
        "generations": generations,
        "database_replacement_epoch": generations[
            DataGenerationNamespace.DATABASE_REPLACEMENT.value
        ],
        "error_codes": error_codes,
        "revisions": {
            "structure": str(payload.get("structure_revision") or ""),
            "page": str(payload.get("page_revision") or ""),
        },
        "runtime_consistent": runtime_consistent,
        "needs_full_refresh": needs_full_refresh,
    }


def attach_live_runtime_envelope(
    payload: Mapping[str, Any],
    *,
    surface: str,
    runtime: "AppRuntime | None" = None,
    collector_status: Mapping[str, Any] | None = None,
    scope_report_date: str | None = None,
    live_report_date: str | None = None,
) -> dict[str, Any]:
    result = dict(payload)
    result["runtime"] = build_live_runtime_envelope(
        result,
        surface=surface,
        runtime=runtime,
        collector_status=collector_status,
        scope_report_date=scope_report_date,
        live_report_date=live_report_date,
    )
    for field in _RUNTIME_ALIAS_FIELDS:
        result.pop(field, None)
    return result


__all__ = [
    "LIVE_RUNTIME_SCHEMA_VERSION",
    "attach_live_runtime_envelope",
    "build_live_runtime_envelope",
]
