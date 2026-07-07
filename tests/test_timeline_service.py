import pytest

from worktrace.constants import STATUS_ERROR, STATUS_EXCLUDED, STATUS_IDLE, STATUS_PAUSED, UNCATEGORIZED_PROJECT
from worktrace.db import get_connection
from worktrace.services import activity_service, project_service, session_boundary_service, settings_service, timeline_service


def _activity(app, process, title, start, project_id=None, status="normal"):
    # create_activity no longer auto-closes old rows (lifecycle hard
    # cutover); close any existing open activity using the new start
    # time as the end time, mimicking the old create_activity behavior.
    activity_service.close_all_open_rows(f"2026-06-18 {start}")
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
    activity_service.close_all_open_rows(start_time)
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
    activity_service.close_all_open_rows("2026-06-18 10:10:00")

    sessions = timeline_service.get_project_sessions_by_date("2026-06-18")
    latest_details = timeline_service.get_session_activity_details(sessions[0]["activity_ids"])

    assert [session["project_name"] for session in sessions] == ["A", "B", "A"]
    assert [session["start_time"][11:16] for session in sessions] == ["10:00", "09:30", "09:00"]
    assert sessions[0]["event_count"] == 2
    assert [row["start_time"][11:16] for row in latest_details] == ["10:05", "10:00"]


def test_same_project_after_midnight_is_split_by_calendar_day(temp_db):
    project_a = project_service.create_project("A")
    project_b = project_service.create_project("B")
    _activity_at("Word", "winword.exe", "A1.docx", "2026-06-18 23:50:00", project_a)
    _activity_at("Word", "winword.exe", "A2.docx", "2026-06-19 00:10:00", project_a)
    _activity_at("Word", "winword.exe", "B1.docx", "2026-06-19 00:30:00", project_b)
    activity_service.close_all_open_rows("2026-06-19 00:45:00")

    previous_day = timeline_service.get_project_sessions_by_date("2026-06-18")
    next_day = timeline_service.get_project_sessions_by_date("2026-06-19")

    assert [session["project_name"] for session in previous_day] == ["A"]
    assert previous_day[0]["duration_seconds"] == 10 * 60
    assert previous_day[0]["report_date"] == "2026-06-18"
    assert [session["project_name"] for session in next_day] == ["B", "A"]
    assert next_day[0]["duration_seconds"] == 15 * 60
    assert next_day[1]["duration_seconds"] == 30 * 60


def test_same_project_next_day_does_not_carry_when_previous_activity_ended_before_midnight(temp_db):
    project_a = project_service.create_project("A")
    first = _activity_at("Word", "winword.exe", "A1.docx", "2026-06-18 23:40:00", project_a)
    activity_service.close_activity(first, "2026-06-18 23:50:00")
    _activity_at("Word", "winword.exe", "A2.docx", "2026-06-19 08:00:00", project_a)
    activity_service.close_all_open_rows("2026-06-19 08:30:00")

    previous_day = timeline_service.get_project_sessions_by_date("2026-06-18")
    next_day = timeline_service.get_project_sessions_by_date("2026-06-19")

    assert previous_day[0]["duration_seconds"] == 10 * 60
    assert next_day[0]["duration_seconds"] == 30 * 60
    assert next_day[0]["report_date"] == "2026-06-19"


def test_idle_and_uncategorized_split_at_midnight(temp_db):
    _activity_at("空闲", "idle", "用户空闲", "2026-06-18 23:50:00", status="idle")
    activity_service.close_all_open_rows("2026-06-19 00:10:00")
    _activity_at("Edge", "msedge.exe", "Search", "2026-06-19 00:10:00")
    activity_service.close_all_open_rows("2026-06-19 00:30:00")

    previous_day = timeline_service.get_project_sessions_by_date("2026-06-18")
    next_day = timeline_service.get_project_sessions_by_date("2026-06-19")

    assert previous_day == []
    assert [session["duration_seconds"] for session in next_day] == [20 * 60]
    assert [session["project_name"] for session in next_day] == [UNCATEGORIZED_PROJECT]


@pytest.mark.parametrize("status", [STATUS_IDLE, STATUS_PAUSED, STATUS_EXCLUDED, STATUS_ERROR])
def test_system_status_rows_do_not_become_project_sessions(temp_db, status):
    _activity("系统状态", status, status, "09:00:00", status=status)
    activity_service.close_all_open_rows("2026-06-18 09:10:00")

    sessions = timeline_service.get_project_sessions_by_date("2026-06-18")

    assert sessions == []


def test_timeline_db_only_contract_open_row_ignores_current_snapshot(temp_db):
    """Timeline / Statistics / Export MUST be DB-only / report-only.

    An open activity's DB duration MUST NOT be mutated by
    ``current_activity_snapshot`` projection. Live overlay is the sole
    responsibility of ``activity_display_model_service`` +
    ``view_model_service``; the DB/report layer must return the stored
    duration unchanged.
    """
    from datetime import date

    from worktrace.services import statistics_service

    today_str = date.today().isoformat()
    project = project_service.create_project("A")
    activity_id = _activity_at("Word", "winword.exe", "A.docx", f"{today_str} 09:00:00", project)
    # Force DB duration to 10 seconds.
    with get_connection() as conn:
        conn.execute(
            "UPDATE activity_log SET duration_seconds = 10 WHERE id = ?",
            (activity_id,),
        )
    settings_service.set_setting(
        "current_activity_snapshot",
        (
            '{"status":"normal","app_name":"Word","process_name":"winword.exe",'
            '"window_title":"A.docx","start_time":"' + today_str + ' 09:00:00",'
            f'"elapsed_seconds":999,"extra_seconds":0,"persisted_activity_id":{activity_id},'
            '"is_persisted":true}'
        ),
    )

    sessions = timeline_service.get_project_sessions_by_date(today_str)
    assert sessions[0]["duration_seconds"] == 10

    summary = statistics_service.get_summary(today_str, today_str)
    assert summary["total_duration"] == 10
    assert 999 not in (
        summary.get("total_duration", 0),
        summary.get("classified_duration", 0),
        summary.get("uncategorized_duration", 0),
    )


def test_timeline_db_only_contract_closed_row_unaffected_by_snapshot(temp_db):
    """A closed activity row's duration MUST NOT depend on snapshot.

    Regression guard: even when ``current_activity_snapshot`` references
    a closed activity id, the DB/report layer must use the stored
    duration only.
    """
    from datetime import date

    from worktrace.services import statistics_service

    today_str = date.today().isoformat()
    project = project_service.create_project("A")
    activity_id = _activity_at("Word", "winword.exe", "A.docx", f"{today_str} 09:00:00", project)
    activity_service.close_all_open_rows(f"{today_str} 09:01:00")
    with get_connection() as conn:
        conn.execute(
            "UPDATE activity_log SET duration_seconds = 60 WHERE id = ?",
            (activity_id,),
        )
    settings_service.set_setting(
        "current_activity_snapshot",
        (
            '{"status":"normal","app_name":"Word","process_name":"winword.exe",'
            '"window_title":"A.docx","start_time":"' + today_str + ' 09:00:00",'
            f'"elapsed_seconds":999,"extra_seconds":0,"persisted_activity_id":{activity_id},'
            '"is_persisted":true}'
        ),
    )

    sessions = timeline_service.get_project_sessions_by_date(today_str)
    assert sessions[0]["duration_seconds"] == 60

    summary = statistics_service.get_summary(today_str, today_str)
    assert summary["total_duration"] == 60


def test_auxiliary_between_same_project_anchors_merges_into_session(temp_db):
    project = project_service.create_project("A")
    _activity("Word", "winword.exe", "A1.docx", "09:00:00", project)
    _activity("Edge", "msedge.exe", "Search 1", "09:01:00")
    _activity("Chrome", "chrome.exe", "Search 2", "09:01:30")
    _activity("Word", "winword.exe", "A2.docx", "09:02:00", project)
    activity_service.close_all_open_rows("2026-06-18 09:05:00")

    sessions = timeline_service.get_project_sessions_by_date("2026-06-18")
    details = timeline_service.get_session_activity_details(sessions[0]["activity_ids"])

    assert len(sessions) == 1
    assert sessions[0]["project_name"] == "A"
    assert {"Search 1", "Search 2"} <= {row["window_title"] for row in details}


def test_short_other_project_between_same_project_anchors_reports_inside_anchor_session(temp_db):
    project_a = project_service.create_project("A")
    project_b = project_service.create_project("B")
    _activity("Word", "winword.exe", "A1.docx", "09:00:00", project_a)
    b_activity = _activity("Word", "winword.exe", "B1.docx", "09:05:00", project_b)
    _activity("Word", "winword.exe", "A2.docx", "09:09:00", project_a)
    activity_service.close_all_open_rows("2026-06-18 09:15:00")

    sessions = timeline_service.get_project_sessions_by_date("2026-06-18")
    details = timeline_service.get_session_activity_details(sessions[0]["activity_ids"])

    assert len(sessions) == 1
    assert sessions[0]["project_name"] == "A"
    assert sessions[0]["duration_seconds"] == 900
    assert sessions[0]["event_count"] == 3
    assert [row["project_name"] for row in details] == ["A", "B", "A"]
    assert activity_service.get_activity(b_activity)["project_id"] == project_b


def test_short_idle_between_same_project_anchors_breaks_anchor_session(temp_db):
    project_a = project_service.create_project("A")
    _activity("Word", "winword.exe", "A1.docx", "09:00:00", project_a)
    _activity("空闲", "idle", "用户空闲", "09:05:00", status="idle")
    _activity("Word", "winword.exe", "A2.docx", "09:08:00", project_a)
    activity_service.close_all_open_rows("2026-06-18 09:12:00")

    sessions = timeline_service.get_project_sessions_by_date("2026-06-18")

    assert len(sessions) == 2
    assert [session["project_name"] for session in sessions] == ["A", "A"]
    assert [session["duration_seconds"] for session in sessions] == [240, 300]
    assert all(session["status_code"] == "normal" for session in sessions)
    assert all(session["row_kind"] == "project_session" for session in sessions)
    assert all(session["contributes_to_totals"] is True for session in sessions)


def test_five_minute_other_project_between_anchors_does_not_merge(temp_db):
    project_a = project_service.create_project("A")
    project_b = project_service.create_project("B")
    _activity("Word", "winword.exe", "A1.docx", "09:00:00", project_a)
    _activity("Word", "winword.exe", "B1.docx", "09:05:00", project_b)
    _activity("Word", "winword.exe", "A2.docx", "09:10:00", project_a)
    activity_service.close_all_open_rows("2026-06-18 09:12:00")

    sessions = timeline_service.get_project_sessions_by_date("2026-06-18")

    assert [session["project_name"] for session in sessions] == ["A", "B", "A"]


def test_short_other_project_does_not_merge_when_anchor_gap_exceeds_context_window(temp_db):
    project_a = project_service.create_project("A")
    project_b = project_service.create_project("B")
    first_anchor = _activity("Word", "winword.exe", "A1.docx", "09:00:00", project_a)
    activity_service.close_activity(first_anchor, "2026-06-18 09:00:30")
    _activity("Word", "winword.exe", "B1.docx", "09:20:00", project_b)
    _activity("Word", "winword.exe", "A2.docx", "09:24:00", project_a)
    activity_service.close_all_open_rows("2026-06-18 09:30:00")

    sessions = timeline_service.get_project_sessions_by_date("2026-06-18")

    assert [session["project_name"] for session in sessions] == ["A", "B", "A"]


def test_activity_group_correction_updates_selected_activities(temp_db):
    project_a = project_service.create_project("A")
    project_b = project_service.create_project("B")
    _activity("Word", "winword.exe", "Contract.docx", "09:00:00", project_a)
    _activity("Word", "winword.exe", "Contract.docx", "09:10:00", project_a)
    activity_service.close_all_open_rows("2026-06-18 09:20:00")

    session = timeline_service.get_project_sessions_by_date("2026-06-18")[0]
    timeline_service.update_activity_group_project(session["activity_ids"], project_b)

    rows = [activity_service.get_activity(aid) for aid in session["activity_ids"]]
    assert {row["project_id"] for row in rows} == {project_b}
    assert all(row["manual_override"] == 1 for row in rows)

def test_auxiliary_activity_can_be_corrected_for_current_record(temp_db):
    project = project_service.create_project("A")
    activity = _activity("Edge", "msedge.exe", "Search", "09:00:00")
    activity_service.close_all_open_rows("2026-06-18 09:10:00")
    session = timeline_service.get_project_sessions_by_date("2026-06-18")[0]
    assert session["project_name"] == UNCATEGORIZED_PROJECT
    timeline_service.update_activity_group_project([activity], project)
    assert activity_service.get_activity(activity)["project_id"] == project


def test_activity_details_keep_same_app_activity_names(temp_db):
    _activity("Edge", "msedge.exe", "Search", "09:00:00")
    _activity("Edge", "msedge.exe", "Docs", "09:10:00")
    _activity("Edge", "msedge.exe", "Search", "09:20:00")
    activity_service.close_all_open_rows("2026-06-18 09:30:00")

    session = timeline_service.get_project_sessions_by_date("2026-06-18")[0]
    details = timeline_service.get_session_activity_details(session["activity_ids"])

    assert [row["window_title"] for row in details] == ["Search", "Docs", "Search"]


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

    # The activity-level project is uncategorized (no concrete project).
    assert activity["project_name"] == UNCATEGORIZED_PROJECT
    # Attribution contract: suggested_project_name is a CANDIDATE, not an
    # official project. The formal session project_name MUST be uncategorized.
    assert sessions[0]["project_name"] == UNCATEGORIZED_PROJECT
    assert sessions[0]["is_uncategorized"] is True
    assert sessions[0]["is_official_project"] is False
    # The suggested name is retained as candidate_project_name metadata.
    rows = timeline_service.get_report_activity_rows("2026-06-18", "2026-06-18")
    suggested_row = next(r for r in rows if int(r["id"]) == aid)
    assert suggested_row["candidate_project_name"] == "ClientA"
    # No project row is auto-created for the suggested name.
    assert "ClientA" not in [project["name"] for project in project_service.list_selectable_projects()]
    with get_connection() as conn:
        assert conn.execute("SELECT id FROM project WHERE name = 'ClientA'").fetchone() is None


def test_session_level_project_update_warns_about_unassigned_anchor_files(temp_db):
    target_project = project_service.create_project("Target")
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
    activity_service.close_activity(first, "2026-06-18 09:05:00")
    activity_service.finalize_created_activity(second)
    activity_service.close_activity(second, "2026-06-18 09:10:00")

    preview = timeline_service.preview_session_project_update([first, second], target_project)
    timeline_service.update_session_project([first, second], target_project)

    assert "file_project_conflicts" not in preview
    assert len(preview["unassigned_anchor_files"]) == 2
    assert {activity_service.get_activity(aid)["project_id"] for aid in [first, second]} == {target_project}


def test_session_boundary_splits_same_project_records(temp_db):
    project_a = project_service.create_project("A")
    first = _activity_at("Word", "winword.exe", "A1.docx", "2026-06-18 09:00:00", project_a)
    activity_service.close_activity(first, "2026-06-18 09:10:00")
    session_boundary_service.record_boundary("2026-06-18 09:10:00", "stopped")
    second = _activity_at("Word", "winword.exe", "A2.docx", "2026-06-18 09:20:00", project_a)
    activity_service.close_activity(second, "2026-06-18 09:30:00")

    sessions = timeline_service.get_project_sessions_by_date("2026-06-18")

    assert [session["project_name"] for session in sessions] == ["A", "A"]
    assert [session["start_time"][11:16] for session in sessions] == ["09:20", "09:00"]


def test_project_sessions_batch_load_session_boundaries(temp_db, monkeypatch):
    project_a = project_service.create_project("A")
    first = _activity_at("Word", "winword.exe", "A1.docx", "2026-06-18 09:00:00", project_a)
    activity_service.close_activity(first, "2026-06-18 09:10:00")
    session_boundary_service.record_boundary("2026-06-18 09:10:00", "stopped")
    second = _activity_at("Word", "winword.exe", "A2.docx", "2026-06-18 09:20:00", project_a)
    activity_service.close_activity(second, "2026-06-18 09:30:00")
    calls = []
    original = session_boundary_service.list_boundaries

    def counted_list_boundaries(start_time: str, end_time: str):
        calls.append((start_time, end_time))
        return original(start_time, end_time)

    monkeypatch.setattr(session_boundary_service, "list_boundaries", counted_list_boundaries)
    monkeypatch.setattr(
        session_boundary_service,
        "has_boundary_between",
        lambda _start, _end: (_ for _ in ()).throw(AssertionError("per-pair boundary lookup should not run")),
    )

    sessions = timeline_service.get_project_sessions_by_date("2026-06-18")

    assert [session["project_name"] for session in sessions] == ["A", "A"]
    assert 1 <= len(calls) <= 2


def test_unrecorded_gap_splits_same_project_records(temp_db):
    project_a = project_service.create_project("A")
    first = _activity_at("Word", "winword.exe", "A1.docx", "2026-06-18 09:00:00", project_a)
    activity_service.close_activity(first, "2026-06-18 09:10:00")
    second = _activity_at("Word", "winword.exe", "A2.docx", "2026-06-18 09:40:00", project_a)
    activity_service.close_activity(second, "2026-06-18 09:50:00")

    sessions = timeline_service.get_project_sessions_by_date("2026-06-18")

    assert [session["project_name"] for session in sessions] == ["A", "A"]
    assert [session["start_time"][11:16] for session in sessions] == ["09:40", "09:00"]


def test_project_description_flows_to_timeline_rows(temp_db):
    project = project_service.create_project("Client", "billable")
    activity = _activity_at("Word", "winword.exe", "Spec.docx", "2026-06-18 09:00:00", project)
    activity_service.close_activity(activity, "2026-06-18 09:10:00")

    session = timeline_service.get_project_sessions_by_date("2026-06-18")[0]
    details = timeline_service.get_session_activity_details(session["activity_ids"])

    assert session["project_description"] == "billable"
    assert details[0]["project_description"] == "billable"


def test_session_boundary_stops_same_project_merge_after_midnight(temp_db):
    project_a = project_service.create_project("A")
    first = _activity_at("Word", "winword.exe", "A1.docx", "2026-06-18 23:50:00", project_a)
    activity_service.close_activity(first, "2026-06-19 00:05:00")
    session_boundary_service.record_boundary("2026-06-19 00:05:00", "stopped")
    second = _activity_at("Word", "winword.exe", "A2.docx", "2026-06-19 00:10:00", project_a)
    activity_service.close_activity(second, "2026-06-19 00:20:00")

    previous_day = timeline_service.get_project_sessions_by_date("2026-06-18")
    next_day = timeline_service.get_project_sessions_by_date("2026-06-19")

    assert previous_day[0]["duration_seconds"] == 10 * 60
    assert [session["duration_seconds"] for session in next_day] == [10 * 60, 5 * 60]


def test_midnight_anchor_classifies_following_auxiliary_without_file_default(temp_db):
    project_a = project_service.create_project("A")
    anchor = _activity_at("Edge", "msedge.exe", "A browser", "2026-06-19 00:00:00")
    activity_service.apply_midnight_anchor_assignment(anchor, project_a)
    chat = _activity_at("Chat", "chat.exe", "Discuss A", "2026-06-19 00:00:10")
    activity_service.close_activity(chat, "2026-06-19 00:00:45")

    sessions = timeline_service.get_project_sessions_by_date("2026-06-19")

    # Attribution contract: midnight_anchor is a derived internal source,
    # NOT official. The formal session project must be uncategorized.
    assert len(sessions) == 1
    assert sessions[0]["project_name"] == UNCATEGORIZED_PROJECT
    assert sessions[0]["is_official_project"] is False


def test_project_session_note_attaches_to_session_by_first_activity(temp_db):
    project = project_service.create_project("Client")
    first = _activity_at("Word", "winword.exe", "Spec.docx", "2026-06-18 09:00:00", project)
    _activity_at("Word", "winword.exe", "Spec 2.docx", "2026-06-18 09:10:00", project)
    activity_service.close_all_open_rows("2026-06-18 09:20:00")
    sessions = timeline_service.get_project_sessions_by_date("2026-06-18")

    timeline_service.update_session_note("2026-06-18", first, "follow up with client")
    sessions = timeline_service.get_project_sessions_by_date("2026-06-18")

    assert sessions[0]["first_activity_id"] == first
    assert sessions[0]["session_note"] == "follow up with client"


def test_project_session_note_can_be_cleared(temp_db):
    project = project_service.create_project("Client")
    first = _activity_at("Word", "winword.exe", "Spec.docx", "2026-06-18 09:00:00", project)
    activity_service.close_all_open_rows("2026-06-18 09:20:00")

    timeline_service.update_session_note("2026-06-18", first, "temporary")
    timeline_service.update_session_note("2026-06-18", first, "")

    assert timeline_service.get_project_sessions_by_date("2026-06-18")[0]["session_note"] == ""




def test_session_has_display_and_raw_duration_fields(temp_db):
    """Sessions carry raw_duration_seconds, display_duration_seconds,
    adjusted_duration_seconds, has_duration_override."""
    project = project_service.create_project("Client")
    _activity_at("Word", "winword.exe", "Spec.docx", "2026-06-18 09:00:00", project)
    activity_service.close_all_open_rows("2026-06-18 09:02:00")
    sessions = timeline_service.get_project_sessions_by_date("2026-06-18")

    session = sessions[0]
    assert "raw_duration_seconds" in session
    assert "display_duration_seconds" in session
    assert "adjusted_duration_seconds" in session
    assert "has_duration_override" in session


def test_display_duration_uses_override_when_set(temp_db):
    """When adjusted_duration_seconds is set, display_duration_seconds uses it."""
    project = project_service.create_project("Client")
    first = _activity_at("Word", "winword.exe", "Spec.docx", "2026-06-18 09:00:00", project)
    activity_service.close_all_open_rows("2026-06-18 09:02:00")  # 120 seconds raw

    timeline_service.update_session_note_and_duration("2026-06-18", first, "", 60)
    sessions = timeline_service.get_project_sessions_by_date("2026-06-18")

    session = sessions[0]
    assert session["raw_duration_seconds"] == 120
    assert session["adjusted_duration_seconds"] == 60
    assert session["display_duration_seconds"] == 60
    assert session["has_duration_override"] is True


def test_display_duration_uses_raw_when_no_override(temp_db):
    """When no override, display_duration_seconds == raw_duration_seconds."""
    project = project_service.create_project("Client")
    _activity_at("Word", "winword.exe", "Spec.docx", "2026-06-18 09:00:00", project)
    activity_service.close_all_open_rows("2026-06-18 09:02:00")  # 120 seconds raw
    sessions = timeline_service.get_project_sessions_by_date("2026-06-18")

    session = sessions[0]
    assert session["raw_duration_seconds"] == 120
    assert session["adjusted_duration_seconds"] is None
    assert session["display_duration_seconds"] == 120
    assert session["has_duration_override"] is False


def test_display_duration_uses_zero_override(temp_db):
    """``adjusted_duration_seconds = 0`` is a valid override and must not
    fall back to the raw duration."""
    project = project_service.create_project("Client")
    first = _activity_at("Word", "winword.exe", "Spec.docx", "2026-06-18 09:00:00", project)
    activity_service.close_all_open_rows("2026-06-18 09:02:00")  # 120 seconds raw

    timeline_service.update_session_note_and_duration("2026-06-18", first, "", 0)
    sessions = timeline_service.get_project_sessions_by_date("2026-06-18")

    session = sessions[0]
    assert session["raw_duration_seconds"] == 120
    assert session["adjusted_duration_seconds"] == 0
    assert session["display_duration_seconds"] == 0
    assert session["has_duration_override"] is True


def test_update_session_note_and_duration_writes_both(temp_db):
    """update_session_note_and_duration writes both note and duration."""
    project = project_service.create_project("Client")
    first = _activity_at("Word", "winword.exe", "Spec.docx", "2026-06-18 09:00:00", project)
    activity_service.close_all_open_rows("2026-06-18 09:02:00")

    timeline_service.update_session_note_and_duration("2026-06-18", first, "test", 60)
    from worktrace.services import session_note_service
    fields = session_note_service.get_session_user_fields("2026-06-18", first)

    assert fields["note"] == "test"
    assert fields["adjusted_duration_seconds"] == 60


def test_empty_note_preserves_duration_override(temp_db):
    """Setting empty note does not delete row when duration override exists."""
    project = project_service.create_project("Client")
    first = _activity_at("Word", "winword.exe", "Spec.docx", "2026-06-18 09:00:00", project)
    activity_service.close_all_open_rows("2026-06-18 09:02:00")

    # Set both note and duration
    timeline_service.update_session_note_and_duration("2026-06-18", first, "test", 60)
    # Set note to empty - should preserve adjusted=60
    timeline_service.update_session_note_and_duration("2026-06-18", first, "", 60)
    from worktrace.services import session_note_service
    fields = session_note_service.get_session_user_fields("2026-06-18", first)

    assert fields["note"] == ""
    assert fields["adjusted_duration_seconds"] == 60


def test_empty_note_and_null_duration_deletes_row(temp_db):
    """Setting empty note and None duration deletes the row."""
    project = project_service.create_project("Client")
    first = _activity_at("Word", "winword.exe", "Spec.docx", "2026-06-18 09:00:00", project)
    activity_service.close_all_open_rows("2026-06-18 09:02:00")

    # Set both note and duration
    timeline_service.update_session_note_and_duration("2026-06-18", first, "test", 60)
    # Set note to empty and duration to None - should delete row
    timeline_service.update_session_note_and_duration("2026-06-18", first, "", None)
    from worktrace.services import session_note_service
    fields = session_note_service.get_session_user_fields("2026-06-18", first)

    assert fields["note"] == ""
    assert fields["adjusted_duration_seconds"] is None



def test_is_project_anchor_delegates_to_shared_file_context_predicate():
    """``_is_project_anchor`` reuses ``is_file_context_anchor`` so that browser
    tabs / email are excluded and file anchors (docx/pdf/xlsx) are included,
    while also requiring a concrete display project."""
    # File anchor assigned to a concrete project → True
    file_row = {
        "status": "normal",
        "assignment_source": "manual",
        "display_project_name": "A",
        "resource_is_anchor": True,
        "resource_kind": "file",
        "resource_display_name": "report.docx",
    }
    assert timeline_service._is_project_anchor(file_row) is True

    # Browser tab → False (is_file_context_anchor returns False)
    browser_row = {
        "status": "normal",
        "assignment_source": "uncategorized",
        "display_project_name": UNCATEGORIZED_PROJECT,
        "resource_is_anchor": True,
        "resource_kind": "browser_tab",
        "resource_display_name": "Search",
    }
    assert timeline_service._is_project_anchor(browser_row) is False

    # Email → False
    email_row = {
        "status": "normal",
        "assignment_source": "uncategorized",
        "display_project_name": UNCATEGORIZED_PROJECT,
        "resource_is_anchor": True,
        "resource_kind": "email",
        "resource_display_name": "Inbox",
    }
    assert timeline_service._is_project_anchor(email_row) is False

    # File anchor but uncategorized project → False
    uncategorized_file_row = {
        "status": "normal",
        "assignment_source": "uncategorized",
        "display_project_name": UNCATEGORIZED_PROJECT,
        "resource_is_anchor": True,
        "resource_kind": "file",
        "resource_display_name": "loose.docx",
    }
    assert timeline_service._is_project_anchor(uncategorized_file_row) is False

    # midnight_anchor is NOT a project anchor — it is a derived internal
    # source used for cross-midnight continuity only.
    midnight_row = {
        "status": "normal",
        "assignment_source": "midnight_anchor",
        "display_project_name": "A",
        "resource_is_anchor": False,
        "resource_kind": "",
        "resource_display_name": "",
    }
    assert timeline_service._is_project_anchor(midnight_row) is False


def test_get_session_anchor_folders_excludes_browser_and_includes_file_anchors(temp_db):
    """``get_session_anchor_folders`` does not return browser/email folders,
    while file anchors (docx/pdf/xlsx) with a local path still surface their
    parent directory."""
    project = project_service.create_project("A")

    docx_id = activity_service.create_activity(
        "Word", "winword.exe", "report.docx",
        start_time="2026-06-18 09:00:00",
        file_path_hint=r"C:\Projects\A\report.docx",
        project_id=project,
    )
    activity_service.finalize_created_activity(docx_id)
    activity_service.close_activity(docx_id, "2026-06-18 09:20:00")

    browser_id = activity_service.create_activity(
        "Edge", "msedge.exe", "Search",
        start_time="2026-06-18 09:20:00",
    )
    activity_service.finalize_created_activity(browser_id)
    activity_service.close_activity(browser_id, "2026-06-18 09:30:00")

    pdf_id = activity_service.create_activity(
        "Adobe", "acrobat.exe", "slides.pdf",
        start_time="2026-06-18 09:30:00",
        file_path_hint=r"C:\Projects\A\slides.pdf",
        project_id=project,
    )
    activity_service.finalize_created_activity(pdf_id)
    activity_service.close_activity(pdf_id, "2026-06-18 09:40:00")

    folders = timeline_service.get_session_anchor_folders([docx_id, browser_id, pdf_id])

    # Browser must NOT produce a folder; docx and pdf share the same parent.
    assert len(folders) == 1
    assert folders[0] == r"C:\Projects\A"
