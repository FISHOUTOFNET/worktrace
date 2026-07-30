"""Cross-revision consistency and scenario isolation tests for product comparison.

Covers the pure-Python functions in ``scripts/benchmark_comparison.py``:
the scenario-scoped ``SideResult`` loader, per-side revision identity
validation, cross-revision consistency checks, per-scenario fixture
isolation, metric extraction, gate computation, and fail-closed
exit-code semantics.

The comparison is scenario-scoped: each invocation compares exactly one
scenario (``--scenario``) and reads ``result.json`` from the baseline and
HEAD driver output directories.  When ``result.json`` is missing on
either side, the comparison reads ``progress.json`` and ``failure.json``
so the artifact can still report the last completed phase, the failure
category, and any partial samples.

The script is loaded from its file path because ``scripts/`` is not a
Python package; using ``importlib`` keeps the test hermetic.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

from tests.support.performance_artifact_factory import (
    BASELINE_SHA,
    HEAD_SHA,
    make_product_fixture_audit,
    make_product_progress,
    make_product_result,
    make_product_side,
)

pytestmark = [pytest.mark.unit, pytest.mark.contract, pytest.mark.parallel_safe]

ROOT = Path(__file__).resolve().parents[2]
COMPARISON_PATH = ROOT / "scripts" / "benchmark_comparison.py"


@pytest.fixture(scope="module")
def comparison_module():
    """Load scripts/benchmark_comparison.py as a module."""
    spec = importlib.util.spec_from_file_location(
        "benchmark_comparison_under_test", COMPARISON_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["benchmark_comparison_under_test"] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop("benchmark_comparison_under_test", None)
        raise
    return module


# ---------------------------------------------------------------------------
# _validate_cross_revision_consistency
# ---------------------------------------------------------------------------

class TestValidateCrossRevisionConsistency:
    """Tests for the cross-revision consistency checks.

    ``_validate_cross_revision_consistency`` cross-checks driver_version,
    fixture_hash, and Python major.minor between baseline and HEAD.
    """

    def test_consistent_sides_pass(
        self, comparison_module, tmp_path: Path
    ) -> None:
        baseline = make_product_side(
            comparison_module, tmp_path / "baseline",
            result=make_product_result(revision=BASELINE_SHA),
            expected_sha=BASELINE_SHA,
        )
        head = make_product_side(
            comparison_module, tmp_path / "head",
            result=make_product_result(revision=HEAD_SHA),
            expected_sha=HEAD_SHA,
        )
        comparison_module._validate_cross_revision_consistency(baseline, head)

    def test_driver_version_mismatch_raises(
        self, comparison_module, tmp_path: Path
    ) -> None:
        baseline = make_product_side(
            comparison_module, tmp_path / "baseline",
            result=make_product_result(
                revision=BASELINE_SHA, driver_version="1.0"
            ),
            expected_sha=BASELINE_SHA,
        )
        head = make_product_side(
            comparison_module, tmp_path / "head",
            result=make_product_result(
                revision=HEAD_SHA, driver_version="2.0"
            ),
            expected_sha=HEAD_SHA,
        )
        with pytest.raises(
            comparison_module.ComparisonError, match="driver_version"
        ):
            comparison_module._validate_cross_revision_consistency(baseline, head)

    def test_fixture_hash_mismatch_raises(
        self, comparison_module, tmp_path: Path
    ) -> None:
        baseline = make_product_side(
            comparison_module, tmp_path / "baseline",
            result=make_product_result(
                revision=BASELINE_SHA, fixture_hash="hashA"
            ),
            expected_sha=BASELINE_SHA,
        )
        head = make_product_side(
            comparison_module, tmp_path / "head",
            result=make_product_result(
                revision=HEAD_SHA, fixture_hash="hashB"
            ),
            expected_sha=HEAD_SHA,
        )
        with pytest.raises(
            comparison_module.ComparisonError, match="fixture_hash"
        ):
            comparison_module._validate_cross_revision_consistency(baseline, head)

    def test_fixture_hash_empty_on_one_side_skipped(
        self, comparison_module, tmp_path: Path
    ) -> None:
        """If one side has an empty fixture_hash, the check is skipped."""
        baseline = make_product_side(
            comparison_module, tmp_path / "baseline",
            result=make_product_result(
                revision=BASELINE_SHA, fixture_hash=""
            ),
            expected_sha=BASELINE_SHA,
        )
        head = make_product_side(
            comparison_module, tmp_path / "head",
            result=make_product_result(
                revision=HEAD_SHA, fixture_hash="hashB"
            ),
            expected_sha=HEAD_SHA,
        )
        comparison_module._validate_cross_revision_consistency(baseline, head)

    def test_python_major_minor_mismatch_raises(
        self, comparison_module, tmp_path: Path
    ) -> None:
        baseline = make_product_side(
            comparison_module, tmp_path / "baseline",
            result=make_product_result(
                revision=BASELINE_SHA, python_version="3.11.5"
            ),
            expected_sha=BASELINE_SHA,
        )
        head = make_product_side(
            comparison_module, tmp_path / "head",
            result=make_product_result(
                revision=HEAD_SHA, python_version="3.12.1"
            ),
            expected_sha=HEAD_SHA,
        )
        with pytest.raises(
            comparison_module.ComparisonError, match="python_version"
        ):
            comparison_module._validate_cross_revision_consistency(baseline, head)

    def test_python_patch_difference_allowed(
        self, comparison_module, tmp_path: Path
    ) -> None:
        baseline = make_product_side(
            comparison_module, tmp_path / "baseline",
            result=make_product_result(
                revision=BASELINE_SHA, python_version="3.11.5"
            ),
            expected_sha=BASELINE_SHA,
        )
        head = make_product_side(
            comparison_module, tmp_path / "head",
            result=make_product_result(
                revision=HEAD_SHA, python_version="3.11.9"
            ),
            expected_sha=HEAD_SHA,
        )
        comparison_module._validate_cross_revision_consistency(baseline, head)


# ---------------------------------------------------------------------------
# _validate_scenario_isolation
# ---------------------------------------------------------------------------

class TestValidateScenarioIsolation:
    """Tests for the per-side fixture_audit isolation contract.

    ``_validate_scenario_isolation`` takes a ``SideResult`` and verifies
    its ``fixture_audit`` reports clean isolation:
      * ``preexisting_activity_count == 0`` (no carryover),
      * ``inserted_count == requested_count`` (every row inserted),
      * ``connection_count >= 1`` (the O(1) connection contract held),
      * ``commit_count >= 1`` (at least one commit happened).
    """

    def test_clean_audit_passes(
        self, comparison_module, tmp_path: Path
    ) -> None:
        side = make_product_side(
            comparison_module, tmp_path / "baseline",
            result=make_product_result(revision=BASELINE_SHA),
            expected_sha=BASELINE_SHA,
        )
        comparison_module._validate_scenario_isolation(side)

    def test_empty_fixture_audit_raises(
        self, comparison_module, tmp_path: Path
    ) -> None:
        payload = make_product_result(
            revision=BASELINE_SHA, fixture_audit={},
        )
        side = make_product_side(
            comparison_module, tmp_path / "baseline",
            result=payload, expected_sha=BASELINE_SHA,
        )
        with pytest.raises(comparison_module.ComparisonError, match="empty"):
            comparison_module._validate_scenario_isolation(side)

    def test_fixture_audit_not_object_raises(
        self, comparison_module, tmp_path: Path
    ) -> None:
        payload = make_product_result(revision=BASELINE_SHA)
        payload["fixture_audit"] = "not-an-object"
        side = make_product_side(
            comparison_module, tmp_path / "baseline",
            result=payload, expected_sha=BASELINE_SHA,
        )
        with pytest.raises(
            comparison_module.ComparisonError, match="fixture_audit"
        ):
            comparison_module._validate_scenario_isolation(side)

    def test_preexisting_activity_count_nonzero_raises(
        self, comparison_module, tmp_path: Path
    ) -> None:
        audit = make_product_fixture_audit(preexisting_activity_count=5)
        payload = make_product_result(
            revision=BASELINE_SHA, fixture_audit=audit,
        )
        side = make_product_side(
            comparison_module, tmp_path / "baseline",
            result=payload, expected_sha=BASELINE_SHA,
        )
        with pytest.raises(
            comparison_module.ComparisonError, match="preexisting_activity_count"
        ):
            comparison_module._validate_scenario_isolation(side)

    def test_inserted_count_mismatch_raises(
        self, comparison_module, tmp_path: Path
    ) -> None:
        audit = make_product_fixture_audit(inserted_count=19999)
        payload = make_product_result(
            revision=BASELINE_SHA, fixture_audit=audit,
        )
        side = make_product_side(
            comparison_module, tmp_path / "baseline",
            result=payload, expected_sha=BASELINE_SHA,
        )
        with pytest.raises(
            comparison_module.ComparisonError, match="inserted_count"
        ):
            comparison_module._validate_scenario_isolation(side)

    def test_connection_count_zero_raises(
        self, comparison_module, tmp_path: Path
    ) -> None:
        audit = make_product_fixture_audit(connection_count=0)
        payload = make_product_result(
            revision=BASELINE_SHA, fixture_audit=audit,
        )
        side = make_product_side(
            comparison_module, tmp_path / "baseline",
            result=payload, expected_sha=BASELINE_SHA,
        )
        with pytest.raises(
            comparison_module.ComparisonError, match="connection_count"
        ):
            comparison_module._validate_scenario_isolation(side)

    def test_commit_count_zero_raises(
        self, comparison_module, tmp_path: Path
    ) -> None:
        audit = make_product_fixture_audit(commit_count=0)
        payload = make_product_result(
            revision=BASELINE_SHA, fixture_audit=audit,
        )
        side = make_product_side(
            comparison_module, tmp_path / "baseline",
            result=payload, expected_sha=BASELINE_SHA,
        )
        with pytest.raises(
            comparison_module.ComparisonError, match="commit_count"
        ):
            comparison_module._validate_scenario_isolation(side)

    def test_isolation_checked_from_progress(
        self, comparison_module, tmp_path: Path
    ) -> None:
        """When only progress.json is present, fixture_audit is read from
        progress — isolation is still validated."""
        audit = make_product_fixture_audit(preexisting_activity_count=3)
        progress = make_product_progress(
            revision=BASELINE_SHA, fixture_audit=audit,
        )
        side = make_product_side(
            comparison_module, tmp_path / "baseline",
            progress=progress, expected_sha=BASELINE_SHA,
        )
        with pytest.raises(
            comparison_module.ComparisonError, match="preexisting_activity_count"
        ):
            comparison_module._validate_scenario_isolation(side)
