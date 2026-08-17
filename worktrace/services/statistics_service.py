"""Statistics status semantics.

The central report status policy includes normal and attributable
idle/error/excluded time, keeps paused separate, and leaves suppressed
unattributed statuses outside reportable totals.
"""

from __future__ import annotations

from datetime import date

from ..constants import (
    STATUS_EXCLUDED,
    STATUS_IDLE,
    STATUS_NORMAL,
    STATUS_PAUSED,
    UNCATEGORIZED_PROJECT,
)
from ..formatters import format_status_label
from .report_projection_identity import stable_json_hash
from .statistics_scope_policy import normalize_statistics_project_scope

STATISTICS_SUMMARY_MAX_RANGE_DAYS = 31
STATISTICS_ALL_TIME_START_DATE = "1970-01-01"
_UNKNOWN_APP_LABEL = "未知应用"
_EXPORT_TICKET_SCHEMA_VERSION = 1


def get_summary(start_date: str, end_date: str) -> dict:
    projection = _build_projection(start_date, end_date)
    by_status = {
        str(row["key"]): int(row["duration_seconds"])
        for row in projection.by_status
    }
    return {
        "total_duration": projection.total_duration_seconds,
        "effective_duration": by_status.get(STATUS_NORMAL, 0),
        "classified_duration": projection.classified_duration_seconds,
        "idle_duration": by_status.get(STATUS_IDLE, 0),
        "paused_duration": by_status.get(STATUS_PAUSED, 0),
        "excluded_duration": projection.excluded_duration_seconds,
        "uncategorized_duration": projection.uncategorized_duration_seconds,
    }


def get_project_stats(start_date: str, end_date: str) -> list[dict]:
    projection = _build_projection(start_date, end_date)
    return [
        {
            "project": row["display_name"],
            "total_duration": row["duration_seconds"],
            "record_count": row.get("record_count") or row["activity_count"],
        }
        for row in projection.by_project
    ]


def get_uncategorized_duration(start_date: str, end_date: str) -> int:
    return sum(
        int(row["total_duration"])
        for row in get_project_stats(start_date, end_date)
        if row["project"] == UNCATEGORIZED_PROJECT
    )


def _build_projection(start_date: str, end_date: str, project_id=None):
    from .report_projection_snapshot_service import build_visible_snapshot
    from .statistics_projection import build_statistics_projection

    return build_statistics_projection(
        build_visible_snapshot(start_date, end_date), project_id=project_id
    )


def _build_summary_projection(start_date: str, end_date: str, project_id=None):
    from .report_projection_snapshot_service import build_visible_snapshot
    from .statistics_projection import build_statistics_summary_projection

    return build_statistics_summary_projection(
        build_visible_snapshot(start_date, end_date), project_id=project_id
    )


def _scoped_live_target(live_target, projection) -> dict | None:
    if not isinstance(live_target, dict) or live_target.get("enabled") is not True:
        return None
    project_keys = {str(group.get("key") or "") for group in projection.by_project}
    target = dict(live_target)
    target["enabled"] = bool(
        target.get("includes_today") is True
        and str(target.get("project_key") or "") in project_keys
    )
    target.pop("includes_today", None)
    return target if target["enabled"] else None


def _statistics_export_summary_from_projection(
    projection,
    date_from: str,
    date_to: str,
    project_id,
    *,
    live_target=None,
) -> dict:
    normalized_scope = normalize_statistics_project_scope(project_id)
    ticket_revision = compute_statistics_export_ticket_revision(
        projection.snapshot_revision,
        date_from,
        date_to,
        normalized_scope,
    )
    return {
        "date_from": date_from,
        "date_to": date_to,
        "project_id": str(project_id or ""),
        "snapshot_revision": projection.snapshot_revision,
        "ticket_revision": ticket_revision,
        "total_duration_seconds": projection.total_duration_seconds,
        "project_duration_seconds": projection.project_duration_seconds,
        "classified_duration_seconds": projection.classified_duration_seconds,
        "uncategorized_duration_seconds": projection.uncategorized_duration_seconds,
        "excluded_duration_seconds": projection.excluded_duration_seconds,
        "activity_count": projection.activity_count,
        "report_slice_count": projection.report_slice_count,
        "session_count": projection.session_count,
        "export_row_count": projection.export_row_count,
        "project_count": projection.concrete_project_count,
        "app_count": projection.concrete_app_count,
        "by_project": list(projection.by_project),
        "by_app": list(projection.by_app),
        "by_status": list(projection.by_status),
        "live_target": live_target,
        "export_preview": {
            "date_from": date_from,
            "date_to": date_to,
            "snapshot_revision": projection.snapshot_revision,
            "included_activity_count": projection.activity_count,
            "included_report_slice_count": projection.report_slice_count,
            "session_count": projection.session_count,
            "export_row_count": projection.export_row_count,
            "included_duration_seconds": projection.total_duration_seconds,
            "available_formats": ["csv"],
            "export_actions_enabled": True,
        },
    }


def get_statistics_export_summary(
    date_from: str,
    date_to: str,
    project_id: str | int | None = None,
) -> dict:
    """Return the durable closed-only Statistics service contract."""

    date_from, date_to = resolve_statistics_date_range(date_from, date_to)
    validate_statistics_project_scope(project_id)
    projection = _build_summary_projection(date_from, date_to, project_id)
    return _statistics_export_summary_from_projection(
        projection,
        date_from,
        date_to,
        project_id,
    )


def get_statistics_realtime_export_summary(
    date_from: str,
    date_to: str,
    project_id: str | int | None = None,
) -> dict:
    """Return the UI read model frozen at one verified runtime/SQLite sample."""

    date_from, date_to = resolve_statistics_date_range(date_from, date_to)
    validate_statistics_project_scope(project_id)

    from .page_read_context import page_read_scope
    from .report_as_of_snapshot_service import build_statistics_as_of_snapshot
    from .statistics_projection import build_statistics_summary_projection
    from .statistics_snapshot_provider import get_statistics_base_snapshot

    with page_read_scope(allow_unpersisted_runtime=True):
        base_snapshot = get_statistics_base_snapshot(date_from, date_to)
        as_of = build_statistics_as_of_snapshot(
            date_from,
            date_to,
            base_snapshot=base_snapshot,
        )
        projection = build_statistics_summary_projection(
            as_of.snapshot,
            project_id=project_id,
        )
        live_target = _scoped_live_target(
            dict(as_of.live_target) if as_of.live_target is not None else None,
            projection,
        )
    return _statistics_export_summary_from_projection(
        projection,
        date_from,
        date_to,
        project_id,
        live_target=live_target,
    )


def compute_statistics_export_ticket_revision(
    snapshot_revision: str,
    date_from: str,
    date_to: str,
    normalized_scope: str,
) -> str:
    """Compute a compatibility ticket for the accepted page snapshot."""

    return stable_json_hash(
        {
            "snapshot_revision": str(snapshot_revision or ""),
            "date_from": str(date_from or ""),
            "date_to": str(date_to or ""),
            "project_scope": str(normalized_scope or ""),
            "format": "csv",
            "schema_version": _EXPORT_TICKET_SCHEMA_VERSION,
        }
    )


def validate_statistics_date_range(date_from: str, date_to: str) -> None:
    if not isinstance(date_from, str) or not isinstance(date_to, str):
        raise ValueError("invalid_date")
    try:
        start = date.fromisoformat(date_from)
        end = date.fromisoformat(date_to)
    except ValueError:
        raise ValueError("invalid_date")
    if start > end:
        raise ValueError("invalid_range")


def resolve_statistics_date_range(date_from: str, date_to: str) -> tuple[str, str]:
    """Resolve transport-level dates to a canonical date range.

    Empty ``date_from`` and ``date_to`` together mean *all time* and resolve
    to a canonical range from ``STATISTICS_ALL_TIME_START_DATE`` through today.
    One empty and one non-empty is invalid. Both non-empty are validated and
    returned as-is.
    """

    if date_from == "" and date_to == "":
        return STATISTICS_ALL_TIME_START_DATE, date.today().isoformat()
    if date_from == "" or date_to == "":
        raise ValueError("invalid_date")
    validate_statistics_date_range(date_from, date_to)
    return date_from, date_to


def validate_statistics_project_scope(project_id) -> None:
    scope = normalize_statistics_project_scope(project_id)
    if scope == "" or scope == "unclassified":
        return
    try:
        pid = int(scope)
    except (TypeError, ValueError):
        raise ValueError("invalid_project")
    if pid <= 0:
        raise ValueError("invalid_project")
    from .project_service import get_project

    project = get_project(pid)
    if project is None or bool(project.get("is_deleted")):
        raise ValueError("invalid_project")


_validate_summary_date_range = validate_statistics_date_range


def _accumulate_summary_group(
    groups: dict[str, dict],
    key: str,
    display_name: str,
    duration: int,
    activity_id: int,
) -> None:
    group = groups.setdefault(
        key,
        {"display_name": display_name, "duration_seconds": 0, "activity_ids": set()},
    )
    group["duration_seconds"] += duration
    if activity_id:
        group["activity_ids"].add(activity_id)


def _build_summary_groups(groups: dict[str, dict], total_duration: int) -> list[dict]:
    items: list[dict] = []
    for key, group in groups.items():
        duration = int(group["duration_seconds"])
        items.append(
            {
                "key": key,
                "display_name": str(group["display_name"]),
                "duration_seconds": duration,
                "activity_count": len(group["activity_ids"]),
                "percentage": round(duration / total_duration * 100, 1)
                if total_duration > 0
                else 0.0,
            }
        )
    items.sort(
        key=lambda item: (-item["duration_seconds"], str(item["display_name"]).casefold())
    )
    return items