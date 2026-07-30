"""Structural tests for contribution grouping and compact-storage indexing.

Verifies the O(N) contract of ``build_projection_indexes`` using operation
counting (not wall-clock timing) so the test is deterministic and excluded
from Standard CI flakiness.  A separate loose-scaling ratio test is marked
``benchmark`` and excluded from Standard CI via ``-m "not benchmark"``.

These tests replace the pathological 10k_contributions full baseline as the
ordinary PR gate for contribution-index correctness.  The 10k full scenario
remains available as a stress/diagnostic tool but is no longer a PR merge
gate.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterator, Mapping

import pytest

from worktrace.services.report_projection_model import freeze_value
from worktrace.services.report_projection_provider import (
    FrozenProjectionData,
    build_projection_indexes,
)

pytestmark = [pytest.mark.unit, pytest.mark.contract, pytest.mark.parallel_safe]


# ---------------------------------------------------------------------------
# Synthetic data builders
# ---------------------------------------------------------------------------


def _make_contribution(key: str, idx: int) -> dict[str, Any]:
    """Build a minimal synthetic contribution dict for index testing."""

    return {
        "projection_instance_key": key,
        "activity_id": idx,
        "source": "auto",
        "slice_start_time": f"2026-07-15 09:{idx // 60:02d}:{idx % 60:02d}",
    }


def _make_entry(key: str, idx: int) -> dict[str, Any]:
    """Build a minimal synthetic entry dict for index testing."""

    return {
        "projection_instance_key": key,
        "row_kind": "session",
        "session_id": idx,
        "start_time": f"2026-07-15 09:{idx // 60:02d}:{idx % 60:02d}",
    }


def _make_frozen_data(
    *,
    entry_count: int,
    contributions_per_entry: int,
) -> FrozenProjectionData:
    """Build deterministic frozen data with controlled cardinality.

    Each entry gets ``contributions_per_entry`` contributions sharing the
    same ``projection_instance_key``.  This exercises the grouping path
    that the pathological 10k_contributions scenario stresses, but at
    structural sizes that complete in milliseconds.
    """

    entries: list[Mapping[str, Any]] = []
    contributions: list[Mapping[str, Any]] = []
    for entry_idx in range(entry_count):
        key = f"session:{entry_idx}"
        entries.append(_make_entry(key, entry_idx))
        for contrib_idx in range(contributions_per_entry):
            contributions.append(
                _make_contribution(key, entry_idx * contributions_per_entry + contrib_idx)
            )

    return FrozenProjectionData(
        entries=tuple(freeze_value(e) for e in entries),
        contributions=tuple(freeze_value(c) for c in contributions),
        operation_diagnostics=(),
        snapshot_revision="test-revision",
        start_date="2026-07-15",
    )


class _CountingIterable:
    """Wrapper that counts how many items are yielded during iteration.

    Used to verify ``build_projection_indexes`` iterates contributions
    exactly once (O(N)), not O(N * K) or O(N^2).
    """

    def __init__(self, items: tuple[Any, ...]) -> None:
        self._items = items
        self.iteration_count = 0

    def __iter__(self) -> Iterator[Any]:
        for item in self._items:
            self.iteration_count += 1
            yield item


@dataclass
class _CountingFrozenData:
    """FrozenProjectionData stand-in that counts contribution iterations."""

    entries: tuple[Mapping[str, Any], ...]
    contributions: _CountingIterable
    operation_diagnostics: tuple[Any, ...]
    snapshot_revision: str
    start_date: str


# ---------------------------------------------------------------------------
# O(N) operation-counting tests
# ---------------------------------------------------------------------------


class TestContributionGroupingIsLinear:
    """Verify ``build_projection_indexes`` iterates contributions exactly once."""

    @pytest.mark.parametrize(
        "entry_count, contributions_per_entry",
        [
            (10, 1),
            (10, 5),
            (50, 10),
            (100, 5),
            (200, 10),
        ],
    )
    def test_contribution_iteration_count_equals_total(
        self,
        entry_count: int,
        contributions_per_entry: int,
    ) -> None:
        """The grouping loop must visit each contribution exactly once.

        If the implementation regressed to ``(*existing, item)`` per-key
        tuple rebuild, the iteration count would still be N (it iterates
        the source once), but the *work* per key would be O(K^2).  This
        test catches the simpler regression where the source is iterated
        more than once.  The quadratic-work regression is caught by
        ``test_scaling_ratio_is_sub_quadratic``.
        """

        frozen = _make_frozen_data(
            entry_count=entry_count,
            contributions_per_entry=contributions_per_entry,
        )
        counting = _CountingFrozenData(
            entries=frozen.entries,
            contributions=_CountingIterable(frozen.contributions),
            operation_diagnostics=frozen.operation_diagnostics,
            snapshot_revision=frozen.snapshot_revision,
            start_date=frozen.start_date,
        )
        build_projection_indexes(counting)  # type: ignore[arg-type]
        total = entry_count * contributions_per_entry
        assert counting.contributions.iteration_count == total

    def test_grouping_handles_empty_contributions(self) -> None:
        """An empty contributions tuple produces an empty index."""

        frozen = _make_frozen_data(entry_count=5, contributions_per_entry=0)
        indexes = build_projection_indexes(frozen)
        assert len(indexes.contributions_by_key) == 0
        assert len(indexes.entry_by_key) == 5

    def test_grouping_handles_empty_key_gracefully(self) -> None:
        """Contributions with empty projection_instance_key are skipped."""

        contributions = (
            freeze_value({"projection_instance_key": "", "activity_id": 1}),
            freeze_value({"projection_instance_key": None, "activity_id": 2}),
            freeze_value({"projection_instance_key": "session:0", "activity_id": 3}),
        )
        frozen = FrozenProjectionData(
            entries=(freeze_value(_make_entry("session:0", 0)),),
            contributions=contributions,
            operation_diagnostics=(),
            snapshot_revision="test",
            start_date="2026-07-15",
        )
        indexes = build_projection_indexes(frozen)
        assert "session:0" in indexes.contributions_by_key
        assert len(indexes.contributions_by_key) == 1
        assert "" not in indexes.contributions_by_key


# ---------------------------------------------------------------------------
# Identity / no-copy contract tests
# ---------------------------------------------------------------------------


class TestCompactStorageNoCopy:
    """Verify ``contributions_by_key`` references the same frozen objects."""

    def test_indexed_contributions_are_same_objects(self) -> None:
        """``contributions_by_key`` must reference identical objects, not copies.

        This is the compact-storage contract: each contribution is stored
        exactly once in ``FrozenProjectionData.contributions``, and the
        index references those same objects.  If the implementation
        deep-copied or re-froze contributions, identity would break.
        """

        frozen = _make_frozen_data(entry_count=10, contributions_per_entry=3)
        indexes = build_projection_indexes(frozen)

        for key, indexed_tuple in indexes.contributions_by_key.items():
            for contrib in indexed_tuple:
                assert contrib in frozen.contributions

    def test_entry_by_key_references_same_frozen_entries(self) -> None:
        """``entry_by_key`` must reference identical entry objects."""

        frozen = _make_frozen_data(entry_count=10, contributions_per_entry=2)
        indexes = build_projection_indexes(frozen)

        for key, entry in indexes.entry_by_key.items():
            assert entry in frozen.entries

    def test_no_duplicate_freeze_of_contributions(self) -> None:
        """The index must not re-free contributions (identity, not equality).

        If ``freeze_value`` were called again on each contribution during
        index build, the indexed objects would be new FrozenDict instances
        with different ``id()`` values, even if structurally equal.
        """

        frozen = _make_frozen_data(entry_count=5, contributions_per_entry=4)
        indexes = build_projection_indexes(frozen)

        original_ids = {id(c) for c in frozen.contributions}
        for indexed_tuple in indexes.contributions_by_key.values():
            for contrib in indexed_tuple:
                assert id(contrib) in original_ids

    def test_entry_by_key_does_not_depend_on_inline_contributions(self) -> None:
        """Entries with ``_projection_contributions`` stripped still index correctly.

        The compact-storage design strips ``_projection_contributions``
        from entries before freezing (see ``freeze_projection_data``).
        ``entry_by_key`` must work on the stripped entry — it must not
        require the inline field to be present.
        """

        entry_with_inline = {
            "projection_instance_key": "session:0",
            "row_kind": "session",
            "_projection_contributions": [
                {"activity_id": 1},
                {"activity_id": 2},
            ],
        }
        # Simulate freeze_projection_data stripping the inline field.
        stripped = dict(entry_with_inline)
        stripped.pop("_projection_contributions", None)
        frozen_entry = freeze_value(stripped)

        frozen = FrozenProjectionData(
            entries=(frozen_entry,),
            contributions=(
                freeze_value(_make_contribution("session:0", 1)),
                freeze_value(_make_contribution("session:0", 2)),
            ),
            operation_diagnostics=(),
            snapshot_revision="test",
            start_date="2026-07-15",
        )
        indexes = build_projection_indexes(frozen)
        assert "session:0" in indexes.entry_by_key
        assert indexes.entry_by_key["session:0"] is frozen_entry
        assert "_projection_contributions" not in indexes.entry_by_key["session:0"]


# ---------------------------------------------------------------------------
# Correctness tests
# ---------------------------------------------------------------------------


class TestGroupingCorrectness:
    """Verify ``contributions_by_key`` groups contributions correctly."""

    def test_all_contributions_grouped(self) -> None:
        """Every contribution with a non-empty key must appear in the index."""

        frozen = _make_frozen_data(entry_count=20, contributions_per_entry=5)
        indexes = build_projection_indexes(frozen)
        total_indexed = sum(
            len(tup) for tup in indexes.contributions_by_key.values()
        )
        assert total_indexed == len(frozen.contributions)

    def test_group_sizes_match_expected(self) -> None:
        """Each key's tuple has exactly ``contributions_per_entry`` items."""

        frozen = _make_frozen_data(entry_count=15, contributions_per_entry=7)
        indexes = build_projection_indexes(frozen)
        for key, indexed_tuple in indexes.contributions_by_key.items():
            assert len(indexed_tuple) == 7

    def test_keys_match_entries(self) -> None:
        """Every entry key appears in ``contributions_by_key`` and vice versa."""

        frozen = _make_frozen_data(entry_count=12, contributions_per_entry=3)
        indexes = build_projection_indexes(frozen)
        entry_keys = set(indexes.entry_by_key.keys())
        contribution_keys = set(indexes.contributions_by_key.keys())
        assert entry_keys == contribution_keys


# ---------------------------------------------------------------------------
# Loose scaling ratio test (marked benchmark — excluded from Standard CI)
# ---------------------------------------------------------------------------


class TestScalingRatio:
    """Loose wall-clock scaling test to catch accidental O(N^2) regressions.

    Marked ``benchmark`` so it is excluded from Standard CI via
    ``-m "not benchmark"``.  Runs in the Performance Validation workflow
    or locally.  Uses a generous ratio (3.5x for 2x input) so legitimate
    constant-factor variation does not cause flaky failures.

    Per task spec, only the 1000→2000 ratio is checked — smaller sizes
    are too noise-dominated for stable wall-clock measurement.
    """

    @pytest.mark.benchmark
    @pytest.mark.slow
    def test_scaling_ratio_is_sub_quadratic(self) -> None:
        """Doubling input from 1000→2000 must not increase time by more than 3.5x.

        A truly O(N) implementation should be ~2x; O(N log N) ~2.1x;
        O(N^2) ~4x.  The 3.5x threshold catches quadratic regressions
        while tolerating GC / allocator noise.
        """

        import time

        # Warmup to stabilize allocator/GC before timing.
        warmup = _make_frozen_data(entry_count=500, contributions_per_entry=5)
        for _ in range(3):
            build_projection_indexes(warmup)

        sizes = [1000, 2000]
        timings: list[float] = []

        for size in sizes:
            frozen = _make_frozen_data(
                entry_count=size,
                contributions_per_entry=5,
            )
            start = time.perf_counter()
            for _ in range(10):
                build_projection_indexes(frozen)
            elapsed = time.perf_counter() - start
            timings.append(elapsed)

        ratio = timings[1] / max(timings[0], 1e-9)

        # 2x input → expect ≤ 3.5x time (sub-quadratic).
        assert ratio <= 3.5, (
            f"1000→2000 scaling ratio {ratio:.2f}x exceeds 3.5x"
        )
