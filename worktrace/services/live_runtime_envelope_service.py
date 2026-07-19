"""Canonical live-runtime transport envelope.

Page services own domain DTOs. This module is the sole transport builder for
current/recent runtime identity, the live clock, process-local worker health,
and durable generation coordinates exposed to the WebView.
"""

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


def _optional_mapping(value: Any) -> dict[str, Any] | None:
    mapped = _mapping(value)
    return mapped or None


def _generation_snapshot() -> dict[str, int]:
    context = current_page_read_context()
    if context is not None:
        values = DataGenerationRepository.get_many(
            context.conn,
            ALL_DATA_GENERATION_NAMESPACES,
        )
    else:
        with get_connection() as conn:
            values = DataGenerationRepository.get_many(
                conn,
                ALL_DATA_GENERATION_NAMESPACES,
            )
    return {namespace.value: int(values[namespace]) for namespace in values}


def _clock_payload(
    payload: Mapping[str, Any],
    current_activity: Mapping[str, Any],
) -> dict[str, Any]:
    source = _mapping(payload.get("live_clock"))
    duration_at_sample = max(
        0,
        int(
            source.get("duration_seconds_at_sample")
            or current_activity.get("duration_seconds_at_sample")
            or current_activity.get("current_live_duration_seconds")
            or current_activity.get("elapsed_seconds")
            or current_activity.get("duration_seconds")
            or 0
        ),
    )
    active_elapsed_at_sample = max(
        0,
        int(
            source.get("current_elapsed_at_sample")
            or source.get("active_elapsed_at_sample")
            or source.get("active_elapsed_seconds_at_sample")
            or duration_at_sample
        ),
    )
    sample_epoch_ms = max(
        0,
        int(
            source.get("sample_epoch_ms")
            or payload.get("sample_epoch_ms")
            or 0
        ),
    )
    live_started_at_epoch_ms = max(
        0,
        int(
            source.get("live_started_at_epoch_ms")
            or current_activity.get("live_started_at_epoch_ms")
            or 0
        ),
    )
    project_duration_live = bool(
        source.get("project_duration_live")
        or source.get("is_project_duration_live")
    )
    current_duration_live = bool(source.get("current_duration_live"))
    return {
        "live_state": str(source.get("live_state") or "none"),
        "is_live": bool(source.get("is_live")),
        "persisted_duration_seconds": duration_at_sample,
        "duration_seconds_at_sample": duration_at_sample,
        "current_live_duration_seconds": max(
            duration_at_sample,
            int(source.get("current_live_duration_seconds") or duration_at_sample),
        ),
        "current_elapsed_at_sample": active_elapsed_at_sample,
        "active_elapsed_at_sample": active_elapsed_at_sample,
        "current_duration_live": current_duration_live,
        "project_duration_live": project_duration_live,
        "is_project_duration_live": project_duration_live,
        "sample_epoch_ms": sample_epoch_ms,
        "live_started_at_epoch_ms": live_started_at_epoch_ms,
        "display_span_id": str(source.get("display_span_id") or ""),
        "stable_live_key_hash": str(
            source.get("stable_live_key_hash")
            or current_activity.get("stable_live_key_hash")
            or ""
        ),
    }


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


def _recent_first_row(
    payload: Mapping[str, Any],
    current_activity: Mapping[str, Any],
) -> dict[str, Any] | None:
    if current_activity.get("active") is True and (
        current_activity.get("activity_id") is not None
        or current_activity.get("persisted_activity_id")
        or current_activity.get("is_in_progress") is True
    ):
        return dict(current_activity)
    activities = payload.get("activities")
    if isinstance(activities, list) and activities:
        return _optional_mapping(activities[0])
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
    clock = _clock_payload(payload, current_activity)
    generations = _generation_snapshot()
    runtime_phase, workers, degraded_workers = _runtime_health(runtime)
    collector = _mapping(collector_status or payload.get("collection_status"))
    if not collector:
        collector = {
            "status": str(payload.get("collector_status") or ""),
            "paused": bool(payload.get("paused")),
            "display": str(payload.get("status_display") or ""),
        }
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
    scoped_date = str(
        scope_report_date
        or payload.get("report_date")
        or payload.get("date")
        or ""
    )
    live_date = str(
        live_report_date
        or payload.get("today")
        or scoped_date
        or ""
    )
    sample_id = str(payload.get("sample_id") or "")
    sample_epoch_ms = int(clock.get("sample_epoch_ms") or 0)
    return {
        "schema_version": LIVE_RUNTIME_SCHEMA_VERSION,
        "surface": str(surface or ""),
        "scope_report_date": scoped_date,
        "live_report_date": live_date,
        "snapshot": {
            "id": sample_id,
            "timestamp_epoch_ms": sample_epoch_ms,
            "revision": str(payload.get("live_revision") or ""),
        },
        "current_activity": current_activity or None,
        "recent_first_row": _recent_first_row(payload, current_activity),
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
            "display_span_id": str(
                payload.get("display_span_id")
                or clock.get("display_span_id")
                or ""
            ),
            "stable_live_key_hash": str(
                payload.get("stable_live_key_hash")
                or clock.get("stable_live_key_hash")
                or ""
            ),
            "current_activity_display_span_id": str(
                current_activity.get("current_activity_display_span_id") or ""
            ),
            "current_resource_identity_hash": str(
                current_activity.get("current_resource_identity_hash") or ""
            ),
        },
        "revisions": {
            "structure": str(payload.get("structure_revision") or ""),
            "page": str(payload.get("page_revision") or ""),
        },
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
    """Attach v2 and remove retired top-level runtime transport aliases."""

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
