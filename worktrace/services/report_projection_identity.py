from __future__ import annotations

import hashlib
import json
from typing import Any


def member_identity_key(member: dict[str, Any], *, report_date: str = "") -> tuple[str, int, str]:
    """Stable logical report-slice identity.

    End time and elapsed seconds are mutable content. They must not participate
    in report projection identity.
    """
    return (
        str(member.get("report_date") or report_date or "")[:10],
        int(member.get("activity_id") or member.get("id") or 0),
        str(member.get("slice_start_time") or member.get("start_time") or ""),
    )


def member_set_hash(report_date: str, members: list[dict[str, Any]]) -> str:
    parts = [
        "|".join((key[0], str(key[1]), key[2]))
        for key in sorted(member_identity_key(member, report_date=report_date) for member in members)
    ]
    return hashlib.sha1("\n".join(parts).encode("utf-8")).hexdigest()


def base_projection_key(report_date: str, members: list[dict[str, Any]]) -> str:
    return f"base:{member_set_hash(report_date, members)}"


def copy_projection_key(operation_id: int) -> str:
    return f"copy:{int(operation_id)}"


def merge_projection_key(operation_id: int) -> str:
    return f"merge:{int(operation_id)}"


def stable_json_hash(payload: Any) -> str:
    return hashlib.sha1(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def projection_revision(session: dict[str, Any], *, applied_commands: list[dict[str, Any]] | None = None) -> str:
    """Revision for optimistic UI writes and detail cache ownership.

    Live elapsed seconds are intentionally excluded. Contribution identity and
    allocated durations are included so structural changes, edit commands and
    summary grouping changes produce a new revision.
    """
    contributions = []
    for row in session.get("_projection_contributions") or []:
        contributions.append(
            {
                "member": member_identity_key(row),
                "duration": int(row.get("duration_seconds") or 0),
                "activity_identity_key": str(row.get("activity_identity_key") or ""),
                "display_project_id": int(row.get("display_project_id") or 0),
                "report_project_id": int(row.get("report_project_id") or row.get("project_id") or 0),
                "status": str(row.get("status") or ""),
            }
        )
    payload = {
        "projection_instance_key": str(session.get("projection_instance_key") or ""),
        "projection_kind": str(session.get("projection_kind") or ""),
        "members": [member_identity_key(member) for member in session.get("member_slices") or []],
        "commands": [
            {
                "id": int(command.get("id") or 0),
                "replay_order": int(command.get("replay_order") or command.get("id") or 0),
                "type": str(command.get("operation_type") or ""),
                "payload": command.get("payload") or command.get("payload_json") or {},
            }
            for command in (applied_commands or session.get("_applied_commands") or [])
        ],
        "project": {
            "id": int(session.get("project_id") or 0),
            "deleted": bool(session.get("project_is_deleted")),
            "archived": bool(session.get("project_is_archived")),
            "has_override": bool(session.get("has_project_override")),
        },
        "duration": {
            "value": int(session.get("duration_seconds") or 0),
            "adjusted": session.get("adjusted_duration_seconds"),
            "has_override": bool(session.get("has_duration_override")),
        },
        "note": str(session.get("session_note") or ""),
        "contributions": sorted(contributions, key=lambda item: item["member"]),
    }
    return stable_json_hash(payload)


__all__ = [
    "base_projection_key",
    "copy_projection_key",
    "member_identity_key",
    "member_set_hash",
    "merge_projection_key",
    "projection_revision",
    "stable_json_hash",
]
