from __future__ import annotations

import pytest

from worktrace.retry_state import RetryEpisode

pytestmark = pytest.mark.unit


def test_retry_episode_bounds_backoff_and_throttles_repeated_detail_logs():
    now = {"value": 100.0}
    episode = RetryEpisode(
        initial_delay_seconds=1.0,
        max_delay_seconds=4.0,
        summary_interval_seconds=10.0,
        monotonic_func=lambda: now["value"],
    )

    first = episode.failed("database_busy")
    assert first.attempt == 1
    assert first.delay_seconds == 1.0
    assert first.detail_log_due is True
    assert first.summary_log_due is False

    now["value"] += 1.0
    second = episode.failed("database_busy")
    assert second.attempt == 2
    assert second.delay_seconds == 2.0
    assert second.detail_log_due is False
    assert second.summary_log_due is False

    now["value"] += 10.0
    third = episode.failed("database_busy")
    assert third.attempt == 3
    assert third.delay_seconds == 4.0
    assert third.summary_log_due is True

    recovery = episode.succeeded()
    assert recovery.recovered is True
    assert recovery.code == "database_busy"
    assert recovery.attempts == 3

    restarted = episode.failed("database_busy")
    assert restarted.attempt == 1
    assert restarted.detail_log_due is True


def test_retry_episode_treats_code_change_as_new_diagnostic_detail():
    episode = RetryEpisode(initial_delay_seconds=0.0, max_delay_seconds=0.0)
    episode.failed("database_busy")
    changed = episode.failed("database_generation_changed")
    assert changed.attempt == 1
    assert changed.code_changed is True
    assert changed.detail_log_due is True
    assert changed.delay_seconds == 0.0
