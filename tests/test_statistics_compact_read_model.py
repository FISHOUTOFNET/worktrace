from __future__ import annotations

import pytest

from tests.support import activity_factory
from tests.support.activity_factory import create_closed_activity
from worktrace.services import (
    assignment_command_service,
    project_service,
    report_as_of_snapshot_service,
    report_projection_snapshot_service,
    statistics_service,
    statistics_snapshot_provider,
)
from worktrace.services.page_read_context import page_read_scope
from worktrace.services.report_projection_model import ReportProjectionSnapshot
from worktrace.services.runtime_activity_state_service import publish_runtime_activity_snapshot
from worktrace.services.timeline_service import get_default_report_date

pytestmark = [pytest.mark.db, pytest.mark.integration, pytest.mark.contract]
DATE = "2026-08-17"


def _seed_closed(project_id: int, *, start: str = "10:00:00") -> None:
    create_closed_activity(
        day=DATE,
        start=start,
        end="10:20:00" if start == "10:00:00" else "11:20:00",
        window_title="Compact.xlsx",
        project_id=project_id,
    )


def test_interactive_statistics_does_not_build_full_range_snapshot(
    temp_db,
    monkeypatch,
):
    project_id = project_service.create_project("Compact stats")
    _seed_closed(project_id)
    statistics_snapshot_provider.clear_statistics_snapshot_cache()

    def fail_full_snapshot(*_args, **_kwargs):
        pytest.fail("interactive Statistics must not build a full range snapshot")

    monkeypatch.setattr(
        report_projection_snapshot_service,
        "build_visible_snapshot",
        fail_full_snapshot,
    )

    summary = statistics_service.get_statistics_realtime_export_summary(
        DATE,
        DATE,
        project_id,
    )

    assert summary["total_duration_seconds"] == 1200
    assert summary["session_count"] == 1


def test_statistics_range_projection_stores_compact_collections_once(temp_db):
    project_id = project_service.create_project("Compact storage")
    _seed_closed(project_id)
    statistics_snapshot_provider.clear_statistics_snapshot_cache()

    with page_read_scope():
        projection = statistics_snapshot_provider.get_statistics_range_projection(
            DATE,
            DATE,
        )

    assert not isinstance(projection, ReportProjectionSnapshot)
    assert projection.final_entries is projection.entries
    assert projection.final_contributions is projection.contributions
    assert all(
        "_projection_contributions" not in entry
        for entry in projection.entries
    )
    for contribution in projection.contributions:
        key = str(contribution.get("projection_instance_key") or "")
        assert key
        assert any(
            indexed is contribution
            for indexed in projection.contributions_by_key[key]
        )


def test_statistics_range_cache_replaces_generation_in_same_slot(
    temp_db,
):
    project_id = project_service.create_project("Compact generation")
    _seed_closed(project_id)
    statistics_snapshot_provider.clear_statistics_snapshot_cache()

    statistics_service.get_statistics_realtime_export_summary(
        DATE,
        DATE,
        project_id,
    )
    assert statistics_snapshot_provider.statistics_range_cache_size() == 1

    project_service.create_project("Compact generation bump")
    statistics_service.get_statistics_realtime_export_summary(
        DATE,
        DATE,
        project_id,
    )

    assert statistics_snapshot_provider.statistics_range_cache_size() == 1
    assert statistics_snapshot_provider.cached_statistics_ranges() == ((DATE, DATE),)


def test_realtime_overlay_receives_only_live_fragment_not_all_history(
    temp_db,
    monkeypatch,
):
    project_id = project_service.create_project("Compact live fragment")
    day = get_default_report_date()
    for index, hour in enumerate((1, 3, 5, 7, 9, 11, 13, 15), start=1):
        create_closed_activity(
            day=day,
            start=f"{hour:02d}:00:00",
            end=f"{hour:02d}:10:00",
            window_title=f"history-{index}.docx",
            project_id=project_id,
        )

    start = f"{day} 23:00:00"
    activity_id = activity_factory.create_activity(
        "Word",
        "winword.exe",
        "live-fragment.docx",
        start_time=start,
        project_id=project_id,
        file_path_hint=r"C:\Work\live-fragment.docx",
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
            "elapsed_seconds": 600,
            "start_time": start,
            "status": "normal",
            "app_name": "Word",
            "process_name": "winword.exe",
            "resource_display_name": "live-fragment.docx",
        },
        reason="statistics_compact_fragment_test",
    )
    statistics_snapshot_provider.clear_statistics_snapshot_cache()

    original = report_as_of_snapshot_service.build_statistics_as_of_snapshot
    fragment_sizes: list[int] = []

    def captured(*args, **kwargs):
        base = kwargs.get("base_snapshot")
        fragment_sizes.append(len(base.final_entries))
        return original(*args, **kwargs)

    monkeypatch.setattr(
        report_as_of_snapshot_service,
        "build_statistics_as_of_snapshot",
        captured,
    )

    summary = statistics_service.get_statistics_realtime_export_summary(
        "",
        "",
        project_id,
    )

    assert summary["total_duration_seconds"] >= 8 * 600 + 600
    assert fragment_sizes == [1]
