from __future__ import annotations

import csv
from datetime import datetime

import pytest

from tests.support import activity_factory
from worktrace.db import get_connection
from worktrace.services import assignment_command_service, export_service, project_service, statistics_service
from worktrace.services.runtime_activity_state_service import publish_runtime_activity_snapshot
from worktrace.services.timeline_service import get_default_report_date

pytestmark = [pytest.mark.db, pytest.mark.integration, pytest.mark.contract]


def _seed_verified_open(project_id: int, *, elapsed_seconds: int) -> tuple[int, str]:
    day = get_default_report_date()
    start = f"{day} 09:00:00"
    activity_id = activity_factory.create_activity(
        "Word",
        "winword.exe",
        "live.docx",
        start_time=start,
        project_id=project_id,
        file_path_hint=r"C:\\Work\\live.docx",
        status="normal",
    )
    assignment_command_service.assign_with_uow(
        activity_id=activity_id,
        project_id=project_id,
        source="manual",
        confidence=100,
        is_manual=True,
    )
    publish_runtime_activity_snapshot(
        {
            "persisted_activity_id": activity_id,
            "is_persisted": True,
            "elapsed_seconds": int(elapsed_seconds),
            "start_time": start,
            "status": "normal",
            "app_name": "Word",
            "process_name": "winword.exe",
            "resource_display_name": "live.docx",
        },
        reason="statistics_as_of_test",
    )
    return activity_id, day


def test_statistics_summary_includes_verified_open_activity_without_persisting_close(temp_db):
    project_id = project_service.create_project("Live Client")
    activity_id, day = _seed_verified_open(project_id, elapsed_seconds=1800)

    summary = statistics_service.get_statistics_export_summary(day, day)

    assert summary["total_duration_seconds"] == 1800
    assert summary["activity_count"] == 1
    assert summary["session_count"] == 1
    assert summary["export_row_count"] == 1
    assert summary["by_project"][0]["display_name"] == "Live Client"
    assert summary["by_project"][0]["duration_seconds"] == 1800
    assert summary["by_app"][0]["display_name"] == "Word"
    assert summary["live_target"]["enabled"] is True
    assert summary["live_target"]["elapsed_seconds_at_sample"] == 1800

    with get_connection() as conn:
        row = conn.execute(
            "SELECT end_time, duration_seconds FROM activity_log WHERE id = ?",
            (activity_id,),
        ).fetchone()
    assert row["end_time"] is None
    assert int(row["duration_seconds"] or 0) < 1800


def test_statistics_project_scope_excludes_other_live_project(temp_db):
    selected_project = project_service.create_project("Selected")
    live_project = project_service.create_project("Live Other")
    _activity_id, day = _seed_verified_open(live_project, elapsed_seconds=900)

    summary = statistics_service.get_statistics_export_summary(
        day,
        day,
        selected_project,
    )

    assert summary["total_duration_seconds"] == 0
    assert summary["by_project"] == []
    assert summary["live_target"] is None


def test_prepared_statistics_export_is_frozen_before_later_runtime_updates(temp_db, tmp_path):
    project_id = project_service.create_project("Frozen Client")
    activity_id, day = _seed_verified_open(project_id, elapsed_seconds=1800)

    prepared = export_service.prepare_statistics_csv(day, day)

    publish_runtime_activity_snapshot(
        {
            "persisted_activity_id": activity_id,
            "is_persisted": True,
            "elapsed_seconds": 2400,
            "start_time": f"{day} 09:00:00",
            "status": "normal",
            "app_name": "Word",
            "process_name": "winword.exe",
            "resource_display_name": "live.docx",
        },
        reason="statistics_as_of_test_advanced",
    )

    output = tmp_path / "frozen.csv"
    result = export_service.write_prepared_statistics_csv(prepared, output)

    assert result["duration_seconds"] == 1800
    with open(output, "r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 1
    assert rows[0]["时长秒数"] == "1800"
    expected_end = datetime.fromisoformat(f"{day}T09:30:00").strftime("%Y-%m-%d %H:%M:%S")
    assert rows[0]["结束时间"] == expected_end
