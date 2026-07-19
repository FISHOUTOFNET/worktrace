"""Canonical live-runtime transport envelope."""
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
    if (
        type(clock["sampled_at_epoch_ms"]) is not int
        or type(clock["started_at_epoch_ms"]) is not int
        or type(clock["elapsed_seconds_at_sample"]) is not int
        or type(clock["aggregate_base_seconds"]) is not int
        or type(clock["is_live"]) is not bool
        or clock["duration_semantic"]
        not in {"current_live", "aggregate_live", "static_closed"}
        or clock["live_state"] not in {"persisted_open", "suppressed", "none"}
        or not isinstance(clock["display_span_id"], str)
        or not isinstance(clock["stable_live_key_hash"], str)
    ):
        raise ValueError("live_clock_invalid_values")
    return clock


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
    if isinstance(activities, list) and activities and isinstance(activities[0], Mapping):
        return dict(activities[0])
    return None


def _runtime_health(
    runtime: "AppRuntime | None",
) -> tuple[str, dict[str, Any], list[str]]:
    if runtime is None:
        return "unavailable", {}, []
    phase = getattr(runtime, "phase", "unavailable")
    phase_value = str(getattr(phase, "value", phase) or "unavailable")
    snapshot = _mapping(runtime.worker_health_snapshot())
    workers = _mapping(snapshot.get("workers"))
    degraded = [str(value) for value in list(snapshot.get("degraded_workers") or [])]
    return phase_value, workers, degraded


def build_live_runtime_envelope(
    payload: Mapping[str, Any],
    *,
    surface: str,
    runtime: "AppRuntime | None" = None,
    collector_status: Mapping[str, Any] | None = None,
    scope_report_date: str | None = None,
    live_report_date: str | None = None,
) -> dict[str, Any]:
    """Build the sole current-only live-runtime transport contract."""

    current_activity = _mapping(payload.get("current_activity"))
    clock = _require_live_clock(payload)
    generations = _generation_snapshot()
    runtime_phase, workers, degraded_workers = _runtime_health(runtime)
    collector = _mapping(collector_status)
    if not collector:
        raise ValueError("collector_status_missing")
    error_codes = sorted(
        {
            str(value.get("last_failure_code") or "")
            for value in workers.values()
            if isinstance(value, Mapping) and value.get("last_failure_code")
        }
        | {
            str(collector.get("collector_last_failure_code") or "")
            if collector.get("collector_last_failure_code")
            else ""
        }
        - {""}
    )
    scoped_date = str(scope_report_date or payload.get("report_date") or payload.get("date") or "")
    live_date = str(live_report_date or payload.get("today") or scoped_date or "")
    return {
        "schema_version": LIVE_RUNTIME_SCHEMA_VERSION,
        "surface": str(surface or ""),
        "scope_report_date": scoped_date,
        "live_report_date": live_date,
        "snapshot": {
            "id": str(payload.get("sample_id") or ""),
            "timestamp_epoch_ms": int(clock["sampled_at_epoch_ms"]),
            "revision": str(payload.get("live_revision") or ""),
        },
        "current_activity": current_activity or None,
        "recent_first_row": _recent_first_row(payload),
        "clock": clock,
        "current_project": _project_payload(current_activity),
        "collector": collector,
        "runtime_phase": runtime_phase,
        "worker_health": workers,
        "degraded_workers": degraded_workers,
        "generations": generations,
        "database_replacement_epoch": generations[
            DataGenerationNamespace.DATABASE_REPLACEMENT.value
        ],
        "error_codes": error_codes,
        "identity": {
            "display_span_id": str(clock["display_span_id"]),
            "stable_live_key_hash": str(clock["stable_live_key_hash"]),
            "current_activity_display_span_id": str(
                current_activity.get("current_activity_display_span_id") or ""
            ),
        },
        "revisions": {
            "structure": str(payload.get("structure_revision") or ""),
            "page": str(payload.get("page_revision") or ""),
        },
        "runtime_consistent": bool(
            current_page_read_context() is None
            or current_page_read_context().runtime_consistent
        ),
        "needs_full_refresh": bool(
            current_page_read_context() is not None
            and current_page_read_context().needs_full_refresh
        ),
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
