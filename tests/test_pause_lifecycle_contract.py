from __future__ import annotations

import threading

import pytest

from tests.support.application import TestMaintenance
from worktrace.api.app_api import ApplicationControlService
from worktrace.collector import collector as collector_module
from worktrace.collector.collector import run_collector
from worktrace.collector.state_machine import CollectorStateMachine
from worktrace.constants import SOURCE_AUTO, STATUS_NORMAL
from worktrace.data_generation_repository import (
    DataGenerationNamespace,
    DataGenerationRepository,
)
from worktrace.db import get_connection
from worktrace.platforms.base import ActiveWindow
from worktrace.platforms.fake_adapter import FakeAdapter
from worktrace.services import activity_lifecycle_service, runtime_activity_state_service
from worktrace.services.settings_service import (
    get_bool_setting,
    get_setting,
    set_setting,
)

pytestmark = [pytest.mark.db, pytest.mark.integration, pytest.mark.contract]


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


def test_missing_runtime_composition_is_rejected_without_business_mutation(temp_db):
    activity_id = _open_activity()
    runtime_activity_state_service.publish_runtime_activity_snapshot(
        {"status": STATUS_NORMAL},
        "test",
    )

    with pytest.raises(ValueError, match="application_runtime_required"):
        ApplicationControlService(None, TestMaintenance())  # type: ignore[arg-type]

    with get_connection() as conn:
        row = conn.execute(
            "SELECT end_time FROM activity_log WHERE id = ?",
            (activity_id,),
        ).fetchone()
        boundaries = conn.execute("SELECT reason FROM session_boundary").fetchall()
    assert row["end_time"] is None
    assert boundaries == []
    assert get_bool_setting("user_paused", False) is False
    assert runtime_activity_state_service.get_runtime_activity_snapshot() is not None


def test_normal_pause_uses_collector_state_machine_and_clears_runtime(temp_db):
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


def test_runtime_exception_pause_fails_without_business_fallback(temp_db):
    class FailingRuntime:
        def pause_collection_now(self):
            raise RuntimeError("runtime unavailable")

    activity_id = _open_activity()
    control = ApplicationControlService(FailingRuntime(), TestMaintenance())

    result = control.pause_collection_now()

    assert result == {
        "ok": False,
        "pause_pending": False,
        "error": "collector_pause_failed",
    }
    with get_connection() as conn:
        row = conn.execute(
            "SELECT end_time FROM activity_log WHERE id = ?",
            (activity_id,),
        ).fetchone()
        boundaries = conn.execute("SELECT reason FROM session_boundary").fetchall()
    assert row["end_time"] is None
    assert boundaries == []
    assert get_bool_setting("user_paused", False) is False


def test_repeated_missing_runtime_composition_is_side_effect_free(temp_db):
    for _ in range(2):
        with pytest.raises(ValueError, match="application_runtime_required"):
            ApplicationControlService(None, TestMaintenance())  # type: ignore[arg-type]

    with get_connection() as conn:
        boundaries = conn.execute(
            "SELECT reason FROM session_boundary ORDER BY id"
        ).fetchall()
    assert boundaries == []
    assert get_bool_setting("user_paused", False) is False


def test_pause_invalidates_hot_settings_cache_and_gates_next_collector_loop(
    temp_db,
    monkeypatch,
):
    set_setting("user_paused", "false")
    set_setting("collector_status", "running")
    assert get_bool_setting("user_paused", True) is False
    with get_connection() as conn:
        before = {
            namespace: DataGenerationRepository.get(conn, namespace)
            for namespace in (
                DataGenerationNamespace.SETTINGS,
                DataGenerationNamespace.REPORT_STRUCTURE,
            )
        }

    activity_lifecycle_service.pause_collection("2026-06-18 12:00:00")

    assert get_bool_setting("user_paused", False) is True
    with get_connection() as conn:
        after = {
            namespace: DataGenerationRepository.get(conn, namespace)
            for namespace in before
        }
    assert after == {namespace: value + 1 for namespace, value in before.items()}

    activity_lifecycle_service.pause_collection("2026-06-18 12:01:00")
    with get_connection() as conn:
        repeated = {
            namespace: DataGenerationRepository.get(conn, namespace)
            for namespace in before
        }
    assert repeated == after

    calls = {"window": 0, "idle": 0, "clipboard": 0}

    class GuardedAdapter(FakeAdapter):
        def get_active_window(self):
            calls["window"] += 1
            raise AssertionError("paused collector polled the active window")

        def get_idle_seconds(self):
            calls["idle"] += 1
            raise AssertionError("paused collector polled idle state")

        def get_clipboard_events(self):
            calls["clipboard"] += 1
            raise AssertionError("paused collector polled clipboard facts")

    stop_event = threading.Event()

    def stop_after_gate(_stop_event, _control, next_deadline):
        stop_event.set()
        return next_deadline

    monkeypatch.setattr(
        collector_module,
        "_sleep_until_next_poll",
        stop_after_gate,
    )
    run_collector(GuardedAdapter(), stop_event)
    assert calls == {"window": 0, "idle": 0, "clipboard": 0}


def test_pause_settings_failure_rolls_back_lifecycle_and_generations(
    temp_db,
    monkeypatch,
):
    activity_id = _open_activity()
    set_setting("user_paused", "false")
    set_setting("collector_status", "running")
    assert get_bool_setting("user_paused", True) is False
    with get_connection() as conn:
        before = {
            namespace: DataGenerationRepository.get(conn, namespace)
            for namespace in (
                DataGenerationNamespace.SETTINGS,
                DataGenerationNamespace.REPORT_STRUCTURE,
            )
        }
    original = activity_lifecycle_service.set_settings_in_transaction

    def fail_after_settings_write(uow, conn, values):
        original(uow, conn, values)
        raise RuntimeError("settings write failed")

    monkeypatch.setattr(
        activity_lifecycle_service,
        "set_settings_in_transaction",
        fail_after_settings_write,
    )
    with pytest.raises(RuntimeError, match="settings write failed"):
        activity_lifecycle_service.pause_collection("2026-06-18 13:00:00")

    with get_connection() as conn:
        activity = conn.execute(
            "SELECT end_time FROM activity_log WHERE id = ?",
            (activity_id,),
        ).fetchone()
        after = {
            namespace: DataGenerationRepository.get(conn, namespace)
            for namespace in before
        }
    assert activity["end_time"] is None
    assert get_bool_setting("user_paused", True) is False
    assert after == before
