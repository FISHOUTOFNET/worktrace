import json

from worktrace.collector.state_machine import CollectorStateMachine
from worktrace.constants import EXCLUDED_WINDOW_TITLE
from worktrace.platforms.base import ActiveWindow
from worktrace.services import activity_service, privacy_service, settings_service


def _snapshot():
    return json.loads(settings_service.get_setting("current_activity_snapshot", "") or "{}")


def test_state_transitions_persist_when_segment_reaches_threshold(temp_db):
    machine = CollectorStateMachine()
    machine.transition_to(
        "recording",
        ActiveWindow("Word", "word.exe", "Doc"),
        at_time="2026-06-18 09:00:00",
    )
    assert activity_service.get_open_activity() is None

    machine.transition_to("idle", at_time="2026-06-18 09:10:00")
    rows = activity_service.get_activities_by_date("2026-06-18")
    normal = [row for row in rows if row["status"] == "normal"]
    assert len(normal) == 1
    assert normal[0]["duration_seconds"] == 600
    assert activity_service.get_open_activity() is None


def test_excluded_transition_anonymizes_snapshot_title(temp_db):
    privacy_service.set_exclude_keywords(["银行"])
    machine = CollectorStateMachine()
    machine.transition_to(
        "excluded",
        ActiveWindow("BankApp", "bank.exe", "银行真实标题"),
        at_time="2026-06-18 09:00:00",
    )
    snap = _snapshot()
    assert snap["status"] == "excluded"
    assert snap["window_title"] == EXCLUDED_WINDOW_TITLE
    assert "真实" not in snap["window_title"]
    assert snap["file_path_hint"] is None
    assert activity_service.get_open_activity() is None


def test_pause_resume_short_segments_do_not_create_history(temp_db):
    machine = CollectorStateMachine()
    machine.transition_to(
        "recording",
        ActiveWindow("Word", "word.exe", "Doc"),
        at_time="2026-06-18 09:00:00",
    )
    machine.transition_to("paused", at_time="2026-06-18 09:00:29")
    machine.transition_to(
        "recording",
        ActiveWindow("Excel", "excel.exe", "Sheet"),
        at_time="2026-06-18 09:00:45",
    )
    assert activity_service.get_activities_by_date("2026-06-18") == []
    assert _snapshot()["window_title"] == "Sheet"


def test_state_machine_writes_file_path_hint_to_snapshot(temp_db):
    machine = CollectorStateMachine()
    machine.transition_to(
        "recording",
        ActiveWindow("Word", "winword.exe", "Spec.docx - Word", "D:\\CaseA\\Spec.docx"),
        at_time="2026-06-18 09:00:00",
    )
    assert _snapshot()["file_path_hint"] == "D:\\CaseA\\Spec.docx"


def test_state_machine_fills_missing_path_without_splitting(temp_db):
    machine = CollectorStateMachine()
    machine.transition_to(
        "recording",
        ActiveWindow("Word", "winword.exe", "Spec.docx - Word"),
        at_time="2026-06-18 09:00:00",
    )
    machine.transition_to(
        "recording",
        ActiveWindow("Word", "winword.exe", "Spec.docx - Word", "D:\\CaseA\\Spec.docx"),
        at_time="2026-06-18 09:00:30",
    )
    machine.transition_to(
        "recording",
        ActiveWindow("Word", "winword.exe", "Spec.docx - Word", "D:\\CaseA\\Spec.docx"),
        at_time="2026-06-18 09:01:00",
    )
    row = activity_service.get_open_activity()
    assert row["file_path_hint"] == "D:\\CaseA\\Spec.docx"
    assert row["start_time"] == "2026-06-18 09:00:00"
    assert row["end_time"] is None


def test_state_machine_keeps_activity_when_new_path_is_missing(temp_db):
    machine = CollectorStateMachine()
    machine.transition_to(
        "recording",
        ActiveWindow("Word", "winword.exe", "Spec.docx - Word", "D:\\CaseA\\Spec.docx"),
        at_time="2026-06-18 09:00:00",
    )
    machine.transition_to(
        "recording",
        ActiveWindow("Word", "winword.exe", "Spec.docx - Word"),
        at_time="2026-06-18 09:01:00",
    )
    first_id = activity_service.get_open_activity()["id"]
    machine.transition_to(
        "recording",
        ActiveWindow("Word", "winword.exe", "Spec.docx - Word"),
        at_time="2026-06-18 09:01:30",
    )
    assert activity_service.get_open_activity()["id"] == first_id


def test_state_machine_splits_when_both_paths_differ(temp_db):
    machine = CollectorStateMachine()
    machine.transition_to(
        "recording",
        ActiveWindow("Word", "winword.exe", "Spec.docx - Word", "D:\\CaseA\\Spec.docx"),
        at_time="2026-06-18 09:00:00",
    )
    machine.transition_to(
        "recording",
        ActiveWindow("Word", "winword.exe", "Spec.docx - Word", "D:\\CaseA\\Spec.docx"),
        at_time="2026-06-18 09:01:00",
    )
    first_id = activity_service.get_open_activity()["id"]
    machine.transition_to(
        "recording",
        ActiveWindow("Word", "winword.exe", "Spec.docx - Word", "D:\\CaseB\\Spec.docx"),
        at_time="2026-06-18 09:01:10",
    )
    assert activity_service.get_activity(first_id)["end_time"] == "2026-06-18 09:01:10"
    assert activity_service.get_open_activity() is None
    assert _snapshot()["file_path_hint"] == "D:\\CaseB\\Spec.docx"
