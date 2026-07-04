from __future__ import annotations

from tests.support.db_helpers import assignment_row


def assert_live_clock_state(payload: dict, expected_state: str) -> dict:
    live_clock = payload.get("live_clock")
    assert isinstance(live_clock, dict), "payload must include live_clock"
    assert live_clock.get("live_state") == expected_state
    return live_clock


def assert_duration_seconds(row: dict, expected_seconds: int) -> None:
    assert int(row.get("duration_seconds") or 0) == expected_seconds


def assert_assignment(activity_id: int, *, project_id: int, is_manual: bool | None = None) -> dict:
    row = assignment_row(activity_id)
    assert row is not None, "activity assignment row must exist"
    assert int(row["project_id"]) == int(project_id)
    if is_manual is not None:
        assert bool(row["is_manual"]) is bool(is_manual)
    return row


def assert_privacy_redacted(payload: object, forbidden_fragments: list[str]) -> None:
    text = repr(payload).lower()
    for fragment in forbidden_fragments:
        assert fragment.lower() not in text


def assert_api_error_envelope(result: dict, expected_error: str) -> None:
    assert result == {"ok": False, "error": expected_error}
