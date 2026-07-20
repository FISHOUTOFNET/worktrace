"""A small product matrix for persisted-open, status-only, and fail-closed."""

from __future__ import annotations

import pytest

from tests.support.live_semantics_harness import LiveSemanticsHarness


pytestmark = [pytest.mark.contract, pytest.mark.integration, pytest.mark.db, pytest.mark.live_display]


@pytest.fixture()
def live(temp_db, monkeypatch) -> LiveSemanticsHarness:
    return LiveSemanticsHarness(monkeypatch)


def test_normal_activity_is_persisted_open_on_its_first_sample(live):
    live.record("A", "09:00:00")
    rows = live.rows()
    assert len(rows) == 1 and rows[0]["end_time"] is None
    pages = live.pages(details_ids=[int(rows[0]["id"])])
    assert pages["overview"]["runtime"]["clock"]["live_state"] == "persisted_open"
    assert pages["timeline"]["entries"][0]["open_activity_id"] == rows[0]["id"]


def test_window_switch_closes_the_previous_row_and_opens_its_own_row(live):
    live.record("A", "09:00:00")
    live.record("B", "09:00:10")
    rows = live.rows()
    by_title = {row["window_title"]: row for row in rows}
    assert set(by_title) == {"A", "B"}
    assert by_title["A"]["duration_seconds"] == 10
    assert by_title["B"]["end_time"] is None


@pytest.mark.parametrize("state", ["paused", "idle", "excluded", "error"])
def test_non_normal_states_are_status_only(state, live):
    live.record("A", "09:00:00")
    if state == "paused":
        live.pause("09:00:10")
    else:
        live.status(state, "09:00:10")
    overview = live.pages()["overview"]
    expected_live_state = "none" if state == "paused" else "suppressed"
    assert overview["runtime"]["clock"]["live_state"] == expected_live_state
