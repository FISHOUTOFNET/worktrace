import json
from pathlib import Path

from openpyxl import load_workbook

from worktrace.collector.state_machine import CollectorStateMachine
from worktrace.platforms.base import ActiveWindow
from worktrace.services import activity_service, export_service, settings_service, statistics_service


def _rows():
    return activity_service.get_activities_by_date("2026-06-18")


def _snapshot():
    return json.loads(settings_service.get_setting("current_activity_snapshot", "") or "{}")


def _normal(title: str) -> ActiveWindow:
    return ActiveWindow(title, f"{title.lower()}.exe", title)


def test_single_auto_activity_29_seconds_has_snapshot_but_no_history_stats_or_export(temp_db, tmp_path):
    machine = CollectorStateMachine()
    machine.transition_to("recording", _normal("Doc"), at_time="2026-06-18 09:00:00")
    machine.transition_to("recording", _normal("Doc"), at_time="2026-06-18 09:00:29")

    assert _snapshot()["window_title"] == "Doc"
    assert _snapshot()["is_persisted"] is False
    assert _rows() == []
    assert statistics_service.get_summary("2026-06-18", "2026-06-18")["total_duration"] == 0

    md_path = export_service.export_markdown("2026-06-18", "2026-06-18", str(tmp_path / "out.md"))
    assert "Doc" not in Path(md_path).read_text(encoding="utf-8")
    xlsx_path = export_service.export_excel("2026-06-18", "2026-06-18", str(tmp_path / "out.xlsx"))
    assert load_workbook(xlsx_path)["Activity Logs"].max_row == 1


def test_single_auto_activity_30_seconds_persists_once_with_actual_start(temp_db):
    machine = CollectorStateMachine()
    machine.transition_to("recording", _normal("Doc"), at_time="2026-06-18 09:00:00")
    machine.transition_to("recording", _normal("Doc"), at_time="2026-06-18 09:00:30")
    machine.transition_to("recording", _normal("Doc"), at_time="2026-06-18 09:00:45")

    rows = _rows()
    assert len(rows) == 1
    assert rows[0]["start_time"] == "2026-06-18 09:00:00"
    assert rows[0]["end_time"] is None
    assert _snapshot()["is_persisted"] is True


def test_short_activity_merges_into_previous_formal_normal_activity(temp_db):
    machine = CollectorStateMachine()
    machine.transition_to("recording", _normal("A"), at_time="2026-06-18 09:00:00")
    machine.transition_to("recording", _normal("A"), at_time="2026-06-18 09:01:00")
    machine.transition_to("recording", _normal("B"), at_time="2026-06-18 09:05:00")
    machine.transition_to("recording", _normal("C"), at_time="2026-06-18 09:05:20")

    rows = _rows()
    assert len(rows) == 1
    assert rows[0]["window_title"] == "A"
    assert rows[0]["duration_seconds"] == 320


def test_same_activity_resumes_after_absorbed_short_activity_without_new_record(temp_db):
    machine = CollectorStateMachine()
    machine.transition_to("recording", _normal("A"), at_time="2026-06-18 09:00:00")
    machine.transition_to("recording", _normal("A"), at_time="2026-06-18 09:01:00")
    machine.transition_to("recording", _normal("B"), at_time="2026-06-18 09:05:00")
    machine.transition_to("recording", _normal("A"), at_time="2026-06-18 09:05:20")
    machine.transition_to("recording", _normal("A"), at_time="2026-06-18 09:07:00")
    machine.transition_to("stopped", at_time="2026-06-18 09:07:00")

    rows = _rows()
    assert len(rows) == 1
    assert rows[0]["window_title"] == "A"
    assert rows[0]["start_time"] == "2026-06-18 09:00:00"
    assert rows[0]["end_time"] == "2026-06-18 09:07:00"
    assert rows[0]["duration_seconds"] == 7 * 60


def test_multiple_short_activities_merge_into_previous_formal_activity(temp_db):
    machine = CollectorStateMachine()
    machine.transition_to("recording", _normal("A"), at_time="2026-06-18 09:00:00")
    machine.transition_to("recording", _normal("A"), at_time="2026-06-18 09:00:30")
    machine.transition_to("recording", _normal("B"), at_time="2026-06-18 09:05:00")
    machine.transition_to("recording", _normal("C"), at_time="2026-06-18 09:05:20")
    machine.transition_to("recording", _normal("D"), at_time="2026-06-18 09:05:29")
    machine.transition_to("stopped", at_time="2026-06-18 09:05:29")

    rows = _rows()
    assert len(rows) == 1
    assert rows[0]["duration_seconds"] == 329


def test_initial_short_activity_merges_into_first_formal_normal_activity(temp_db):
    machine = CollectorStateMachine()
    machine.transition_to("recording", _normal("B"), at_time="2026-06-18 09:00:00")
    machine.transition_to("recording", _normal("A"), at_time="2026-06-18 09:00:20")
    machine.transition_to("recording", _normal("A"), at_time="2026-06-18 09:01:20")
    machine.transition_to("stopped", at_time="2026-06-18 09:01:20")

    rows = _rows()
    assert len(rows) == 1
    assert rows[0]["window_title"] == "A"
    assert rows[0]["duration_seconds"] == 80
    assert settings_service.get_setting("pending_short_seconds") == "0"


def test_pending_short_seconds_are_not_added_twice_when_formal_activity_closes(temp_db):
    machine = CollectorStateMachine()
    machine.transition_to("recording", _normal("B"), at_time="2026-06-18 09:00:00")
    machine.transition_to("recording", _normal("A"), at_time="2026-06-18 09:00:20")
    machine.transition_to("recording", _normal("A"), at_time="2026-06-18 09:01:20")
    machine.transition_to("stopped", at_time="2026-06-18 09:01:30")

    rows = _rows()
    assert len(rows) == 1
    assert rows[0]["window_title"] == "A"
    assert rows[0]["duration_seconds"] == 90


def test_persisted_current_activity_continues_to_90_seconds_without_duplicate_insert(temp_db):
    machine = CollectorStateMachine()
    machine.transition_to("recording", _normal("A"), at_time="2026-06-18 09:00:00")
    machine.transition_to("recording", _normal("A"), at_time="2026-06-18 09:01:00")
    machine.transition_to("recording", _normal("A"), at_time="2026-06-18 09:01:30")
    assert len(_rows()) == 1
    machine.transition_to("idle", at_time="2026-06-18 09:01:30")

    rows = _rows()
    assert len(rows) == 1
    assert rows[0]["duration_seconds"] == 90


def test_stop_short_current_activity_merges_or_pends(temp_db):
    machine = CollectorStateMachine()
    machine.transition_to("recording", _normal("B"), at_time="2026-06-18 09:00:00")
    machine.transition_to("stopped", at_time="2026-06-18 09:00:29")
    assert _rows() == []
    assert settings_service.get_setting("pending_short_seconds") == "0"

    machine = CollectorStateMachine()
    machine.transition_to("recording", _normal("A"), at_time="2026-06-18 09:01:00")
    machine.transition_to("recording", _normal("A"), at_time="2026-06-18 09:01:30")
    machine.transition_to("stopped", at_time="2026-06-18 09:01:30")
    assert _rows()[0]["duration_seconds"] == 30


def test_short_idle_polling_does_not_create_history(temp_db):
    machine = CollectorStateMachine()
    machine.transition_to("idle", at_time="2026-06-18 09:00:00")
    machine.transition_to("idle", at_time="2026-06-18 09:00:01")
    assert _rows() == []
    assert _snapshot()["status"] == "idle"


def test_idle_30_seconds_creates_one_idle_record(temp_db):
    machine = CollectorStateMachine()
    machine.transition_to("idle", at_time="2026-06-18 09:00:00")
    for second in range(1, 31):
        machine.transition_to("idle", at_time=f"2026-06-18 09:{second // 60:02d}:{second % 60:02d}")
        assert len(_rows()) <= 1

    rows = _rows()
    assert len(rows) == 1
    assert rows[0]["status"] == "idle"
    assert rows[0]["end_time"] is None


def test_short_idle_merges_into_previous_normal_when_normal_resumes(temp_db):
    machine = CollectorStateMachine()
    machine.transition_to("recording", _normal("A"), at_time="2026-06-18 09:00:00")
    machine.transition_to("recording", _normal("A"), at_time="2026-06-18 09:01:00")
    machine.transition_to("idle", at_time="2026-06-18 09:05:00")
    machine.transition_to("recording", _normal("B"), at_time="2026-06-18 09:05:29")

    rows = _rows()
    assert len(rows) == 1
    assert rows[0]["window_title"] == "A"
    assert rows[0]["duration_seconds"] == 329
