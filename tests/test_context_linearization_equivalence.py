"""Equivalence and complexity tests for the linearized Context Projection.

These tests verify that the O(N) bidirectional-anchor precomputation produces
identical results to the former O(N²) per-row neighbour scan, across a broad
spectrum of random and edge-case activity sequences. They also verify that
anchor-lookup work grows linearly (not quadratically) with row count.

The reference implementation (``_ReferenceContextProjection``) is a minimal
copy of the original algorithm preserved here for cross-validation. It must
NOT be imported by production code.
"""

from __future__ import annotations

import random
from copy import deepcopy
from datetime import datetime, timedelta
from typing import Any, Mapping, Sequence

import pytest

from worktrace.constants import (
    REPORT_CONTEXT_SHORT_MERGE_SECONDS,
    STATUS_ERROR,
    STATUS_EXCLUDED,
    STATUS_IDLE,
    STATUS_NORMAL,
    STATUS_PAUSED,
    TIME_FORMAT,
)
from worktrace.services.activity_status_policy import does_status_require_boundary
from worktrace.services.context_service import (
    BoundaryIndex,
    DIRECT_ASSIGNMENT_SOURCES,
    DERIVED_CONTEXT_SOURCES,
    CONTEXT_ATTRIBUTABLE_STATUSES,
    ReportContextProjection,
    _context_kind,
    _context_role,
    _copy_project,
    _clear_project,
    _eligible,
    _has_durable_direct_assignment,
    _row_duration_seconds,
    _row_end,
    _context_distance_seconds,
    _parse,
)

pytestmark = [pytest.mark.unit, pytest.mark.contract]

DATE = "2026-07-15"


def _row(
    aid: int,
    start: str,
    *,
    seconds: int = 30,
    project_id: int = 0,
    source: str = "uncategorized",
    status: str = STATUS_NORMAL,
    deleted: bool = False,
    hidden: bool = False,
    is_anchor: bool = False,
) -> dict:
    start_dt = datetime.strptime(start, TIME_FORMAT)
    end = (start_dt + timedelta(seconds=seconds)).strftime(TIME_FORMAT)
    project = project_id > 0 and not deleted
    return {
        "id": aid,
        "start_time": start,
        "end_time": end,
        "duration_seconds": seconds,
        "report_duration_seconds": seconds,
        "status": status,
        "assignment_source": source,
        "effective_project_id": project_id or None,
        "effective_project_is_deleted": deleted,
        "report_project_id": project_id,
        "report_project_name": f"P{project_id}" if project else "未归类",
        "report_project_key": (
            f"project:{project_id}" if project else "uncategorized:1"
        ),
        "report_project_is_deleted": deleted,
        "is_report_project": project,
        "is_report_classified": project,
        "is_report_uncategorized": not project,
        "is_official_project": project
        and source in {"manual", "keyword_rule", "folder_rule"},
        "report_attribution_kind": "official_direct" if project else "none",
        "is_deleted": deleted,
        "is_hidden": hidden,
        "resource_is_anchor": is_anchor,
    }


# --- Reference implementation (former O(N²) algorithm) ---


def _ref_crosses_boundary(
    left: Mapping[str, Any],
    right: Mapping[str, Any],
    boundaries: Sequence[str],
) -> bool:
    start = str(left.get("end_time") or left.get("start_time") or "")
    end = str(right.get("start_time") or "")
    return bool(
        start and end and any(start <= boundary <= end for boundary in boundaries)
    )


def _ref_find_anchor(
    rows: Sequence[dict[str, Any]],
    origin: int,
    step: int,
    carry_seconds: int,
    boundaries: Sequence[str],
) -> dict[str, Any] | None:
    cursor = origin + step
    while 0 <= cursor < len(rows):
        left, right = (
            (rows[cursor], rows[cursor - step])
            if step < 0
            else (rows[cursor - step], rows[cursor])
        )
        if _ref_crosses_boundary(left, right, boundaries):
            return None
        role = _context_role(rows[cursor], carry_seconds)
        if role.can_anchor_context:
            if (
                _context_distance_seconds(rows[origin], rows[cursor], step)
                <= carry_seconds
            ):
                return rows[cursor]
            return None
        if role.blocks_context_search:
            return None
        cursor += step
    return None


def _ref_neighbour_attribution(
    rows: Sequence[dict[str, Any]],
    index: int,
    carry_seconds: int,
    boundaries: Sequence[str],
) -> tuple[dict[str, Any], str] | None:
    previous = _ref_find_anchor(rows, index, -1, carry_seconds, boundaries)
    following = _ref_find_anchor(rows, index, 1, carry_seconds, boundaries)
    if previous and following:
        if int(previous.get("report_project_id") or 0) != int(
            following.get("report_project_id") or 0
        ):
            return None
        return previous, _context_kind(previous)
    anchor = previous or following
    return (anchor, _context_kind(anchor)) if anchor else None


def _ref_clipboard_attribution(
    rows: Sequence[dict[str, Any]],
    index: int,
    clipboard_times: Mapping[int, Sequence[str]],
    boundaries: Sequence[str],
) -> tuple[dict[str, Any], str] | None:
    from worktrace.constants import CLIPBOARD_TRANSITION_SECONDS

    if index <= 0:
        return None
    previous = rows[index - 1]
    current = rows[index]
    if str(current.get("status") or "") != STATUS_NORMAL:
        return None
    if (
        not _context_role(
            previous,
            REPORT_CONTEXT_SHORT_MERGE_SECONDS,
        ).can_anchor_context
        or _ref_crosses_boundary(previous, current, boundaries)
    ):
        return None
    current_start = _parse(current.get("start_time"))
    if current_start is None:
        return None
    previous_id = int(previous.get("id") or previous.get("activity_id") or 0)
    for copied_at in clipboard_times.get(previous_id, ()):
        copied = _parse(copied_at)
        if (
            copied is not None
            and 0
            <= (current_start - copied).total_seconds()
            <= CLIPBOARD_TRANSITION_SECONDS
        ):
            return previous, "clipboard_transition_context"
    return None


def _reference_build(
    rows: Sequence[Mapping[str, Any]],
    *,
    carry_minutes: int,
    boundary_times: Iterable[str] = (),
    clipboard_times: Mapping[int, Sequence[str]] | None = None,
) -> ReportContextProjection:
    """Exact copy of the former O(N²) build for equivalence testing."""

    from typing import Iterable

    projected = [deepcopy(dict(row)) for row in rows]
    boundaries = tuple(sorted(str(value) for value in boundary_times if value))
    copies = clipboard_times or {}
    carry_seconds = min(
        max(0, int(carry_minutes)) * 60,
        REPORT_CONTEXT_SHORT_MERGE_SECONDS,
    )
    attributions: list = []

    for row in projected:
        if str(row.get("assignment_source") or "") in DERIVED_CONTEXT_SOURCES:
            _clear_project(row)

    for index, row in enumerate(projected):
        role = _context_role(row, carry_seconds)
        if not role.can_receive_context:
            continue
        attribution = _ref_clipboard_attribution(projected, index, copies, boundaries)
        if attribution is None and carry_seconds > 0:
            attribution = _ref_neighbour_attribution(
                projected, index, carry_seconds, boundaries
            )
        if attribution is None:
            continue
        anchor, kind = attribution
        _copy_project(row, anchor, kind)
        attributions.append(
            (int(row.get("id") or 0), int(row.get("report_project_id") or 0), kind)
        )
    return projected, attributions


# --- Random equivalence testing ---


def _generate_random_sequence(
    rng: random.Random,
    count: int,
) -> tuple[list[dict], list[str], dict[int, list[str]]]:
    """Generate a random activity sequence with anchors, blockers, and boundaries."""

    rows: list[dict] = []
    start = datetime(2026, 7, 15, 9, 0, 0)
    boundaries: list[str] = []
    clipboard: dict[int, list[str]] = {}
    projects = [0, 7, 8, 9]
    statuses = [STATUS_NORMAL] * 6 + [STATUS_IDLE, STATUS_ERROR, STATUS_EXCLUDED, STATUS_PAUSED]
    sources = ["uncategorized", "manual", "keyword_rule", "folder_rule"]

    for i in range(count):
        seconds = rng.choice([10, 30, 60, 120, 600, 900, 16 * 60])
        status = rng.choice(statuses)
        source = rng.choice(sources)
        project_id = rng.choice(projects) if source != "uncategorized" else 0
        deleted = rng.random() < 0.05
        is_anchor = rng.random() < 0.15

        row = _row(
            aid=i + 1,
            start=start.strftime(TIME_FORMAT),
            seconds=seconds,
            project_id=project_id,
            source=source,
            status=status,
            deleted=deleted,
            is_anchor=is_anchor,
        )
        rows.append(row)

        if rng.random() < 0.1:
            boundary_at = (start + timedelta(seconds=rng.randint(1, max(1, seconds - 1)))).strftime(TIME_FORMAT)
            boundaries.append(boundary_at)

        if rng.random() < 0.1 and rows:
            clip_id = rng.choice(rows)["id"]
            clip_time = (start + timedelta(seconds=rng.randint(0, seconds))).strftime(TIME_FORMAT)
            clipboard.setdefault(clip_id, []).append(clip_time)

        start = start + timedelta(seconds=seconds)

    return rows, boundaries, clipboard


def _extract_attribution_key(row: dict) -> tuple:
    return (
        int(row.get("report_project_id") or 0),
        str(row.get("report_attribution_kind") or ""),
        bool(row.get("is_report_project")),
        str(row.get("report_project_key") or ""),
    )


@pytest.mark.parametrize("seed_start", [0, 10, 20, 30, 40])
def test_random_sequence_equivalence(seed_start: int):
    """New O(N) algorithm must produce identical results to the old O(N²) on random data.

    Batches 10 seeds per pytest item to reduce collection, JUnit, and
    progress-hook overhead while preserving full 50-seed coverage.
    Each failure surfaces the failing ``seed`` in the assertion message.
    """

    for seed in range(seed_start, seed_start + 10):
        rng = random.Random(seed)
        count = rng.randint(5, 40)
        rows, boundaries, clipboard = _generate_random_sequence(rng, count)
        carry_minutes = rng.choice([0, 5, 10, 15])

        old_rows, old_attrs = _reference_build(
            rows,
            carry_minutes=carry_minutes,
            boundary_times=boundaries,
            clipboard_times=clipboard,
        )
        new_proj = ReportContextProjection.build(
            rows,
            carry_minutes=carry_minutes,
            boundary_times=boundaries,
            clipboard_times=clipboard,
        )

        old_keys = [_extract_attribution_key(r) for r in old_rows]
        new_keys = [_extract_attribution_key(r) for r in new_proj.rows]
        assert old_keys == new_keys, (
            f"Seed {seed}: attribution mismatch.\n"
            f"Old: {old_keys}\nNew: {new_keys}"
        )

        old_attr_tuples = [(a[0], a[1], a[2]) for a in old_attrs]
        new_attr_tuples = [
            (a.activity_id, a.project_id, a.attribution_kind)
            for a in new_proj.attributions
        ]
        assert old_attr_tuples == new_attr_tuples, (
            f"Seed {seed}: attribution list mismatch.\n"
            f"Old: {old_attr_tuples}\nNew: {new_attr_tuples}"
        )


# --- Specific scenario equivalence tests ---


def test_direct_assignment_preserved():
    rows = [_row(1, f"{DATE} 09:00:00", project_id=7, source="manual")]
    old_rows, _ = _reference_build(rows, carry_minutes=15)
    new_proj = ReportContextProjection.build(rows, carry_minutes=15)
    assert _extract_attribution_key(old_rows[0]) == _extract_attribution_key(new_proj.rows[0])


def test_previous_anchor_attribution():
    rows = [
        _row(1, f"{DATE} 09:00:00", project_id=7, source="manual"),
        _row(2, f"{DATE} 09:01:00"),
    ]
    old_rows, _ = _reference_build(rows, carry_minutes=15)
    new_proj = ReportContextProjection.build(rows, carry_minutes=15)
    assert _extract_attribution_key(old_rows[1]) == _extract_attribution_key(new_proj.rows[1])
    assert new_proj.rows[1]["report_project_id"] == 7


def test_next_anchor_attribution():
    rows = [
        _row(1, f"{DATE} 09:00:00", seconds=600, status=STATUS_IDLE),
        _row(2, f"{DATE} 09:10:00", seconds=60, project_id=7, source="manual"),
    ]
    old_rows, _ = _reference_build(rows, carry_minutes=15)
    new_proj = ReportContextProjection.build(rows, carry_minutes=15)
    assert _extract_attribution_key(old_rows[0]) == _extract_attribution_key(new_proj.rows[0])
    assert new_proj.rows[0]["report_project_id"] == 7


def test_conflicting_anchors_no_attribution():
    rows = [
        _row(1, f"{DATE} 09:00:00", project_id=7, source="manual"),
        _row(2, f"{DATE} 09:01:00"),
        _row(3, f"{DATE} 09:02:00", project_id=8, source="manual"),
    ]
    old_rows, old_attrs = _reference_build(rows, carry_minutes=15)
    new_proj = ReportContextProjection.build(rows, carry_minutes=15)
    assert _extract_attribution_key(old_rows[1]) == _extract_attribution_key(new_proj.rows[1])
    assert len(new_proj.attributions) == len(old_attrs)


def test_clipboard_transition_attribution():
    rows = [
        _row(1, f"{DATE} 09:00:00", project_id=7, source="manual"),
        _row(2, f"{DATE} 09:01:00"),
    ]
    clipboard = {1: [f"{DATE} 09:00:50"]}
    old_rows, _ = _reference_build(
        rows, carry_minutes=0, clipboard_times=clipboard
    )
    new_proj = ReportContextProjection.build(
        rows, carry_minutes=0, clipboard_times=clipboard
    )
    assert _extract_attribution_key(old_rows[1]) == _extract_attribution_key(new_proj.rows[1])
    assert new_proj.rows[1]["report_attribution_kind"] == "clipboard_transition_context"


def test_boundary_blocks_attribution():
    rows = [
        _row(1, f"{DATE} 09:00:00", project_id=7, source="manual"),
        _row(2, f"{DATE} 09:01:00"),
    ]
    boundaries = [f"{DATE} 09:00:45"]
    old_rows, _ = _reference_build(rows, carry_minutes=15, boundary_times=boundaries)
    new_proj = ReportContextProjection.build(rows, carry_minutes=15, boundary_times=boundaries)
    assert _extract_attribution_key(old_rows[1]) == _extract_attribution_key(new_proj.rows[1])
    assert new_proj.rows[1]["is_report_project"] is False


def test_carry_boundary_excludes_anchor():
    rows = [
        _row(1, f"{DATE} 09:00:00", project_id=7, source="manual"),
        _row(2, f"{DATE} 09:20:00"),
    ]
    old_rows, _ = _reference_build(rows, carry_minutes=5)
    new_proj = ReportContextProjection.build(rows, carry_minutes=5)
    assert _extract_attribution_key(old_rows[1]) == _extract_attribution_key(new_proj.rows[1])
    assert new_proj.rows[1]["is_report_project"] is False


def test_long_consecutive_unattributed_normal_activities():
    """The worst case for the old O(N²) algorithm — many transparent rows."""
    rows = [_row(1, f"{DATE} 09:00:00", seconds=5)]
    for i in range(2, 202):
        prev_start = datetime.strptime(rows[-1]["start_time"], TIME_FORMAT)
        start = prev_start + timedelta(seconds=5)
        rows.append(_row(i, start.strftime(TIME_FORMAT), seconds=5))

    old_rows, old_attrs = _reference_build(rows, carry_minutes=15)
    new_proj = ReportContextProjection.build(rows, carry_minutes=15)
    old_keys = [_extract_attribution_key(r) for r in old_rows]
    new_keys = [_extract_attribution_key(r) for r in new_proj.rows]
    assert old_keys == new_keys


def test_paused_status_blocks():
    rows = [
        _row(1, f"{DATE} 09:00:00", project_id=7, source="manual"),
        _row(2, f"{DATE} 09:01:00", seconds=60, status=STATUS_PAUSED),
        _row(3, f"{DATE} 09:02:00", seconds=30),
    ]
    old_rows, _ = _reference_build(rows, carry_minutes=15)
    new_proj = ReportContextProjection.build(rows, carry_minutes=15)
    assert _extract_attribution_key(old_rows[2]) == _extract_attribution_key(new_proj.rows[2])
    assert new_proj.rows[2]["is_report_project"] is False


def test_open_activity_attribution():
    rows = [
        _row(1, f"{DATE} 09:00:00", project_id=7, source="manual"),
        _row(2, f"{DATE} 09:01:00", seconds=0),
    ]
    rows[1]["end_time"] = None
    old_rows, _ = _reference_build(rows, carry_minutes=15)
    new_proj = ReportContextProjection.build(rows, carry_minutes=15)
    assert _extract_attribution_key(old_rows[1]) == _extract_attribution_key(new_proj.rows[1])


def test_cross_midnight_activity():
    rows = [
        _row(1, f"2026-07-14 23:50:00", seconds=1200, project_id=7, source="manual"),
        _row(2, f"2026-07-15 00:10:00", seconds=60),
    ]
    old_rows, _ = _reference_build(rows, carry_minutes=15)
    new_proj = ReportContextProjection.build(rows, carry_minutes=15)
    assert _extract_attribution_key(old_rows[1]) == _extract_attribution_key(new_proj.rows[1])


def test_deleted_project_anchor():
    rows = [
        _row(1, f"{DATE} 09:00:00", project_id=7, source="manual", deleted=True),
        _row(2, f"{DATE} 09:01:00", seconds=30),
    ]
    old_rows, _ = _reference_build(rows, carry_minutes=15)
    new_proj = ReportContextProjection.build(rows, carry_minutes=15)
    assert _extract_attribution_key(old_rows[1]) == _extract_attribution_key(new_proj.rows[1])


# --- Complexity test ---


def test_anchor_lookup_grows_linearly_not_quadratically():
    """1000→2000 rows should show ~2x growth in context build, not ~4x.

    Uses wall-clock ratio as a proxy. The hard gate is that the ratio must
    be well below 4x, confirming O(N) rather than O(N²).
    """

    import time

    def _build(count: int) -> float:
        rows = [_row(1, f"{DATE} 09:00:00", seconds=5)]
        for i in range(2, count + 1):
            prev_start = datetime.strptime(rows[-1]["start_time"], TIME_FORMAT)
            start = prev_start + timedelta(seconds=5)
            rows.append(_row(i, start.strftime(TIME_FORMAT), seconds=5))
        t0 = time.perf_counter()
        ReportContextProjection.build(rows, carry_minutes=15)
        return time.perf_counter() - t0

    # Warm up to stabilize timings.
    _build(100)

    t_1000 = _build(1000)
    t_2000 = _build(2000)
    ratio = t_2000 / t_1000 if t_1000 > 0 else 0
    # O(N) → ratio ≈ 2; O(N²) → ratio ≈ 4. Allow generous slack for noise.
    assert ratio < 3.5, (
        f"Context projection growth ratio {ratio:.2f} suggests super-linear "
        f"complexity (1000: {t_1000:.4f}s, 2000: {t_2000:.4f}s)"
    )


# --- BoundaryIndex unit tests ---


def test_boundary_index_empty_never_crosses():
    bi = BoundaryIndex()
    assert not bi
    assert not bi.crosses("2026-07-15 09:00:00", "2026-07-15 10:00:00")


def test_boundary_index_crosses_inclusive():
    bi = BoundaryIndex(["2026-07-15 09:30:00"])
    assert bi.crosses("2026-07-15 09:00:00", "2026-07-15 10:00:00")
    assert bi.crosses("2026-07-15 09:30:00", "2026-07-15 09:30:00")
    assert not bi.crosses("2026-07-15 10:00:00", "2026-07-15 11:00:00")


def test_boundary_index_rejects_inverted_range():
    bi = BoundaryIndex(["2026-07-15 09:30:00"])
    assert not bi.crosses("2026-07-15 10:00:00", "2026-07-15 09:00:00")


def test_boundary_index_multiple_boundaries():
    bi = BoundaryIndex([
        "2026-07-15 09:00:00",
        "2026-07-15 10:00:00",
        "2026-07-15 11:00:00",
    ])
    assert bi.crosses("2026-07-15 09:30:00", "2026-07-15 10:30:00")
    assert not bi.crosses("2026-07-15 09:30:00", "2026-07-15 09:45:00")
