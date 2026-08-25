from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest

from tests.support import activity_factory as activity_service
from worktrace.collector import collector_health
from worktrace.platforms.fake_adapter import FakeAdapter
from worktrace.runtime import app_runtime
from worktrace.runtime.app_runtime import AppRuntime
from worktrace.services import activity_lifecycle_service, settings_service
from worktrace.worker_health import WorkerHealthRegistry


pytestmark = [pytest.mark.db, pytest.mark.collector_runtime, pytest.mark.integration]


def test_worker_progress_lease_covers_first_iteration_before_serving() -> None:
    now = {"value": 100.0}
    registry = WorkerHealthRegistry(monotonic_func=lambda: now["value"])
    health = registry.reporter("folder_index")

    health.started()
    assert registry.snapshots()["folder_index"].served is False
    assert registry.stalled_workers({"folder_index": 300.0}) == ()

    now["value"] = 401.0
    assert registry.stalled_workers({"folder_index": 300.0}) == ("folder_index",)


def test_collector_first_observation_gets_same_progress_lease(
    temp_db,
    monkeypatch,
) -> None:
    now = {"value": 100.0}
    monkeypatch.setattr(collector_health.time, "monotonic", lambda: now["value"])
    monkeypatch.setattr(app_runtime.time, "monotonic", lambda: now["value"])

    runtime = AppRuntime(
        SimpleNamespace(db_path="", log_path=""),
        adapter=FakeAdapter(),
    )
    runtime.owns_application_instance = True
    runtime._collector_generation = 7
    runtime._collector_ready_generation = 7
    runtime._collector_stop_event = threading.Event()

    thread_stop = threading.Event()
    thread = threading.Thread(target=thread_stop.wait, daemon=True)
    thread.start()
    runtime._collector_thread = thread

    collector_health.begin_runtime_invocation(7)
    collector_health.record_runtime_status("running")
    try:
        initial = runtime.collection_liveness_snapshot()
        assert initial["state"] == "starting"
        assert initial["live_eligible"] is False

        now["value"] = 109.0
        delayed = runtime.collection_liveness_snapshot()
        assert delayed["state"] == "degraded"
        assert delayed["reason"] == "collector_progress_delayed"
        assert delayed["live_eligible"] is False

        now["value"] = 281.0
        stale = runtime.collection_liveness_snapshot()
        assert stale["state"] == "stale"
        assert stale["reason"] == "collector_progress_stale"
        assert stale["live_eligible"] is False
    finally:
        collector_health.terminalize_runtime_invocation(7, "test_complete")
        thread_stop.set()
        thread.join(timeout=1.0)


def test_shutdown_uses_safe_checkpoint_not_legacy_heartbeat(
    temp_db,
    monkeypatch,
) -> None:
    runtime = AppRuntime(
        SimpleNamespace(db_path="", log_path=""),
        adapter=FakeAdapter(),
    )
    runtime.owns_application_instance = True
    runtime._initialized = True
    runtime._collector_generation = 11

    settings_service.set_setting("collector_last_successful_observation_at", "")
    settings_service.set_setting(
        "last_collector_heartbeat",
        "2026-08-24 09:30:00",
    )
    activity_id = activity_service.create_activity(
        "Word",
        "word.exe",
        "Draft.docx",
        start_time="2026-08-24 09:00:00",
    )
    assert activity_lifecycle_service.checkpoint_activity(activity_id, 120) is True

    collector_health.begin_runtime_invocation(11)
    collector_health.record_runtime_status("running")
    monkeypatch.setattr(app_runtime.db, "now_str", lambda: "2026-08-24 09:45:00")

    runtime.shutdown()

    row = activity_service.get_activity(activity_id)
    assert row["end_time"] == "2026-08-24 09:02:00"
    assert row["duration_seconds"] == 120
    assert settings_service.get_setting("last_shutdown_at") == "2026-08-24 09:45:00"
