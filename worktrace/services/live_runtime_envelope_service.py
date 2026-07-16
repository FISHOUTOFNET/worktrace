"""Canonical live-runtime envelope shared by page payloads and heartbeat."""

from __future__ import annotations

from typing import Any, Mapping


def build_live_runtime_envelope(
    payload: Mapping[str, Any],
    *,
    report_date: str | None = None,
    today: str | None = None,
) -> dict[str, Any]:
    """Return the minimal runtime state accepted by the frontend store."""

    live_clock = payload.get("live_clock")
    current_activity = payload.get("current_activity")
    return {
        "runtime_revision": str(
            payload.get("runtime_revision")
            or payload.get("live_revision")
            or ""
        ),
        "structure_revision": str(
            payload.get("structure_revision")
            or payload.get("page_revision")
            or ""
        ),
        "sample_id": str(payload.get("sample_id") or ""),
        "report_date": str(
            report_date
            or payload.get("report_date")
            or payload.get("date")
            or ""
        ),
        "today": str(today or payload.get("today") or ""),
        "collector_status": str(payload.get("collector_status") or ""),
        "paused": bool(payload.get("paused")),
        "status_display": str(payload.get("status_display") or ""),
        "display_span_id": str(payload.get("display_span_id") or ""),
        "live_clock": dict(live_clock) if isinstance(live_clock, Mapping) else {},
        "current_activity": (
            dict(current_activity)
            if isinstance(current_activity, Mapping)
            else {}
        ),
    }


def attach_live_runtime_envelope(
    payload: dict[str, Any],
    *,
    report_date: str | None = None,
    today: str | None = None,
) -> dict[str, Any]:
    payload["runtime"] = build_live_runtime_envelope(
        payload,
        report_date=report_date,
        today=today,
    )
    return payload


__all__ = ["attach_live_runtime_envelope", "build_live_runtime_envelope"]
