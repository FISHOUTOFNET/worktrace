from datetime import datetime

from worktrace.services.live_time_service import snapshot_elapsed_seconds, snapshot_total_seconds


def test_snapshot_elapsed_seconds_uses_start_time_with_controlled_clock():
    snapshot = {
        "start_time": "2026-06-18 09:00:00",
        "elapsed_seconds": 1,
        "extra_seconds": 2,
    }

    assert snapshot_elapsed_seconds(snapshot, now=datetime(2026, 6, 18, 9, 0, 5)) == 5
    assert snapshot_total_seconds(snapshot, now=datetime(2026, 6, 18, 9, 0, 5)) == 7


def test_snapshot_elapsed_seconds_falls_back_for_implausible_clock_gap():
    snapshot = {
        "start_time": "2026-06-18 09:00:00",
        "elapsed_seconds": 42,
    }

    assert snapshot_elapsed_seconds(snapshot, now=datetime(2026, 6, 20, 9, 0, 1)) == 42
