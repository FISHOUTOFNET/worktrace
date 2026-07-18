from __future__ import annotations

import pytest

from worktrace.api import app_api
from worktrace.collector.state_machine import CollectorStateMachine
from worktrace.constants import SOURCE_AUTO, STATUS_NORMAL
from worktrace.db import get_connection
from worktrace.platforms.base import ActiveWindow
from worktrace.services import activity_lifecycle_service, runtime_activity_state_service
from worktrace.services.settings_service import get_bool_setting, get_setting

pytestmark = [pytest.mark.db, pytest.mark.integration, pytest.mark.contract]


@pytest.fixture(autouse=True)
def _restore_runtime():
    previous = app_api.get_runtime()
    app_api.set_runtime(None)
    try:
        yield
    finally:
        app_api.set_runtime(previous)


def _open_activity() -> int:
    return activity_lifecycle_service.persist_open_activity(
        start_time="2026-06-18 09:00:00",
        source=SOURCE_AUTO,
        payload={
            "app_name": "Edge",
            "process_name": "msedge.exe",
            "window_title": "Research",
            "status": STATUS_NORMAL,
        },
    )


def _assert_paused_without_open_activity() -> None:
    with get_connection() as conn:
        open_count = conn.execute(
            "SELECT COUNT(*) AS c FROM activity_log WHERE end_time IS NULL"
        ).fetchone()["c"]
    assert open_count == 0
    assert get_bool_setting("user_paused", False) is True
    assert get_setting("collector_status", "") == "paused"
    assert runtime_activity_state_service.get_runtime_activity_snapshot() is None


def test_runtime_missing_pause_uses_lifecycle_owner(temp_db):
    _open_activity()
    runtime_activity_state_service.publish_runtime_activity_snapshot(
        {"status": STATUS_NORMAL},
        "test",
    )

    result = app_api.pause_collection_now()

    assert result == {"ok": False, "pause_pending": True}
    _assert_paused_without_open_activity()


def test_normal_pause_uses_lifecycle_owner_and_clears_runtime(temp_db):
    machine = CollectorStateMachine()
    machine.transition_to(
        "recording",
        ActiveWindow("Edge", "msedge.exe", "Research"),
        at_time="2026-06-18 09:00:00",
    )

    machine.pause(at_time="2026-06-18 09:05:00")
    machine.pause(at_time="2026-06-18 09:06:00")

    with get_connection() as conn:
        boundaries = conn.execute(
            "SELECT reason FROM session_boundary ORDER BY id"
        ).fetchall()
    assert [row["reason"] for row in boundaries] == ["user_pause"]
    _assert_paused_without_open_activity()


def test_runtime_exception_pause_uses_same_lifecycle_owner(temp_db):
    class FailingRuntime:
        def pause_collection_now(self):
            raise RuntimeError("runtime unavailable")

    _open_activity()
    app_api.set_runtime(FailingRuntime())

    result = app_api.pause_collection_now()

    assert result == {"ok": False, "pause_pending": True}
    _assert_paused_without_open_activity()


def test_pause_without_open_row_and_repeated_pause_are_idempotent(temp_db):
    first = app_api.pause_collection_now()
    second = app_api.pause_collection_now()

    with get_connection() as conn:
        boundaries = conn.execute(
            "SELECT reason FROM session_boundary ORDER BY id"
        ).fetchall()
    assert first == second == {"ok": False, "pause_pending": True}
    assert [row["reason"] for row in boundaries] == ["pause_fallback"]
    _assert_paused_without_open_activity()
