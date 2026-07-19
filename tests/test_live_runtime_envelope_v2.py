from __future__ import annotations

from worktrace.services.live_runtime_envelope_service import _clock_payload, _recent_first_row


def test_v2_clock_separates_active_elapsed_from_aggregate_duration(monkeypatch):
    monkeypatch.setattr(
        "worktrace.services.live_runtime_envelope_service.time.time_ns",
        lambda: 12_000_000_000,
    )
    clock = _clock_payload(
        {
            "live_clock": {
                "display_span_id": "span:1",
                "stable_live_key_hash": "stable-1",
                "live_state": "persisted_open",
                "is_live": True,
                "current_live_seconds_at_sample": 5,
                "current_elapsed_at_sample": 5,
                "aggregate_display_base_seconds": 100,
                "aggregate_duration_seconds_at_sample": 105,
                "duration_seconds_at_sample": 105,
                "current_duration_live": True,
                "project_duration_live": True,
                "live_started_at_epoch_ms": 7_000,
            }
        },
        {"elapsed_seconds": 5},
    )

    assert clock["duration_seconds_at_sample"] == 5
    assert clock["current_live_duration_seconds"] == 5
    assert clock["current_elapsed_at_sample"] == 5
    assert clock["aggregate_display_base_seconds"] == 100
    assert clock["aggregate_duration_seconds_at_sample"] == 105
    assert clock["sample_epoch_ms"] == 12_000


def test_v2_recent_first_row_preserves_the_materialized_recent_shape():
    current = {
        "active": True,
        "activity_id": 41,
        "persisted_activity_id": 41,
        "is_in_progress": True,
        "stable_live_key_hash": "stable-1",
    }
    recent = {
        "row_kind": "project_session",
        "activity_id": 41,
        "duration_seconds": 105,
        "display_base_seconds": 100,
        "live_delta_eligible": True,
        "stable_live_key_hash": "stable-1",
    }

    assert _recent_first_row({"activities": [recent]}, current) == recent


def test_v2_recent_first_row_does_not_materialize_an_absent_recent_row():
    current = {
        "active": True,
        "activity_id": None,
        "persisted_activity_id": 0,
        "is_in_progress": False,
        "status": "idle",
    }

    assert _recent_first_row({"activities": []}, current) is None
