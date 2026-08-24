from __future__ import annotations

import sqlite3
import threading
from types import SimpleNamespace

import pytest

from worktrace.collector import collector as collector_module
from worktrace.collector.collector import run_collector
from worktrace.collector.collector_failure_policy import CollectorFailureCode
from worktrace.platforms.fake_adapter import FakeAdapter


pytestmark = [pytest.mark.db, pytest.mark.collector_runtime, pytest.mark.integration]


def _fake_machine():
    return SimpleNamespace(
        transition_to=lambda *_args, **_kwargs: None,
        reset_runtime_state=lambda *_args, **_kwargs: None,
        stop=lambda *_args, **_kwargs: None,
    )


def test_collector_reports_ready_before_sqlite_backed_startup_health(temp_db, monkeypatch) -> None:
    entered_health_write = threading.Event()
    release_health_write = threading.Event()
    stop_event = threading.Event()
    ready_event = threading.Event()
    failed_event = threading.Event()

    monkeypatch.setattr(collector_module, "CollectorStateMachine", _fake_machine)
    monkeypatch.setattr(collector_module, "ClockTracker", lambda: object())
    monkeypatch.setattr(
        collector_module.collector_health,
        "record_collector_started",
        lambda *_args: (entered_health_write.set(), release_health_write.wait(1.0)),
    )
    monkeypatch.setattr(
        collector_module.collector_health,
        "record_collector_stopped",
        lambda *_args: None,
    )
    monkeypatch.setattr(collector_module, "_normalize_poll_interval_setting", lambda: None)
    monkeypatch.setattr(collector_module, "_run_clipboard_maintenance_tick", lambda: None)

    thread = threading.Thread(
        target=run_collector,
        args=(FakeAdapter(), stop_event, None, ready_event, failed_event),
        daemon=True,
    )
    thread.start()
    try:
        assert ready_event.wait(0.5)
        assert entered_health_write.wait(0.5)
        assert failed_event.is_set() is False
    finally:
        stop_event.set()
        release_health_write.set()
        thread.join(timeout=1.0)

    assert not thread.is_alive()


def test_collector_retries_database_busy_during_startup_runtime_work(temp_db, monkeypatch) -> None:
    stop_event = threading.Event()
    ready_event = threading.Event()
    failed_event = threading.Event()
    attempts = 0

    monkeypatch.setattr(collector_module, "CollectorStateMachine", _fake_machine)
    monkeypatch.setattr(collector_module, "ClockTracker", lambda: object())
    monkeypatch.setattr(
        collector_module.collector_health,
        "record_collector_stopped",
        lambda *_args: None,
    )
    monkeypatch.setattr(collector_module, "_set_clipboard_capture_enabled", lambda *_args: None)
    monkeypatch.setattr(
        collector_module,
        "_wait_for_poll_delay",
        lambda *_args: None,
    )

    def transient_start(*_args) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            error = sqlite3.OperationalError("database is locked")
            error.sqlite_errorcode = sqlite3.SQLITE_BUSY
            raise error
        stop_event.set()

    monkeypatch.setattr(
        collector_module.collector_health,
        "record_collector_started",
        transient_start,
    )
    monkeypatch.setattr(collector_module, "_normalize_poll_interval_setting", lambda: None)
    monkeypatch.setattr(collector_module, "_run_clipboard_maintenance_tick", lambda: None)

    run_collector(
        FakeAdapter(),
        stop_event,
        None,
        ready_event,
        failed_event,
    )

    assert ready_event.is_set()
    assert failed_event.is_set() is False
    assert attempts == 2
    disposition = collector_module.classify_collector_failure(
        sqlite3.OperationalError("database is locked")
    )
    assert disposition.code is CollectorFailureCode.DATABASE_BUSY
    assert disposition.retryable is True
