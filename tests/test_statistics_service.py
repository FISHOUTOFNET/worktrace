from worktrace.services import activity_service, project_service, statistics_service


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

    assert stats == [{"project": "A", "total_duration": 900, "record_count": 3}]
    assert activity_service.get_activity(b)["project_id"] == project_b
