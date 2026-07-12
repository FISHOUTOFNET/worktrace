from __future__ import annotations

import hashlib
import json
from typing import Any

from .report_projection_model import OperationDiagnostic, ProjectState, ReportMemberIdentity


def member_identity_key(member: dict[str, Any] | ReportMemberIdentity, *, report_date: str = "") -> tuple[str, int, str]:
    """Stable logical report-slice identity.

    End time and elapsed seconds are mutable content. They must not participate
    in report projection identity.
    """
    if isinstance(member, ReportMemberIdentity):
        return (member.report_date, member.activity_id, member.slice_start_time)
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


def _project_revision_payload(session: dict[str, Any], project_state: ProjectState | None) -> dict[str, Any]:
    """Return only durable project semantics for an entry revision.

    Project names, descriptions and lifecycle presentation flags are mutable
    metadata. Including them caused committed report operations to stop replaying
    after a project rename, archive or enable/disable action. Snapshot/page
    revisions still include the complete ``ProjectState`` and therefore refresh
    display content, while this entry revision remains a durable optimistic-write
    and replay precondition for the same logical projection.
    """
    if project_state is not None:
        return {
            "project_id": project_state.project_id,
            "is_report_project": project_state.is_report_project,
            "is_report_classified": project_state.is_report_classified,
            "is_report_uncategorized": project_state.is_report_uncategorized,
            "is_official_project": project_state.is_official_project,
            "report_attribution_kind": project_state.report_attribution_kind,
            "project_key": project_state.project_key,
            "report_project_key": project_state.report_project_key,
        }
    return {
        "project_id": int(session.get("project_id") or 0),
        "is_report_project": bool(session.get("is_report_project")),
        "is_report_classified": bool(session.get("is_report_classified")),
        "is_report_uncategorized": bool(session.get("is_report_uncategorized")),
        "is_official_project": bool(session.get("is_official_project")),
        "report_attribution_kind": str(session.get("report_attribution_kind") or "none"),
        "project_key": str(session.get("project_key") or ""),
        "report_project_key": str(session.get("report_project_key") or ""),
    }


def projection_revision(
    session: dict[str, Any],
    *,
    project_state: ProjectState | None = None,
    applied_commands: list[dict[str, Any]] | None = None,
) -> str:
    """Durable revision for optimistic writes and immutable operation replay.

    Live elapsed seconds and mutable project presentation metadata are excluded.
    Contribution identity and allocated durations are included so structural
    changes, edit commands and summary grouping changes still produce a new
    revision. Full project metadata remains part of the page/snapshot revision.
    """
    del applied_commands  # command history and request metadata are not report content
    is_live = bool(session.get("is_in_progress"))
    contributions = []
    for row in session.get("_projection_contributions") or []:
        contributions.append(
            {
                "member": member_identity_key(row),
                "duration": None if is_live else int(row.get("duration_seconds") or 0),
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
        "project": _project_revision_payload(session, project_state),
        "has_project_override": bool(session.get("has_project_override")),
        "duration": {
            "value": None if is_live else int(session.get("duration_seconds") or 0),
            "adjusted": None if is_live else session.get("adjusted_duration_seconds"),
            "has_override": bool(session.get("has_duration_override")),
        },
        "note": str(session.get("session_note") or ""),
        "contributions": sorted(contributions, key=lambda item: item["member"]),
    }
    return stable_json_hash(payload)


def snapshot_revision(
    entries: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    diagnostics: list[OperationDiagnostic] | tuple[OperationDiagnostic, ...],
) -> str:
    return stable_json_hash(
        {
            "entries": [
                {
                    "key": str(entry.get("projection_instance_key") or ""),
                    "revision": str(entry.get("projection_revision") or ""),
                }
                for entry in entries
            ],
            "diagnostics": [diagnostic.to_dict() for diagnostic in diagnostics],
        }
    )


__all__ = [
    "base_projection_key",
    "copy_projection_key",
    "member_identity_key",
    "member_set_hash",
    "merge_projection_key",
    "projection_revision",
    "snapshot_revision",
    "stable_json_hash",
]
