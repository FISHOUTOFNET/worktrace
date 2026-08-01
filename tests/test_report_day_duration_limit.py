from __future__ import annotations

import pytest

from tests.support.activity_factory import create_closed_activity
from worktrace.data_generation_repository import DataGenerationNamespace, DataGenerationRepository
from worktrace.db import get_connection
from worktrace.services import project_service, report_session_operation_service as mutations
from worktrace.services.report_projection_model import DayDurationExceedsLimitError
from worktrace.services.report_projection_snapshot_service import build_visible_snapshot
from worktrace.services.reported_duration_policy import (
    reported_day_total_seconds,
    reported_entry_duration_seconds,
)


pytestmark = [pytest.mark.db, pytest.mark.integration, pytest.mark.contract]
DATE = "2026-07-20"


def test_reported_duration_prefers_explicit_field_and_honors_total_membership():
    assert reported_entry_duration_seconds(
        {"report_duration_seconds": 720, "duration_seconds": 360}
    ) == 720
    assert reported_entry_duration_seconds(
        {
            "report_duration_seconds": 720,
            "duration_seconds": 360,
            "contributes_to_totals": False,
        }
    ) == 0


def _activity(start: str, end: str, project_id: int, name: str) -> int:
    return create_closed_activity(
        day=DATE,
        start=start,
        end=end,
        app_name=name,
        process_name=name.lower() + ".exe",
        window_title=name,
        project_id=project_id,
    )


def _sessions():
    return list(build_visible_snapshot(DATE, DATE).final_sessions)


def _counts_and_generation():
    with get_connection() as conn:
        return (
            conn.execute("SELECT COUNT(*) FROM report_session_operation").fetchone()[0],
            conn.execute("SELECT COUNT(*) FROM report_session_operation_member").fetchone()[0],
            conn.execute("SELECT COUNT(*) FROM report_mutation_request").fetchone()[0],
            DataGenerationRepository.get(conn, DataGenerationNamespace.REPORT_STRUCTURE),
        )


def test_exactly_24_hours_allowed_but_24_point_1_rejected_without_writes(
    temp_db,
    monkeypatch,
):
    first_project = project_service.create_project("Limit A")
    second_project = project_service.create_project("Limit B")
    _activity("00:00:00", "01:00:00", first_project, "A")
    _activity("02:00:00", "03:00:00", second_project, "B")
    source = next(row for row in _sessions() if row["project_id"] == first_project)

    committed = mutations.edit_session(
        DATE, source["projection_instance_key"], source["projection_revision"],
        "limit-exact", project_id=None, adjusted_duration_seconds=82_800, note="",
    )
    assert committed.outcome_type == "operation_committed"
    exact = build_visible_snapshot(DATE, DATE)
    assert reported_day_total_seconds(
        exact.final_sessions, exact.standalone_status_entries
    ) == 86_400

    updated = next(row for row in exact.final_sessions if row["project_id"] == first_project)
    before = _counts_and_generation()
    from worktrace.services import report_projection_snapshot_service

    original_build = report_projection_snapshot_service.build_visible_snapshot
    build_calls = []

    def counted_build(*args, **kwargs):
        build_calls.append((args, kwargs))
        return original_build(*args, **kwargs)

    monkeypatch.setattr(
        report_projection_snapshot_service,
        "build_visible_snapshot",
        counted_build,
    )
    with pytest.raises(DayDurationExceedsLimitError):
        mutations.edit_session(
            DATE, updated["projection_instance_key"], updated["projection_revision"],
            "limit-over", project_id=None, adjusted_duration_seconds=83_160, note="",
        )
    assert _counts_and_generation() == before
    assert len(build_calls) == 1, "rejected preview must not build an after snapshot"


def test_clear_override_and_copy_are_rejected_when_preview_exceeds_day_limit(temp_db):
    first_project = project_service.create_project("Clear A")
    second_project = project_service.create_project("Clear B")
    _activity("00:00:00", "23:30:00", first_project, "Long")
    _activity("01:00:00", "02:00:00", second_project, "Overlap")
    source = next(row for row in _sessions() if row["project_id"] == first_project)
    mutations.edit_session(
        DATE, source["projection_instance_key"], source["projection_revision"],
        "clear-setup", project_id=None, adjusted_duration_seconds=82_800, note="",
    )
    overridden = next(row for row in _sessions() if row["project_id"] == first_project)
    before_clear = _counts_and_generation()
    with pytest.raises(DayDurationExceedsLimitError):
        mutations.edit_session(
            DATE, overridden["projection_instance_key"], overridden["projection_revision"],
            "clear-over", project_id=None, adjusted_duration_seconds=None, note="",
        )
    assert _counts_and_generation() == before_clear

    other_date_project = project_service.create_project("Copy")
    copy_id = create_closed_activity(
        day="2026-07-21", start="00:00:00", end="13:00:00",
        app_name="Copy", process_name="copy.exe", window_title="Copy",
        project_id=other_date_project,
    )
    del copy_id
    copy_source = build_visible_snapshot("2026-07-21", "2026-07-21").final_sessions[0]
    before_copy = _counts_and_generation()
    with pytest.raises(DayDurationExceedsLimitError):
        mutations.copy_session(
            "2026-07-21", copy_source["projection_instance_key"],
            copy_source["projection_revision"], "copy-over",
        )
    assert _counts_and_generation() == before_copy


def test_note_and_hide_remain_available_for_historical_over_limit_day(temp_db):
    first_project = project_service.create_project("Historical A")
    second_project = project_service.create_project("Historical B")
    _activity("00:00:00", "13:00:00", first_project, "First")
    _activity("01:00:00", "14:00:00", second_project, "Second")
    source = next(row for row in _sessions() if row["project_id"] == first_project)

    result = mutations.edit_session(
        DATE, source["projection_instance_key"], source["projection_revision"],
        "historical-note", project_id=None, adjusted_duration_seconds=None, note="repair",
    )
    assert result.outcome_type == "operation_committed"
    refreshed = next(row for row in _sessions() if row["project_id"] == first_project)
    hidden = mutations.hide_session(
        DATE, refreshed["projection_instance_key"], refreshed["projection_revision"],
        "historical-hide",
    )
    assert hidden.outcome_type == "operation_committed"


def test_standalone_status_is_counted_once_in_preview_limit(temp_db):
    project_id = project_service.create_project("Standalone total")
    create_closed_activity(
        day=DATE, start="00:00:00", end="01:00:00",
        app_name="Excluded", process_name="excluded.exe", window_title="Excluded",
        status="excluded",
    )
    _activity("02:00:00", "03:00:00", project_id, "Project")
    snapshot = build_visible_snapshot(DATE, DATE)
    assert len(snapshot.standalone_status_entries) == 1
    source = snapshot.final_sessions[0]

    with pytest.raises(DayDurationExceedsLimitError):
        mutations.edit_session(
            DATE, source["projection_instance_key"], source["projection_revision"],
            "standalone-over", project_id=None,
            adjusted_duration_seconds=83_160, note="",
        )
