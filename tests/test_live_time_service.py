from datetime import datetime

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.live_display, pytest.mark.parallel_safe]

from worktrace.services.live_time_service import snapshot_elapsed_seconds, snapshot_total_seconds


def test_snapshot_elapsed_seconds_uses_snapshot_sample_not_current_clock():
    snapshot = {
        "start_time": "2026-06-18 09:00:00",
        "elapsed_seconds": 1,
    }

    assert snapshot_elapsed_seconds(snapshot, now=datetime(2026, 6, 18, 9, 0, 5)) == 1
    assert snapshot_total_seconds(snapshot, now=datetime(2026, 6, 18, 9, 0, 5)) == 1


def test_snapshot_elapsed_seconds_is_not_recomputed_from_wall_clock_gap():
    snapshot = {
        "start_time": "2026-06-18 09:00:00",
        "elapsed_seconds": 42,
    }

    assert snapshot_elapsed_seconds(snapshot, now=datetime(2026, 6, 20, 9, 0, 1)) == 42
