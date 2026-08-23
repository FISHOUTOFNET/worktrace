from __future__ import annotations

import pytest

from worktrace.services.report_session_builder import merge_short_project_returns

DATE = "2026-08-21"
UNCATEGORIZED_ID = 999
pytestmark = pytest.mark.unit


def _stamp(clock: str) -> str:
    return f"{DATE} {clock}"


def _session(
    project_id: int,
    name: str,
    start: str,
    end: str,
    duration_seconds: int,
    activity_id: int,
    *,
    uncategorized: bool = False,
) -> dict:
    member = {
        "report_date": DATE,
        "activity_id": activity_id,
        "slice_start_time": _stamp(start),
        "slice_end_time": _stamp(end),
    }
    return {
        "row_kind": "project_session",
        "project_id": project_id,
        "project_name": name,
        "project_description": "",
        "project_is_deleted": False,
        "project_is_archived": False,
        "report_project_key": (
            f"uncategorized:{project_id}" if uncategorized else f"project:{project_id}"
        ),
        "start_time": _stamp(start),
        "end_time": _stamp(end),
        "report_date": DATE,
        "duration_seconds": duration_seconds,
        "closed_duration_seconds": duration_seconds,
        "open_activity_id": 0,
        "activity_ids": [activity_id],
        "member_slices": [member],
        "activity_member_hash": f"member-{activity_id}",
        "anchor_activity_id": activity_id,
        "first_activity_id": activity_id,
        "session_note": "",
        "sort_time": _stamp(start),
        "event_count": 1,
        "status": "normal",
        "status_code": "normal",
        "display_status": name,
        "status_summary": name,
        "contributes_to_totals": True,
        "live_delta_eligible": False,
        "editable": True,
        "exportable": True,
        "is_suggested_project": False,
        "is_in_progress": False,
        "is_official_project": not uncategorized,
        "report_attribution_kind": "none" if uncategorized else "official_direct",
        "is_report_project": not uncategorized,
        "is_report_classified": not uncategorized,
        "is_report_uncategorized": uncategorized,
        "is_classified": not uncategorized,
        "is_uncategorized": uncategorized,
    }


def _u(start: str, end: str, duration_seconds: int, activity_id: int) -> dict:
    return _session(
        UNCATEGORIZED_ID,
        "未归类",
        start,
        end,
        duration_seconds,
        activity_id,
        uncategorized=True,
    )


def _compact(
    *sessions: dict,
    boundary_times: tuple[str, ...] = (),
    protected_member_sets: tuple[frozenset[tuple[str, int, str]], ...] = (),
) -> list[dict]:
    return merge_short_project_returns(
        sessions,
        boundary_times=boundary_times,
        protected_member_sets=protected_member_sets,
        unrecorded_gap_boundary_seconds=15 * 60,
    )


def _project_ids(sessions: list[dict]) -> list[int]:
    return [int(item["project_id"]) for item in sessions]


def _members(session: dict) -> set[int]:
    return {int(item["activity_id"]) for item in session["member_slices"]}


def test_short_return_ignores_uncategorized_time_in_foreign_project_budget() -> None:
    result = _compact(
        _session(1, "A", "09:00:00", "09:10:00", 600, 1),
        _u("09:10:00", "09:17:00", 420, 2),
        _session(2, "B", "09:17:00", "09:18:00", 60, 3),
        _session(1, "A", "09:18:00", "09:19:00", 60, 4),
    )

    assert _project_ids(result) == [1]
    assert result[0]["duration_seconds"] == 19 * 60
    assert _members(result[0]) == {1, 2, 3, 4}


def test_short_return_stops_after_fifteen_minute_overall_window() -> None:
    result = _compact(
        _session(1, "A", "09:00:00", "09:10:00", 600, 1),
        _u("09:10:00", "09:20:00", 600, 2),
        _session(2, "B", "09:20:00", "09:21:00", 60, 3),
        _u("09:21:00", "09:31:00", 600, 4),
        _session(1, "A", "09:31:00", "09:32:00", 60, 5),
    )

    assert _project_ids(result) == [1, 2, 1]
    assert _members(result[0]) == {1, 2}
    assert _members(result[1]) == {3, 4}
    assert _members(result[2]) == {5}


def test_short_return_stops_when_foreign_project_duration_exceeds_five_minutes() -> None:
    result = _compact(
        _session(1, "A", "09:00:00", "09:10:00", 600, 1),
        _u("09:10:00", "09:12:00", 120, 2),
        _session(2, "B", "09:12:00", "09:19:00", 420, 3),
        _u("09:19:00", "09:21:00", 120, 4),
        _session(1, "A", "09:21:00", "09:22:00", 60, 5),
    )

    assert _project_ids(result) == [1, 2, 1]
    assert result[0]["duration_seconds"] == 12 * 60
    assert result[1]["duration_seconds"] == 9 * 60
    assert result[2]["duration_seconds"] == 60


def test_left_anchor_greedily_returns_before_later_bridge_decisions() -> None:
    result = _compact(
        _session(1, "A", "09:00:00", "09:10:00", 600, 1),
        _session(2, "B", "09:10:00", "09:11:00", 60, 2),
        _u("09:11:00", "09:21:00", 600, 3),
        _session(1, "A", "09:21:00", "09:22:00", 60, 4),
        _session(2, "B", "09:22:00", "09:32:00", 600, 5),
    )

    assert _project_ids(result) == [1, 2]
    assert result[0]["duration_seconds"] == 22 * 60
    assert _members(result[0]) == {1, 2, 3, 4}
    assert _members(result[1]) == {5}


def test_short_uncategorized_bridge_goes_to_longer_left_neighbor() -> None:
    result = _compact(
        _session(1, "A", "09:00:00", "09:40:00", 2400, 1),
        _u("09:40:00", "09:46:00", 360, 2),
        _session(2, "B", "09:46:00", "10:01:00", 900, 3),
    )

    assert _project_ids(result) == [1, 2]
    assert result[0]["duration_seconds"] == 46 * 60
    assert _members(result[0]) == {1, 2}


def test_short_uncategorized_bridge_goes_to_longer_right_neighbor() -> None:
    result = _compact(
        _session(1, "A", "09:00:00", "09:10:00", 600, 1),
        _u("09:10:00", "09:16:00", 360, 2),
        _session(2, "B", "09:16:00", "10:06:00", 3000, 3),
    )

    assert _project_ids(result) == [1, 2]
    assert result[1]["duration_seconds"] == 56 * 60
    assert _members(result[1]) == {2, 3}


def test_short_uncategorized_bridge_tie_goes_left() -> None:
    result = _compact(
        _session(1, "A", "09:00:00", "09:10:00", 600, 1),
        _u("09:10:00", "09:16:00", 360, 2),
        _session(2, "B", "09:16:00", "09:26:00", 600, 3),
    )

    assert _project_ids(result) == [1, 2]
    assert result[0]["duration_seconds"] == 16 * 60
    assert _members(result[0]) == {1, 2}


def test_recomputation_can_move_bridge_after_right_project_grows_by_greedy_return() -> None:
    initial = _compact(
        _session(1, "A", "09:00:00", "09:10:00", 600, 1),
        _u("09:10:00", "09:11:00", 60, 2),
        _session(2, "B", "09:11:00", "09:19:00", 480, 3),
    )
    assert _project_ids(initial) == [1, 2]
    assert _members(initial[0]) == {1, 2}

    recomputed = _compact(
        _session(1, "A", "09:00:00", "09:10:00", 600, 1),
        _u("09:10:00", "09:11:00", 60, 2),
        _session(2, "B", "09:11:00", "09:19:00", 480, 3),
        _session(3, "C", "09:19:00", "09:21:00", 120, 4),
        _session(2, "B", "09:21:00", "09:41:00", 1200, 5),
    )

    assert _project_ids(recomputed) == [1, 2]
    assert recomputed[1]["duration_seconds"] == 31 * 60
    assert _members(recomputed[1]) == {2, 3, 4, 5}


def test_bridge_does_not_change_a_protected_neighbor_identity() -> None:
    left = _session(1, "A", "09:00:00", "09:40:00", 2400, 1)
    protected = frozenset({(DATE, 1, _stamp("09:00:00"))})
    result = _compact(
        left,
        _u("09:40:00", "09:46:00", 360, 2),
        _session(2, "B", "09:46:00", "10:01:00", 900, 3),
        protected_member_sets=(protected,),
    )

    assert _project_ids(result) == [1, UNCATEGORIZED_ID, 2]
    assert _members(result[0]) == {1}
    assert _members(result[1]) == {2}


def test_short_return_respects_explicit_boundary() -> None:
    result = _compact(
        _session(1, "A", "09:00:00", "09:10:00", 600, 1),
        _u("09:10:00", "09:17:00", 420, 2),
        _session(2, "B", "09:17:00", "09:18:00", 60, 3),
        _session(1, "A", "09:18:00", "09:19:00", 60, 4),
        boundary_times=(_stamp("09:15:00"),),
    )

    assert len(result) > 1
    assert _members(result[0]) != {1, 2, 3, 4}
