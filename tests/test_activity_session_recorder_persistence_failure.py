from __future__ import annotations

import sqlite3

import pytest

from worktrace.collector import activity_session_recorder as recorder_module
from worktrace.collector.activity_session_recorder import ActivitySessionRecorder

pytestmark = [pytest.mark.unit, pytest.mark.collector_runtime]


def _unpersisted_recorder() -> ActivitySessionRecorder:
    recorder = ActivitySessionRecorder()
    recorder.current_payload = {"status": "normal"}
    recorder.current_start_time = "2026-06-18 09:00:00"
    recorder.current_last_seen_time = "2026-06-18 09:00:00"
    return recorder


def test_nonretryable_open_persistence_failure_is_not_retried_during_cleanup(
    monkeypatch,
):
    recorder = _unpersisted_recorder()
    attempts = 0

    def fail_insert(**_kwargs):
        nonlocal attempts
        attempts += 1
        raise sqlite3.IntegrityError("constraint")

    monkeypatch.setattr(recorder_module, "persist_open_activity", fail_insert)

    with pytest.raises(sqlite3.IntegrityError):
        recorder._ensure_persisted("2026-06-18 09:00:01")

    recorder._ensure_persisted("2026-06-18 09:00:02")
    assert attempts == 1
    assert recorder.persisted_activity_id is None


def test_retryable_open_persistence_failure_can_retry_next_observation(monkeypatch):
    recorder = _unpersisted_recorder()
    attempts = 0

    def transient_then_success(**_kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise sqlite3.OperationalError("database is locked")
        return 42

    monkeypatch.setattr(
        recorder_module,
        "persist_open_activity",
        transient_then_success,
    )

    with pytest.raises(sqlite3.OperationalError):
        recorder._ensure_persisted("2026-06-18 09:00:01")

    recorder._ensure_persisted("2026-06-18 09:00:02")
    assert attempts == 2
    assert recorder.persisted_activity_id == 42
