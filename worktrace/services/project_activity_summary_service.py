from __future__ import annotations

import hashlib
from typing import Any

from ..constants import UNCATEGORIZED_PROJECT
from ..formatters import format_duration, format_safe_display_name


def build_activity_summary_rows(
    rows: list[dict],
    report_date: str,
    scope_key: str,
    projection_revision: str,
) -> list[dict]:
    """Aggregate already-scoped report rows into activity summary rows."""
    groups: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = activity_group_key(row)
        accounted_project_id = int(
            row.get("report_project_id")
            or row.get("project_id")
            or 0
        )
        seconds = int(
            row.get("report_duration_seconds")
            or row.get("duration_seconds")
            or 0
        )
        if key not in groups:
            groups[key] = _new_group(
                report_date,
                scope_key,
                accounted_project_id,
                key,
                row,
            )
        group = groups[key]
        group["duration_seconds"] = int(group["duration_seconds"]) + seconds
        if not bool(row.get("is_in_progress")):
            group["closed_duration_seconds"] = (
                int(group["closed_duration_seconds"]) + seconds
            )
        else:
            group["is_in_progress"] = True
            group["open_activity_id"] = int(
                row.get("id") or row.get("activity_id") or 0
            )
        activity_id = int(row.get("id") or row.get("activity_id") or 0)
        if activity_id > 0 and activity_id not in group["activity_ids"]:
            group["activity_ids"].append(activity_id)
        group["member_identities"].append(
            (
                str(row.get("report_date") or report_date),
                activity_id,
                str(row.get("slice_start_time") or row.get("start_time") or ""),
            )
        )

    summaries = [
        _finalize_group(group, projection_revision)
        for group in groups.values()
    ]
    summaries.sort(
        key=lambda item: (
            -int(item.get("duration_seconds") or 0),
            str(item.get("activity_name") or ""),
        )
    )
    return summaries


def get_projection_session_activity_summary(
    projection_instance_key: str,
    report_date: str,
    *,
    expected_projection_revision: str | None = None,
) -> dict[str, Any]:
    """Return right-panel summaries from the canonical final contribution set."""
    from .report_projection_snapshot_service import build_visible_snapshot

    snapshot = build_visible_snapshot(report_date, report_date)
    session = next(
        (
            item
            for item in snapshot.final_entries
            if str(item.get("projection_instance_key") or "")
            == str(projection_instance_key or "")
        ),
        None,
    )
    if not session:
        raise ValueError("stale_selection")
    resolved_revision = str(session.get("projection_revision") or "")
    if (
        expected_projection_revision is not None
        and resolved_revision != str(expected_projection_revision or "")
    ):
        raise ValueError("stale_selection")

    contributions = [
        dict(row)
        for row in snapshot.final_contributions
        if str(row.get("projection_instance_key") or "")
        == str(projection_instance_key or "")
    ]
    summaries = build_activity_summary_rows(
        contributions,
        report_date,
        projection_instance_key,
        resolved_revision,
    )
    for summary in summaries:
        summary["projection_instance_key"] = projection_instance_key
        summary["can_hide_activity"] = bool(session.get("can_hide_activity"))
    return {
        "projection_instance_key": projection_instance_key,
        "resolved_projection_revision": resolved_revision,
        "summary_rows": summaries,
    }


def _new_group(
    report_date: str,
    scope_key: str,
    accounted_project_id: int,
    key: str,
    row: dict,
) -> dict[str, Any]:
    display_project_name = str(
        row.get("display_project_name") or UNCATEGORIZED_PROJECT
    )
    display_project_description = str(
        row.get("display_project_description") or ""
    )
    accounted_project_name = str(
        row.get("report_project_name") or UNCATEGORIZED_PROJECT
    )
    accounted_project_description = str(
        row.get("report_project_description") or ""
    )
    return {
        "row_kind": "project_activity_summary",
        "summary_id": "",
        "_report_date": report_date,
        "_scope_key": scope_key,
        "activity_identity_key": key,
        "activity_name": _activity_display_name(row),
        "duration_seconds": 0,
        "duration": "00:00:00",
        "accounted_project_id": int(accounted_project_id),
        "accounted_project_name": accounted_project_name,
        "accounted_project_description": accounted_project_description,
        "project_id": int(accounted_project_id),
        "project_name": accounted_project_name,
        "project_description": accounted_project_description,
        "display_project_id": int(row.get("display_project_id") or 0),
        "display_project_name": display_project_name,
        "display_project_description": display_project_description,
        "activity_ids": [],
        "member_identities": [],
        "is_in_progress": False,
        "open_activity_id": 0,
        "closed_duration_seconds": 0,
        "live_delta_eligible": False,
        "duration_semantic": "static_closed",
        "display_span_id": "",
        "stable_live_key_hash": "",
        "display_base_seconds": 0,
        "edit_disabled": False,
        "disable_reason": "",
        "editable": True,
        "exportable": True,
        "source": "db",
        "is_report_project": bool(row.get("is_report_project")),
        "is_report_classified": bool(row.get("is_report_classified")),
        "is_report_uncategorized": bool(row.get("is_report_uncategorized")),
        "report_attribution_kind": str(
            row.get("report_attribution_kind") or "none"
        ),
        "is_official_project": bool(row.get("is_official_project")),
        "is_uncategorized": bool(row.get("is_report_uncategorized")),
        "is_classified": bool(row.get("is_report_classified")),
    }


def _finalize_group(
    group: dict[str, Any],
    projection_revision: str,
) -> dict[str, Any]:
    seconds = int(group.get("duration_seconds") or 0)
    group["duration"] = format_duration(seconds)
    group["display_base_seconds"] = seconds
    if group.get("is_in_progress"):
        group["edit_disabled"] = True
        group["editable"] = False
        group["exportable"] = False
        group["disable_reason"] = "进行中记录暂不支持编辑"
    group["activity_ids"] = sorted(
        int(aid) for aid in group.get("activity_ids") or []
    )
    member_identities = sorted(
        set(tuple(item) for item in group.pop("member_identities", []))
    )
    group["summary_id"] = _summary_id(
        str(group.pop("_report_date", "")),
        str(group.pop("_scope_key", "")),
        projection_revision,
        str(group.get("activity_identity_key") or ""),
        member_identities,
    )
    return group


def activity_group_key(row: dict) -> str:
    """Return the stable public grouping key used by summary and mutation paths."""
    return _activity_identity_part(row)


def _activity_identity_part(row: dict) -> str:
    for field in ("activity_identity_key", "resource_identity_key"):
        value = str(row.get(field) or "").strip()
        if value:
            return value
    resource_parts = [
        str(row.get("resource_kind") or "").strip(),
        str(row.get("resource_subtype") or "").strip(),
        str(
            row.get("resource_path_hint")
            or row.get("path_key")
            or row.get("resource_uri_host")
            or ""
        )
        .strip()
        .lower(),
    ]
    if any(resource_parts):
        return "resource:" + "|".join(resource_parts)
    display = _activity_display_name(row).lower()
    app = str(row.get("app_name") or "").strip().lower()
    return "fallback:" + app + "|" + display


def _activity_display_name(row: dict) -> str:
    for value in (
        format_safe_display_name(row),
        row.get("activity_display_name"),
        row.get("resource_display_name"),
        row.get("app_name"),
    ):
        text = str(value or "").strip()
        if text:
            return text
    return "未知"


def _summary_id(
    report_date: str,
    scope_key: str,
    projection_revision: str,
    key: str,
    member_identities: list[tuple],
) -> str:
    raw = (
        f"{report_date}|{scope_key}|{projection_revision}|"
        f"{key}|{member_identities!r}"
    )
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


__all__ = [
    "activity_group_key",
    "build_activity_summary_rows",
    "get_projection_session_activity_summary",
]
