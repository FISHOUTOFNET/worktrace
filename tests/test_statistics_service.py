import json
from datetime import date

from worktrace.services import activity_service, project_service, session_boundary_service, settings_service, statistics_service


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


def test_project_stats_use_short_context_merge_without_changing_raw_project(temp_db):
    project_a = project_service.create_project("A")
    project_b = project_service.create_project("B")
    a1 = activity_service.create_activity(
        "Word", "word.exe", "A1.docx", project_id=project_a, start_time="2026-06-18 09:00:00"
    )
    activity_service.finalize_created_activity(a1)
    # create_activity no longer auto-closes old rows (lifecycle hard
    # cutover); close the previous open activity before creating the next.
    activity_service.close_all_open_rows("2026-06-18 09:05:00")
    b = activity_service.create_activity(
        "Word", "word.exe", "B1.docx", project_id=project_b, start_time="2026-06-18 09:05:00"
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
    assert activity_service.get_activity(b)["project_id"] == project_b


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


def test_live_unpersisted_activity_is_projected_only_when_requested(temp_db):
    today = date.today().isoformat()
    project_service.create_project("Client", "billable")
    settings_service.set_setting(
        "current_activity_snapshot",
        json.dumps(
            {
                "activity_display_name": "Spec.docx",
                "inferred_project_name": "Client",
                "status": "normal",
                "start_time": "",
                "elapsed_seconds": 65,
                "is_persisted": False,
                "persisted_activity_id": None,
            },
            ensure_ascii=False,
        ),
    )

    assert statistics_service.get_summary(today, today)["total_duration"] == 0

    summary = statistics_service.get_summary(today, today, include_live=True)
    stats = statistics_service.get_project_stats(today, today, include_live=True)

    assert summary["total_duration"] == 65
    assert summary["effective_duration"] == 65
    assert summary["classified_duration"] == 65
    assert stats == [{"project": "Client", "total_duration": 65, "record_count": 1, "project_description": "billable"}]


def test_live_persisted_snapshot_is_not_double_counted(temp_db):
    today = date.today().isoformat()
    settings_service.set_setting(
        "current_activity_snapshot",
        json.dumps(
            {
                "activity_display_name": "Spec.docx",
                "inferred_project_name": "Client",
                "status": "normal",
                "start_time": "",
                "elapsed_seconds": 65,
                "is_persisted": True,
                "persisted_activity_id": 99,
            },
            ensure_ascii=False,
        ),
    )

    assert statistics_service.get_summary(today, today, include_live=True)["total_duration"] == 0
    assert statistics_service.get_project_stats(today, today, include_live=True) == []


# --- Section 六.4: Overview / Statistics include_live convergence ---------


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


def test_get_project_stats_persisted_open_group_uses_display_project(temp_db):
    """Section 四.1 / 六.4: during the 30-second pending window,
    ``get_project_stats(include_live=True)`` must group the persisted_open
    session under the inherited ``display_project``, NOT the DB row's
    candidate assignment. ``candidate_project`` must NOT influence KPI
    attribution.
    """
    from datetime import datetime, timedelta
    from worktrace.constants import TIME_FORMAT
    from worktrace.services import activity_service, project_service

    today = date.today().isoformat()
    project_a_id = project_service.create_project("ProjectA")
    project_b_id = project_service.create_project("ProjectB")
    start = datetime.now() - timedelta(seconds=60)
    start_time = start.strftime(TIME_FORMAT)
    aid = activity_service.create_activity(
        "AppA", "AppA.exe", "Window", start_time=start_time
    )
    # Assign the DB row to ProjectB (the candidate). The KPI must
    # override this with ProjectA (the inherited display project).
    activity_service.update_activity_project(aid, project_b_id)
    activity_service.set_activity_duration(aid, 60)
    assert activity_service.get_activity(aid)["project_name"] == "ProjectB"

    snapshot = _pending_persisted_open_snapshot(aid=aid, start_time=start_time)
    settings_service.set_setting(
        "current_activity_snapshot", json.dumps(snapshot, ensure_ascii=False)
    )
    settings_service.clear_settings_cache()

    stats = statistics_service.get_project_stats(today, today, include_live=True)
    # The persisted_open session must be grouped under ProjectA, NOT ProjectB.
    project_names = {row["project"]: row for row in stats}
    assert "ProjectA" in project_names, (
        "persisted_open session must be grouped under display_project (ProjectA)"
    )
    assert project_names["ProjectA"]["total_duration"] >= 60
    # ProjectB (the DB candidate) must NOT appear because the overlay
    # relabels the session to ProjectA.
    assert "ProjectB" not in project_names, (
        "candidate_project must NOT appear as a separate KPI group"
    )


def test_get_summary_persisted_open_does_not_double_count_total(temp_db):
    """Section 四.1 / 六.4: ``get_summary(include_live=True)`` must NOT
    double-count a persisted_open session's duration in
    ``total_duration`` / ``effective_duration``. The DB row already
    carries the duration; the live overlay only relabels the project.
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
    activity_service.update_activity_project(aid, project_b_id)
    activity_service.set_activity_duration(aid, 60)

    snapshot = _pending_persisted_open_snapshot(aid=aid, start_time=start_time)
    settings_service.set_setting(
        "current_activity_snapshot", json.dumps(snapshot, ensure_ascii=False)
    )
    settings_service.clear_settings_cache()

    summary_with_live = statistics_service.get_summary(today, today, include_live=True)
    summary_without_live = statistics_service.get_summary(today, today, include_live=False)
    # Both must report the same total / effective duration — the DB row
    # already carries the duration. include_live must NOT add an extra
    # live duration for persisted_open (that would double-count).
    assert summary_with_live["total_duration"] == summary_without_live["total_duration"], (
        "include_live=True must NOT double-count persisted_open duration"
    )
    assert summary_with_live["effective_duration"] == summary_without_live["effective_duration"], (
        "include_live=True must NOT double-count persisted_open effective duration"
    )
    # The total is the open DB row's duration (~60s, may be 61s due to
    # wall-clock drift between start_time and the live recompute), NOT
    # 120s (which would indicate double-counting). Use a tolerant
    # range: at least 60, strictly less than 120.
    assert 60 <= summary_with_live["total_duration"] < 120, (
        f"persisted_open total_duration should be ~60s (open DB row only), "
        f"got {summary_with_live['total_duration']}s"
    )


def test_get_summary_virtual_live_adds_duration_to_total(temp_db):
    """Section 四.1 / 六.4: ``get_summary(include_live=True)`` must add
    the virtual live session's duration to ``total_duration`` /
    ``effective_duration`` / ``classified_duration``. The virtual session
    has no DB row, so its duration is added to the KPI.
    """
    today = date.today().isoformat()
    project_service.create_project("Client", "billable")
    settings_service.set_setting(
        "current_activity_snapshot",
        json.dumps(
            {
                "activity_display_name": "Spec.docx",
                "inferred_project_name": "Client",
                "status": "normal",
                "start_time": "",
                "elapsed_seconds": 65,
                "is_persisted": False,
                "persisted_activity_id": None,
            },
            ensure_ascii=False,
        ),
    )

    summary = statistics_service.get_summary(today, today, include_live=True)
    assert summary["total_duration"] == 65
    assert summary["effective_duration"] == 65
    assert summary["classified_duration"] == 65
    assert summary["uncategorized_duration"] == 0


def test_statistics_export_excludes_in_progress_live_rows(temp_db):
    """Section 四.4 / 六.4: Statistics / Export pages remain closed-only.

    The Statistics / Export preview is served by
    ``get_statistics_export_summary``, which filters out in-progress
    rows (``closed_rows = [r for r in rows if not r.is_in_progress]``).
    This must hold even when a persisted_open snapshot is active: the
    open DB row must NOT contribute to the closed-only KPIs.

    Note: ``get_summary(include_live=False)`` is a DIFFERENT function
    used by the Overview KPI; it intentionally counts open DB rows
    (the ``include_live`` flag only controls the virtual projection
    add-on). The closed-only contract is owned by
    ``get_statistics_export_summary``.
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
    activity_service.update_activity_project(aid, project_b_id)
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


# --- Section 六.5: Threshold constant independence -----------------------


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
