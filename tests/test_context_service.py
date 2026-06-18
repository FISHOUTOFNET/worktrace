from worktrace.constants import UNCATEGORIZED_PROJECT
from worktrace.services import activity_service, project_service
from worktrace.services.context_service import recompute_context_assignments_for_date


def _activity(app, process, title, start, project_id=None, status="normal"):
    aid = activity_service.create_activity(
        app,
        process,
        title,
        start_time=f"2026-06-18 {start}",
        project_id=project_id,
        status=status,
        is_billable=status == "normal",
    )
    activity_service.finalize_created_activity(aid)
    return aid


def test_same_project_different_anchor_files_classify_auxiliary(temp_db):
    project = project_service.create_project("A")
    _activity("Word", "winword.exe", "A_file_1.docx", "09:00:00", project)
    browser = _activity("Edge", "msedge.exe", "Search", "09:10:00")
    _activity("Adobe", "acrobat.exe", "A_file_2.pdf", "09:20:00", project)
    activity_service.close_current_open_record("2026-06-18 09:30:00")

    recompute_context_assignments_for_date("2026-06-18")

    assert activity_service.get_activity(browser)["project_id"] == project


def test_different_project_anchors_leave_auxiliary_uncategorized(temp_db):
    project_a = project_service.create_project("A")
    project_b = project_service.create_project("B")
    _activity("Word", "winword.exe", "A_file.docx", "09:00:00", project_a)
    browser = _activity("Edge", "msedge.exe", "Search", "09:10:00")
    _activity("Word", "winword.exe", "B_file.docx", "09:20:00", project_b)
    activity_service.close_current_open_record("2026-06-18 09:30:00")

    recompute_context_assignments_for_date("2026-06-18")

    assert activity_service.get_activity(browser)["project_name"] == UNCATEGORIZED_PROJECT


def test_interrupt_and_carry_window_stop_context(temp_db):
    project = project_service.create_project("A")
    _activity("Word", "winword.exe", "A_file.docx", "09:00:00", project)
    interrupted = _activity("空闲", "idle", "用户空闲", "09:05:00", status="idle")
    browser = _activity("Edge", "msedge.exe", "Search", "09:10:00")
    late = _activity("Edge", "msedge.exe", "Later Search", "09:40:00")
    activity_service.close_current_open_record("2026-06-18 09:45:00")

    recompute_context_assignments_for_date("2026-06-18")

    assert activity_service.get_activity(interrupted)["project_name"] == UNCATEGORIZED_PROJECT
    assert activity_service.get_activity(browser)["project_name"] == UNCATEGORIZED_PROJECT
    assert activity_service.get_activity(late)["project_name"] == UNCATEGORIZED_PROJECT


def test_recompute_is_idempotent_and_preserves_manual_auxiliary(temp_db):
    project = project_service.create_project("A")
    manual_project = project_service.create_project("Manual")
    _activity("Word", "winword.exe", "A_file.docx", "09:00:00", project)
    browser = _activity("Edge", "msedge.exe", "Search", "09:10:00")
    _activity("Word", "winword.exe", "A_file_2.docx", "09:20:00", project)
    activity_service.close_current_open_record("2026-06-18 09:30:00")
    activity_service.update_activity_project(browser, manual_project, manual=True)

    recompute_context_assignments_for_date("2026-06-18")
    first = activity_service.get_activity(browser)
    recompute_context_assignments_for_date("2026-06-18")
    second = activity_service.get_activity(browser)

    assert first["project_id"] == manual_project
    assert second["project_id"] == manual_project
    assert second["updated_at"] == first["updated_at"]
