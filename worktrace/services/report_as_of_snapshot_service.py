"""Read-only as-of overlay for report projections.

The canonical report projection remains the sole durable business owner. This
module overlays the verified runtime activity onto a request-scoped immutable
snapshot for realtime Statistics and point-in-time export. Persisted open rows
replace their durable duration; a stable unpersisted normal activity is
represented only in memory and is never written to SQLite.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import time
from typing import Any, Mapping

from ..constants import (
    STATUS_EXCLUDED,
    STATUS_NORMAL,
    STATUS_PAUSED,
    TIME_FORMAT,
    UNCATEGORIZED_PROJECT,
)
from .live_time_service import snapshot_seconds_for_date_range, snapshot_start_time
from .page_read_context import current_page_read_context
from .project_attribution_policy import is_report_visible_project_source
from .report_projection_identity import stable_json_hash
from .report_projection_model import ReportProjectionSnapshot, thaw_value
from .report_projection_snapshot_service import build_visible_snapshot
from .timeline_service import get_default_report_date


@dataclass(frozen=True)
class ReportAsOfSnapshot:
    snapshot: ReportProjectionSnapshot
    live_target: Mapping[str, Any] | None


def _record_contains_activity(record: Mapping[str, Any], activity_id: int) -> bool:
    for field in ("activity_id", "first_activity_id", "open_activity_id", "anchor_activity_id"):
        try:
            if int(record.get(field) or 0) == activity_id:
                return True
        except (TypeError, ValueError):
            continue
    values = record.get("activity_ids") or []
    if isinstance(values, (list, tuple)):
        for value in values:
            try:
                if int(value) == activity_id:
                    return True
            except (TypeError, ValueError):
                continue
    members = record.get("member_slices") or []
    if isinstance(members, (list, tuple)):
        for member in members:
            if not isinstance(member, Mapping):
                continue
            try:
                if int(member.get("activity_id") or member.get("id") or 0) == activity_id:
                    return True
            except (TypeError, ValueError):
                continue
    return False


def _slice_end_text(runtime_snapshot: Mapping[str, Any], report_date: str) -> str:
    start = snapshot_start_time(runtime_snapshot)
    if start is None:
        return ""
    full_end = start + timedelta(seconds=max(0, int(runtime_snapshot.get("elapsed_seconds") or 0)))
    try:
        day_start = datetime.fromisoformat(str(report_date) + "T00:00:00")
    except ValueError:
        return full_end.strftime(TIME_FORMAT)
    day_end = day_start + timedelta(days=1)
    bounded = min(full_end, day_end)
    return bounded.strftime(TIME_FORMAT)


def _live_target(
    entry: Mapping[str, Any] | None,
    contribution: Mapping[str, Any] | None,
    *,
    range_seconds: int,
    runtime_snapshot: Mapping[str, Any],
) -> dict[str, Any] | None:
    if entry is None or range_seconds <= 0:
        return None
    status = str((contribution or {}).get("status") or entry.get("status_code") or "normal")
    privacy_redacted = bool((contribution or {}).get("privacy_redacted")) or status == STATUS_EXCLUDED
    standalone_excluded = str(entry.get("row_kind") or "") == "standalone_status" and privacy_redacted
    project_key = "已排除" if standalone_excluded else str(
        entry.get("project_name") or UNCATEGORIZED_PROJECT
    )
    app_key = "已排除" if privacy_redacted else str(
        (contribution or {}).get("app_name") or runtime_snapshot.get("app_name") or "未知应用"
    )
    project_id = int(entry.get("report_project_id") or entry.get("project_id") or 0)
    is_uncategorized = bool(
        not standalone_excluded and not bool(entry.get("is_report_classified"))
    )
    is_concrete_project = bool(
        not standalone_excluded
        and project_id > 0
        and project_key != UNCATEGORIZED_PROJECT
        and not bool(entry.get("project_is_deleted"))
    )
    today = get_default_report_date()
    return {
        "enabled": True,
        "ticking": status != STATUS_PAUSED,
        "sampled_at_epoch_ms": int(time.time() * 1000),
        "elapsed_seconds_at_sample": int(range_seconds),
        "project_key": project_key,
        "app_key": app_key,
        "status_key": status,
        "is_concrete_project": is_concrete_project,
        "is_uncategorized": is_uncategorized,
        "contributes_project_duration": bool(
            not standalone_excluded and not is_uncategorized
        ),
        "is_excluded_status": status == STATUS_EXCLUDED,
        "includes_today": str(entry.get("report_date") or "") == today,
    }


def _runtime_report_project(runtime_snapshot: Mapping[str, Any]) -> tuple[int, str, str]:
    value = runtime_snapshot.get("display_project")
    if not isinstance(value, Mapping):
        return 0, UNCATEGORIZED_PROJECT, ""
    source = str(value.get("source") or "").strip()
    name = str(value.get("name") or "").strip()
    try:
        project_id = int(value.get("id") or 0)
    except (TypeError, ValueError):
        project_id = 0
    if (
        project_id <= 0
        or not name
        or bool(value.get("is_uncategorized"))
        or not is_report_visible_project_source(source)
    ):
        return 0, UNCATEGORIZED_PROJECT, ""
    return project_id, name, str(value.get("description") or "")


def _transient_identity(runtime_snapshot: Mapping[str, Any]) -> tuple[str, int]:
    digest = stable_json_hash(
        {
            "resource_identity_key": str(runtime_snapshot.get("resource_identity_key") or ""),
            "resource_display_name": str(runtime_snapshot.get("resource_display_name") or ""),
            "activity_display_name": str(runtime_snapshot.get("activity_display_name") or ""),
            "app_name": str(runtime_snapshot.get("app_name") or ""),
            "process_name": str(runtime_snapshot.get("process_name") or ""),
            "start_time": str(runtime_snapshot.get("start_time") or ""),
            "status": str(runtime_snapshot.get("status") or ""),
        }
    )
    # SQLite rowids are signed 64-bit integers. Keeping the transient member
    # above that range makes it count like an activity without ever colliding
    # with a durable row or leaking a fake database identity outside this snapshot.
    transient_activity_id = (1 << 63) + int(digest[:15], 16)
    return "transient-live:" + digest[:20], transient_activity_id


def _build_transient_statistics_overlay(
    base: ReportProjectionSnapshot,
    runtime_snapshot: Mapping[str, Any],
    *,
    runtime_revision: int,
    start_date: str,
    end_date: str,
) -> ReportAsOfSnapshot | None:
    if str(runtime_snapshot.get("status") or "") != STATUS_NORMAL:
        return None
    if runtime_snapshot.get("is_persisted") is True:
        return None
    try:
        if int(runtime_snapshot.get("persisted_activity_id") or 0) > 0:
            return None
    except (TypeError, ValueError):
        return None

    start = snapshot_start_time(runtime_snapshot)
    if start is None:
        return None
    today = get_default_report_date()
    range_seconds = max(
        0,
        int(snapshot_seconds_for_date_range(runtime_snapshot, start_date, end_date)),
    )
    if range_seconds <= 0:
        return None

    key, activity_id = _transient_identity(runtime_snapshot)
    project_id, project_name, project_description = _runtime_report_project(runtime_snapshot)
    start_text = start.strftime(TIME_FORMAT)
    end_text = _slice_end_text(runtime_snapshot, today)
    app_name = str(runtime_snapshot.get("app_name") or "未知应用")
    member = {
        "report_date": today,
        "activity_id": activity_id,
        "slice_start_time": start_text,
        "start_time": start_text,
    }
    entry = {
        "projection_instance_key": key,
        "report_date": today,
        "start_time": start_text,
        "end_time": end_text,
        "duration_seconds": range_seconds,
        "row_kind": "project_session",
        "privacy_redacted": False,
        "status": STATUS_NORMAL,
        "status_code": STATUS_NORMAL,
        "report_project_id": project_id,
        "project_id": project_id,
        "project_name": project_name,
        "project_description": project_description,
        "project_is_deleted": False,
        "is_report_classified": project_id > 0,
        "is_report_project": project_id > 0,
        "is_report_uncategorized": project_id <= 0,
        "member_slices": [member],
        "activity_ids": [activity_id],
        "first_activity_id": activity_id,
        "is_in_progress": False,
        "exportable": True,
        "editable": False,
        "edit_disabled": True,
        "session_note": "",
        "has_duration_override": False,
        "adjusted_duration_seconds": None,
    }
    contribution = {
        "projection_instance_key": key,
        "report_date": today,
        "activity_id": activity_id,
        "slice_start_time": start_text,
        "duration_seconds": range_seconds,
        "status": STATUS_NORMAL,
        "privacy_redacted": False,
        "app_name": app_name,
    }
    revision = stable_json_hash(
        {
            "persistent_snapshot_revision": base.snapshot_revision,
            "runtime_revision": int(runtime_revision),
            "transient_key": key,
            "transient_seconds": range_seconds,
            "end": end_text,
        }
    )
    snapshot = ReportProjectionSnapshot(
        start_date=base.start_date,
        end_date=base.end_date,
        base_sessions=tuple(list(base.base_sessions) + [entry]),
        final_entries=tuple(list(base.final_entries) + [entry]),
        final_sessions=tuple(list(base.final_sessions) + [entry]),
        standalone_status_entries=base.standalone_status_entries,
        final_contributions=tuple(list(base.final_contributions) + [contribution]),
        operation_diagnostics=base.operation_diagnostics,
        snapshot_revision=revision,
    )
    return ReportAsOfSnapshot(
        snapshot,
        _live_target(
            entry,
            contribution,
            range_seconds=range_seconds,
            runtime_snapshot=runtime_snapshot,
        ),
    )


def build_statistics_as_of_snapshot(
    start_date: str,
    end_date: str,
) -> ReportAsOfSnapshot:
    """Return a canonical snapshot overlaid with one verified runtime activity."""

    base = build_visible_snapshot(start_date, end_date)
    context = current_page_read_context()
    if context is None or not context.runtime_consistent:
        return ReportAsOfSnapshot(base, None)
    runtime_snapshot = context.runtime_sample.snapshot
    if not isinstance(runtime_snapshot, Mapping):
        return ReportAsOfSnapshot(base, None)

    open_activity_id = context.verified_open_activity_id
    if open_activity_id is None:
        transient = _build_transient_statistics_overlay(
            base,
            runtime_snapshot,
            runtime_revision=int(context.runtime_sample.revision),
            start_date=start_date,
            end_date=end_date,
        )
        return transient or ReportAsOfSnapshot(base, None)

    try:
        runtime_id = int(runtime_snapshot.get("persisted_activity_id") or 0)
    except (TypeError, ValueError):
        return ReportAsOfSnapshot(base, None)
    if runtime_id != int(open_activity_id):
        return ReportAsOfSnapshot(base, None)

    contributions = [thaw_value(value) for value in base.final_contributions]
    delta_by_key: dict[str, int] = {}
    live_seconds_by_key: dict[str, int] = {}
    live_contribution_by_key: dict[str, dict[str, Any]] = {}
    any_live = False

    for row in contributions:
        try:
            row_activity_id = int(row.get("activity_id") or 0)
        except (TypeError, ValueError):
            row_activity_id = 0
        if row_activity_id != runtime_id:
            continue
        report_date = str(row.get("report_date") or "")
        if not report_date:
            continue
        live_seconds = snapshot_seconds_for_date_range(
            runtime_snapshot,
            report_date,
            report_date,
        )
        old_seconds = max(0, int(row.get("duration_seconds") or 0))
        live_seconds = max(old_seconds, int(live_seconds))
        key = str(row.get("projection_instance_key") or "")
        delta = live_seconds - old_seconds
        delta_by_key[key] = delta_by_key.get(key, 0) + delta
        live_seconds_by_key[key] = live_seconds_by_key.get(key, 0) + live_seconds
        live_contribution_by_key[key] = row
        row["duration_seconds"] = live_seconds
        if "observed_duration_seconds" in row:
            row["observed_duration_seconds"] = live_seconds
        if "report_duration_seconds" in row:
            row["report_duration_seconds"] = live_seconds
        row["is_in_progress"] = False
        any_live = True

    if not any_live:
        return ReportAsOfSnapshot(base, None)

    def overlay_records(values):
        result: list[dict[str, Any]] = []
        for value in values:
            row = thaw_value(value)
            key = str(row.get("projection_instance_key") or "")
            if key in delta_by_key and _record_contains_activity(row, runtime_id):
                row["duration_seconds"] = max(
                    0,
                    int(row.get("duration_seconds") or 0) + delta_by_key[key],
                )
                row["is_in_progress"] = False
                row["exportable"] = True
                row["editable"] = False
                row["edit_disabled"] = True
                report_date = str(row.get("report_date") or "")
                if report_date:
                    end_text = _slice_end_text(runtime_snapshot, report_date)
                    if end_text:
                        row["end_time"] = end_text
            result.append(row)
        return result

    final_entries = overlay_records(base.final_entries)
    final_sessions = overlay_records(base.final_sessions)
    standalone_status_entries = overlay_records(base.standalone_status_entries)
    base_sessions = overlay_records(base.base_sessions)

    live_entry = next(
        (
            row
            for row in final_entries
            if str(row.get("projection_instance_key") or "") in delta_by_key
            and _record_contains_activity(row, runtime_id)
        ),
        None,
    )
    live_key = str(live_entry.get("projection_instance_key") or "") if live_entry else ""
    range_seconds = int(live_seconds_by_key.get(live_key, 0))
    live_target = _live_target(
        live_entry,
        live_contribution_by_key.get(live_key),
        range_seconds=range_seconds,
        runtime_snapshot=runtime_snapshot,
    )
    revision = stable_json_hash(
        {
            "persistent_snapshot_revision": base.snapshot_revision,
            "runtime_revision": int(context.runtime_sample.revision),
            "open_activity_id": runtime_id,
            "live_seconds": live_seconds_by_key,
            "end": _slice_end_text(runtime_snapshot, str(live_entry.get("report_date") or ""))
            if live_entry
            else "",
        }
    )
    snapshot = ReportProjectionSnapshot(
        start_date=base.start_date,
        end_date=base.end_date,
        base_sessions=tuple(base_sessions),
        final_entries=tuple(final_entries),
        final_sessions=tuple(final_sessions),
        standalone_status_entries=tuple(standalone_status_entries),
        final_contributions=tuple(contributions),
        operation_diagnostics=base.operation_diagnostics,
        snapshot_revision=revision,
    )
    return ReportAsOfSnapshot(snapshot, live_target)


__all__ = ["ReportAsOfSnapshot", "build_statistics_as_of_snapshot"]
