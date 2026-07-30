"""Analytics and export records derived only from a canonical snapshot."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterator

from ..constants import STATUS_EXCLUDED, UNCATEGORIZED_PROJECT
from ..formatters import format_duration, format_status_label
from .report_projection_snapshot_service import ReportProjectionSnapshot
from .report_revision_service import export_revision as build_export_revision
from .statistics_scope_policy import (
    entry_matches_statistics_project_scope,
    normalize_statistics_project_scope,
)


@dataclass(frozen=True)
class StatisticsSummaryProjection:
    """Summary fields without export records — for lightweight page reads."""

    snapshot_revision: str
    total_duration_seconds: int
    project_duration_seconds: int
    classified_duration_seconds: int
    uncategorized_duration_seconds: int
    excluded_duration_seconds: int
    activity_count: int
    report_slice_count: int
    session_count: int
    entry_count: int
    export_row_count: int
    concrete_project_count: int
    concrete_app_count: int
    by_project: tuple[dict[str, Any], ...]
    by_app: tuple[dict[str, Any], ...]
    by_status: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class ReportAnalyticsProjection:
    snapshot_revision: str
    export_revision: str
    total_duration_seconds: int
    project_duration_seconds: int
    classified_duration_seconds: int
    uncategorized_duration_seconds: int
    excluded_duration_seconds: int
    activity_count: int
    report_slice_count: int
    session_count: int
    entry_count: int
    export_row_count: int
    concrete_project_count: int
    concrete_app_count: int
    by_project: tuple[dict[str, Any], ...]
    by_app: tuple[dict[str, Any], ...]
    by_status: tuple[dict[str, Any], ...]
    export_records: tuple[dict[str, Any], ...]


def build_statistics_summary_projection(
    snapshot: ReportProjectionSnapshot,
    project_id: str | int | None = None,
) -> StatisticsSummaryProjection:
    """Compute summary fields without building or holding export records."""

    normalized_scope = normalize_statistics_project_scope(project_id)
    contributions_by_entry = _index_contributions(snapshot)

    members: set[tuple[str, int, str]] = set()
    activity_ids: set[int] = set()
    by_project: dict[str, dict] = {}
    by_app: dict[str, dict] = {}
    by_status: dict[str, dict] = {}
    concrete_apps: set[str] = set()
    total = classified = uncategorized = project_duration = 0
    export_row_count = 0
    closed_keys: set[str] = set()
    meta_by_key: dict[str, dict[str, Any]] = {}

    for entry in snapshot.final_entries:
        if not entry_matches_statistics_project_scope(entry, normalized_scope):
            continue
        if bool(entry.get("is_in_progress")) or not bool(entry.get("exportable", True)):
            continue
        duration = int(entry.get("duration_seconds") or 0)
        if duration <= 0:
            continue
        key = str(entry.get("projection_instance_key") or "")
        rows = contributions_by_entry.get(key, [])
        meta = _entry_metadata(entry, rows, key, duration)
        closed_keys.add(key)
        meta_by_key[key] = meta

        total += duration
        if not meta["_standalone_excluded"]:
            if meta["is_uncategorized"]:
                uncategorized += duration
            else:
                classified += duration
                project_duration += duration
        identities = [tuple(item) for item in meta["_member_identities"]]
        _accumulate(
            by_project,
            meta["project"],
            duration,
            identities,
            key,
            is_concrete_project=meta["_is_concrete_project"],
        )
        members.update(identities)
        activity_ids.update(int(item[1]) for item in identities if int(item[1]) > 0)
        export_row_count += 1

    excluded = 0
    contributed_keys: set[str] = set()
    for key, contributions in contributions_by_entry.items():
        if key not in closed_keys:
            continue
        contributed_keys.add(key)
        for row in contributions:
            identity = (
                str(row.get("report_date") or ""),
                int(row.get("activity_id") or 0),
                str(row.get("slice_start_time") or ""),
            )
            duration = int(row.get("duration_seconds") or 0)
            status = str(row.get("status") or "unknown")
            privacy_redacted = bool(row.get("privacy_redacted")) or status == STATUS_EXCLUDED
            if status == STATUS_EXCLUDED:
                excluded += duration
            app = "已排除" if privacy_redacted else str(row.get("app_name") or "未知应用")
            if not privacy_redacted:
                concrete_apps.add(app)
            _accumulate(by_app, app, duration, [identity], key)
            _accumulate(
                by_status,
                status,
                duration,
                [identity],
                key,
                display_name=format_status_label(status),
            )

    for key in closed_keys - contributed_keys:
        meta = meta_by_key[key]
        if bool(meta["_standalone_excluded"]):
            excluded += int(meta["duration_seconds"])

    project_groups = tuple(_groups(by_project, total))
    return StatisticsSummaryProjection(
        snapshot_revision=snapshot.snapshot_revision,
        total_duration_seconds=total,
        project_duration_seconds=project_duration,
        classified_duration_seconds=classified,
        uncategorized_duration_seconds=uncategorized,
        excluded_duration_seconds=excluded,
        activity_count=len(activity_ids),
        report_slice_count=len(members),
        session_count=sum(
            1 for entry in snapshot.final_sessions
            if not bool(entry.get("is_in_progress"))
            and entry_matches_statistics_project_scope(entry, normalized_scope)
        ),
        entry_count=sum(
            1 for entry in snapshot.final_entries
            if not bool(entry.get("is_in_progress"))
            and entry_matches_statistics_project_scope(entry, normalized_scope)
        ),
        export_row_count=export_row_count,
        concrete_project_count=sum(
            1 for group in project_groups if bool(group.get("is_concrete_project"))
        ),
        concrete_app_count=len(concrete_apps),
        by_project=project_groups,
        by_app=tuple(_groups(by_app, total)),
        by_status=tuple(_groups(by_status, total)),
    )


def iter_statistics_export_records(
    snapshot: ReportProjectionSnapshot,
    project_id: str | int | None = None,
) -> Iterator[dict[str, Any]]:
    """Yield display-safe export records one at a time, in sorted order."""

    normalized_scope = normalize_statistics_project_scope(project_id)
    contributions_by_entry = _index_contributions(snapshot)
    sorted_entries = sorted(
        snapshot.final_entries,
        key=lambda entry: (
            str(entry.get("report_date") or ""),
            str(entry.get("start_time") or ""),
            str(entry.get("projection_instance_key") or ""),
        ),
    )
    for entry in sorted_entries:
        if not entry_matches_statistics_project_scope(entry, normalized_scope):
            continue
        if bool(entry.get("is_in_progress")) or not bool(entry.get("exportable", True)):
            continue
        duration = int(entry.get("duration_seconds") or 0)
        if duration <= 0:
            continue
        key = str(entry.get("projection_instance_key") or "")
        rows = contributions_by_entry.get(key, [])
        yield _build_public_record(entry, rows, duration)


def build_statistics_projection(
    snapshot: ReportProjectionSnapshot,
    project_id: str | int | None = None,
) -> ReportAnalyticsProjection:
    private_records = tuple(_build_export_records(snapshot, project_id=project_id))
    public_records = tuple(_public_record(record) for record in private_records)
    contributions_by_entry: dict[str, list[dict]] = {}
    for contribution in snapshot.final_contributions:
        contributions_by_entry.setdefault(
            str(contribution.get("projection_instance_key") or ""), []
        ).append(contribution)

    members: set[tuple[str, int, str]] = set()
    activity_ids: set[int] = set()
    by_project: dict[str, dict] = {}
    by_app: dict[str, dict] = {}
    by_status: dict[str, dict] = {}
    concrete_apps: set[str] = set()
    total = classified = uncategorized = project_duration = 0
    closed_keys = {str(record["_record_key"]) for record in private_records}
    record_by_key = {str(record["_record_key"]): record for record in private_records}

    for record in private_records:
        duration = int(record["duration_seconds"])
        total += duration
        concrete_project = bool(record["_is_concrete_project"])
        if not bool(record["_standalone_excluded"]):
            if bool(record["is_uncategorized"]):
                uncategorized += duration
            else:
                classified += duration
                project_duration += duration
        identities = [tuple(item) for item in record["_member_identities"]]
        _accumulate(
            by_project,
            str(record["project"]),
            duration,
            identities,
            str(record["_record_key"]),
            is_concrete_project=concrete_project,
        )
        members.update(identities)
        activity_ids.update(int(item[1]) for item in identities if int(item[1]) > 0)

    excluded = 0
    contributed_keys: set[str] = set()
    for key, contributions in contributions_by_entry.items():
        if key not in closed_keys:
            continue
        contributed_keys.add(key)
        for row in contributions:
            identity = (
                str(row.get("report_date") or ""),
                int(row.get("activity_id") or 0),
                str(row.get("slice_start_time") or ""),
            )
            duration = int(row.get("duration_seconds") or 0)
            status = str(row.get("status") or "unknown")
            privacy_redacted = bool(row.get("privacy_redacted")) or status == STATUS_EXCLUDED
            if status == STATUS_EXCLUDED:
                excluded += duration
            app = "已排除" if privacy_redacted else str(row.get("app_name") or "未知应用")
            if not privacy_redacted:
                concrete_apps.add(app)
            _accumulate(by_app, app, duration, [identity], key)
            _accumulate(
                by_status,
                status,
                duration,
                [identity],
                key,
                display_name=format_status_label(status),
            )

    for key in closed_keys - contributed_keys:
        record = record_by_key[key]
        if bool(record["_standalone_excluded"]):
            excluded += int(record["duration_seconds"])

    project_groups = tuple(_groups(by_project, total))
    return ReportAnalyticsProjection(
        snapshot_revision=snapshot.snapshot_revision,
        export_revision=build_export_revision(
            snapshot.start_date, snapshot.end_date, public_records
        ),
        total_duration_seconds=total,
        project_duration_seconds=project_duration,
        classified_duration_seconds=classified,
        uncategorized_duration_seconds=uncategorized,
        excluded_duration_seconds=excluded,
        activity_count=len(activity_ids),
        report_slice_count=len(members),
        session_count=sum(
            1 for entry in snapshot.final_sessions
            if not bool(entry.get("is_in_progress")) and _matches_project(entry, project_id)
        ),
        entry_count=sum(
            1 for entry in snapshot.final_entries
            if not bool(entry.get("is_in_progress")) and _matches_project(entry, project_id)
        ),
        export_row_count=len(private_records),
        concrete_project_count=sum(
            1 for group in project_groups if bool(group.get("is_concrete_project"))
        ),
        concrete_app_count=len(concrete_apps),
        by_project=project_groups,
        by_app=tuple(_groups(by_app, total)),
        by_status=tuple(_groups(by_status, total)),
        export_records=public_records,
    )


def _matches_project(entry: dict[str, Any], project_id: str | int | None) -> bool:
    try:
        normalized = normalize_statistics_project_scope(project_id)
    except ValueError:
        return False
    return entry_matches_statistics_project_scope(entry, normalized)


def _index_contributions(
    snapshot: ReportProjectionSnapshot,
) -> dict[str, list[dict]]:
    contributions: dict[str, list[dict]] = {}
    for row in snapshot.final_contributions:
        contributions.setdefault(
            str(row.get("projection_instance_key") or ""), []
        ).append(row)
    return contributions


def _entry_metadata(
    entry: dict[str, Any],
    rows: list[dict],
    key: str,
    duration: int,
) -> dict[str, Any]:
    statuses = sorted({str(row.get("status") or "normal") for row in rows}) or [
        str(entry.get("status_code") or "normal")
    ]
    standalone_excluded = str(entry.get("row_kind") or "") == "standalone_status" and (
        bool(entry.get("privacy_redacted")) or STATUS_EXCLUDED in statuses
    )
    project = "已排除" if standalone_excluded else str(
        entry.get("project_name") or UNCATEGORIZED_PROJECT
    )
    entry_project_id = int(
        entry.get("report_project_id") or entry.get("project_id") or 0
    )
    is_concrete_project = bool(
        not standalone_excluded
        and entry_project_id > 0
        and project != UNCATEGORIZED_PROJECT
        and not bool(entry.get("project_is_deleted"))
    )
    member_identities = sorted(
        {
            (
                str(member.get("report_date") or entry.get("report_date") or ""),
                int(member.get("activity_id") or member.get("id") or 0),
                str(member.get("slice_start_time") or member.get("start_time") or ""),
            )
            for member in entry.get("member_slices") or []
        }
    )
    return {
        "duration_seconds": duration,
        "_record_key": key,
        "project": project,
        "statuses": statuses,
        "_standalone_excluded": standalone_excluded,
        "_is_concrete_project": is_concrete_project,
        "is_uncategorized": not standalone_excluded
        and not bool(entry.get("is_report_classified")),
        "_member_identities": member_identities,
        "entry_project_id": entry_project_id,
    }


def _build_export_records(
    snapshot: ReportProjectionSnapshot,
    *,
    project_id: str | int | None = None,
) -> list[dict[str, Any]]:
    contributions: dict[str, list[dict]] = {}
    for row in snapshot.final_contributions:
        contributions.setdefault(
            str(row.get("projection_instance_key") or ""), []
        ).append(row)
    result: list[dict[str, Any]] = []
    for entry in snapshot.final_entries:
        if not _matches_project(entry, project_id):
            continue
        if bool(entry.get("is_in_progress")) or not bool(entry.get("exportable", True)):
            continue
        duration = int(entry.get("duration_seconds") or 0)
        if duration <= 0:
            continue
        key = str(entry.get("projection_instance_key") or "")
        rows = contributions.get(key, [])
        statuses = sorted({str(row.get("status") or "normal") for row in rows}) or [
            str(entry.get("status_code") or "normal")
        ]
        standalone_excluded = str(entry.get("row_kind") or "") == "standalone_status" and (
            bool(entry.get("privacy_redacted")) or STATUS_EXCLUDED in statuses
        )
        project = "已排除" if standalone_excluded else str(
            entry.get("project_name") or UNCATEGORIZED_PROJECT
        )
        entry_project_id = int(
            entry.get("report_project_id") or entry.get("project_id") or 0
        )
        is_concrete_project = bool(
            not standalone_excluded
            and entry_project_id > 0
            and project != UNCATEGORIZED_PROJECT
            and not bool(entry.get("project_is_deleted"))
        )
        members = sorted(
            {
                (
                    str(member.get("report_date") or entry.get("report_date") or ""),
                    int(member.get("activity_id") or member.get("id") or 0),
                    str(member.get("slice_start_time") or member.get("start_time") or ""),
                )
                for member in entry.get("member_slices") or []
            }
        )
        result.append(
            {
                "date": str(entry.get("report_date") or ""),
                "start_time": str(entry.get("start_time") or ""),
                "end_time": str(entry.get("end_time") or ""),
                "duration": format_duration(duration),
                "duration_seconds": duration,
                "project": project,
                "status": "、".join(format_status_label(value) for value in statuses),
                "status_code": STATUS_EXCLUDED if standalone_excluded else "+".join(statuses),
                "note": str(entry.get("session_note") or ""),
                "adjusted_duration": (
                    format_duration(entry.get("adjusted_duration_seconds"))
                    if bool(entry.get("has_duration_override"))
                    else ""
                ),
                "is_adjusted": "是" if bool(entry.get("has_duration_override")) else "否",
                "is_uncategorized": not standalone_excluded
                and not bool(entry.get("is_report_classified")),
                "_standalone_excluded": standalone_excluded,
                "_is_concrete_project": is_concrete_project,
                "_member_identities": members,
                "_record_key": key,
            }
        )
    return sorted(
        result,
        key=lambda item: (
            str(item["date"]),
            str(item["start_time"]),
            str(item["_record_key"]),
        ),
    )


def _build_public_record(
    entry: dict[str, Any],
    rows: list[dict],
    duration: int,
) -> dict[str, Any]:
    statuses = sorted({str(row.get("status") or "normal") for row in rows}) or [
        str(entry.get("status_code") or "normal")
    ]
    standalone_excluded = str(entry.get("row_kind") or "") == "standalone_status" and (
        bool(entry.get("privacy_redacted")) or STATUS_EXCLUDED in statuses
    )
    project = "已排除" if standalone_excluded else str(
        entry.get("project_name") or UNCATEGORIZED_PROJECT
    )
    return {
        "date": str(entry.get("report_date") or ""),
        "start_time": str(entry.get("start_time") or ""),
        "end_time": str(entry.get("end_time") or ""),
        "duration": format_duration(duration),
        "duration_seconds": duration,
        "project": project,
        "status": "、".join(format_status_label(value) for value in statuses),
        "note": str(entry.get("session_note") or ""),
        "adjusted_duration": (
            format_duration(entry.get("adjusted_duration_seconds"))
            if bool(entry.get("has_duration_override"))
            else ""
        ),
        "is_adjusted": "是" if bool(entry.get("has_duration_override")) else "否",
    }


def _public_record(record: dict[str, Any]) -> dict[str, Any]:
    fields = (
        "date",
        "start_time",
        "end_time",
        "duration",
        "duration_seconds",
        "project",
        "status",
        "note",
        "adjusted_duration",
        "is_adjusted",
    )
    return {field: record[field] for field in fields}


def _accumulate(
    groups: dict[str, dict],
    name: str,
    duration: int,
    members,
    record_key: str,
    *,
    display_name: str | None = None,
    is_concrete_project: bool | None = None,
) -> None:
    group = groups.setdefault(
        name,
        {
            "duration": 0,
            "members": set(),
            "records": set(),
            "display_name": display_name or name,
            "is_concrete_project": bool(is_concrete_project),
        },
    )
    group["duration"] += duration
    group["members"].update(tuple(item) for item in members)
    group["records"].add(record_key)
    if is_concrete_project is not None:
        group["is_concrete_project"] = bool(group["is_concrete_project"] or is_concrete_project)


def _groups(groups: dict[str, dict], total: int) -> list[dict[str, Any]]:
    result = [
        {
            "key": name,
            "display_name": value["display_name"],
            "duration_seconds": int(value["duration"]),
            "activity_count": len(
                {int(member[1]) for member in value["members"] if int(member[1]) > 0}
            ),
            "report_slice_count": len(value["members"]),
            "record_count": len(value["records"]),
            "percentage": round(int(value["duration"]) / total * 100, 1) if total else 0.0,
            "is_concrete_project": bool(value.get("is_concrete_project")),
        }
        for name, value in groups.items()
    ]
    return sorted(
        result,
        key=lambda item: (-int(item["duration_seconds"]), str(item["display_name"])),
    )


__all__ = [
    "ReportAnalyticsProjection",
    "StatisticsSummaryProjection",
    "build_statistics_projection",
    "build_statistics_summary_projection",
    "iter_statistics_export_records",
]
