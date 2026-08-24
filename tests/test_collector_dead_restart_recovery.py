from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest

from tests.support import activity_factory as activity_service
from worktrace.collector import collector_health
from worktrace.db import get_connection
from worktrace.platforms.fake_adapter import FakeAdapter
from worktrace.runtime import app_runtime
from worktrace.runtime.app_runtime import AppRuntime

pytestmark = [pytest.mark.db, pytest.mark.collector_runtime, pytest.mark.integration]


def test_dead_collector_reconciles_open_fact_before_replacement_thread_starts(
    temp_db,
    monkeypatch,
):
    runtime = AppRuntime(
        SimpleNamespace(db_path="", log_path=""),
        adapter=FakeAdapter(),
    )
    runtime.owns_application_instance = True
    runtime._collector_generation = 7
    collector_health.begin_runtime_invocation(7)
    collector_health.record_successful_observation("2026-06-18 09:10:00")
    activity_id = activity_service.create_activity(
        "Word",
        "word.exe",
        "Draft",
        start_time="2026-06-18 09:00:00",
    )

    dead = threading.Thread(target=lambda: None)
    dead.start()
    dead.join(timeout=1)
    runtime._collector_thread = dead

    open_counts_at_start: list[int] = []

    def fake_run_collector(
        _adapter,
        stop_event,
        _control,
        startup_ready_event,
        _startup_failed_event,
    ):
        with get_connection() as conn:
            open_counts_at_start.append(
                int(
                    conn.execute(
                        "SELECT COUNT(*) AS value FROM activity_log WHERE end_time IS NULL"
                    ).fetchone()["value"]
                )
            )
        collector_health.record_collector_started()
        startup_ready_event.set()
        stop_event.wait(2)

    monkeypatch.setattr(app_runtime, "run_collector", fake_run_collector)

    result = runtime.start_collector()
    try:
        assert result == {
            "ok": True,
            "started": True,
            "already_running": False,
        }
        assert open_counts_at_start == [0]
        recovered = activity_service.get_activity(activity_id)
        assert recovered["end_time"] == "2026-06-18 09:10:00"
        assert recovered["duration_seconds"] == 600
    finally:
        runtime.request_shutdown()
        assert runtime._collector_thread is not None
        runtime._collector_thread.join(timeout=2)
