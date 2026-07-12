from __future__ import annotations

import copyreg
import hashlib
import json
from types import MappingProxyType
from typing import Any, Mapping

from .report_projection_model import OperationDiagnostic, ProjectState, ReportMemberIdentity


SequenceMapping = list[Mapping[str, Any]] | tuple[Mapping[str, Any], ...]


def _restore_mapping_proxy(value: dict[str, Any]) -> Mapping[str, Any]:
    return MappingProxyType(value)


# Replay results use mappingproxy internally. Register a deterministic reduction
# so callers may deepcopy an operation fixture or immutable replay result without
# weakening the runtime mapping itself.
copyreg.pickle(MappingProxyType, lambda value: (_restore_mapping_proxy, (dict(value),)))


def member_identity_key(member: Mapping[str, Any] | ReportMemberIdentity, *, report_date: str = "") -> tuple[str, int, str]:
    """Stable logical report-slice identity."""
    if isinstance(member, ReportMemberIdentity):
        return (member.report_date, member.activity_id, member.slice_start_time)
    return (
        str(member.get("report_date") or report_date or "")[:10],
        int(member.get("activity_id") or member.get("id") or 0),
        str(member.get("slice_start_time") or member.get("start_time") or ""),
    )


def member_set_hash(report_date: str, members: SequenceMapping) -> str:
    parts = [
        "|".join((key[0], str(key[1]), key[2]))
        for key in sorted(member_identity_key(member, report_date=report_date) for member in members)
    ]
    return hashlib.sha1("\n".join(parts).encode("utf-8")).hexdigest()


def base_projection_key(report_date: str, members: SequenceMapping) -> str:
    return f"base:{member_set_hash(report_date, members)}"


def copy_projection_key(operation_id: int) -> str:
    return f"copy:{int(operation_id)}"


def merge_projection_key(operation_id: int) -> str:
    return f"merge:{int(operation_id)}"


def stable_json_hash(payload: Any) -> str:
    return hashlib.sha1(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def _project_revision_payload(session: Mapping[str, Any], project_state: ProjectState | None) -> dict[str, Any]:
    """Return only durable project semantics for an entry revision."""
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


def _legacy_project_revision_payload(session: Mapping[str, Any], project_state: ProjectState | None) -> dict[str, Any]:
    """Exact v4 pre-fix project payload for existing operation ledgers."""
    if project_state is not None:
        return project_state.to_dict()
    return {
        "project_id": int(session.get("project_id") or 0),
        "project_name": str(session.get("project_name") or ""),
        "project_description": str(session.get("project_description") or ""),
        "is_deleted": bool(session.get("project_is_deleted") or session.get("is_deleted")),
        "is_archived": bool(session.get("project_is_archived") or session.get("is_archived")),
        "is_enabled": bool(session.get("project_is_enabled", session.get("is_enabled", True))),
        "is_system": bool(session.get("project_is_system")),
        "is_special": bool(session.get("project_is_special")),
        "is_report_project": bool(session.get("is_report_project")),
        "is_report_classified": bool(session.get("is_report_classified")),
        "is_report_uncategorized": bool(session.get("is_report_uncategorized")),
        "is_official_project": bool(session.get("is_official_project")),
        "report_attribution_kind": str(session.get("report_attribution_kind") or "none"),
        "project_key": str(session.get("project_key") or ""),
        "report_project_key": str(session.get("report_project_key") or ""),
    }


def _projection_revision_with_project(
    session: Mapping[str, Any],
    project_payload: Mapping[str, Any],
) -> str:
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
    return stable_json_hash(
        {
            "projection_instance_key": str(session.get("projection_instance_key") or ""),
            "projection_kind": str(session.get("projection_kind") or ""),
            "members": [member_identity_key(member) for member in session.get("member_slices") or []],
            "project": dict(project_payload),
            "has_project_override": bool(session.get("has_project_override")),
            "duration": {
                "value": None if is_live else int(session.get("duration_seconds") or 0),
                "adjusted": None if is_live else session.get("adjusted_duration_seconds"),
                "has_override": bool(session.get("has_duration_override")),
            },
            "note": str(session.get("session_note") or ""),
            "contributions": sorted(contributions, key=lambda item: item["member"]),
        }
    )


def projection_revision(
    session: Mapping[str, Any],
    *,
    project_state: ProjectState | None = None,
    applied_commands: list[dict[str, Any]] | None = None,
) -> str:
    """Durable revision for optimistic writes and immutable operation replay."""
    del applied_commands
    return _projection_revision_with_project(
        session,
        _project_revision_payload(session, project_state),
    )


def legacy_projection_revision(
    session: Mapping[str, Any],
    *,
    project_state: ProjectState | None = None,
) -> str:
    """Compute the previous v4 revision solely to replay persisted operations."""
    return _projection_revision_with_project(
        session,
        _legacy_project_revision_payload(session, project_state),
    )


def snapshot_revision(
    entries: SequenceMapping,
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
    "legacy_projection_revision",
    "member_identity_key",
    "member_set_hash",
    "merge_projection_key",
    "projection_revision",
    "snapshot_revision",
    "stable_json_hash",
]
