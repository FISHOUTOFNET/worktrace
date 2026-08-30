from __future__ import annotations

import pytest

from worktrace.services.report_session_builder import merge_short_project_returns

DATE = "2026-08-26"
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
    in_progress: bool = False,
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
        "end_time": None if in_progress else _stamp(end),
        "report_date": DATE,
        "duration_seconds": duration_seconds,
        "closed_duration_seconds": 0 if in_progress else duration_seconds,
        "open_activity_id": activity_id if in_progress else 0,
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
        "editable": not in_progress,
        "exportable": not in_progress,
        "is_suggested_project": False,
        "is_in_progress": in_progress,
        "is_official_project": not uncategorized,
        "report_attribution_kind": "none" if uncategorized else "official_direct",
        "is_report_project": not uncategorized,
        "is_report_classified": not uncategorized,
        "is_report_uncategorized": uncategorized,
        "is_classified": not uncategorized,
        "is_uncategorized": uncategorized,
    }


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
        max_interruption_seconds=5 * 60,
    )


def _project_ids(sessions: list[dict]) -> list[int]:
    return [int(item["project_id"]) for item in sessions]


def _members(session: dict) -> set[int]:
    return {int(item["activity_id"]) for item in session["member_slices"]}


def test_five_second_concrete_fragment_goes_to_longer_left_neighbor() -> None:
    result = _compact(
        _session(1, "A", "10:33:00", "10:44:11", 671, 1),
        _session(2, "X", "10:44:11", "10:44:16", 5, 2),
        _session(3, "B", "10:44:16", "10:53:53", 577, 3),
    )

    assert _project_ids(result) == [1, 3]
    assert result[0]["duration_seconds"] == 676
    assert _members(result[0]) == {1, 2}


def test_short_concrete_fragment_goes_to_longer_right_neighbor() -> None:
    result = _compact(
        _session(1, "A", "09:00:00", "09:05:00", 300, 1),
        _session(2, "X", "09:05:00", "09:05:20", 20, 2),
        _session(3, "B", "09:05:20", "09:20:20", 900, 3),
    )

    assert _project_ids(result) == [1, 3]
    assert result[1]["duration_seconds"] == 920
    assert _members(result[1]) == {2, 3}


def test_short_concrete_fragment_tie_goes_left() -> None:
    result = _compact(
        _session(1, "A", "09:00:00", "09:10:00", 600, 1),
        _session(2, "X", "09:10:00", "09:10:10", 10, 2),
        _session(3, "B", "09:10:10", "09:20:10", 600, 3),
    )

    assert _project_ids(result) == [1, 3]
    assert result[0]["duration_seconds"] == 610
    assert _members(result[0]) == {1, 2}


def test_concrete_fragment_exactly_five_minutes_is_eligible() -> None:
    result = _compact(
        _session(1, "A", "09:00:00", "09:10:00", 600, 1),
        _session(2, "X", "09:10:00", "09:15:00", 300, 2),
        _session(3, "B", "09:15:00", "09:25:00", 600, 3),
    )

    assert _project_ids(result) == [1, 3]
    assert result[0]["duration_seconds"] == 900


def test_concrete_fragment_over_five_minutes_is_preserved() -> None:
    result = _compact(
        _session(1, "A", "09:00:00", "09:10:00", 600, 1),
        _session(2, "X", "09:10:00", "09:15:01", 301, 2),
        _session(3, "B", "09:15:01", "09:25:01", 600, 3),
    )

    assert _project_ids(result) == [1, 2, 3]


def test_concrete_fragment_exactly_fifteen_minute_context_window_is_eligible() -> None:
    result = _compact(
        _session(1, "A", "09:00:00", "09:10:00", 600, 1),
        _session(2, "X", "09:13:00", "09:17:00", 240, 2),
        _session(3, "B", "09:25:00", "09:35:00", 600, 3),
    )

    assert _project_ids(result) == [1, 3]
    assert result[0]["duration_seconds"] == 840


def test_concrete_fragment_over_fifteen_minute_context_window_is_preserved() -> None:
    result = _compact(
        _session(1, "A", "09:00:00", "09:10:00", 600, 1),
        _session(2, "X", "09:13:00", "09:17:00", 240, 2),
        _session(3, "B", "09:26:00", "09:36:00", 600, 3),
    )

    assert _project_ids(result) == [1, 2, 3]


def test_same_project_neighbors_remain_owned_by_return_stage() -> None:
    middle_identity = frozenset({(DATE, 2, _stamp("09:10:00"))})
    result = _compact(
        _session(1, "A", "09:00:00", "09:10:00", 600, 1),
        _session(2, "X", "09:10:00", "09:10:05", 5, 2),
        _session(1, "A", "09:10:05", "09:20:05", 600, 3),
        protected_member_sets=(middle_identity,),
    )

    assert _project_ids(result) == [1, 2, 1]


def test_concrete_bridge_respects_explicit_boundary() -> None:
    result = _compact(
        _session(1, "A", "09:00:00", "09:10:00", 600, 1),
        _session(2, "X", "09:10:00", "09:10:05", 5, 2),
        _session(3, "B", "09:11:00", "09:21:00", 600, 3),
        boundary_times=(_stamp("09:10:30"),),
    )

    assert _project_ids(result) == [1, 2, 3]


def test_concrete_bridge_respects_protected_middle_identity() -> None:
    protected = frozenset({(DATE, 2, _stamp("09:10:00"))})
    result = _compact(
        _session(1, "A", "09:00:00", "09:10:00", 600, 1),
        _session(2, "X", "09:10:00", "09:10:05", 5, 2),
        _session(3, "B", "09:10:05", "09:20:05", 600, 3),
        protected_member_sets=(protected,),
    )

    assert _project_ids(result) == [1, 2, 3]


def test_in_progress_concrete_fragment_is_never_reassigned() -> None:
    result = _compact(
        _session(1, "A", "09:00:00", "09:10:00", 600, 1),
        _session(2, "X", "09:10:00", "09:10:05", 5, 2, in_progress=True),
        _session(3, "B", "09:10:05", "09:20:05", 600, 3),
    )

    assert _project_ids(result) == [1, 2, 3]


def test_existing_uncategorized_bridge_semantics_are_unchanged() -> None:
    result = _compact(
        _session(1, "A", "09:00:00", "09:40:00", 2400, 1),
        _session(
            UNCATEGORIZED_ID,
            "未归类",
            "09:40:00",
            "09:46:00",
            360,
            2,
            uncategorized=True,
        ),
        _session(3, "B", "09:46:00", "10:01:00", 900, 3),
    )

    assert _project_ids(result) == [1, 3]
    assert result[0]["duration_seconds"] == 2760
    assert _members(result[0]) == {1, 2}
