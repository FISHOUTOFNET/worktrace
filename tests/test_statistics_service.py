from worktrace.services import activity_service, project_service, session_boundary_service, statistics_service


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
    b = activity_service.create_activity(
        "Word", "word.exe", "B1.docx", project_id=project_b, start_time="2026-06-18 09:05:00"
    )
    activity_service.finalize_created_activity(b)
    a2 = activity_service.create_activity(
        "Word", "word.exe", "A2.docx", project_id=project_a, start_time="2026-06-18 09:09:00"
    )
    activity_service.finalize_created_activity(a2)
    activity_service.close_current_open_record("2026-06-18 09:15:00")

    stats = statistics_service.get_project_stats("2026-06-18", "2026-06-18")

    assert stats == [{"project": "A", "total_duration": 900, "record_count": 1}]
    assert activity_service.get_activity(b)["project_id"] == project_b


def test_statistics_use_report_date_for_cross_midnight_projects_and_split_idle(temp_db):
    project_a = project_service.create_project("A")
    project_b = project_service.create_project("B")
    a1 = activity_service.create_activity(
        "Word", "word.exe", "A1.docx", project_id=project_a, start_time="2026-06-18 23:50:00"
    )
    activity_service.finalize_created_activity(a1)
    a2 = activity_service.create_activity(
        "Word", "word.exe", "A2.docx", project_id=project_a, start_time="2026-06-19 00:10:00"
    )
    activity_service.finalize_created_activity(a2)
    b = activity_service.create_activity(
        "Word", "word.exe", "B1.docx", project_id=project_b, start_time="2026-06-19 00:30:00"
    )
    activity_service.finalize_created_activity(b)
    idle = activity_service.create_activity(
        "空闲", "idle", "用户空闲", status="idle", start_time="2026-06-19 00:45:00"
    )
    activity_service.finalize_created_activity(idle)
    activity_service.close_current_open_record("2026-06-19 01:15:00")

    previous = statistics_service.get_summary("2026-06-18", "2026-06-18")
    current = statistics_service.get_summary("2026-06-19", "2026-06-19")

    assert previous["total_duration"] == 40 * 60
    assert previous["classified_duration"] == 40 * 60
    assert statistics_service.get_project_stats("2026-06-18", "2026-06-18") == [
        {"project": "A", "total_duration": 40 * 60, "record_count": 1}
    ]
    assert current["total_duration"] == 45 * 60
    assert current["effective_duration"] == 15 * 60
    assert current["idle_duration"] == 30 * 60


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
