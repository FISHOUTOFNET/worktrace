"""Page ViewModel projection over the unified Activity Display Model."""
from __future__ import annotations

from typing import Any

from ..constants import STATUS_NORMAL, UNCATEGORIZED_PROJECT
from ..contracts.live_display_contracts import ActivitySnapshotContract, DisplaySpanContract
from ..formatters import format_duration
from ..resources.title_parsing import extract_anchor_file_name
from . import (
    page_revision_service,
    project_activity_summary_service,
    timeline_service,
)
from .activity_display_model_service import build_activity_display_model
from .activity_display_projection import build_kpi_live_targets
from .activity_row_overlay import (
    ROW_KIND_PROJECT_ACTIVITY_SUMMARY_ROW,
    ROW_KIND_PROJECT_SESSION_ROW,
    ROW_KIND_RECENT_PROJECT_SESSION_ROW,
    apply_live_span_to_row,
)
from .page_view_model_common import enable_safe_open_edit
from .report_projection_identity import stable_json_hash
from .report_revision_service import get_report_structure_revision
from .runtime_activity_state_service import sample_runtime_activity_state

_RECENT_LIMIT = 20
_ATTENTION_LIMIT = 3


def _select_overview_recent_rows(
    recent_rows: list[dict[str, Any]],
    attention_rows: list[dict[str, Any]],
    *,
    limit: int,
) -> list[dict[str, Any]]:
    """Select the visible recent window so every displayed attention row is
    also present in the displayed recent list.

    The authoritative ``recent_rows`` is already filtered, merged, and sorted
    (in-progress first, then start time descending). We take the first
    ``limit`` rows as the base window, then promote any attention row that
    fell beyond the truncation boundary by replacing the tail-most ordinary
    (non-in-progress, non-attention) row. The result is re-sorted so
    in-progress stays first and start-time descending order is preserved.
    """
    if limit <= 0:
        return []

    selected = list(recent_rows[:limit])
    selected_keys = {
        str(row.get("projection_instance_key") or "")
        for row in selected
    }

    required_rows = [
        row
        for row in attention_rows
        if str(row.get("projection_instance_key") or "") not in selected_keys
    ]

    for required in required_rows:
        required_key = str(required.get("projection_instance_key") or "")
        if not required_key:
            continue

        replace_index = next(
            (
                index
                for index in range(len(selected) - 1, -1, -1)
                if not bool(selected[index].get("is_in_progress"))
                and not bool(selected[index].get("needs_attention"))
            ),
            None,
        )

        if replace_index is None:
            break

        selected[replace_index] = required
        selected_keys.add(required_key)

    selected.sort(
        key=lambda row: (
            bool(row.get("is_in_progress")),
            str(row.get("start_time") or ""),
        ),
        reverse=True,
    )
    return selected


def _get_current_activity_snapshot() -> ActivitySnapshotContract | None:
    return sample_runtime_activity_state().snapshot


def _first_display_span(model: dict[str, Any]) -> DisplaySpanContract | None:
    spans = model.get("display_spans") or []
    return spans[0] if spans else None


def _apply_live_span_to_rows(
    rows: list[dict[str, Any]],
    model: dict[str, Any],
    *,
    row_kind: str,
) -> None:
    span = _first_display_span(model)
    for row in rows:
        apply_live_span_to_row(row, span, row_kind=row_kind)


def _set_summary_activity_ids(rows: list[dict[str, Any]]) -> None:
    for row in rows:
        ids = _unique_positive_ids(row.get("activity_ids") or [])
        anchor_id = int(row.get("live_anchor_activity_id") or row.get("anchor_activity_id") or 0)
        clock = row.get("live_clock")
        if isinstance(clock, dict) and clock.get("is_live") is True and anchor_id > 0:
            ids = _unique_positive_ids([*ids, anchor_id])
        row["summary_activity_ids"] = ids


def _unique_positive_ids(values: list[Any]) -> list[int]:
    result: list[int] = []
    for value in values:
        try:
            item = int(value)
        except (TypeError, ValueError):
            continue
        if item > 0 and item not in result:
            result.append(item)
    return result


def _revision_fields_for_model(
    model: dict[str, Any],
    *,
    today: str,
    report_date: str,
) -> dict[str, str]:
    live_clock = model.get("live_clock") or {}
    current_activity = model.get("current_activity") or {}
    live_revision = page_revision_service.live_revision(current_activity, live_clock)
    structure_revision = get_report_structure_revision(report_date)
    return {
        "live_revision": live_revision,
        "structure_revision": structure_revision,
        "page_revision": stable_json_hash(
            [structure_revision, live_revision if report_date == today else ""]
        ),
    }


def _detail_report_project_dict(row: dict[str, Any]) -> dict[str, Any]:
    project_name = str(row.get("project_name") or UNCATEGORIZED_PROJECT)
    is_report_project = bool(row.get("is_report_project"))
    return {
        "id": int(row.get("project_id") or 0) or None,
        "name": project_name,
        "description": str(row.get("project_description") or ""),
        "source": str(row.get("report_attribution_kind") or "none"),
        "is_uncategorized": not is_report_project,
        "is_suggested_project": False,
    }


def _detail_report_attribution_fields(row: dict[str, Any]) -> dict[str, Any]:
    is_report_project = bool(row.get("is_report_project"))
    is_report_classified = bool(row.get("is_report_classified", is_report_project))
    is_report_uncategorized = bool(
        row.get("is_report_uncategorized", not is_report_project)
    )
    return {
        "project_id": int(row.get("project_id") or 0),
        "project_name": str(row.get("project_name") or UNCATEGORIZED_PROJECT),
        "project_description": str(row.get("project_description") or ""),
        "display_project": row.get("display_project")
        or _detail_report_project_dict(row),
        "is_uncategorized": is_report_uncategorized,
        "is_classified": is_report_classified,
        "is_report_project": is_report_project,
        "is_report_classified": is_report_classified,
        "is_report_uncategorized": is_report_uncategorized,
        "report_attribution_kind": str(
            row.get("report_attribution_kind") or "none"
        ),
        "is_official_project": bool(row.get("is_official_project")),
        "assignment_source": str(row.get("assignment_source") or ""),
        "project_attribution_kind": str(
            row.get("project_attribution_kind") or ""
        ),
    }


def _base_session_row(session: dict[str, Any], *, row_kind: str) -> dict[str, Any]:
    base_seconds = int(session.get("duration_seconds") or 0)
    adjusted = session.get("adjusted_duration_seconds")
    adjusted = int(adjusted) if adjusted is not None else None
    display_seconds = adjusted if adjusted is not None else base_seconds
    is_in_progress = bool(session.get("is_in_progress"))
    is_report_project = bool(
        session.get("is_report_project", session.get("is_classified"))
    )
    is_report_classified = bool(
        session.get("is_report_classified", is_report_project)
    )
    is_report_uncategorized = bool(
        session.get("is_report_uncategorized", not is_report_project)
    )
    first_activity_id = int(session.get("first_activity_id") or 0) or None
    row = {
        "row_kind": row_kind,
        "project_name": str(session.get("project_name") or UNCATEGORIZED_PROJECT),
        "project_description": str(session.get("project_description") or ""),
        "project_id": int(session.get("project_id") or 0),
        "start_time": str(session.get("start_time") or ""),
        "end_time": str(session.get("end_time") or ""),
        "duration": format_duration(display_seconds),
        "duration_seconds": display_seconds,
        "adjusted_duration_seconds": adjusted,
        "has_duration_override": adjusted is not None,
        "is_in_progress": is_in_progress,
        "contributes_to_totals": bool(session.get("contributes_to_totals", True)),
        "activity_ids": list(session.get("activity_ids") or []),
        "activity_member_hash": str(session.get("activity_member_hash") or ""),
        "anchor_activity_id": int(session.get("anchor_activity_id") or 0),
        "first_activity_id": first_activity_id,
        "activity_id": int(first_activity_id or 0),
        "open_activity_id": int(session.get("open_activity_id") or 0),
        "closed_duration_seconds": int(
            session.get("closed_duration_seconds") or 0
        ),
        "source": "db",
        "editable": bool(session.get("editable", not is_in_progress)),
        "exportable": bool(session.get("exportable", not is_in_progress)),
        "edit_disabled": bool(is_in_progress),
        "disable_reason": "进行中记录暂不支持编辑" if is_in_progress else "",
        "status": str(session.get("status") or "normal"),
        "status_code": str(
            session.get("status_code") or session.get("status") or "normal"
        ),
        "display_status": str(
            session.get("display_status")
            or session.get("status_label")
            or session.get("status_summary")
            or ""
        ),
        "status_summary": str(session.get("status_summary") or ""),
        "is_uncategorized": is_report_uncategorized,
        "is_classified": is_report_classified,
        "is_report_project": is_report_project,
        "is_report_classified": is_report_classified,
        "is_report_uncategorized": is_report_uncategorized,
        "report_attribution_kind": str(
            session.get("report_attribution_kind") or "none"
        ),
        "is_official_project": bool(session.get("is_official_project")),
        "has_project_override": bool(session.get("has_project_override")),
        "session_note": str(session.get("session_note") or ""),
        "projection_instance_key": str(
            session.get("projection_instance_key") or ""
        ),
        "projection_revision": str(session.get("projection_revision") or ""),
        "projection_kind": str(session.get("projection_kind") or "base"),
        "operation_id": session.get("operation_id"),
        "origin_activity_member_hashes": list(
            session.get("origin_activity_member_hashes") or []
        ),
        "event_count": int(session.get("event_count") or 0),
        "can_hide": bool(session.get("can_hide")),
        "can_merge_previous": bool(session.get("can_merge_previous")),
        "can_merge_next": bool(session.get("can_merge_next")),
        "can_split": bool(session.get("can_split")),
        "can_copy": bool(session.get("can_copy")),
        "can_hide_activity": bool(session.get("can_hide_activity")),
        "display_project": session.get("display_project"),
    }
    row.update(_description_display_fields(session))
    return row


def _description_display_fields(session: dict[str, Any]) -> dict[str, Any]:
    user_description = str(session.get("session_note") or "").strip()
    labels: list[str] = []
    contributions = sorted(
        list(session.get("_projection_contributions") or []),
        key=lambda item: -int(item.get("duration_seconds") or 0),
    )
    for contribution in contributions:
        if bool(contribution.get("privacy_redacted")):
            continue
        if str(contribution.get("status") or STATUS_NORMAL) != STATUS_NORMAL:
            continue
        activity_name = str(contribution.get("activity_display_name") or "").strip()
        if contribution.get("resource_is_anchor") and activity_name:
            label = activity_name
        else:
            label = extract_anchor_file_name(contribution.get("window_title")) or str(
                contribution.get("app_name") or contribution.get("process_name") or ""
            ).strip()
        if label and label not in labels:
            labels.append(label)
        if len(labels) >= 3:
            break
    derived_summary = " · ".join(labels)
    if user_description:
        display_description = user_description
        description_source = "user"
    elif derived_summary:
        display_description = derived_summary
        description_source = "derived"
    else:
        display_description = "暂无描述"
        description_source = "none"
    needs_project = not bool(session.get("is_report_project"))
    needs_user_description = not bool(user_description)
    missing_fields = (
        "project_and_description"
        if needs_project and needs_user_description
        else "project"
        if needs_project
        else "description"
        if needs_user_description
        else ""
    )
    return {
        "user_description": user_description,
        "display_description": display_description,
        "description_source": description_source,
        "needs_project": needs_project,
        "needs_user_description": needs_user_description,
        "needs_attention": bool(
            not session.get("is_in_progress")
            and (needs_project or needs_user_description)
        ),
        "missing_fields": missing_fields,
        "can_delete": bool(session.get("can_hide")),
        "delete_blocked_reason": "" if session.get("can_hide") else "当前时间段不可删除",
    }


def get_overview_view_model(today: str | None = None) -> dict[str, Any]:
    scoped_today = today or timeline_service.get_default_report_date()
    snapshot = _get_current_activity_snapshot()
    model = build_activity_display_model(
        report_date=scoped_today,
        today=scoped_today,
        snapshot=snapshot,
    )
    current_activity = model.get("current_activity") or {}

    from .report_projection_snapshot_service import build_visible_snapshot
    from .report_status_policy import decide_report_status

    projection = build_visible_snapshot(scoped_today, scoped_today)
    sessions = list(projection.final_sessions)
    standalone_entries = [
        entry
        for entry in projection.final_entries
        if str(entry.get("row_kind") or "") == "standalone_status"
        and not bool(entry.get("is_in_progress"))
    ]
    project_count = len(
        {
            int(row.get("report_project_id") or row.get("project_id") or 0)
            for row in projection.final_contributions
            if bool(row.get("is_report_project"))
            and int(row.get("report_project_id") or row.get("project_id") or 0) > 0
        }
    )

    recent_rows: list[dict[str, Any]] = []
    for session in sessions:
        contributions = list(session.get("_projection_contributions") or [])
        if contributions and not any(
            decide_report_status(
                str(item.get("status") or ""),
                has_project_attribution=bool(item.get("is_report_project")),
            ).visible_in_recent
            for item in contributions
        ):
            continue
        recent_rows.append(
            _base_session_row(session, row_kind="project_session")
        )
    _apply_live_span_to_rows(
        recent_rows,
        model,
        row_kind=ROW_KIND_RECENT_PROJECT_SESSION_ROW,
    )
    # Stable business order: in-progress report sessions first, then by
    # start time descending. A pure string sort would let a closed session
    # leapfrog an in-progress one when start times tie, so in-progress is
    # promoted explicitly via a second stable sort.
    recent_rows.sort(
        key=lambda row: str(row.get("start_time") or ""), reverse=True
    )
    recent_rows.sort(
        key=lambda row: bool(row.get("is_in_progress")), reverse=True
    )

    total_rows = [
        row for row in recent_rows if row.get("contributes_to_totals") is not False
    ]
    today_total_seconds = sum(int(row.get("duration_seconds") or 0) for row in total_rows)
    classified_seconds = sum(
        int(row.get("duration_seconds") or 0)
        for row in total_rows
        if bool(row.get("is_classified"))
    )
    uncategorized_seconds = sum(
        int(row.get("duration_seconds") or 0)
        for row in total_rows
        if bool(row.get("is_uncategorized"))
    )
    today_total_seconds += sum(
        int(entry.get("duration_seconds") or 0) for entry in standalone_entries
    )
    kpi_live_targets = build_kpi_live_targets(
        total_rows,
        model.get("live_clock") or {},
    )
    current_session = next(
        (row for row in recent_rows if bool(row.get("is_in_progress"))),
        None,
    )
    attention_candidates = [
        row for row in recent_rows if bool(row.get("needs_attention"))
    ]
    attention_rows = attention_candidates[:_ATTENTION_LIMIT]
    visible_recent_rows = _select_overview_recent_rows(
        recent_rows,
        attention_rows,
        limit=_RECENT_LIMIT,
    )
    return {
        "ok": True,
        "date": scoped_today,
        **_revision_fields_for_model(
            model,
            today=scoped_today,
            report_date=scoped_today,
        ),
        "live_clock": model.get("live_clock") or {},
        "overview": {
            "total_duration": format_duration(today_total_seconds),
            "classified_duration": format_duration(classified_seconds),
            "uncategorized_duration": format_duration(uncategorized_seconds),
            "project_count": project_count,
            "today_total_seconds": today_total_seconds,
            "classified_seconds": classified_seconds,
            "uncategorized_seconds": uncategorized_seconds,
        },
        "current_activity": current_activity,
        "current_session": current_session,
        "attention": attention_rows,
        "attention_remaining_count": max(0, len(attention_candidates) - _ATTENTION_LIMIT),
        "recent": visible_recent_rows,
        "today_total_seconds": today_total_seconds,
        "classified_seconds": classified_seconds,
        "uncategorized_seconds": uncategorized_seconds,
        "kpi_live_targets": kpi_live_targets,
    }


def get_timeline_view_model(report_date: str | None = None) -> dict[str, Any]:
    scoped_report_date = report_date or timeline_service.get_default_report_date()
    today = timeline_service.get_default_report_date()
    snapshot = _get_current_activity_snapshot()
    report_model = build_activity_display_model(
        report_date=scoped_report_date,
        today=today,
        snapshot=snapshot,
    )
    live_model = (
        report_model
        if scoped_report_date == today
        else build_activity_display_model(
            report_date=today,
            today=today,
            snapshot=snapshot,
        )
    )

    from .report_projection_snapshot_service import build_visible_snapshot

    projection = build_visible_snapshot(scoped_report_date, scoped_report_date)
    sessions = [
        _base_session_row(
            session,
            row_kind=str(session.get("row_kind") or "project_session"),
        )
        for session in projection.final_entries
    ]
    _apply_live_span_to_rows(
        sessions,
        report_model,
        row_kind=ROW_KIND_PROJECT_SESSION_ROW,
    )
    _set_summary_activity_ids(sessions)
    for row in sessions:
        enable_safe_open_edit(row)

    display_total_seconds = sum(
        int(row.get("duration_seconds") or 0) for row in sessions
    )
    total_target = build_kpi_live_targets(
        sessions,
        report_model.get("live_clock") or {},
    )["today_total_seconds"]
    return {
        "ok": True,
        "date": scoped_report_date,
        "today": today,
        "total_duration": format_duration(display_total_seconds),
        "total_seconds": display_total_seconds,
        "current_activity": live_model.get("current_activity") or {},
        "live_clock": live_model.get("live_clock") or {},
        **_revision_fields_for_model(
            report_model,
            today=today,
            report_date=scoped_report_date,
        ),
        "entries": sessions,
        "snapshot_revision": projection.snapshot_revision,
        "today_total_seconds": display_total_seconds,
        "total_live_clock": total_target.get("live_clock")
        if total_target.get("enabled") is True
        else None,
    }


def get_session_activity_summary_view_model(
    *,
    report_date: str | None = None,
    projection_instance_key: str,
    expected_projection_revision: str | None = None,
) -> dict[str, Any]:
    date = report_date or timeline_service.get_default_report_date()
    today = timeline_service.get_default_report_date()
    snapshot = _get_current_activity_snapshot()
    report_model = build_activity_display_model(
        report_date=date,
        today=today,
        snapshot=snapshot,
    )
    live_model = (
        report_model
        if date == today
        else build_activity_display_model(
            report_date=today,
            today=today,
            snapshot=snapshot,
        )
    )
    detail_projection = (
        project_activity_summary_service.get_projection_session_activity_summary(
            projection_instance_key,
            date,
            expected_projection_revision=expected_projection_revision,
        )
    )
    rows = [dict(row) for row in detail_projection["summary_rows"]]
    for row in rows:
        row.update(_detail_report_attribution_fields(row))
        row["can_delete"] = bool(row.get("can_hide_activity"))
        row["delete_blocked_reason"] = (
            "" if row.get("can_hide_activity") else "当前活动不可删除"
        )
    _apply_live_span_to_rows(
        rows,
        report_model,
        row_kind=ROW_KIND_PROJECT_ACTIVITY_SUMMARY_ROW,
    )
    for row in rows:
        if row.get("is_in_progress") and not row.get("edit_disabled"):
            row["edit_disabled"] = True
            row["disable_reason"] = (
                row.get("disable_reason") or "进行中记录暂不支持编辑"
            )
        row["duration"] = format_duration(int(row.get("duration_seconds") or 0))
    rows.sort(
        key=lambda item: (
            -int(item.get("duration_seconds") or 0),
            str(item.get("activity_name") or ""),
        )
    )
    return {
        "ok": True,
        "date": date,
        "today": today,
        "projection_instance_key": projection_instance_key,
        "resolved_projection_revision": detail_projection[
            "resolved_projection_revision"
        ],
        "summary_rows": rows,
        "current_activity": live_model.get("current_activity") or {},
        "live_clock": live_model.get("live_clock") or {},
        **_revision_fields_for_model(
            report_model,
            today=today,
            report_date=date,
        ),
    }


__all__ = [
    "get_overview_view_model",
    "get_session_activity_summary_view_model",
    "get_timeline_view_model",
]
