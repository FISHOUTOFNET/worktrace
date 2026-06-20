from worktrace.constants import UNCATEGORIZED_PROJECT
from worktrace.db import get_connection
from worktrace.services import activity_service, project_service, settings_service, timeline_service


def _activity(app, process, title, start, project_id=None, status="normal"):
    aid = activity_service.create_activity(
        app,
        process,
        title,
        start_time=f"2026-06-18 {start}",
        project_id=project_id,
        status=status,
    )
    activity_service.finalize_created_activity(aid)
    return aid


def _activity_at(app, process, title, start_time, project_id=None, status="normal"):
    aid = activity_service.create_activity(
        app,
        process,
        title,
        start_time=start_time,
        project_id=project_id,
        status=status,
    )
    activity_service.finalize_created_activity(aid)
    return aid


def test_sessions_merge_same_project_and_split_a_b_a(temp_db):
    project_a = project_service.create_project("A")
    project_b = project_service.create_project("B")
    _activity("Word", "winword.exe", "A1.docx", "09:00:00", project_a)
    _activity("Word", "winword.exe", "B1.docx", "09:30:00", project_b)
    _activity("Word", "winword.exe", "A2.docx", "10:00:00", project_a)
    _activity("Word", "winword.exe", "A3.docx", "10:05:00", project_a)
    activity_service.close_current_open_record("2026-06-18 10:10:00")

    sessions = timeline_service.get_project_sessions_by_date("2026-06-18")
    latest_details = timeline_service.get_session_activity_details(sessions[0]["activity_ids"])

    assert [session["project_name"] for session in sessions] == ["A", "B", "A"]
    assert [session["start_time"][11:16] for session in sessions] == ["10:00", "09:30", "09:00"]
    assert sessions[0]["event_count"] == 2
    assert [row["start_time"][11:16] for row in latest_details] == ["10:05", "10:00"]


def test_same_project_after_midnight_reports_on_previous_day_until_next_project(temp_db):
    project_a = project_service.create_project("A")
    project_b = project_service.create_project("B")
    _activity_at("Word", "winword.exe", "A1.docx", "2026-06-18 23:50:00", project_a)
    _activity_at("Word", "winword.exe", "A2.docx", "2026-06-19 00:10:00", project_a)
    _activity_at("Word", "winword.exe", "B1.docx", "2026-06-19 00:30:00", project_b)
    activity_service.close_current_open_record("2026-06-19 00:45:00")

    previous_day = timeline_service.get_project_sessions_by_date("2026-06-18")
    next_day = timeline_service.get_project_sessions_by_date("2026-06-19")

    assert [session["project_name"] for session in previous_day] == ["A"]
    assert previous_day[0]["duration_seconds"] == 40 * 60
    assert previous_day[0]["report_date"] == "2026-06-18"
    assert [session["project_name"] for session in next_day] == ["B"]
    assert next_day[0]["duration_seconds"] == 15 * 60


def test_same_project_next_day_does_not_carry_when_previous_activity_ended_before_midnight(temp_db):
    project_a = project_service.create_project("A")
    first = _activity_at("Word", "winword.exe", "A1.docx", "2026-06-18 23:40:00", project_a)
    activity_service.close_activity(first, "2026-06-18 23:50:00")
    _activity_at("Word", "winword.exe", "A2.docx", "2026-06-19 08:00:00", project_a)
    activity_service.close_current_open_record("2026-06-19 08:30:00")

    previous_day = timeline_service.get_project_sessions_by_date("2026-06-18")
    next_day = timeline_service.get_project_sessions_by_date("2026-06-19")

    assert previous_day[0]["duration_seconds"] == 10 * 60
    assert next_day[0]["duration_seconds"] == 30 * 60
    assert next_day[0]["report_date"] == "2026-06-19"


def test_idle_and_uncategorized_split_at_midnight(temp_db):
    _activity_at("空闲", "idle", "用户空闲", "2026-06-18 23:50:00", status="idle")
    activity_service.close_current_open_record("2026-06-19 00:10:00")
    _activity_at("Edge", "msedge.exe", "Search", "2026-06-19 00:10:00")
    activity_service.close_current_open_record("2026-06-19 00:30:00")

    previous_day = timeline_service.get_project_sessions_by_date("2026-06-18")
    next_day = timeline_service.get_project_sessions_by_date("2026-06-19")

    assert previous_day[0]["status"] == "idle"
    assert previous_day[0]["duration_seconds"] == 10 * 60
    assert [session["duration_seconds"] for session in next_day] == [20 * 60, 10 * 60]
    assert [session["project_name"] for session in next_day] == [UNCATEGORIZED_PROJECT, UNCATEGORIZED_PROJECT]


def test_open_activity_duration_uses_current_snapshot_projection(temp_db):
    project = project_service.create_project("A")
    activity_id = _activity_at("Word", "winword.exe", "A.docx", "2026-06-18 09:00:00", project)
    settings_service.set_setting(
        "current_activity_snapshot",
        (
            '{"status":"normal","app_name":"Word","process_name":"winword.exe",'
            '"window_title":"A.docx","start_time":"2026-06-18 09:00:00",'
            f'"elapsed_seconds":90,"extra_seconds":5,"persisted_activity_id":{activity_id},'
            '"is_persisted":true}'
        ),
    )

    sessions = timeline_service.get_project_sessions_by_date("2026-06-18")

    assert sessions[0]["duration_seconds"] == 95


def test_auxiliary_between_same_project_anchors_merges_into_session(temp_db):
    project = project_service.create_project("A")
    _activity("Word", "winword.exe", "A1.docx", "09:00:00", project)
    _activity("Edge", "msedge.exe", "Search 1", "09:10:00")
    _activity("Chrome", "chrome.exe", "Search 2", "09:15:00")
    _activity("Word", "winword.exe", "A2.docx", "09:20:00", project)
    activity_service.close_current_open_record("2026-06-18 09:30:00")

    sessions = timeline_service.get_project_sessions_by_date("2026-06-18")
    summary = timeline_service.get_session_resource_summary(sessions[0]["activity_ids"])
    app_rows = [row for row in summary if row["resource_type"] == "app"]

    assert len(sessions) == 1
    assert sessions[0]["project_name"] == "A"
    assert {row["display_name"] for row in app_rows} == {"Edge", "Chrome"}
    assert all(row["event_count"] == 1 for row in app_rows)


def test_short_other_project_between_same_project_anchors_reports_inside_anchor_session(temp_db):
    project_a = project_service.create_project("A")
    project_b = project_service.create_project("B")
    _activity("Word", "winword.exe", "A1.docx", "09:00:00", project_a)
    b_activity = _activity("Word", "winword.exe", "B1.docx", "09:05:00", project_b)
    _activity("Word", "winword.exe", "A2.docx", "09:09:00", project_a)
    activity_service.close_current_open_record("2026-06-18 09:15:00")

    sessions = timeline_service.get_project_sessions_by_date("2026-06-18")
    details = timeline_service.get_session_activity_details(sessions[0]["activity_ids"])

    assert len(sessions) == 1
    assert sessions[0]["project_name"] == "A"
    assert sessions[0]["duration_seconds"] == 900
    assert sessions[0]["event_count"] == 3
    assert [row["project_name"] for row in details] == ["A", "B", "A"]
    assert activity_service.get_activity(b_activity)["project_id"] == project_b


def test_short_idle_between_same_project_anchors_reports_inside_anchor_session(temp_db):
    project_a = project_service.create_project("A")
    _activity("Word", "winword.exe", "A1.docx", "09:00:00", project_a)
    idle_activity = _activity("空闲", "idle", "用户空闲", "09:05:00", status="idle")
    _activity("Word", "winword.exe", "A2.docx", "09:08:00", project_a)
    activity_service.close_current_open_record("2026-06-18 09:12:00")

    sessions = timeline_service.get_project_sessions_by_date("2026-06-18")
    details = timeline_service.get_session_activity_details(sessions[0]["activity_ids"])
    idle_detail = next(row for row in details if row["id"] == idle_activity)

    assert len(sessions) == 1
    assert sessions[0]["project_name"] == "A"
    assert sessions[0]["status"] == "mixed"
    assert sessions[0]["duration_seconds"] == 720
    assert idle_detail["status"] == "idle"
    assert idle_detail["project_name"] == UNCATEGORIZED_PROJECT


def test_five_minute_other_project_between_anchors_does_not_merge(temp_db):
    project_a = project_service.create_project("A")
    project_b = project_service.create_project("B")
    _activity("Word", "winword.exe", "A1.docx", "09:00:00", project_a)
    _activity("Word", "winword.exe", "B1.docx", "09:05:00", project_b)
    _activity("Word", "winword.exe", "A2.docx", "09:10:00", project_a)
    activity_service.close_current_open_record("2026-06-18 09:12:00")

    sessions = timeline_service.get_project_sessions_by_date("2026-06-18")

    assert [session["project_name"] for session in sessions] == ["A", "B", "A"]


def test_short_other_project_does_not_merge_when_anchor_gap_exceeds_context_window(temp_db):
    project_a = project_service.create_project("A")
    project_b = project_service.create_project("B")
    first_anchor = _activity("Word", "winword.exe", "A1.docx", "09:00:00", project_a)
    activity_service.close_activity(first_anchor, "2026-06-18 09:00:30")
    _activity("Word", "winword.exe", "B1.docx", "09:20:00", project_b)
    _activity("Word", "winword.exe", "A2.docx", "09:24:00", project_a)
    activity_service.close_current_open_record("2026-06-18 09:30:00")

    sessions = timeline_service.get_project_sessions_by_date("2026-06-18")

    assert [session["project_name"] for session in sessions] == ["A", "B", "A"]


def test_resource_level_correction_and_remember_rules(temp_db):
    project_a = project_service.create_project("A")
    project_b = project_service.create_project("B")
    _activity("Word", "winword.exe", "Contract.docx", "09:00:00", project_a)
    _activity("Word", "winword.exe", "Contract.docx", "09:10:00", project_a)
    activity_service.close_current_open_record("2026-06-18 09:20:00")

    session = timeline_service.get_project_sessions_by_date("2026-06-18")[0]
    summary = timeline_service.get_session_resource_summary(session["activity_ids"])
    resource = summary[0]
    timeline_service.update_resource_project_for_session(
        session["activity_ids"],
        resource["resource_id"],
        project_b,
        remember_for_future=True,
    )

    rows = [activity_service.get_activity(aid) for aid in session["activity_ids"]]
    assert {row["project_id"] for row in rows} == {project_b}
    assert all(row["manual_override"] == 1 for row in rows)


def test_auxiliary_cannot_be_remembered_for_future(temp_db):
    project = project_service.create_project("A")
    _activity("Edge", "msedge.exe", "Search", "09:00:00")
    activity_service.close_current_open_record("2026-06-18 09:10:00")
    session = timeline_service.get_project_sessions_by_date("2026-06-18")[0]
    resource = timeline_service.get_session_resource_summary(session["activity_ids"])[0]
    assert session["project_name"] == UNCATEGORIZED_PROJECT
    try:
        timeline_service.update_resource_project_for_session(
            session["activity_ids"],
            resource["resource_id"],
            project,
            remember_for_future=True,
        )
    except ValueError:
        pass
    else:
        raise AssertionError("auxiliary resources must not support remember_for_future")


def test_auto_suggested_project_name_displays_without_creating_project(temp_db):
    aid = activity_service.create_activity(
        "WPS Writer",
        "wps.exe",
        "合同审查意见.docx - WPS",
        file_path_hint="D:\\ClientA\\合同审查意见.docx",
        start_time="2026-06-18 09:00:00",
    )
    activity_service.finalize_created_activity(aid)
    activity_service.close_activity(aid, "2026-06-18 09:10:00")

    activity = activity_service.get_activity(aid)
    sessions = timeline_service.get_project_sessions_by_date("2026-06-18")

    assert activity["project_name"] == UNCATEGORIZED_PROJECT
    assert sessions[0]["project_name"] == "ClientA"
    assert sessions[0]["is_uncategorized"] is True
    assert "ClientA" not in [project["name"] for project in project_service.list_selectable_projects()]
    with get_connection() as conn:
        assert conn.execute("SELECT id FROM project WHERE name = 'ClientA'").fetchone() is None


def test_session_level_project_update_warns_but_does_not_change_anchor_defaults(temp_db):
    target_project = project_service.create_project("Target")
    other_project = project_service.create_project("Other")
    first = activity_service.create_activity(
        "Word",
        "winword.exe",
        "One.docx - Word",
        file_path_hint="D:\\CaseA\\One.docx",
        start_time="2026-06-18 09:00:00",
    )
    second = activity_service.create_activity(
        "Word",
        "winword.exe",
        "Two.docx - Word",
        file_path_hint="D:\\CaseA\\Two.docx",
        start_time="2026-06-18 09:05:00",
    )
    activity_service.finalize_created_activity(first)
    activity_service.finalize_created_activity(second)
    first_resource = activity_service.get_activity(first)["resource_id"]
    with get_connection() as conn:
        conn.execute("UPDATE resource SET default_project_id = ? WHERE id = ?", (other_project, first_resource))

    preview = timeline_service.preview_session_project_update([first, second], target_project)
    timeline_service.update_session_project([first, second], target_project)

    assert len(preview["file_project_conflicts"]) == 1
    assert len(preview["unassigned_anchor_files"]) == 1
    assert {activity_service.get_activity(aid)["project_id"] for aid in [first, second]} == {target_project}
    with get_connection() as conn:
        row = conn.execute("SELECT default_project_id FROM resource WHERE id = ?", (first_resource,)).fetchone()
    assert row["default_project_id"] == other_project
