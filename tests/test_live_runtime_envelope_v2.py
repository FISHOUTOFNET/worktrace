from __future__ import annotations

import pytest

from worktrace.services.live_runtime_envelope_service import (
    _recent_first_row,
    _require_live_clock,
)


EXACT_CLOCK = {
    "sampled_at_epoch_ms": 12_000,
    "started_at_epoch_ms": 7_000,
    "elapsed_seconds_at_sample": 5,
    "aggregate_base_seconds": 100,
    "duration_semantic": "aggregate_live",
    "is_live": True,
    "live_state": "persisted_open",
    "display_span_id": "span:1",
    "stable_live_key_hash": "stable-1",
}


def test_v2_clock_accepts_only_the_exact_transport_contract():
    assert _require_live_clock({"live_clock": EXACT_CLOCK}) == EXACT_CLOCK


def test_v2_clock_rejects_missing_alias_negative_and_invalid_live_state():
    missing = dict(EXACT_CLOCK)
    missing.pop("elapsed_seconds_at_sample")
    with pytest.raises(ValueError, match="live_clock_invalid_keys"):
        _require_live_clock({"live_clock": missing})

    alias = dict(EXACT_CLOCK)
    alias["duration_seconds_at_sample"] = 105
    with pytest.raises(ValueError, match="live_clock_invalid_keys"):
        _require_live_clock({"live_clock": alias})

    negative = dict(EXACT_CLOCK)
    negative["aggregate_base_seconds"] = -1
    with pytest.raises(ValueError, match="live_clock_invalid_values"):
        _require_live_clock({"live_clock": negative})

    invalid_state = dict(EXACT_CLOCK)
    invalid_state["live_state"] = "none"
    with pytest.raises(ValueError, match="live_clock_invalid_live_state"):
        _require_live_clock({"live_clock": invalid_state})


def test_v2_recent_first_row_is_static_metadata_only():
    recent = {
        "row_kind": "project_session",
        "activity_id": 41,
        "duration_seconds": 105,
        "live_clock": dict(EXACT_CLOCK),
        "display_span_id": "duplicate",
        "stable_live_key_hash": "duplicate",
    }
    assert _recent_first_row({"activities": [recent]}) == {
        "row_kind": "project_session",
        "activity_id": 41,
        "duration_seconds": 105,
    }


def test_v2_recent_first_row_does_not_materialize_an_absent_recent_row():
    assert _recent_first_row({"activities": []}) is None
