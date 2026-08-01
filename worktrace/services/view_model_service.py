"""Page ViewModel projection over the unified Activity Display Model."""
from __future__ import annotations

from typing import Any, Mapping

from ..constants import STATUS_NORMAL, UNCATEGORIZED_PROJECT
from ..contracts.live_display_contracts import ActivitySnapshotContract, DisplaySpanContract
from ..formatters import format_duration, format_status_label
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
from .projection_performance import stage
from .report_projection_identity import stable_json_hash
from .report_revision_service import get_report_structure_revision
from .runtime_activity_state_service import sample_runtime_activity_state

_RECENT_LIMIT = 20


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


def _base_session_row(
    session: dict[str, Any],
    *,
    row_kind: str,
    contributions: tuple[Mapping[str, Any], ...] = (),
) -> dict[str, Any]:
    is_standalone_status = row_kind == "standalone_status"
    base_seconds = int(session.get("duration_seconds") or 0)
    adjusted = session.get("adjusted_duration_seconds")
    adjusted = int(adjusted) if adjusted is not None else None
    display_seconds = adjusted if adjusted is not None else base_seconds
    is_in_progress = bool(session.get("is_in_progress"))
    editable = bool(session.get("editable", not is_in_progress)) and not is_in_progress
    is_report_project = False if is_standalone_status else bool(
        session.get("is_report_project", session.get("is_classified"))
    )
    is_report_classified = False if is_standalone_status else bool(
        session.get("is_report_classified", is_report_project)
    )
    is_report_uncategorized = False if is_standalone_status else bool(
        session.get("is_report_uncategorized", not is_report_project)
    )
    status_code = str(
        session.get("status_code") or session.get("status") or "normal"
    )
    display_status = str(
        session.get("display_status")
        or session.get("status_label")
        or (
            format_status_label(status_code)
            if is_standalone_status
            else session.get("status_summary") or ""
        )
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
        "editable": editable,
        "exportable": bool(session.get("exportable", not is_in_progress)),
        "edit_disabled": bool(is_in_progress),
        "can_edit_project": editable,
        "can_edit_note": editable,
        "can_edit_duration": editable,
        "disable_reason": "进行中时段不可编辑" if is_in_progress else "",
        "status": str(session.get("status") or "normal"),
        "status_code": status_code,
        "display_status": display_status,
        "status_summary": str(session.get("status_summary") or ""),
        "privacy_redacted": bool(session.get("privacy_redacted")),
        "project_is_deleted": bool(session.get("project_is_deleted")),
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
        "can_hide": False if is_in_progress else bool(session.get("can_hide")),
        "can_merge_previous": False
        if is_in_progress
        else bool(session.get("can_merge_previous")),
        "can_merge_next": False
        if is_in_progress
        else bool(session.get("can_merge_next")),
        "can_split": False if is_in_progress else bool(session.get("can_split")),
        "can_copy": False if is_in_progress else bool(session.get("can_copy")),
        "can_hide_activity": False
        if is_in_progress
        else bool(session.get("can_hide_activity")),
        "display_project": session.get("display_project"),
    }
    row.update(_description_display_fields(session, contributions))
    return row


def _contribution_label(contribution: Mapping[str, Any]) -> str:
    """Extract the display label from a single contribution row."""
    activity_name = str(contribution.get("activity_display_name") or "").strip()
    if contribution.get("resource_is_anchor") and activity_name:
        return activity_name
    return extract_anchor_file_name(contribution.get("window_title")) or str(
        contribution.get("app_name") or contribution.get("process_name") or ""
    ).strip()


def _top3_distinct_labels(contributions: list[dict[str, Any]]) -> list[str]:
    """Return up to 3 distinct labels by the original sort rule.

    Original semantic: sort contributions by duration descending (stable),
    iterate, extract label, skip duplicates, break at 3 distinct labels.
    Equivalent O(n) implementation: keep the best (duration, position) per
    label (first wins on ties = stable secondary sort), then rank labels
    by (-duration, position) — identical to the sorted()+break order.
    """
    best_per_label: dict[str, tuple[int, int]] = {}
    for pos, item in enumerate(contributions):
        if bool(item.get("privacy_redacted")):
            continue
        if str(item.get("status") or STATUS_NORMAL) != STATUS_NORMAL:
            continue
        label = _contribution_label(item)
        if not label:
            continue
        duration = int(item.get("duration_seconds") or 0)
        existing = best_per_label.get(label)
        if existing is None or duration > existing[0]:
            best_per_label[label] = (duration, pos)
    ranked = sorted(
        best_per_label,
        key=lambda lbl: (-best_per_label[lbl][0], best_per_label[lbl][1]),
    )
    return ranked[:3]


def _description_display_fields(
    session: dict[str, Any],
    contributions: tuple[Mapping[str, Any], ...] = (),
) -> dict[str, Any]:
    user_description = str(session.get("session_note") or "").strip()
    labels = _top3_distinct_labels(list(contributions))
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


def _session_display_seconds(session: Mapping[str, Any]) -> int:
    """Lightweight duration extraction matching _base_session_row's logic."""
    base = int(session.get("duration_seconds") or 0)
    adjusted = session.get("adjusted_duration_seconds")
    if adjusted is not None:
        return int(adjusted)
    return base


def _accumulate_overview_distribution_bucket(
    buckets: dict[str, dict[str, Any]],
    session: Mapping[str, Any],
    display_seconds: int,
) -> None:
    """Accumulate one authoritative final session into its Overview category."""
    if session.get("contributes_to_totals", True) is False or display_seconds <= 0:
        return

    project_id = int(
        session.get("report_project_id") or session.get("project_id") or 0
    )
    if bool(session.get("is_report_project")) and project_id > 0:
        key = f"project:{project_id}"
        project_name = str(session.get("project_name") or "").strip()
        bucket = buckets.setdefault(
            key,
            {
                "key": key,
                "project_id": project_id,
                "label": project_name or UNCATEGORIZED_PROJECT,
                "duration_seconds": 0,
                "is_uncategorized": False,
                "is_other": False,
            },
        )
    elif bool(session.get("is_report_uncategorized")):
        key = "uncategorized"
        bucket = buckets.setdefault(
            key,
            {
                "key": key,
                "project_id": None,
                "label": UNCATEGORIZED_PROJECT,
                "duration_seconds": 0,
                "is_uncategorized": True,
                "is_other": False,
            },
        )
    else:
        return

    bucket["duration_seconds"] = int(bucket["duration_seconds"]) + display_seconds


def _finalize_overview_project_distribution(
    buckets: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Sort categories and collapse categories after the top three."""
    categories = [
        dict(bucket)
        for bucket in buckets.values()
        if int(bucket.get("duration_seconds") or 0) > 0
    ]
    categories.sort(
        key=lambda bucket: (
            -int(bucket["duration_seconds"]),
            str(bucket["key"]),
        )
    )
    total_seconds = sum(int(bucket["duration_seconds"]) for bucket in categories)
    if len(categories) <= 3:
        segments = categories
    else:
        remainder = categories[3:]
        segments = [
            *categories[:3],
            {
                "key": "other",
                "project_id": None,
                "label": "其他",
                "duration_seconds": sum(
                    int(bucket["duration_seconds"]) for bucket in remainder
                ),
                "category_count": len(remainder),
                "is_uncategorized": False,
                "is_other": True,
            },
        ]
    return {
        "total_seconds": total_seconds,
        "segments": segments,
    }


def _session_visible_in_recent(
    session: Mapping[str, Any],
    decide_report_status,
    contributions: tuple[Mapping[str, Any], ...] = (),
) -> bool:
    """Lightweight visibility check without building a full DTO."""
    if not contributions:
        return True
    return any(
        decide_report_status(
            str(item.get("status") or ""),
            has_project_attribution=bool(item.get("is_report_project")),
        ).visible_in_recent
        for item in contributions
    )


def get_overview_view_model(today: str | None = None) -> dict[str, Any]:
    scoped_today = today or timeline_service.get_default_report_date()
    snapshot = _get_current_activity_snapshot()
    model = build_activity_display_model(
        report_date=scoped_today,
        today=scoped_today,
        snapshot=snapshot,
    )
    current_activity = model.get("current_activity") or {}

    from .report_projection_provider import get_day_projection
    from .report_status_policy import decide_report_status

    projection = get_day_projection(scoped_today)
    with stage("overview_assemble"):
        sessions = list(projection.final_sessions)
        standalone_entries = [
            entry
            for entry in projection.standalone_status_entries
            if not bool(entry.get("is_in_progress"))
        ]
        project_count = len(
            {
                int(row.get("report_project_id") or row.get("project_id") or 0)
                for row in projection.contributions
                if bool(row.get("is_report_project"))
                and int(row.get("report_project_id") or row.get("project_id") or 0) > 0
            }
        )

        # Select-then-transform: compute lightweight selection keys for all
        # sessions, pick the visible 20 recent rows, then build full DTOs only
        # for the surviving rows. Distribution aggregation shares this same
        # authoritative final-session traversal.
        candidates: list[dict[str, Any]] = []
        distribution_buckets: dict[str, dict[str, Any]] = {}
        for session in sessions:
            display_seconds = _session_display_seconds(session)
            _accumulate_overview_distribution_bucket(
                distribution_buckets,
                session,
                display_seconds,
            )
            session_key = str(session.get("projection_instance_key") or "")
            session_contributions = projection.contributions_by_key.get(
                session_key, ()
            )
            if not _session_visible_in_recent(
                session, decide_report_status, session_contributions
            ):
                continue
            candidates.append(
                {
                    "session": session,
                    "contributions": session_contributions,
                    "start_time": str(session.get("start_time") or ""),
                    "is_in_progress": bool(session.get("is_in_progress")),
                    "display_seconds": display_seconds,
                    "contributes_to_totals": bool(
                        session.get("contributes_to_totals", True)
                    ),
                    "is_classified": bool(
                        session.get("is_report_classified")
                        or session.get("is_report_project")
                        or session.get("is_classified")
                    ),
                    "is_uncategorized": bool(
                        session.get("is_report_uncategorized")
                        or (
                            not bool(session.get("is_report_project"))
                            and not bool(session.get("is_classified"))
                        )
                    ),
                }
            )
        project_distribution = _finalize_overview_project_distribution(
            distribution_buckets
        )

        # KPI must be computed from the full projection, not the truncated
        # visible set, so it is calculated from candidates (pre-truncation).
        total_candidates = [
            c for c in candidates if c["contributes_to_totals"]
        ]
        today_total_seconds = sum(
            c["display_seconds"] for c in total_candidates
        )
        classified_seconds = sum(
            c["display_seconds"]
            for c in total_candidates
            if c["is_classified"]
        )
        uncategorized_seconds = sum(
            c["display_seconds"]
            for c in total_candidates
            if c["is_uncategorized"]
        )
        today_total_seconds += sum(
            int(entry.get("duration_seconds") or 0) for entry in standalone_entries
        )

        # Sort: in-progress first, then start_time descending.
        candidates.sort(
            key=lambda c: c["start_time"], reverse=True
        )
        candidates.sort(
            key=lambda c: c["is_in_progress"], reverse=True
        )

        # Build full DTOs only for the visible window.
        visible_candidates = list(candidates[:_RECENT_LIMIT])

        recent_rows = [
            _base_session_row(
                c["session"],
                row_kind="project_session",
                contributions=c["contributions"],
            )
            for c in visible_candidates
        ]
        _apply_live_span_to_rows(
            recent_rows,
            model,
            row_kind=ROW_KIND_RECENT_PROJECT_SESSION_ROW,
        )

        # Re-sort the visible rows (same business order).
        recent_rows.sort(
            key=lambda row: str(row.get("start_time") or ""), reverse=True
        )
        recent_rows.sort(
            key=lambda row: bool(row.get("is_in_progress")), reverse=True
        )

    kpi_live_targets = build_kpi_live_targets(
        [row for row in recent_rows if row.get("contributes_to_totals") is not False],
        model.get("live_clock") or {},
    )
    current_session = next(
        (row for row in recent_rows if bool(row.get("is_in_progress"))),
        None,
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
        "project_distribution": project_distribution,
        "recent": recent_rows,
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

    from .report_projection_provider import get_day_projection

    projection = get_day_projection(scoped_report_date)
    with stage("timeline_assemble"):
        sessions = [
            _base_session_row(
                session,
                row_kind=str(session.get("row_kind") or "project_session"),
                contributions=projection.contributions_by_key.get(
                    str(session.get("projection_instance_key") or ""), ()
                ),
            )
            for session in projection.entries
        ]
        _apply_live_span_to_rows(
            sessions,
            report_model,
            row_kind=ROW_KIND_PROJECT_SESSION_ROW,
        )
        _set_summary_activity_ids(sessions)
    from .reported_duration_policy import reported_day_total_seconds

    display_total_seconds = reported_day_total_seconds(sessions)
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
    expected_source_version: str | None = None,
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
    with stage("detail_lookup"):
        detail_projection = (
            project_activity_summary_service.get_projection_session_activity_summary(
                projection_instance_key,
                date,
                expected_projection_revision=expected_projection_revision,
                expected_source_version=expected_source_version,
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
                row.get("disable_reason") or "进行中时段不可编辑"
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
