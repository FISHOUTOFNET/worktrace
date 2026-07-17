from __future__ import annotations

import pytest

from worktrace.collector import collector_health, heartbeat
from worktrace.data_generation_repository import (
    DataGenerationNamespace,
    DataGenerationRepository,
)
from worktrace.db import get_connection

pytestmark = [pytest.mark.db, pytest.mark.integration, pytest.mark.contract]


def _generations() -> dict[DataGenerationNamespace, int]:
    with get_connection() as conn:
        return {
            namespace: DataGenerationRepository.get(conn, namespace)
            for namespace in DataGenerationNamespace
        }


def test_healthy_observations_persist_at_bounded_frequency(temp_db, monkeypatch):
    calls: list[dict[str, str]] = []
    original = collector_health.set_settings

    def capture(values):
        calls.append(dict(values))
        original(values)

    monkeypatch.setattr(collector_health, "set_settings", capture)
    collector_health.record_collector_started("2026-07-17 09:00:00")
    calls.clear()

    collector_health.record_successful_observation("2026-07-17 09:00:00")
    collector_health.record_successful_observation("2026-07-17 09:00:01")
    collector_health.record_successful_observation("2026-07-17 09:00:29")
    collector_health.record_successful_observation("2026-07-17 09:00:30")

    assert len(calls) == 2
    assert all("collector_last_successful_observation_at" in values for values in calls)


def test_transient_failure_is_one_operational_transaction(temp_db, monkeypatch):
    calls: list[dict[str, str]] = []
    original = collector_health.set_settings

    def capture(values):
        calls.append(dict(values))
        original(values)

    monkeypatch.setattr(collector_health, "set_settings", capture)
    collector_health.record_collector_started("2026-07-17 10:00:00")
    calls.clear()

    collector_health.record_transient_failure(
        "active_window",
        RuntimeError("adapter failed"),
        "2026-07-17 10:00:01",
    )

    assert len(calls) == 1
    assert calls[0]["collector_health_state"] == "degraded"
    assert calls[0]["collector_consecutive_failures"] == "1"


def test_heartbeat_persistence_is_throttled_per_database(temp_db, monkeypatch):
    calls: list[dict[str, str]] = []
    original = heartbeat.set_settings
    ticks = iter((1.0, 2.0, 31.0))

    def capture(values):
        calls.append(dict(values))
        original(values)

    monkeypatch.setattr(heartbeat, "set_settings", capture)
    monkeypatch.setattr(heartbeat.time, "monotonic", lambda: next(ticks))

    heartbeat.update_heartbeat("running")
    heartbeat.update_heartbeat("running")
    heartbeat.update_heartbeat("running")

    assert len(calls) == 2


def test_operational_health_updates_do_not_publish_business_generations(temp_db):
    before = _generations()

    collector_health.record_collector_started("2026-07-17 11:00:00")
    collector_health.record_successful_observation("2026-07-17 11:00:01")
    collector_health.record_transient_failure(
        "privacy",
        RuntimeError("privacy failed"),
        "2026-07-17 11:00:02",
    )

    assert _generations() == before
