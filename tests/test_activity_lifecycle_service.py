"""ActivityLifecycle Command Facade contract tests.

These tests verify the architecture invariants for the open-row state machine:

- ``activity_lifecycle_service`` owns open-row lifecycle transitions.
- ``activity_service`` remains a low-level CRUD helper and does not run project
  inference; the database rejects a second simultaneous open row.
- ``start_activity`` closes and finalizes the prior row before inserting the
  replacement.
- Manual assignments are never overridden.
- Clipboard binding is restricted to normal activity.
- Midnight and recovery paths preserve project assignment.
- An inference failure on one closed row does not block later rows.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from worktrace.constants import (
    SOURCE_AUTO,
    STATUS_NORMAL,
    TIME_FORMAT,
    UNCATEGORIZED_PROJECT,
)
from worktrace.services import (
    activity_service,
    folder_rule_service,
    project_service,
    recovery_service,
    session_boundary_service,
    settings_service,
)
from worktrace.services.activity_lifecycle_service import (
    close_activity as lifecycle_close_activity,
    finalize_closed_activity_ids,
    force_persist_open_activity_for_clipboard,
    persist_midnight_anchor,
    persist_open_activity,
    recover_cross_midnight_segment,
    start_activity,
)
from worktrace.services.project_inference_service import (
    get_assignment_for_activity,
    sync_persisted_open_activity_project,
)

pytestmark = [pytest.mark.db, pytest.mark.collector_runtime, pytest.mark.integration]


@pytest.fixture()
def temp_db_setup(temp_db):
    settings_service.clear_settings_cache()
    settings_service.set_setting("first_run_notice_accepted", "true")
    settings_service.clear_settings_cache()
    return temp_db


def test_start_activity_finalizes_closed_rows_with_folder_rule(temp_db_setup):
    pid = project_service.create_project("ProjA")
    folder_rule_service.create_or_update_folder_rule("D:\\ProjA", pid)

    first = activity_service.create_activity(
        "Word",
        "winword.exe",
        "Doc",
        start_time="2026-07-01 09:00:00",
        file_path_hint="D:\\ProjA\\spec.docx",
    )
    assert (
        activity_service.get_activity(first)["project_name"]
        == UNCATEGORIZED_PROJECT
    )

    second = start_activity(
        start_time="2026-07-01 09:10:00",
        source=SOURCE_AUTO,
        payload={
            "app_name": "Mail",
            "process_name": "mail.exe",
            "window_title": "Inbox",
            "status": STATUS_NORMAL,
        },
    )

    first_row = activity_service.get_activity(first)
    assert first_row["end_time"] == "2026-07-01 09:10:00"
    assignment = get_assignment_for_activity(first)
    assert int(assignment["project_id"]) == pid
    assert assignment["source"] == "folder_rule"
    assert activity_service.get_activity(second)["end_time"] is None


def test_start_activity_finalizes_closed_rows_manual_not_overridden(temp_db_setup):
    manual_pid = project_service.create_project("ManualProj")
    auto_pid = project_service.create_project("AutoProj")
    folder_rule_service.create_or_update_folder_rule("D:\\AutoFolder", auto_pid)

    first = activity_service.create_activity(
        "Word",
        "winword.exe",
        "Doc",
        start_time="2026-07-01 09:00:00",
        file_path_hint="D:\\AutoFolder\\spec.docx",
        project_id=manual_pid,
    )
    assert activity_service.get_activity(first)["project_name"] == "ManualProj"

    start_activity(
        start_time="2026-07-01 09:10:00",
        source=SOURCE_AUTO,
        payload={
            "app_name": "Mail",
            "process_name": "mail.exe",
            "window_title": "Inbox",
            "status": STATUS_NORMAL,
        },
    )

    assignment = get_assignment_for_activity(first)
    assert int(assignment["project_id"]) == manual_pid
    assert assignment["is_manual"] == 1


def test_create_activity_no_open_rows_does_not_fail(temp_db_setup):
    aid = activity_service.create_activity(
        "App",
        "app.exe",
        "Title",
        start_time="2026-07-01 09:00:00",
    )
    assert activity_service.get_activity(aid) is not None


def test_lifecycle_close_activity_triggers_inference(temp_db_setup):
    pid = project_service.create_project("ProjB")
    folder_rule_service.create_or_update_folder_rule("D:\\ProjB", pid)

    aid = activity_service.create_activity(
        "Word",
        "winword.exe",
        "Doc",
        start_time="2026-07-01 09:00:00",
        file_path_hint="D:\\ProjB\\spec.docx",
    )
    lifecycle_close_activity(aid, "2026-07-01 09:30:00")

    assignment = get_assignment_for_activity(aid)
    assert int(assignment["project_id"]) == pid
    assert assignment["source"] == "folder_rule"


def test_persist_open_activity_syncs_open_row_project(temp_db_setup):
    pid = project_service.create_project("ProjC")
    folder_rule_service.create_or_update_folder_rule("D:\\ProjC", pid)

    payload = {
        "app_name": "Word",
        "process_name": "winword.exe",
        "window_title": "Doc",
        "file_path_hint": "D:\\ProjC\\spec.docx",
        "status": STATUS_NORMAL,
    }
    aid = persist_open_activity(
        start_time="2026-07-01 09:00:00",
        source=SOURCE_AUTO,
        payload=payload,
    )
    assert aid is not None

    assignment = get_assignment_for_activity(aid)
    assert int(assignment["project_id"]) == pid
    assert assignment["source"] == "folder_rule"
    assert activity_service.get_activity(aid)["end_time"] is None


def test_force_persist_open_activity_for_clipboard_creates_open_row(temp_db_setup):
    payload = {
        "app_name": "Word",
        "process_name": "winword.exe",
        "window_title": "Doc",
        "status": STATUS_NORMAL,
    }
    aid = force_persist_open_activity_for_clipboard(
        start_time="2026-07-01 09:00:00",
        source=SOURCE_AUTO,
        payload=payload,
    )
    assert aid is not None
    row = activity_service.get_activity(aid)
    assert row is not None
    assert row["end_time"] is None


def test_force_persist_open_activity_for_clipboard_rejects_non_normal_status(
    temp_db_setup,
):
    from worktrace.constants import STATUS_IDLE

    payload = {
        "app_name": "Word",
        "process_name": "winword.exe",
        "window_title": "Doc",
        "status": STATUS_IDLE,
    }
    result = force_persist_open_activity_for_clipboard(
        start_time="2026-07-01 09:00:00",
        source=SOURCE_AUTO,
        payload=payload,
    )
    assert result is None


def test_persist_midnight_anchor_applies_midnight_anchor_assignment(temp_db_setup):
    pid = project_service.create_project("ProjD")
    payload = {
        "app_name": "Word",
        "process_name": "winword.exe",
        "window_title": "Doc",
        "status": STATUS_NORMAL,
    }
    aid = persist_midnight_anchor(
        start_time="2026-07-01 00:00:00",
        source=SOURCE_AUTO,
        payload=payload,
        project_id=pid,
    )
    assignment = get_assignment_for_activity(aid)
    assert int(assignment["project_id"]) == pid
    assert assignment["source"] == "midnight_anchor"
    assert activity_service.get_activity(aid)["end_time"] is None


def test_recover_cross_midnight_segment_creates_and_closes(temp_db_setup):
    pid = project_service.create_project("ProjE")
    payload = {
        "app_name": "Word",
        "process_name": "winword.exe",
        "window_title": "Doc",
    }
    aid = recover_cross_midnight_segment(
        start_time="2026-07-01 00:00:00",
        end_time="2026-07-01 02:00:00",
        source=SOURCE_AUTO,
        status=STATUS_NORMAL,
        payload=payload,
        project_id=pid,
    )
    row = activity_service.get_activity(aid)
    assert row["end_time"] == "2026-07-01 02:00:00"
    assert int(row["duration_seconds"]) == 7200

    assignment = get_assignment_for_activity(aid)
    assert int(assignment["project_id"]) == pid
    assert assignment["source"] == "midnight_anchor"


def test_recovery_cross_midnight_converges_project(temp_db_setup):
    pid = project_service.create_project("ProjF")
    settings_service.set_setting(
        "last_collector_heartbeat",
        "2026-07-02 00:10:00",
    )
    aid = activity_service.create_activity(
        "Word",
        "word.exe",
        "Doc",
        project_id=pid,
        start_time="2026-07-01 23:50:00",
    )

    recovery_service.recover_unclosed_records()

    first = activity_service.get_activity(aid)
    assert first["end_time"] == "2026-07-02 00:00:00"
    assert first["duration_seconds"] == 10 * 60

    rows = activity_service.get_activities_by_date("2026-07-02")
    assert len(rows) == 1
    assert rows[0]["start_time"] == "2026-07-02 00:00:00"
    assert rows[0]["end_time"] == "2026-07-02 00:10:00"
    assert rows[0]["project_id"] == pid
    segment_assignment = get_assignment_for_activity(rows[0]["id"])
    assert segment_assignment["source"] == "midnight_anchor"


def test_finalize_closed_activity_ids_empty_list_is_noop(temp_db_setup):
    finalize_closed_activity_ids([])
    finalize_closed_activity_ids(None)  # type: ignore[arg-type]


def test_finalize_closed_activity_ids_inference_failure_does_not_block(
    temp_db_setup,
    monkeypatch,
):
    pid = project_service.create_project("ProjG")
    folder_rule_service.create_or_update_folder_rule("D:\\ProjG", pid)

    aid1 = activity_service.create_activity(
        "Word",
        "winword.exe",
        "Doc1",
        start_time="2026-07-01 09:00:00",
        file_path_hint="D:\\ProjG\\a.docx",
    )
    activity_service.close_activity_row(aid1, "2026-07-01 09:05:00")
    aid2 = activity_service.create_activity(
        "Word",
        "winword.exe",
        "Doc2",
        start_time="2026-07-01 09:10:00",
        file_path_hint="D:\\ProjG\\b.docx",
    )
    activity_service.close_activity_row(aid2, "2026-07-01 09:20:00")

    call_count = [0]

    def flaky_process_new_activity(activity_id):
        call_count[0] += 1
        if call_count[0] == 1:
            raise RuntimeError("simulated inference failure")

    import worktrace.services.project_inference_service as pis

    monkeypatch.setattr(
        pis,
        "process_new_activity",
        flaky_process_new_activity,
    )
    finalize_closed_activity_ids([aid1, aid2])
    assert call_count[0] == 2


def test_persist_open_activity_persists_without_elapsed_gate(temp_db_setup):
    payload = {
        "app_name": "Word",
        "process_name": "winword.exe",
        "window_title": "Doc",
        "status": STATUS_NORMAL,
    }
    activity_id = persist_open_activity(
        start_time="2026-07-01 09:00:00",
        source=SOURCE_AUTO,
        payload=payload,
    )
    row = activity_service.get_activity(activity_id)
    assert row is not None
    assert row["start_time"] == "2026-07-01 09:00:00"
    assert row["end_time"] is None


def test_sync_persisted_open_activity_project_skips_missing_row(temp_db_setup):
    assert sync_persisted_open_activity_project(999999) is None


def test_start_activity_closes_prior_open_row_at_safe_time(temp_db_setup):
    first = activity_service.create_activity(
        "A",
        "a.exe",
        "A",
        start_time="2026-07-01 09:00:00",
    )
    second = start_activity(
        start_time="2026-07-01 09:05:00",
        source=SOURCE_AUTO,
        payload={
            "app_name": "B",
            "process_name": "b.exe",
            "window_title": "B",
            "status": STATUS_NORMAL,
        },
    )
    assert activity_service.get_activity(first)["end_time"] == "2026-07-01 09:05:00"
    assert activity_service.get_activity(second)["end_time"] is None


def test_recovery_records_boundary_before_cross_midnight_segment(temp_db_setup):
    settings_service.set_setting(
        "last_collector_heartbeat",
        "2026-07-02 00:10:00",
    )
    activity_service.create_activity(
        "Word",
        "word.exe",
        "Doc",
        start_time="2026-07-01 23:50:00",
    )
    recovery_service.recover_unclosed_records()
    boundaries = session_boundary_service.list_boundaries(
        "2026-07-01 23:00:00",
        "2026-07-02 01:00:00",
    )
    assert any(
        str(item.get("occurred_at") or "") == "2026-07-02 00:00:00"
        for item in boundaries
    )


def test_recovery_clamps_future_heartbeat_to_now(temp_db_setup, monkeypatch):
    now = datetime(2026, 7, 1, 10, 0, 0)
    future = now + timedelta(hours=1)
    settings_service.set_setting(
        "last_collector_heartbeat",
        future.strftime(TIME_FORMAT),
    )
    aid = activity_service.create_activity(
        "Word",
        "word.exe",
        "Doc",
        start_time="2026-07-01 09:50:00",
    )
    monkeypatch.setattr(recovery_service, "_now", lambda: now)
    recovery_service.recover_unclosed_records()
    row = activity_service.get_activity(aid)
    assert row["end_time"] == now.strftime(TIME_FORMAT)
