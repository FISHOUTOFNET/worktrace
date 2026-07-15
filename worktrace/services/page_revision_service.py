"""Shared page/live revision semantics for page payloads and heartbeat."""

from __future__ import annotations

from typing import Any

from .report_projection_identity import stable_json_hash


def live_revision(
    current_activity: dict[str, Any] | None,
    live_clock: dict[str, Any] | None,
) -> str:
    current = current_activity or {}
    clock = live_clock or {}
    return stable_json_hash(
        {
            "key": current.get("stable_live_key") or clock.get("stable_live_key"),
            "status": current.get("status") or clock.get("live_state"),
            "persisted_id": int(current.get("activity_id") or 0),
            "display_span_id": str(clock.get("display_span_id") or ""),
            "project_id": int(current.get("project_id") or 0),
        }
    )


def apply_page_revision(
    payload: dict[str, Any],
    *,
    report_date: str,
    today: str,
) -> dict[str, Any]:
    """Align a page payload with heartbeat revision semantics in place."""

    revision = live_revision(
        payload.get("current_activity"),
        payload.get("live_clock"),
    )
    payload["live_revision"] = revision
    structure = str(payload.get("structure_revision") or "")
    payload["page_revision"] = stable_json_hash(
        [structure, revision if report_date == today else ""]
    )
    return payload


__all__ = ["apply_page_revision", "live_revision"]
