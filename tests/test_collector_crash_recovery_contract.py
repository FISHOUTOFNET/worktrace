from __future__ import annotations

import pytest

from tests.support import activity_factory as activity_service
from worktrace.services import recovery_service, runtime_activity_state_service
from worktrace.services.page_read_context import page_read_scope
from worktrace.services import session_boundary_service

pytestmark = [pytest.mark.db, pytest.mark.collector_runtime, pytest.mark.integration]


def test_collector_crash_recovery_seals_open_fact_without_process_restart_boundary(temp_db):
    activity_id = activity_service.create_activity(
        "Word",
        "word.exe",
        "Draft",
        start_time="2026-06-18 09:00:00",
    )

    first = recovery_service.recover_after_collector_crash(
        "2026-06-18 09:05:00"
    )

    assert first["ok"] is True
    assert first["recovered_open_activities"] == 1
    row = activity_service.get_activity(activity_id)
    assert row["end_time"] == "2026-06-18 09:05:00"
    assert row["duration_seconds"] == 300
    boundaries = session_boundary_service.list_boundaries(
        "2026-06-18 09:00:00",
        "2026-06-18 09:10:00",
    )
    assert ("2026-06-18 09:05:00", "recovered") in [
        (item["occurred_at"], item["reason"]) for item in boundaries
    ]
    assert all(item["reason"] != "restart" for item in boundaries)

    second = recovery_service.recover_after_collector_crash(
        "2026-06-18 09:06:00"
    )
    assert second["ok"] is True
    assert second["recovered_open_activities"] == 0


def test_page_read_scope_suppresses_matching_open_snapshot_when_runtime_not_live(temp_db):
    activity_id = activity_service.create_activity(
        "Word",
        "word.exe",
        "Draft",
        start_time="2026-06-18 09:00:00",
    )
    runtime_activity_state_service.publish_runtime_activity_snapshot(
        {
            "status": "normal",
            "is_persisted": True,
            "persisted_activity_id": activity_id,
            "start_time": "2026-06-18 09:00:00",
        },
        "test_stale_snapshot",
    )

    with page_read_scope(collection_live_eligible=False) as context:
        assert context.collection_live_eligible is False
        assert context.runtime_consistent is True
        assert context.verified_open_activity_id == activity_id
        assert context.runtime_sample.snapshot is None
