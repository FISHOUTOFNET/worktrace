from __future__ import annotations

import pytest

from tests.support.live_semantics_harness import LiveSemanticsHarness
from worktrace.services import statistics_service

pytestmark = [
    pytest.mark.contract,
    pytest.mark.integration,
    pytest.mark.db,
    pytest.mark.live_display,
]


@pytest.fixture()
def live(temp_db, monkeypatch) -> LiveSemanticsHarness:
    return LiveSemanticsHarness(monkeypatch)


def _clock(payload: dict) -> dict:
    return payload.get("live_clock") or {}


def _same_live_identity(*payloads: dict) -> None:
    spans = {str(_clock(p).get("display_span_id") or "") for p in payloads}
    hashes = {str(_clock(p).get("stable_live_key_hash") or "") for p in payloads}
    spans.discard("")
    hashes.discard("")
    assert len(spans) <= 1, "all live-bearing views must share one display_span_id"
    assert len(hashes) <= 1, "all live-bearing views must share one stable_live_key_hash"


def test_first_normal_under_30s_is_current_only_without_history_pollution(live):
    live.record("A", "09:00:00")
    live.record("A", "09:00:20")

    pages = live.pages()
    assert live.rows() == [], "a first <30s normal activity must not enter DB history"
    assert pages["overview"]["current_activity"]["elapsed_seconds"] == 20
    assert pages["overview"]["current_activity"]["display_base_seconds"] == 0
    assert _clock(pages["overview"])["live_state"] == "current_only_pending"
    assert pages["overview"]["activities"] == []
    assert pages["timeline"]["sessions"] == []
    assert pages["overview"]["today_total_seconds"] == 0
    _same_live_identity(pages["overview"], pages["recent"], pages["timeline"], pages["refresh"])


def test_first_normal_at_30s_uses_one_persisted_identity_everywhere(live):
    live.record("A", "09:00:00")
    live.record("A", "09:00:30")
    rows = live.rows()
    assert len(rows) == 1, ">=30s normal activity must be persisted as one open row"
    activity_id = int(rows[0]["id"])

    pages = live.pages(details_ids=[activity_id])
    assert _clock(pages["overview"])["live_state"] == "persisted_open"
    assert pages["overview"]["activities"][0]["activity_id"] == activity_id
    assert pages["timeline"]["sessions"][0]["open_activity_id"] == activity_id
    assert pages["details"]["activities"][0]["activity_id"] == activity_id
    _same_live_identity(pages["overview"], pages["timeline"], pages["details"], pages["refresh"])


def test_anchor_then_b_under_30s_projects_only_to_legal_anchor(live):
    live.record("A", "09:00:00")
    live.record("A", "09:01:00")
    live.record("B", "09:02:00")
    live.record("B", "09:02:10")

    rows = live.rows()
    assert len(rows) == 1, "B<30s must not create a second DB row"
    anchor_id = int(rows[0]["id"])
    pages = live.pages(details_ids=[anchor_id])
    recent = pages["overview"]["activities"][0]
    timeline_row = pages["timeline"]["sessions"][0]
    details_rows = pages["details"]["activities"]
    assert _clock(pages["overview"])["live_state"] == "borrowed_anchor_pending"
    assert pages["overview"]["current_activity"]["resource_name"] == "B"
    assert pages["overview"]["current_activity"]["elapsed_seconds"] == 10
    assert pages["overview"]["current_activity"]["display_base_seconds"] == 0
    assert recent["activity_id"] == anchor_id
    assert recent["source"] == "borrowed_anchor_pending"
    assert recent["display_only"] is True
    assert recent["duration_seconds"] == 130
    assert timeline_row["duration_seconds"] == 130
    assert [row["duration_seconds"] for row in details_rows] == [120, 10]
    assert sum(row["duration_seconds"] for row in details_rows) == timeline_row[
        "duration_seconds"
    ]
    pending_detail = details_rows[1]
    assert pending_detail["display_only"] is True
    assert pending_detail["editable"] is False
    assert pending_detail["exportable"] is False
    assert pages["overview"]["today_total_seconds"] == sum(
        row["duration_seconds"]
        for row in pages["overview"]["activities"]
        if row.get("contributes_to_totals") is not False
    )
    assert pages["overview"]["today_total_seconds"] == (
        pages["overview"]["classified_seconds"]
        + pages["overview"]["uncategorized_seconds"]
    )
    _same_live_identity(
        pages["overview"], pages["recent"], pages["timeline"], pages["details"], pages["refresh"]
    )
    assert live.rows()[0]["duration_seconds"] == 120


def test_a_to_short_b_back_to_a_absorbs_and_resumes_anchor(live):
    live.record("A", "09:00:00")
    live.record("A", "09:01:00")
    live.record("B", "09:02:00")
    live.record("A", "09:02:20")

    rows = live.rows()
    assert len(rows) == 1, "short B must be absorbed into the legal A anchor"
    assert rows[0]["window_title"] == "A"
    assert rows[0]["end_time"] is None, "returning to A should resume the anchor row"
    assert rows[0]["duration_seconds"] == 140
    assert live.snapshot()["persisted_activity_id"] == rows[0]["id"]


def test_a_to_b_at_30s_persists_b_independently(live):
    live.record("A", "09:00:00")
    live.record("A", "09:01:00")
    live.record("B", "09:02:00")
    live.record("B", "09:02:30")

    rows = sorted(live.rows(), key=lambda row: row["start_time"])
    assert [r["window_title"] for r in rows] == ["A", "B"]
    assert rows[0]["end_time"] is not None
    assert rows[1]["end_time"] is None
    assert rows[0]["duration_seconds"] == 120
    assert rows[1]["duration_seconds"] == 30


def test_pause_stop_and_shutdown_boundaries_do_not_connect_to_old_project(live):
    live.record("A", "09:00:00")
    live.record("A", "09:01:00")
    live.pause("09:02:00")
    live.record("B", "09:03:00")
    live.stop("09:03:20")
    live.record("C", "09:04:00")
    live.stop("09:04:20")

    rows = live.rows()
    normal_rows = [r for r in rows if r["window_title"] in {"A", "B", "C"}]
    assert [r["window_title"] for r in normal_rows] == ["A"]
    assert normal_rows[0]["duration_seconds"] == 120
    assert all(r["window_title"] != "B" for r in normal_rows)
    assert all(r["window_title"] != "C" for r in normal_rows)


@pytest.mark.parametrize("state", ["paused", "idle", "excluded", "error"])
def test_system_status_is_status_only_and_excluded_from_totals(live, state):
    live.record("A", "09:00:00")
    live.record("A", "09:01:00")
    if state == "paused":
        live.pause("09:02:00")
    else:
        live.status(state, "09:02:00")

    overview = live.pages()["overview"]
    status_rows = [r for r in overview["activities"] if r.get("row_kind") == "status_only"]
    assert status_rows, f"{state} must be visible as a status-only row"
    assert "status" not in status_rows[0]
    assert status_rows[0]["status_code"] == state
    assert status_rows[0]["project_name"] == "—"
    assert status_rows[0]["contributes_to_totals"] is False
    assert status_rows[0]["editable"] is False
    assert status_rows[0]["exportable"] is False
    assert overview["today_total_seconds"] == 120
    assert statistics_service.get_summary(live.date, live.date)["total_duration"] == 120


def test_historical_report_date_is_not_polluted_by_current_live_clock(live):
    live.record("Today", "09:00:00")
    live.record("Today", "09:00:30")

    historical = live.pages(date="2026-06-17")
    assert _clock(historical["timeline"])["live_state"] == "none"
    assert _clock(historical["timeline"])["is_live"] is False
    assert historical["timeline"]["total_seconds"] == 0
    assert historical["details"]["activities"] == []


def test_timeline_details_share_display_span_and_stable_hash(live):
    live.record("A", "09:00:00")
    live.record("A", "09:00:30")
    activity_id = int(live.rows()[0]["id"])
    pages = live.pages(details_ids=[activity_id])
    timeline_row = pages["timeline"]["sessions"][0]
    detail_row = pages["details"]["activities"][0]

    assert timeline_row["display_span_id"] == detail_row["display_span_id"]
    assert timeline_row["stable_live_key_hash"] == detail_row["stable_live_key_hash"]
    assert timeline_row["display_span_id"] == _clock(pages["overview"])["display_span_id"]


def test_natural_growth_keeps_revision_but_handoff_changes_it(live):
    live.record("A", "09:00:00")
    live.record("A", "09:00:29")
    rev_29 = live.pages()["refresh"]["refresh_revision"]
    live.record("A", "09:00:30")
    rev_30 = live.pages()["refresh"]["refresh_revision"]
    live.record("A", "09:00:45")
    rev_45 = live.pages()["refresh"]["refresh_revision"]

    assert rev_29 != rev_30, "persisted-open handoff must be a structural refresh"
    assert rev_30 == rev_45, "natural elapsed growth must not force structural refresh"


def test_current_uses_zero_base_aggregates_use_static_base_plus_same_elapsed(live):
    live.create_closed_activity("A", start="09:00:00", end="09:01:00", seconds=60)
    live.set_snapshot(
        live.normal_snapshot("B", elapsed_seconds=15, start="09:01:05")
    )
    pages = live.pages()
    current = pages["overview"]["current_activity"]
    recent = pages["overview"]["activities"][0]

    assert current["duration_semantic"] == "current_live"
    assert current["display_base_seconds"] == 0
    assert current["elapsed_seconds"] == 15
    assert recent["duration_semantic"] == "aggregate_live"
    assert recent["display_base_seconds"] == 60
    assert recent["duration_seconds"] == 75
    assert _clock(pages["overview"])["current_elapsed_at_sample"] == 15
