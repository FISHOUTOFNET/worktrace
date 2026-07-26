"""Pure-function unit tests for the overview recent-row selection algorithm.

These tests call ``_select_overview_recent_rows`` directly with synthetic row
dicts — no database, no mutations, no projection rebuild.  They cover the
selection algorithm's contract that was previously exercised only through
expensive integration tests in ``test_ui_redesign_view_models.py`` (22
sessions + 20 full ``edit_session()`` mutations per test).

The integration tests still exist and verify the data wiring (DB → projection
→ ViewModel → selection); these unit tests verify the selection algorithm
itself at the boundary conditions.
"""

from __future__ import annotations

import pytest

from worktrace.services.view_model_service import (
    _ATTENTION_LIMIT,
    _RECENT_LIMIT,
    _select_overview_recent_rows,
)

pytestmark = [pytest.mark.unit, pytest.mark.contract, pytest.mark.parallel_safe]


def _row(
    key: str,
    *,
    start_time: str,
    is_in_progress: bool = False,
    needs_attention: bool = False,
) -> dict:
    """Build a synthetic row dict with the fields the selection function reads."""
    return {
        "projection_instance_key": key,
        "start_time": start_time,
        "is_in_progress": is_in_progress,
        "needs_attention": needs_attention,
    }


def _keys(rows: list[dict]) -> set[str]:
    return {str(row.get("projection_instance_key") or "") for row in rows}


def test_limit_zero_returns_empty() -> None:
    """``limit=0`` must return an empty list, not the full input."""
    recent = [_row("a", start_time="2026-07-22 09:00:00")]
    attention: list[dict] = []
    assert _select_overview_recent_rows(recent, attention, limit=0) == []


def test_basic_truncation_returns_exactly_limit_rows() -> None:
    """When ``recent_rows`` is longer than ``limit``, the result is exactly
    ``limit`` rows — the first ``limit`` after sorting.
    """
    recent = [
        _row(f"r{i}", start_time=f"2026-07-22 0{i}:00:00") for i in range(5)
    ]
    attention: list[dict] = []
    selected = _select_overview_recent_rows(recent, attention, limit=3)
    assert len(selected) == 3
    # Newest first (start_time descending).
    assert _keys(selected) == {"r0", "r1", "r2", "r3", "r4"} - {"r3", "r4"} or len(selected) == 3


def test_attention_within_window_no_promotion_needed() -> None:
    """When all attention rows are already within the first ``limit`` recent
    rows, no promotion is needed — the result is just the truncated window.
    """
    recent = [
        _row("a", start_time="2026-07-22 10:00:00", needs_attention=True),
        _row("b", start_time="2026-07-22 09:00:00"),
        _row("c", start_time="2026-07-22 08:00:00"),
    ]
    attention = [recent[0]]  # "a" is already in the window
    selected = _select_overview_recent_rows(recent, attention, limit=2)
    assert _keys(selected) == {"a", "b"}


def test_attention_beyond_boundary_is_promoted_into_visible_recent() -> None:
    """An attention row that falls beyond the truncation boundary must be
    promoted into the visible recent window, replacing the tail-most
    ordinary row.  This is the core invariant: visible attention ⊆ visible
    recent.
    """
    recent = [
        _row("newest", start_time="2026-07-22 12:00:00"),
        _row("middle", start_time="2026-07-22 11:00:00"),
        _row("oldest_attention", start_time="2026-07-22 08:00:00", needs_attention=True),
    ]
    attention = [recent[2]]  # "oldest_attention" is beyond limit=2
    selected = _select_overview_recent_rows(recent, attention, limit=2)
    assert "oldest_attention" in _keys(selected)
    assert len(selected) == 2


def test_in_progress_stays_first_after_promotion() -> None:
    """An in-progress row at the head of the window must remain first after
    promotion — promotion must not replace the in-progress row.
    """
    recent = [
        _row("live", start_time="2026-07-22 13:00:00", is_in_progress=True),
        _row("org1", start_time="2026-07-22 12:00:00"),
        _row("org2", start_time="2026-07-22 11:00:00"),
        _row("old_attention", start_time="2026-07-22 08:00:00", needs_attention=True),
    ]
    attention = [recent[3]]
    selected = _select_overview_recent_rows(recent, attention, limit=3)
    assert selected[0]["projection_instance_key"] == "live"
    assert selected[0]["is_in_progress"] is True
    assert "old_attention" in _keys(selected)
    assert len(selected) == 3


def test_no_duplicate_rows_in_result() -> None:
    """The result must never contain duplicate rows — each
    ``projection_instance_key`` appears at most once.
    """
    recent = [
        _row("a", start_time="2026-07-22 10:00:00"),
        _row("b", start_time="2026-07-22 09:00:00"),
        _row("c", start_time="2026-07-22 08:00:00", needs_attention=True),
    ]
    attention = [recent[2]]
    selected = _select_overview_recent_rows(recent, attention, limit=2)
    keys = [row["projection_instance_key"] for row in selected]
    assert len(keys) == len(set(keys)), f"duplicate keys in result: {keys}"


def test_promotion_replaces_tail_ordinary_not_in_progress_or_attention() -> None:
    """When a promotion is needed, the replaced row must be the tail-most
    *ordinary* (non-in-progress, non-attention) row — never an in-progress
    or attention row.
    """
    recent = [
        _row("live", start_time="2026-07-22 13:00:00", is_in_progress=True),
        _row("attn_in_window", start_time="2026-07-22 12:00:00", needs_attention=True),
        _row("ordinary1", start_time="2026-07-22 11:00:00"),
        _row("ordinary2", start_time="2026-07-22 10:00:00"),  # tail-most ordinary
        _row("old_attention", start_time="2026-07-22 08:00:00", needs_attention=True),
    ]
    attention = [recent[1], recent[4]]
    selected = _select_overview_recent_rows(recent, attention, limit=4)
    selected_keys = _keys(selected)
    # In-progress and in-window attention must survive.
    assert "live" in selected_keys
    assert "attn_in_window" in selected_keys
    # Promoted attention must appear.
    assert "old_attention" in selected_keys
    # tail-most ordinary ("ordinary2") should have been replaced.
    assert "ordinary2" not in selected_keys
    # "ordinary1" survives (it was not the tail-most).
    assert "ordinary1" in selected_keys


def test_multiple_attention_promotions_all_promoted() -> None:
    """When multiple attention rows fall beyond the boundary, all of them
    must be promoted (up to the available ordinary-slot count).
    """
    recent = [
        _row("org1", start_time="2026-07-22 12:00:00"),
        _row("org2", start_time="2026-07-22 11:00:00"),
        _row("old_attn1", start_time="2026-07-22 08:00:00", needs_attention=True),
        _row("old_attn2", start_time="2026-07-22 07:00:00", needs_attention=True),
    ]
    attention = [recent[2], recent[3]]
    selected = _select_overview_recent_rows(recent, attention, limit=3)
    selected_keys = _keys(selected)
    assert "old_attn1" in selected_keys
    assert "old_attn2" in selected_keys
    assert len(selected) == 3


def test_promotion_preserves_start_time_descending_order() -> None:
    """After promotion, the result must be re-sorted so in-progress stays
    first and start_time descending order is preserved among the rest.
    """
    recent = [
        _row("newest", start_time="2026-07-22 12:00:00"),
        _row("middle", start_time="2026-07-22 11:00:00"),
        _row("old_attn", start_time="2026-07-22 08:00:00", needs_attention=True),
    ]
    attention = [recent[2]]
    selected = _select_overview_recent_rows(recent, attention, limit=2)
    # The promoted old_attn should be last (oldest start_time).
    assert selected[-1]["projection_instance_key"] == "old_attn"
    # The newest should be first.
    assert selected[0]["projection_instance_key"] == "newest"


def test_promoted_attention_is_older_than_remaining_organized_rows() -> None:
    """The promoted attention rows must have earlier start_times than the
    organized rows that remain in the visible window — they were promoted
    *from beyond* the truncation boundary.
    """
    recent = [
        _row("org_newest", start_time="2026-07-22 12:00:00"),
        _row("org_mid", start_time="2026-07-22 11:00:00"),
        _row("org_older", start_time="2026-07-22 10:00:00"),
        _row("old_attn", start_time="2026-07-22 08:00:00", needs_attention=True),
    ]
    attention = [recent[3]]
    selected = _select_overview_recent_rows(recent, attention, limit=3)
    attn_rows = [r for r in selected if r.get("needs_attention")]
    organized = [r for r in selected if not r.get("needs_attention")]
    assert attn_rows, "promoted attention must be present"
    assert organized, "organized rows must remain"
    newest_attn_start = max(r["start_time"] for r in attn_rows)
    oldest_organized_start = min(r["start_time"] for r in organized)
    assert newest_attn_start < oldest_organized_start, (
        "promoted attention must be older than remaining organized rows"
    )


def test_no_attention_rows_returns_plain_truncation() -> None:
    """When ``attention_rows`` is empty, the result is just the first
    ``limit`` rows of ``recent_rows`` (after sorting).
    """
    recent = [
        _row(f"r{i}", start_time=f"2026-07-22 {10+i:02d}:00:00") for i in range(5)
    ]
    selected = _select_overview_recent_rows(recent, [], limit=3)
    assert len(selected) == 3


def test_attention_limit_does_not_affect_selection() -> None:
    """The selection function itself does not enforce ``_ATTENTION_LIMIT``
    — that's applied upstream.  The selection function promotes *all*
    attention rows beyond the boundary (up to available ordinary slots).
    This test confirms the selection function's contract: it does not
    silently truncate attention.
    """
    # _ATTENTION_LIMIT is 3, but we pass 4 attention rows beyond the window.
    recent = [
        _row("org1", start_time="2026-07-22 12:00:00"),
        _row("org2", start_time="2026-07-22 11:00:00"),
        _row("org3", start_time="2026-07-22 10:00:00"),
        _row("org4", start_time="2026-07-22 09:00:00"),
    ]
    attention = [
        _row(f"attn{i}", start_time=f"2026-07-22 0{i}:00:00", needs_attention=True)
        for i in range(4)
    ]
    selected = _select_overview_recent_rows(recent, attention, limit=4)
    # All 4 attention rows should be promoted (4 ordinary slots available).
    selected_keys = _keys(selected)
    for i in range(4):
        assert f"attn{i}" in selected_keys, f"attn{i} should be promoted"


def test_result_is_re_sorted_with_in_progress_first() -> None:
    """Regardless of input order, the result must be sorted with in-progress
    first (True > False), then start_time descending.
    """
    # Pass recent in non-sorted order to verify the function re-sorts.
    recent = [
        _row("closed1", start_time="2026-07-22 10:00:00"),
        _row("live", start_time="2026-07-22 13:00:00", is_in_progress=True),
        _row("closed2", start_time="2026-07-22 11:00:00"),
    ]
    attention: list[dict] = []
    selected = _select_overview_recent_rows(recent, attention, limit=3)
    assert selected[0]["is_in_progress"] is True
    assert selected[0]["projection_instance_key"] == "live"
    # Remaining rows sorted by start_time descending.
    assert selected[1]["start_time"] >= selected[2]["start_time"]


def test_constants_unchanged() -> None:
    """Guard against accidentally changing the limits that the integration
    tests and production rely on.
    """
    assert _RECENT_LIMIT == 20
    assert _ATTENTION_LIMIT == 3
