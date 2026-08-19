"""File/resource statistics derived from the canonical report snapshot."""
from __future__ import annotations

from typing import Any, Mapping

from ..constants import STATUS_EXCLUDED
from ..formatters import format_safe_display_name
from .project_activity_summary_service import activity_group_key
from .report_projection_identity import stable_json_hash
from .report_projection_snapshot_service import ReportProjectionSnapshot
from .statistics_scope_policy import (
    entry_matches_statistics_project_scope,
    normalize_statistics_project_scope,
)

_TRANSIENT_ACTIVITY_ID_MIN = 1 << 63


def _public_file_key(identity_key: str) -> str:
    return "file:" + stable_json_hash(["statistics-file", str(identity_key or "")])[:24]


def file_group_identity(row: Mapping[str, Any]) -> tuple[str, str]:
    """Return an opaque stable Statistics key and its safe resource display name."""
    status = str(row.get("status") or "unknown")
    if bool(row.get("privacy_redacted")) or status == STATUS_EXCLUDED:
        return "file:excluded", "已排除"
    materialized = dict(row)
    identity_key = activity_group_key(materialized)
    return _public_file_key(identity_key), format_safe_display_name(materialized)


def _identity_row(
    row: Mapping[str, Any],
    live_runtime_snapshot: Mapping[str, Any] | None,
) -> dict[str, Any]:
    materialized = dict(row)
    if not isinstance(live_runtime_snapshot, Mapping):
        return materialized
    try:
        activity_id = int(materialized.get("activity_id") or 0)
    except (TypeError, ValueError):
        activity_id = 0
    if activity_id < _TRANSIENT_ACTIVITY_ID_MIN:
        return materialized
    # The statistics as-of snapshot intentionally keeps an unpersisted activity
    # in memory only. Enrich that transient contribution from the exact runtime
    # sample so its resource/file identity is available before SQLite persistence.
    enriched = dict(live_runtime_snapshot)
    enriched.update(materialized)
    return enriched


def live_statistics_file_key(
    snapshot: ReportProjectionSnapshot,
    live_runtime_snapshot: Mapping[str, Any] | None,
) -> str:
    """Resolve the live row to the exact opaque key used by file groups."""
    if not isinstance(live_runtime_snapshot, Mapping):
        return ""
    try:
        persisted_activity_id = int(
            live_runtime_snapshot.get("persisted_activity_id") or 0
        )
    except (TypeError, ValueError):
        persisted_activity_id = 0
    if persisted_activity_id > 0:
        for contribution in snapshot.final_contributions:
            try:
                activity_id = int(contribution.get("activity_id") or 0)
            except (TypeError, ValueError):
                activity_id = 0
            if activity_id == persisted_activity_id:
                return file_group_identity(contribution)[0]
    return file_group_identity(live_runtime_snapshot)[0]


def build_statistics_file_groups(
    snapshot: ReportProjectionSnapshot,
    project_id: str | int | None = None,
    *,
    live_runtime_snapshot: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Aggregate visible contribution time by stable activity/resource identity."""
    normalized_scope = normalize_statistics_project_scope(project_id)
    closed_keys: set[str] = set()
    total_duration = 0
    for entry in snapshot.final_entries:
        if not entry_matches_statistics_project_scope(entry, normalized_scope):
            continue
        if bool(entry.get("is_in_progress")) or not bool(entry.get("exportable", True)):
            continue
        duration = max(0, int(entry.get("duration_seconds") or 0))
        if duration <= 0:
            continue
        closed_keys.add(str(entry.get("projection_instance_key") or ""))
        total_duration += duration

    groups: dict[str, dict[str, Any]] = {}
    for contribution in snapshot.final_contributions:
        record_key = str(contribution.get("projection_instance_key") or "")
        if record_key not in closed_keys:
            continue
        duration = max(0, int(contribution.get("duration_seconds") or 0))
        if duration <= 0:
            continue
        identity_row = _identity_row(contribution, live_runtime_snapshot)
        key, display_name = file_group_identity(identity_row)
        activity_id = int(contribution.get("activity_id") or 0)
        member = (
            str(contribution.get("report_date") or ""),
            activity_id,
            str(contribution.get("slice_start_time") or ""),
        )
        group = groups.setdefault(
            key,
            {
                "display_name": display_name,
                "duration_seconds": 0,
                "members": set(),
                "records": set(),
            },
        )
        group["duration_seconds"] = int(group["duration_seconds"]) + duration
        group["members"].add(member)
        group["records"].add(record_key)

    result: list[dict[str, Any]] = []
    for key, group in groups.items():
        duration = int(group["duration_seconds"])
        members = set(group["members"])
        result.append(
            {
                "key": key,
                "display_name": str(group["display_name"] or "未知"),
                "duration_seconds": duration,
                "activity_count": len(
                    {int(member[1]) for member in members if int(member[1]) > 0}
                ),
                "report_slice_count": len(members),
                "record_count": len(group["records"]),
                "percentage": round(duration / total_duration * 100, 1)
                if total_duration > 0
                else 0.0,
            }
        )
    return sorted(
        result,
        key=lambda item: (
            -int(item["duration_seconds"]),
            str(item["display_name"]).casefold(),
            str(item["key"]),
        ),
    )


__all__ = [
    "build_statistics_file_groups",
    "file_group_identity",
    "live_statistics_file_key",
]
