from worktrace.collector.state_machine import CollectorStateMachine
from worktrace.constants import EXCLUDED_WINDOW_TITLE
from worktrace.platforms.base import ActiveWindow
from worktrace.services import activity_service, privacy_service


def test_state_transitions_do_not_leave_duplicate_open_rows(temp_db):
    machine = CollectorStateMachine()
    machine.transition_to(
        "recording",
        ActiveWindow("Word", "word.exe", "Doc"),
        at_time="2026-06-18 09:00:00",
    )
    machine.transition_to("idle", at_time="2026-06-18 09:10:00")
    open_row = activity_service.get_open_activity()
    assert open_row["status"] == "idle"
    rows = activity_service.get_activities_by_date("2026-06-18")
    assert len([row for row in rows if row["end_time"] is None]) == 1
    assert activity_service.get_activity(rows[-1]["id"])["duration_seconds"] == 600


def test_excluded_transition_anonymizes_title(temp_db):
    privacy_service.set_exclude_keywords(["银行"])
    machine = CollectorStateMachine()
    machine.transition_to(
        "excluded",
        ActiveWindow("BankApp", "bank.exe", "银行真实标题"),
        at_time="2026-06-18 09:00:00",
    )
    row = activity_service.get_open_activity()
    assert row["status"] == "excluded"
    assert row["window_title"] == EXCLUDED_WINDOW_TITLE
    assert "真实" not in row["window_title"]
    assert row["file_path_hint"] is None


def test_pause_resume_transition(temp_db):
    machine = CollectorStateMachine()
    machine.transition_to(
        "recording",
        ActiveWindow("Word", "word.exe", "Doc"),
        at_time="2026-06-18 09:00:00",
    )
    machine.transition_to("paused", at_time="2026-06-18 09:05:00")
    machine.transition_to(
        "recording",
        ActiveWindow("Excel", "excel.exe", "Sheet"),
        at_time="2026-06-18 09:06:00",
    )
    assert activity_service.get_open_activity()["window_title"] == "Sheet"


def test_state_machine_writes_file_path_hint(temp_db):
    machine = CollectorStateMachine()
    machine.transition_to(
        "recording",
        ActiveWindow("Word", "winword.exe", "Spec.docx - Word", "D:\\CaseA\\Spec.docx"),
        at_time="2026-06-18 09:00:00",
    )
    row = activity_service.get_open_activity()
    assert row["file_path_hint"] == "D:\\CaseA\\Spec.docx"


def test_state_machine_fills_missing_path_without_splitting(temp_db):
    machine = CollectorStateMachine()
    machine.transition_to(
        "recording",
        ActiveWindow("Word", "winword.exe", "Spec.docx - Word"),
        at_time="2026-06-18 09:00:00",
    )
    first_id = activity_service.get_open_activity()["id"]
    machine.transition_to(
        "recording",
        ActiveWindow("Word", "winword.exe", "Spec.docx - Word", "D:\\CaseA\\Spec.docx"),
        at_time="2026-06-18 09:01:00",
    )
    row = activity_service.get_open_activity()
    assert row["id"] == first_id
    assert row["file_path_hint"] == "D:\\CaseA\\Spec.docx"
    assert row["end_time"] is None


def test_state_machine_keeps_activity_when_new_path_is_missing(temp_db):
    machine = CollectorStateMachine()
    machine.transition_to(
        "recording",
        ActiveWindow("Word", "winword.exe", "Spec.docx - Word", "D:\\CaseA\\Spec.docx"),
        at_time="2026-06-18 09:00:00",
    )
    first_id = activity_service.get_open_activity()["id"]
    machine.transition_to(
        "recording",
        ActiveWindow("Word", "winword.exe", "Spec.docx - Word"),
        at_time="2026-06-18 09:01:00",
    )
    assert activity_service.get_open_activity()["id"] == first_id


def test_state_machine_splits_when_both_paths_differ(temp_db):
    machine = CollectorStateMachine()
    machine.transition_to(
        "recording",
        ActiveWindow("Word", "winword.exe", "Spec.docx - Word", "D:\\CaseA\\Spec.docx"),
        at_time="2026-06-18 09:00:00",
    )
    first_id = activity_service.get_open_activity()["id"]
    machine.transition_to(
        "recording",
        ActiveWindow("Word", "winword.exe", "Spec.docx - Word", "D:\\CaseB\\Spec.docx"),
        at_time="2026-06-18 09:01:00",
    )
    row = activity_service.get_open_activity()
    assert row["id"] != first_id
    assert activity_service.get_activity(first_id)["end_time"] == "2026-06-18 09:01:00"
