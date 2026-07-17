"""Canonical live-runtime transport envelope.

Page services own domain DTOs. This module only projects an already-built
page payload into the versioned transport contract consumed by the WebView.
It performs no database reads and takes no runtime samples.
"""

from __future__ import annotations

from typing import Any, Mapping

LIVE_RUNTIME_SCHEMA_VERSION = 1


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def build_live_runtime_envelope(
    payload: Mapping[str, Any],
    *,
    surface: str,
    scope_report_date: str | None = None,
    live_report_date: str | None = None,
) -> dict[str, Any]:
    """Build the sole versioned live-runtime transport contract."""

    live_clock = _mapping(payload.get("live_clock"))
    current_activity = _mapping(payload.get("current_activity"))
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
    return {
        "schema_version": LIVE_RUNTIME_SCHEMA_VERSION,
        "surface": str(surface or ""),
        "scope_report_date": scoped_date,
        "live_report_date": live_date,
        "collector_status": str(payload.get("collector_status") or ""),
        "paused": bool(payload.get("paused")),
        "status_display": str(payload.get("status_display") or ""),
        "live_revision": str(payload.get("live_revision") or ""),
        "structure_revision": str(payload.get("structure_revision") or ""),
        "page_revision": str(payload.get("page_revision") or ""),
        "sample_id": str(payload.get("sample_id") or ""),
        "display_span_id": str(
            payload.get("display_span_id")
            or live_clock.get("display_span_id")
            or ""
        ),
        "stable_live_key_hash": str(
            payload.get("stable_live_key_hash")
            or live_clock.get("stable_live_key_hash")
            or current_activity.get("stable_live_key_hash")
            or ""
        ),
        "current_activity_display_span_id": str(
            current_activity.get("current_activity_display_span_id") or ""
        ),
        "current_resource_identity_hash": str(
            current_activity.get("current_resource_identity_hash") or ""
        ),
        "live_clock": live_clock,
        "current_activity": current_activity,
    }


def attach_live_runtime_envelope(
    payload: dict[str, Any],
    *,
    surface: str,
    scope_report_date: str | None = None,
    live_report_date: str | None = None,
) -> dict[str, Any]:
    payload["runtime"] = build_live_runtime_envelope(
        payload,
        surface=surface,
        scope_report_date=scope_report_date,
        live_report_date=live_report_date,
    )
    return payload


__all__ = [
    "LIVE_RUNTIME_SCHEMA_VERSION",
    "attach_live_runtime_envelope",
    "build_live_runtime_envelope",
]
