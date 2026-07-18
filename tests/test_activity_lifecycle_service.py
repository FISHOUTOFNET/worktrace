"""Activity lifecycle command boundary contract tests.

These tests verify the open-row state machine and durable inference handoff:

- ``activity_lifecycle_service`` owns open-row lifecycle transitions;
- activity closure and inference-job creation commit together;
- post-commit convergence enters the outbox worker rather than calling the
  assignment command directly;
- manual and midnight-anchor assignments are never overridden;
- clipboard binding is restricted to normal activity;
- one failed inference job does not block later jobs.
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
from tests.support import activity_factory as activity_service
from worktrace.db import get_connection
from worktrace.services import (
    activity_inference_job_repository,
    folder_rule_service,
    privacy_gate_service,
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
    pause_collection,
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
    privacy_gate_service.accept_privacy_notice()
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


def test_finalize_closed_activity_ids_failure_does_not_block_later_job(
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

    with get_connection() as conn:
        activity_inference_job_repository.enqueue_closed_activity_ids(
            conn,
            [aid1, aid2],
            at_time="2026-07-01 09:21:00",
        )

    import worktrace.services.project_inference_service as pis

    original = pis.assign_project_for_activity_in_transaction
    calls: list[int] = []

    def flaky_inference(conn, activity_id):
        calls.append(int(activity_id))
        if int(activity_id) == aid1:
            raise RuntimeError("simulated inference failure")
        return original(conn, activity_id)

    monkeypatch.setattr(
        pis,
        "assign_project_for_activity_in_transaction",
        flaky_inference,
    )
    finalize_closed_activity_ids([aid1, aid2])

    with get_connection() as conn:
        failed_job = conn.execute(
            "SELECT attempt_count FROM activity_inference_job WHERE activity_id = ?",
            (aid1,),
        ).fetchone()
        completed_job = conn.execute(
            "SELECT 1 FROM activity_inference_job WHERE activity_id = ?",
            (aid2,),
        ).fetchone()
    assert calls == [aid1, aid2]
    assert failed_job["attempt_count"] == 1
    assert completed_job is None
    assert int(get_assignment_for_activity(aid2)["project_id"]) == pid


def test_pause_collection_closes_open_row_and_is_idempotent(temp_db_setup):
    activity_id = persist_open_activity(
        start_time="2026-06-18 09:00:00",
        source=SOURCE_AUTO,
        payload={
            "app_name": "Edge",
            "process_name": "msedge.exe",
            "window_title": "Research",
            "status": STATUS_NORMAL,
        },
    )

    first = pause_collection(
        "2026-06-18 09:05:00",
        reason="pause_fallback",
    )
    second = pause_collection(
        "2026-06-18 09:06:00",
        reason="pause_fallback",
    )

    with get_connection() as conn:
        row = conn.execute(
            "SELECT end_time FROM activity_log WHERE id = ?", (activity_id,)
        ).fetchone()
        boundaries = conn.execute(
            "SELECT reason FROM session_boundary ORDER BY id"
        ).fetchall()
        open_count = conn.execute(
            "SELECT COUNT(*) AS c FROM activity_log WHERE end_time IS NULL"
        ).fetchone()["c"]
    assert first == [activity_id]
    assert second == []
    assert row["end_time"] == "2026-06-18 09:05:00"
    assert [item["reason"] for item in boundaries] == ["pause_fallback"]
    assert open_count == 0


def test_persist_open_activity_persists_without_elapsed_time(temp_db_setup):
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
    assert sync_persisted_open_activity_project(999999) == {}


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
    monkeypatch.setattr(
        recovery_service,
        "now_str",
        lambda: now.strftime(TIME_FORMAT),
    )
    recovery_service.recover_unclosed_records()
    row = activity_service.get_activity(aid)
    assert row["end_time"] == now.strftime(TIME_FORMAT)
