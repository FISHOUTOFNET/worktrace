from __future__ import annotations

import pytest

from tests.support import activity_factory
from worktrace.services import (
    assignment_command_service,
    export_service,
    project_service,
    statistics_service,
)
from worktrace.services.page_read_context import page_read_scope
from worktrace.services.report_projection_provider import (
    get_day_projection,
    get_durable_day_projection,
)
from worktrace.services.report_session_builder import merge_short_project_returns
from worktrace.services.runtime_activity_state_service import (
    publish_runtime_activity_snapshot,
)
from worktrace.services.timeline_service import get_default_report_date


pytestmark = [pytest.mark.db, pytest.mark.integration]


def _assign(activity_id: int, project_id: int) -> None:
    assignment_command_service.assign_with_uow(
        activity_id=activity_id,
        project_id=project_id,
        source="manual",
        confidence=100,
        is_manual=True,
    )


def test_effective_read_projection_compacts_verified_open_same_project_return(temp_db):
    day = get_default_report_date()
    project_a = project_service.create_project("Effective A")
    project_b = project_service.create_project("Effective B")

    first = activity_factory.create_closed_activity(
        day=day,
        start="09:00:00",
        end="09:10:00",
        window_title="a-before.docx",
    )
    _assign(first, project_a)
    interruption = activity_factory.create_closed_activity(
        day=day,
        start="09:10:00",
        end="09:12:00",
        window_title="b-short.docx",
    )
    _assign(interruption, project_b)
    current = activity_factory.create_open_activity(
        start_time=f"{day} 09:12:00",
        window_title="a-live.docx",
    )
    _assign(current, project_a)
    activity_factory.set_activity_duration(current, 30)
    publish_runtime_activity_snapshot(
        {
            "persisted_activity_id": current,
            "is_persisted": True,
            "elapsed_seconds": 10 * 60,
            "start_time": f"{day} 09:12:00",
            "status": "normal",
            "app_name": "Word",
            "process_name": "winword.exe",
            "resource_display_name": "a-live.docx",
        },
        reason="effective_live_projection_test",
    )

    with page_read_scope():
        durable = get_durable_day_projection(day)
        effective = get_day_projection(day)

    assert [int(row["project_id"]) for row in durable.final_sessions] == [
        project_a,
        project_b,
        project_a,
    ]
    assert len(effective.final_sessions) == 1
    merged = effective.final_sessions[0]
    assert int(merged["project_id"]) == project_a
    assert bool(merged["is_in_progress"]) is True
    assert bool(merged["read_provisional"]) is True
    assert bool(merged["editable"]) is False
    assert int(merged["duration_seconds"]) == 22 * 60
    assert int(merged["closed_duration_seconds"]) == 12 * 60
    assert set(int(value) for value in merged["activity_ids"]) == {
        first,
        interruption,
        current,
    }

    summary = statistics_service.get_statistics_realtime_export_summary(day, day)
    assert summary["total_duration_seconds"] == 22 * 60
    assert [(row["display_name"], row["duration_seconds"]) for row in summary["by_project"]] == [
        ("Effective A", 22 * 60),
    ]

    prepared = export_service.prepare_statistics_csv(day, day)
    assert prepared.export_row_count == 1
    assert prepared.duration_seconds == 22 * 60
    assert prepared.rows[0].project == "Effective A"


def _session(
    project_id: int,
    name: str,
    start: str,
    end: str,
    duration: int,
    activity_id: int,
    *,
    in_progress: bool = False,
) -> dict:
    day = "2026-08-28"
    return {
        "row_kind": "project_session",
        "project_id": project_id,
        "project_name": name,
        "project_description": "",
        "project_is_deleted": False,
        "project_is_archived": False,
        "report_project_key": f"project:{project_id}",
        "start_time": f"{day} {start}",
        "end_time": f"{day} {end}",
        "report_date": day,
        "duration_seconds": duration,
        "closed_duration_seconds": 0 if in_progress else duration,
        "open_activity_id": activity_id if in_progress else 0,
        "activity_ids": [activity_id],
        "member_slices": [
            {
                "report_date": day,
                "activity_id": activity_id,
                "slice_start_time": f"{day} {start}",
                "slice_end_time": f"{day} {end}",
            }
        ],
        "activity_member_hash": f"member-{activity_id}",
        "anchor_activity_id": activity_id,
        "first_activity_id": activity_id,
        "sort_time": f"{day} {start}",
        "event_count": 1,
        "status": "normal",
        "status_code": "normal",
        "display_status": name,
        "status_summary": name,
        "contributes_to_totals": True,
        "live_delta_eligible": False,
        "editable": not in_progress,
        "exportable": not in_progress,
        "is_in_progress": in_progress,
        "is_official_project": True,
        "report_attribution_kind": "official_direct",
        "is_report_project": True,
        "is_report_classified": True,
        "is_report_uncategorized": False,
        "is_classified": True,
        "is_uncategorized": False,
    }


def test_effective_open_return_still_respects_hard_boundary():
    result = merge_short_project_returns(
        [
            _session(1, "A", "09:00:00", "09:10:00", 600, 1),
            _session(2, "B", "09:10:00", "09:11:00", 60, 2),
            _session(
                1,
                "A",
                "09:11:00",
                "09:16:00",
                300,
                3,
                in_progress=True,
            ),
        ],
        boundary_times=("2026-08-28 09:10:30",),
        effective_open_activity_id=3,
    )
    assert [int(row["project_id"]) for row in result] == [1, 2, 1]
