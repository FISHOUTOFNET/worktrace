"""Activity lifecycle contracts for durable closed-row inference."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from tests.support import activity_factory as activity_service
from worktrace.constants import SOURCE_AUTO, STATUS_NORMAL, TIME_FORMAT
from worktrace.db import get_connection
from worktrace.services import (
    activity_inference_job_service,
    folder_rule_service,
    privacy_gate_service,
    project_inference_service,
    project_service,
    recovery_service,
    session_boundary_service,
    settings_service,
)
from worktrace.services.activity_lifecycle_service import (
    close_activity,
    force_persist_open_activity_for_clipboard,
    pause_collection,
    persist_midnight_anchor,
    persist_open_activity,
    recover_cross_midnight_segment,
    start_activity,
)

pytestmark = [pytest.mark.db, pytest.mark.collector_runtime, pytest.mark.integration]


@pytest.fixture()
def temp_db_setup(temp_db):
    settings_service.clear_settings_cache()
    privacy_gate_service.accept_privacy_notice()
    settings_service.clear_settings_cache()
    return temp_db


def _job(activity_id: int):
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM activity_inference_job WHERE activity_id = ?",
            (int(activity_id),),
        ).fetchone()
    return dict(row) if row else None


def _consume(*activity_ids: int) -> int:
    return activity_inference_job_service.process_pending_inference_jobs(
        project_inference_service.assign_project_for_activity_in_transaction,
        limit=max(1, len(activity_ids) or 100),
        activity_ids=activity_ids or None,
    )


def test_start_activity_closes_prior_row_and_enqueues_in_same_command(temp_db_setup):
    project_id = project_service.create_project("ProjA")
    folder_rule_service.create_or_update_folder_rule("D:\\ProjA", project_id)
    first = activity_service.create_activity(
        "Word",
        "winword.exe",
        "Doc",
        start_time="2026-07-01 09:00:00",
        file_path_hint="D:\\ProjA\\spec.docx",
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

    assert activity_service.get_activity(first)["end_time"] == "2026-07-01 09:10:00"
    assert activity_service.get_activity(second)["end_time"] is None
    assert _job(first)["status"] == "pending"
    assert _job(second) is None
    assert project_inference_service.get_assignment_for_activity(first) == {}

    assert _consume(first) == 1
    assignment = project_inference_service.get_assignment_for_activity(first)
    assert int(assignment["project_id"]) == project_id
    assert assignment["source"] == "folder_rule"
    assert _job(first) is None


def test_close_activity_enqueues_without_immediate_consumer(temp_db_setup):
    project_id = project_service.create_project("ProjB")
    folder_rule_service.create_or_update_folder_rule("D:\\ProjB", project_id)
    activity_id = activity_service.create_activity(
        "Word",
        "winword.exe",
        "Doc",
        start_time="2026-07-01 09:00:00",
        file_path_hint="D:\\ProjB\\spec.docx",
    )

    close_activity(activity_id, "2026-07-01 09:30:00")

    assert _job(activity_id)["reason"] == "closed_activity"
    assert project_inference_service.get_assignment_for_activity(activity_id) == {}
    _consume(activity_id)
    assignment = project_inference_service.get_assignment_for_activity(activity_id)
    assert int(assignment["project_id"]) == project_id


def test_manual_assignment_is_not_enqueued_or_overwritten(temp_db_setup):
    manual_project_id = project_service.create_project("ManualProj")
    activity_id = activity_service.create_activity(
        "Word",
        "winword.exe",
        "Doc",
        start_time="2026-07-01 09:00:00",
        project_id=manual_project_id,
    )

    close_activity(activity_id, "2026-07-01 09:10:00")

    assert _job(activity_id) is None
    assignment = project_inference_service.get_assignment_for_activity(activity_id)
    assert int(assignment["project_id"]) == manual_project_id
    assert assignment["is_manual"] == 1


def test_persist_open_activity_uses_only_open_row_sync(temp_db_setup):
    project_id = project_service.create_project("ProjC")
    folder_rule_service.create_or_update_folder_rule("D:\\ProjC", project_id)
    activity_id = persist_open_activity(
        start_time="2026-07-01 09:00:00",
        source=SOURCE_AUTO,
        payload={
            "app_name": "Word",
            "process_name": "winword.exe",
            "window_title": "Doc",
            "file_path_hint": "D:\\ProjC\\spec.docx",
            "status": STATUS_NORMAL,
        },
    )

    assignment = project_inference_service.get_assignment_for_activity(activity_id)
    assert int(assignment["project_id"]) == project_id
    assert assignment["source"] == "folder_rule"
    assert activity_service.get_activity(activity_id)["end_time"] is None
    assert _job(activity_id) is None


def test_clipboard_open_row_creation_rejects_non_normal_status(temp_db_setup):
    from worktrace.constants import STATUS_IDLE

    assert force_persist_open_activity_for_clipboard(
        start_time="2026-07-01 09:00:00",
        source=SOURCE_AUTO,
        payload={
            "app_name": "Word",
            "process_name": "winword.exe",
            "window_title": "Doc",
            "status": STATUS_IDLE,
        },
    ) is None


def test_midnight_anchor_is_preserved_and_never_enqueued(temp_db_setup):
    project_id = project_service.create_project("ProjD")
    activity_id = persist_midnight_anchor(
        start_time="2026-07-01 00:00:00",
        source=SOURCE_AUTO,
        payload={
            "app_name": "Word",
            "process_name": "winword.exe",
            "window_title": "Doc",
            "status": STATUS_NORMAL,
        },
        project_id=project_id,
    )
    close_activity(activity_id, "2026-07-01 02:00:00")

    assignment = project_inference_service.get_assignment_for_activity(activity_id)
    assert int(assignment["project_id"]) == project_id
    assert assignment["source"] == "midnight_anchor"
    assert _job(activity_id) is None


def test_recovery_cross_midnight_segment_preserves_anchor(temp_db_setup):
    project_id = project_service.create_project("ProjE")
    activity_id = recover_cross_midnight_segment(
        start_time="2026-07-01 00:00:00",
        end_time="2026-07-01 02:00:00",
        source=SOURCE_AUTO,
        status=STATUS_NORMAL,
        payload={
            "app_name": "Word",
            "process_name": "winword.exe",
            "window_title": "Doc",
        },
        project_id=project_id,
    )
    row = activity_service.get_activity(activity_id)
    assignment = project_inference_service.get_assignment_for_activity(activity_id)
    assert row["end_time"] == "2026-07-01 02:00:00"
    assert int(row["duration_seconds"]) == 7200
    assert int(assignment["project_id"]) == project_id
    assert assignment["source"] == "midnight_anchor"
    assert _job(activity_id) is None


def test_pause_collection_closes_and_enqueues_once(temp_db_setup):
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

    first = pause_collection("2026-06-18 09:05:00", reason="pause_fallback")
    second = pause_collection("2026-06-18 09:06:00", reason="pause_fallback")

    with get_connection() as conn:
        boundaries = conn.execute(
            "SELECT reason FROM session_boundary ORDER BY id"
        ).fetchall()
    assert first == [activity_id]
    assert second == []
    assert activity_service.get_activity(activity_id)["end_time"] == "2026-06-18 09:05:00"
    assert [item["reason"] for item in boundaries] == ["pause_fallback"]
    assert _job(activity_id) is not None


def test_recovery_records_boundary_and_enqueues_non_anchor_closed_row(temp_db_setup):
    settings_service.set_setting("last_collector_heartbeat", "2026-07-02 00:10:00")
    activity_id = activity_service.create_activity(
        "Word",
        "word.exe",
        "Doc",
        start_time="2026-07-01 23:50:00",
    )

    recovery_service.recover_unclosed_records()

    row = activity_service.get_activity(activity_id)
    boundaries = session_boundary_service.list_boundaries(
        "2026-07-01 23:00:00",
        "2026-07-02 01:00:00",
    )
    assert row["end_time"] == "2026-07-02 00:00:00"
    assert row["duration_seconds"] == 600
    assert _job(activity_id) is not None
    assert any(
        str(item.get("occurred_at") or "") == "2026-07-02 00:00:00"
        for item in boundaries
    )


def test_recovery_clamps_future_heartbeat_to_now(temp_db_setup, monkeypatch):
    now = datetime(2026, 7, 1, 10, 0, 0)
    settings_service.set_setting(
        "last_collector_heartbeat",
        (now + timedelta(hours=1)).strftime(TIME_FORMAT),
    )
    activity_id = activity_service.create_activity(
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

    assert activity_service.get_activity(activity_id)["end_time"] == now.strftime(TIME_FORMAT)
