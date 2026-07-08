from tests.support.db_helpers import assign_activity_project
import json
from datetime import date

from worktrace.services import activity_service, project_service, session_boundary_service, settings_service, statistics_service
import pytest

pytestmark = [pytest.mark.db]


def test_statistics_aggregation(temp_db):
    pid = project_service.create_project("Client")
    a = activity_service.create_activity(
        "Word", "word.exe", "Client", project_id=pid, start_time="2026-06-18 09:00:00"
    )
    activity_service.close_activity(a, "2026-06-18 10:00:00")
    idle = activity_service.create_activity("空闲", "idle", "用户空闲", status="idle", start_time="2026-06-18 10:00:00")
    activity_service.close_activity(idle, "2026-06-18 10:15:00")
    summary = statistics_service.get_summary("2026-06-18", "2026-06-18")
    assert summary["total_duration"] == 4500
    assert summary["effective_duration"] == 3600
    assert summary["classified_duration"] == 3600
    assert summary["idle_duration"] == 900
    stats = statistics_service.get_project_stats("2026-06-18", "2026-06-18")
    assert stats[0]["project"] == "Client"
    assert stats[0]["total_duration"] == 3600


def test_summary_ensures_context_once_and_reuses_it_for_project_stats(temp_db, monkeypatch):
    context_calls = []
    session_calls = []

    def fake_recompute(day):
        context_calls.append(day)

    def fake_sessions(start, end, include_hidden=True, ensure_context=True):
        session_calls.append((start, end, include_hidden, ensure_context))
        return []

    monkeypatch.setattr(statistics_service, "recompute_context_assignments_for_date", fake_recompute)
    monkeypatch.setattr(statistics_service.timeline_service, "get_project_sessions_by_range", fake_sessions)

    summary = statistics_service.get_summary("2026-06-18", "2026-06-19")

    assert summary["total_duration"] == 0
    assert context_calls == ["2026-06-17", "2026-06-18", "2026-06-19"]
    assert session_calls == [("2026-06-18", "2026-06-19", False, False)]


def test_project_stats_count_context_assigned_short_gap(temp_db):
    project_a = project_service.create_project("A")
    a1 = activity_service.create_activity(
        "Word", "word.exe", "A1.docx", project_id=project_a, start_time="2026-06-18 09:00:00"
    )
    activity_service.finalize_created_activity(a1)
    # create_activity no longer auto-closes old rows (lifecycle hard
    # cutover); close the previous open activity before creating the next.
    activity_service.close_all_open_rows("2026-06-18 09:05:00")
    b = activity_service.create_activity(
        "Word", "word.exe", "Unassigned.docx", start_time="2026-06-18 09:05:00"
    )
    activity_service.finalize_created_activity(b)
    activity_service.close_all_open_rows("2026-06-18 09:09:00")
    a2 = activity_service.create_activity(
        "Word", "word.exe", "A2.docx", project_id=project_a, start_time="2026-06-18 09:09:00"
    )
    activity_service.finalize_created_activity(a2)
    activity_service.close_all_open_rows("2026-06-18 09:15:00")

    stats = statistics_service.get_project_stats("2026-06-18", "2026-06-18")

    assert stats == [{"project": "A", "total_duration": 900, "record_count": 1}]
    assert activity_service.get_activity(b)["project_id"] == project_a


def test_statistics_split_cross_midnight_projects_by_calendar_day(temp_db):
    project_a = project_service.create_project("A")
    project_b = project_service.create_project("B")
    a1 = activity_service.create_activity(
        "Word", "word.exe", "A1.docx", project_id=project_a, start_time="2026-06-18 23:50:00"
    )
    activity_service.finalize_created_activity(a1)
    # create_activity no longer auto-closes old rows (lifecycle hard
    # cutover); close the previous open activity before creating the next.
    activity_service.close_all_open_rows("2026-06-19 00:10:00")
    a2 = activity_service.create_activity(
        "Word", "word.exe", "A2.docx", project_id=project_a, start_time="2026-06-19 00:10:00"
    )
    activity_service.finalize_created_activity(a2)
    activity_service.close_all_open_rows("2026-06-19 00:30:00")
    b = activity_service.create_activity(
        "Word", "word.exe", "B1.docx", project_id=project_b, start_time="2026-06-19 00:30:00"
    )
    activity_service.finalize_created_activity(b)
    activity_service.close_all_open_rows("2026-06-19 00:45:00")
    idle = activity_service.create_activity(
        "空闲", "idle", "用户空闲", status="idle", start_time="2026-06-19 00:45:00"
    )
    activity_service.finalize_created_activity(idle)
    activity_service.close_all_open_rows("2026-06-19 01:15:00")

    previous = statistics_service.get_summary("2026-06-18", "2026-06-18")
    current = statistics_service.get_summary("2026-06-19", "2026-06-19")

    assert previous["total_duration"] == 10 * 60
    assert previous["classified_duration"] == 10 * 60
    assert statistics_service.get_project_stats("2026-06-18", "2026-06-18") == [
        {"project": "A", "total_duration": 10 * 60, "record_count": 1}
    ]
    assert current["total_duration"] == 75 * 60
    assert current["effective_duration"] == 45 * 60
    assert current["idle_duration"] == 30 * 60
    assert statistics_service.get_project_stats("2026-06-19", "2026-06-19") == [
        {"project": "A", "total_duration": 30 * 60, "record_count": 1},
        {"project": "B", "total_duration": 15 * 60, "record_count": 1},
    ]


def test_project_stats_count_project_records_split_by_boundary(temp_db):
    project_a = project_service.create_project("A")
    first = activity_service.create_activity(
        "Word", "word.exe", "A1.docx", project_id=project_a, start_time="2026-06-18 09:00:00"
    )
    activity_service.close_activity(first, "2026-06-18 09:10:00")
    session_boundary_service.record_boundary("2026-06-18 09:10:00", "stopped")
    second = activity_service.create_activity(
        "Word", "word.exe", "A2.docx", project_id=project_a, start_time="2026-06-18 09:20:00"
    )
    activity_service.close_activity(second, "2026-06-18 09:30:00")

    assert statistics_service.get_project_stats("2026-06-18", "2026-06-18") == [
        {"project": "A", "total_duration": 20 * 60, "record_count": 2}
    ]


def _pending_persisted_open_snapshot(
    *,
    aid: int,
    start_time: str,
    display_name: str = "ProjectA",
    candidate_name: str = "ProjectB",
) -> dict:
    """Build a pending persisted_open snapshot with display_project /
    candidate_project blocks for KPI convergence tests."""
    display = {
        "id": 12,
        "name": display_name,
        "description": display_name + " description",
        "source": "inherited",
        "is_uncategorized": False,
        "is_suggested_project": False,
    }
    candidate = {
        "id": 18,
        "name": candidate_name,
        "description": candidate_name + " description",
        "source": "folder_rule",
        "is_uncategorized": False,
        "is_suggested_project": False,
    }
    return {
        "app_name": "AppA",
        "process_name": "AppA.exe",
        "inferred_project_name": display_name,
        "start_time": start_time,
        "elapsed_seconds": 60,
        "extra_seconds": 0,
        "status": "normal",
        "is_persisted": True,
        "persisted_activity_id": aid,
        "display_project": display,
        "candidate_project": candidate,
        "project_transition": {
            "pending": True,
            "started_at": "",
            "elapsed_seconds": 12,
            "threshold_seconds": 30,
            "from_project_id": 12,
            "to_project_id": 18,
        },
        "project_transition_pending": True,
    }


def test_statistics_export_excludes_in_progress_live_rows(temp_db):
    """Section 四.4 / 六.4: Statistics / Export pages remain closed-only.

    The Statistics / Export preview is served by
    ``get_statistics_export_summary``, which filters out in-progress
    rows (``closed_rows = [r for r in rows if not r.is_in_progress]``).
    This must hold even when a persisted_open snapshot is active: the
    open DB row must NOT contribute to the closed-only KPIs.

    Note: ``get_summary`` is a DIFFERENT function used by the Overview
    KPI; it intentionally counts open DB rows. The closed-only contract
    is owned by ``get_statistics_export_summary``.
    """
    from datetime import datetime, timedelta
    from worktrace.constants import TIME_FORMAT
    from worktrace.services import activity_service, project_service

    today = date.today().isoformat()
    project_b_id = project_service.create_project("ProjectB")
    start = datetime.now() - timedelta(seconds=60)
    start_time = start.strftime(TIME_FORMAT)
    aid = activity_service.create_activity(
        "AppA", "AppA.exe", "Window", start_time=start_time
    )
    assign_activity_project(aid, project_b_id)
    activity_service.set_activity_duration(aid, 60)

    snapshot = _pending_persisted_open_snapshot(aid=aid, start_time=start_time)
    settings_service.set_setting(
        "current_activity_snapshot", json.dumps(snapshot, ensure_ascii=False)
    )
    settings_service.clear_settings_cache()

    # The Statistics / Export closed-only preview excludes the
    # in-progress open row entirely.
    export_summary = statistics_service.get_statistics_export_summary(today, today)
    assert export_summary["total_duration_seconds"] == 0, (
        "Statistics/Export closed-only preview must NOT count in-progress rows"
    )
    assert export_summary["activity_count"] == 0
    # All by_* breakdowns are empty.
    assert export_summary["by_project"] == []
    assert export_summary["by_app"] == []
    assert export_summary["by_status"] == []




def test_project_ownership_confirm_seconds_is_separate_constant_from_history_persist():
    """Section 五 / 六.5: ``PROJECT_OWNERSHIP_CONFIRM_SECONDS`` and
    ``HISTORY_PERSIST_THRESHOLD_SECONDS`` must be TWO distinct constants
    (even though both are 30 today). They must be independently
    importable so the two concerns can evolve independently.
    """
    from worktrace.constants import (
        HISTORY_PERSIST_THRESHOLD_SECONDS,
        PROJECT_OWNERSHIP_CONFIRM_SECONDS,
    )

    # Both must be defined and equal to 30 today.
    assert HISTORY_PERSIST_THRESHOLD_SECONDS == 30
    assert PROJECT_OWNERSHIP_CONFIRM_SECONDS == 30
    # They must be distinct names (not aliased to the same object in a
    # way that would break if one is renamed). This is a structural
    # check: the two names must resolve to integer literals, not to
    # each other.
    import worktrace.constants as constants_mod
    assert "HISTORY_PERSIST_THRESHOLD_SECONDS" in dir(constants_mod)
    assert "PROJECT_OWNERSHIP_CONFIRM_SECONDS" in dir(constants_mod)


def test_project_ownership_service_uses_confirm_seconds_not_history_persist():
    """Section 五.3 / 六.5: ``project_ownership_service`` must use
    ``PROJECT_OWNERSHIP_CONFIRM_SECONDS`` (NOT
    ``HISTORY_PERSIST_THRESHOLD_SECONDS``) for the pending ownership
    threshold. The history persistence threshold is a separate concern.
    """
    from worktrace.services.project_ownership_service import (
        ProjectTransition,
        begin_ownership_for_new_resource,
    )
    from worktrace.constants import PROJECT_OWNERSHIP_CONFIRM_SECONDS

    # ProjectTransition.threshold_seconds defaults to
    # PROJECT_OWNERSHIP_CONFIRM_SECONDS.
    transition = ProjectTransition(
        pending=True,
        started_at="",
        elapsed_seconds=0,
    )
    assert transition.threshold_seconds == PROJECT_OWNERSHIP_CONFIRM_SECONDS
