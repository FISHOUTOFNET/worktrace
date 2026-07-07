from tests.support.db_helpers import assign_activity_project
import json

import pytest

pytestmark = [pytest.mark.collector_runtime, pytest.mark.integration, pytest.mark.db, pytest.mark.security_privacy]

from worktrace.collector.state_machine import CollectorStateMachine
from worktrace.constants import EXCLUDED_WINDOW_TITLE
from worktrace.db import get_connection
from worktrace.platforms.base import ActiveWindow, ClipboardTextEvent
from worktrace.services import activity_service, folder_rule_service, project_service, rule_service, settings_service


def _enable_excluded_project_with_keyword(keyword: str) -> int:
    """Enable the 排除规则 project and add a keyword rule. Returns the project id."""
    excluded_project = project_service.get_or_create_excluded_project()
    project_service.set_project_enabled(excluded_project, True)
    rule_service.create_rule(keyword, excluded_project)
    return excluded_project


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
    _enable_excluded_project_with_keyword("银行")
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


def test_current_activity_snapshot_uses_folder_rule_project_before_persistence(temp_db):
    project_id = project_service.create_project("21IP0300")
    folder_rule_service.create_or_update_folder_rule("D:\\Work\\1-21IP0300", project_id)
    machine = CollectorStateMachine()

    machine.transition_to(
        "recording",
        ActiveWindow(
            "WPS Writer",
            "wps.exe",
            "监督阅卷所函_瑞翁_20251020.doc - WPS Office",
            "D:\\Work\\1-21IP0300\\监督阅卷所函_瑞翁_20251020.doc",
        ),
        at_time="2026-06-18 09:00:00",
    )

    snap = _snapshot()
    assert snap["is_persisted"] is False
    assert snap["inferred_project_name"] == "21IP0300"


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


def test_midnight_split_restarts_with_persistent_temporary_anchor(temp_db):
    project_id = project_service.create_project("A")
    machine = CollectorStateMachine()
    machine.transition_to(
        "recording",
        ActiveWindow("Edge", "msedge.exe", "A research"),
        at_time="2026-06-18 23:59:00",
    )
    machine.transition_to(
        "recording",
        ActiveWindow("Edge", "msedge.exe", "A research"),
        at_time="2026-06-18 23:59:30",
    )
    previous = activity_service.get_open_activity()
    assign_activity_project(int(previous["id"]), project_id, manual=False)

    machine.split_at_midnight("2026-06-19 00:00:00")
    machine.transition_to(
        "recording",
        ActiveWindow("Edge", "msedge.exe", "A research"),
        at_time="2026-06-19 00:00:05",
    )

    old_row = activity_service.get_activity(int(previous["id"]))
    new_row = activity_service.get_open_activity()
    with get_connection() as conn:
        assignment = conn.execute(
            "SELECT source, is_manual FROM activity_project_assignment WHERE activity_id = ?",
            (new_row["id"],),
        ).fetchone()
        boundaries = conn.execute(
            "SELECT occurred_at, reason FROM session_boundary ORDER BY occurred_at"
        ).fetchall()

    assert old_row["end_time"] == "2026-06-19 00:00:00"
    assert new_row["start_time"] == "2026-06-19 00:00:00"
    assert new_row["duration_seconds"] == 5
    assert new_row["project_id"] == project_id
    assert new_row["manual_override"] == 0
    assert assignment["source"] == "midnight_anchor"
    assert assignment["is_manual"] == 0
    assert [(row["occurred_at"], row["reason"]) for row in boundaries] == [
        ("2026-06-19 00:00:00", "midnight")
    ]


def test_clipboard_event_forces_short_activity_into_history(temp_db):
    machine = CollectorStateMachine()
    window = ActiveWindow("Edge", "msedge.exe", "Research")
    machine.transition_to("recording", window, at_time="2026-06-18 09:00:00")

    event_id = machine.record_clipboard_event(
        ClipboardTextEvent("copied text", window, copied_at="2026-06-18 09:00:05", sequence_number=7),
        at_time="2026-06-18 09:00:05",
    )

    row = activity_service.get_open_activity()
    with get_connection() as conn:
        event_count = conn.execute("SELECT COUNT(*) AS c FROM activity_clipboard_event").fetchone()["c"]
    assert event_id is not None
    assert row is not None
    assert row["start_time"] == "2026-06-18 09:00:00"
    assert row["duration_seconds"] == 5
    assert event_count == 1


def test_clipboard_event_for_excluded_window_is_not_recorded(temp_db):
    _enable_excluded_project_with_keyword("Secret")
    machine = CollectorStateMachine()
    window = ActiveWindow("Edge", "msedge.exe", "Secret page")
    machine.transition_to("recording", window, at_time="2026-06-18 09:00:00")

    event_id = machine.record_clipboard_event(
        ClipboardTextEvent("sensitive copied text", window, copied_at="2026-06-18 09:00:05", sequence_number=8),
        at_time="2026-06-18 09:00:05",
    )

    with get_connection() as conn:
        event_count = conn.execute("SELECT COUNT(*) AS c FROM activity_clipboard_event").fetchone()["c"]
    assert event_id is None
    assert event_count == 0
