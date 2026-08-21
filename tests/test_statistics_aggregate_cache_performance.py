from __future__ import annotations

import pytest

from tests.support.activity_factory import create_closed_activity
from worktrace.services import (
    project_service,
    report_projection_snapshot_service,
    statistics_projection,
    statistics_service,
    statistics_snapshot_provider,
)

pytestmark = [pytest.mark.db, pytest.mark.integration, pytest.mark.contract]
DATE = "2026-08-17"


def test_statistics_summary_builds_file_groups_in_primary_projection(temp_db, monkeypatch):
    project_id = project_service.create_project("Stats one pass")
    create_closed_activity(
        day=DATE,
        start="10:00:00",
        end="10:20:00",
        window_title="OnePass.xlsx",
        project_id=project_id,
    )
    statistics_snapshot_provider.clear_statistics_snapshot_cache()

    def duplicate_file_scan(*_args, **_kwargs):
        pytest.fail("Statistics must not run a second file-group snapshot scan")

    monkeypatch.setattr(
        statistics_service,
        "build_statistics_file_groups",
        duplicate_file_scan,
        raising=False,
    )

    summary = statistics_service.get_statistics_export_summary(DATE, DATE)

    assert len(summary["by_file"]) == 1
    assert summary["by_file"][0]["display_name"] == "OnePass.xlsx"
    assert summary["by_file"][0]["duration_seconds"] == 1200


def test_statistics_summary_cache_reuses_scope_and_invalidates_on_generation(temp_db, monkeypatch):
    first_project = project_service.create_project("Stats cache A")
    second_project = project_service.create_project("Stats cache B")
    create_closed_activity(
        day=DATE,
        start="11:00:00",
        end="11:20:00",
        window_title="Stats.xlsx",
        project_id=first_project,
    )
    statistics_snapshot_provider.clear_statistics_snapshot_cache()

    original_compute = report_projection_snapshot_service.compute_projection
    projection_calls = 0

    def counted_compute(conn, start_date, end_date):
        nonlocal projection_calls
        projection_calls += 1
        return original_compute(conn, start_date, end_date)

    original_summary = statistics_projection.build_statistics_summary_projection
    summary_calls = 0

    def counted_summary(*args, **kwargs):
        nonlocal summary_calls
        summary_calls += 1
        return original_summary(*args, **kwargs)

    monkeypatch.setattr(
        report_projection_snapshot_service,
        "compute_projection",
        counted_compute,
    )
    monkeypatch.setattr(
        statistics_projection,
        "build_statistics_summary_projection",
        counted_summary,
    )

    statistics_service.get_statistics_realtime_export_summary(DATE, DATE, first_project)
    statistics_service.get_statistics_realtime_export_summary(DATE, DATE, second_project)
    statistics_service.get_statistics_realtime_export_summary(DATE, DATE, first_project)

    assert projection_calls == 1
    assert summary_calls == 2

    project_service.create_project("Stats cache generation bump")
    statistics_service.get_statistics_realtime_export_summary(DATE, DATE, first_project)

    assert projection_calls == 2
    assert summary_calls == 3
