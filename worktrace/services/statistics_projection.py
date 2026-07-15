"""Analytics and export records derived only from a canonical snapshot."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..constants import STATUS_EXCLUDED, UNCATEGORIZED_PROJECT
from ..formatters import format_duration, format_status_label
from .report_projection_snapshot_service import ReportProjectionSnapshot


@dataclass(frozen=True)
class ReportAnalyticsProjection:
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
    by_project: tuple[dict[str, Any], ...]
    by_app: tuple[dict[str, Any], ...]
    by_status: tuple[dict[str, Any], ...]
    export_records: tuple[dict[str, Any], ...]


def build_statistics_projection(
    snapshot: ReportProjectionSnapshot,
) -> ReportAnalyticsProjection:
    records = tuple(_build_export_records(snapshot))
    contributions_by_entry: dict[str, list[dict]] = {}
    for contribution in snapshot.final_contributions:
        contributions_by_entry.setdefault(
            str(contribution.get("projection_instance_key") or ""),
            [],
        ).append(contribution)

    members: set[tuple[str, int, str]] = set()
    activity_ids: set[int] = set()
    by_project: dict[str, dict] = {}
    by_app: dict[str, dict] = {}
    by_status: dict[str, dict] = {}
    total = classified = uncategorized = project_duration = 0
    closed_keys = {str(record["_record_key"]) for record in records}
    record_by_key = {str(record["_record_key"]): record for record in records}

    for record in records:
        duration = int(record["duration_seconds"])
        total += duration
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
        )
        members.update(identities)
        activity_ids.update(int(item[1]) for item in identities if int(item[1]) > 0)

    # Contribution allocation owns status and application analytics. This lets
    # attributed excluded time remain inside its project session while the
    # excluded-duration metric counts only the excluded contribution itself.
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
            privacy_redacted = (
                bool(row.get("privacy_redacted")) or status == STATUS_EXCLUDED
            )
            if status == STATUS_EXCLUDED:
                excluded += duration
            app = (
                "已排除"
                if privacy_redacted
                else str(row.get("app_name") or "未知应用")
            )
            _accumulate(by_app, app, duration, [identity], key)
            _accumulate(
                by_status,
                status,
                duration,
                [identity],
                key,
                display_name=format_status_label(status),
            )

    # Defensive fallback for a valid standalone excluded entry whose
    # contribution payload is absent. Canonical snapshots normally always
    # provide one, but analytics must not silently lose excluded time.
    for key in closed_keys - contributed_keys:
        record = record_by_key[key]
        if bool(record["_standalone_excluded"]):
            excluded += int(record["duration_seconds"])

    return ReportAnalyticsProjection(
        snapshot_revision=snapshot.snapshot_revision,
        total_duration_seconds=total,
        project_duration_seconds=project_duration,
        classified_duration_seconds=classified,
        uncategorized_duration_seconds=uncategorized,
        excluded_duration_seconds=excluded,
        activity_count=len(activity_ids),
        report_slice_count=len(members),
        session_count=sum(
            1
            for entry in snapshot.final_sessions
            if not bool(entry.get("is_in_progress"))
        ),
        entry_count=sum(
            1
            for entry in snapshot.final_entries
            if not bool(entry.get("is_in_progress"))
        ),
        export_row_count=len(records),
        by_project=tuple(_groups(by_project, total)),
        by_app=tuple(_groups(by_app, total)),
        by_status=tuple(_groups(by_status, total)),
        export_records=tuple(_public_record(record) for record in records),
    )


def _build_export_records(
    snapshot: ReportProjectionSnapshot,
) -> list[dict[str, Any]]:
    contributions: dict[str, list[dict]] = {}
    for row in snapshot.final_contributions:
        contributions.setdefault(
            str(row.get("projection_instance_key") or ""),
            [],
        ).append(row)
    result: list[dict[str, Any]] = []
    for entry in snapshot.final_entries:
        if bool(entry.get("is_in_progress")) or not bool(
            entry.get("exportable", True)
        ):
            continue
        duration = int(entry.get("duration_seconds") or 0)
        if duration <= 0:
            continue
        key = str(entry.get("projection_instance_key") or "")
        rows = contributions.get(key, [])
        statuses = sorted(
            {str(row.get("status") or "normal") for row in rows}
        ) or [str(entry.get("status_code") or "normal")]
        standalone_excluded = (
            str(entry.get("row_kind") or "") == "standalone_status"
            and (
                bool(entry.get("privacy_redacted"))
                or STATUS_EXCLUDED in statuses
            )
        )
        project = (
            "已排除"
            if standalone_excluded
            else str(entry.get("project_name") or UNCATEGORIZED_PROJECT)
        )
        members = sorted(
            {
                (
                    str(
                        member.get("report_date")
                        or entry.get("report_date")
                        or ""
                    ),
                    int(member.get("activity_id") or member.get("id") or 0),
                    str(
                        member.get("slice_start_time")
                        or member.get("start_time")
                        or ""
                    ),
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
                "status": "、".join(
                    format_status_label(value) for value in statuses
                ),
                "status_code": (
                    STATUS_EXCLUDED
                    if standalone_excluded
                    else "+".join(statuses)
                ),
                "note": str(entry.get("session_note") or ""),
                "adjusted_duration": (
                    format_duration(entry.get("adjusted_duration_seconds"))
                    if bool(entry.get("has_duration_override"))
                    else ""
                ),
                "is_adjusted": (
                    "是" if bool(entry.get("has_duration_override")) else "否"
                ),
                "is_uncategorized": (
                    not standalone_excluded
                    and not bool(entry.get("is_report_classified"))
                ),
                "_standalone_excluded": standalone_excluded,
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
) -> None:
    group = groups.setdefault(
        name,
        {
            "duration": 0,
            "members": set(),
            "records": set(),
            "display_name": display_name or name,
        },
    )
    group["duration"] += duration
    group["members"].update(tuple(item) for item in members)
    group["records"].add(record_key)


def _groups(groups: dict[str, dict], total: int) -> list[dict[str, Any]]:
    result = [
        {
            "key": name,
            "display_name": value["display_name"],
            "duration_seconds": int(value["duration"]),
            "activity_count": len(
                {
                    int(member[1])
                    for member in value["members"]
                    if int(member[1]) > 0
                }
            ),
            "report_slice_count": len(value["members"]),
            "record_count": len(value["records"]),
            "percentage": (
                round(int(value["duration"]) / total * 100, 1)
                if total
                else 0.0
            ),
        }
        for name, value in groups.items()
    ]
    return sorted(
        result,
        key=lambda item: (
            -int(item["duration_seconds"]),
            str(item["display_name"]),
        ),
    )


__all__ = ["ReportAnalyticsProjection", "build_statistics_projection"]
