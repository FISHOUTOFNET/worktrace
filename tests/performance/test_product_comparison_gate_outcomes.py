"""Metric extraction, gate computation, and comparison builder tests for product comparison.

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
    write_json,
    write_product_result,
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
# _extract_metric
# ---------------------------------------------------------------------------

class TestExtractMetric:
    """Tests for extracting a single gated metric from a SideResult.

    ``_extract_metric`` takes a ``SideResult`` (not a dict) plus
    keyword-only ``metric_key``, ``value_field``, ``sample_field``.
    """

    def test_valid_metric_returns_median_and_samples(
        self, comparison_module, tmp_path: Path
    ) -> None:
        side = make_product_side(
            comparison_module, tmp_path / "baseline",
            result=make_product_result(revision=BASELINE_SHA),
            expected_sha=BASELINE_SHA,
        )
        median, samples = comparison_module._extract_metric(
            side,
            metric_key="projection_20k_total_seconds",
            value_field="median_seconds",
            sample_field="samples_seconds",
        )
        assert median == 1.0
        assert samples == [1.0, 1.05, 0.98]

    def test_missing_metric_raises(
        self, comparison_module, tmp_path: Path
    ) -> None:
        side = make_product_side(
            comparison_module, tmp_path / "baseline",
            result=make_product_result(revision=BASELINE_SHA, metrics={}),
            expected_sha=BASELINE_SHA,
        )
        with pytest.raises(comparison_module.ComparisonError, match="missing"):
            comparison_module._extract_metric(
                side,
                metric_key="projection_20k_total_seconds",
                value_field="median_seconds",
                sample_field="samples_seconds",
            )

    def test_metric_not_object_raises(
        self, comparison_module, tmp_path: Path
    ) -> None:
        payload = make_product_result(
            revision=BASELINE_SHA,
            metrics={"projection_20k_total_seconds": "not-an-object"},
        )
        side = make_product_side(
            comparison_module, tmp_path / "baseline",
            result=payload, expected_sha=BASELINE_SHA,
        )
        with pytest.raises(comparison_module.ComparisonError, match="not object"):
            comparison_module._extract_metric(
                side,
                metric_key="projection_20k_total_seconds",
                value_field="median_seconds",
                sample_field="samples_seconds",
            )

    def test_missing_value_field_raises(
        self, comparison_module, tmp_path: Path
    ) -> None:
        payload = make_product_result(
            revision=BASELINE_SHA,
            metrics={"projection_20k_total_seconds": {"samples_seconds": [1.0]}},
        )
        side = make_product_side(
            comparison_module, tmp_path / "baseline",
            result=payload, expected_sha=BASELINE_SHA,
        )
        with pytest.raises(
            comparison_module.ComparisonError, match="median_seconds"
        ):
            comparison_module._extract_metric(
                side,
                metric_key="projection_20k_total_seconds",
                value_field="median_seconds",
                sample_field="samples_seconds",
            )

    def test_missing_sample_field_raises(
        self, comparison_module, tmp_path: Path
    ) -> None:
        payload = make_product_result(
            revision=BASELINE_SHA,
            metrics={"projection_20k_total_seconds": {"median_seconds": 1.0}},
        )
        side = make_product_side(
            comparison_module, tmp_path / "baseline",
            result=payload, expected_sha=BASELINE_SHA,
        )
        with pytest.raises(
            comparison_module.ComparisonError, match="samples_seconds"
        ):
            comparison_module._extract_metric(
                side,
                metric_key="projection_20k_total_seconds",
                value_field="median_seconds",
                sample_field="samples_seconds",
            )

    def test_samples_not_list_raises(
        self, comparison_module, tmp_path: Path
    ) -> None:
        payload = make_product_result(
            revision=BASELINE_SHA,
            metrics={"projection_20k_total_seconds": {
                "median_seconds": 1.0,
                "samples_seconds": "not-a-list",
            }},
        )
        side = make_product_side(
            comparison_module, tmp_path / "baseline",
            result=payload, expected_sha=BASELINE_SHA,
        )
        with pytest.raises(comparison_module.ComparisonError, match="not a list"):
            comparison_module._extract_metric(
                side,
                metric_key="projection_20k_total_seconds",
                value_field="median_seconds",
                sample_field="samples_seconds",
            )

    def test_zero_samples_raises_comparison_error(
        self, comparison_module, tmp_path: Path
    ) -> None:
        """Zero samples raises ComparisonError (not IncompleteError —
        that class no longer exists in the new API)."""
        payload = make_product_result(
            revision=BASELINE_SHA,
            metrics={"projection_20k_total_seconds": {
                "median_seconds": 0.0,
                "samples_seconds": [],
            }},
        )
        side = make_product_side(
            comparison_module, tmp_path / "baseline",
            result=payload, expected_sha=BASELINE_SHA,
        )
        with pytest.raises(comparison_module.ComparisonError, match="zero samples"):
            comparison_module._extract_metric(
                side,
                metric_key="projection_20k_total_seconds",
                value_field="median_seconds",
                sample_field="samples_seconds",
            )

    def test_10k_contributions_metric(
        self, comparison_module, tmp_path: Path
    ) -> None:
        side = make_product_side(
            comparison_module, tmp_path / "baseline",
            result=make_product_result(
                revision=BASELINE_SHA, scenario="10k_contributions"
            ),
            expected_sha=BASELINE_SHA,
            scenario="10k_contributions",
        )
        median, samples = comparison_module._extract_metric(
            side,
            metric_key="projection_10k_contributions_seconds",
            value_field="median_seconds",
            sample_field="samples_seconds",
        )
        assert median == 1.0
        assert samples == [1.0, 1.05, 0.98]


# ---------------------------------------------------------------------------
# _percent_delta
# ---------------------------------------------------------------------------

class TestPercentDelta:
    """Tests for the percentage delta computation."""

    def test_zero_baseline_zero_head_returns_zero(
        self, comparison_module
    ) -> None:
        assert comparison_module._percent_delta(0.0, 0.0) == 0.0

    def test_zero_baseline_nonzero_head_returns_100(
        self, comparison_module
    ) -> None:
        assert comparison_module._percent_delta(0.0, 1.0) == 100.0

    def test_improvement_returns_negative(self, comparison_module) -> None:
        assert comparison_module._percent_delta(1.0, 0.8) == pytest.approx(-20.0)

    def test_regression_returns_positive(self, comparison_module) -> None:
        assert comparison_module._percent_delta(1.0, 1.15) == pytest.approx(15.0)

    def test_boundary_10pct_regression(self, comparison_module) -> None:
        # head=1.10, baseline=1.0 -> exactly +10% (gate passes with <= 10)
        assert comparison_module._percent_delta(1.0, 1.10) == pytest.approx(10.0)


# ---------------------------------------------------------------------------
# _build_comparison
# ---------------------------------------------------------------------------

class TestBuildComparison:
    """Tests for the full comparison builder including outcome semantics.

    ``_build_comparison`` is scenario-scoped (requires ``--scenario``)
    and always returns an artifact dict with an ``outcome`` field.
    """

    def _make_dirs(
        self,
        tmp_path: Path,
        *,
        baseline_payload: dict[str, Any] | None = None,
        head_payload: dict[str, Any] | None = None,
        baseline_progress: dict[str, Any] | None = None,
        head_progress: dict[str, Any] | None = None,
    ) -> tuple[Path, Path]:
        baseline_dir = tmp_path / "baseline"
        head_dir = tmp_path / "head"
        if baseline_payload is not None:
            write_product_result(baseline_dir, baseline_payload)
        if head_payload is not None:
            write_product_result(head_dir, head_payload)
        if baseline_progress is not None:
            write_json(baseline_dir / "progress.json", baseline_progress)
        if head_progress is not None:
            write_json(head_dir / "progress.json", head_progress)
        return baseline_dir, head_dir

    def test_comparison_passed_when_head_not_regressed(
        self, comparison_module, tmp_path: Path
    ) -> None:
        baseline_dir, head_dir = self._make_dirs(
            tmp_path,
            baseline_payload=make_product_result(
                revision=BASELINE_SHA,
                metrics={"projection_20k_total_seconds": {
                    "samples_seconds": [1.0, 1.0, 1.0],
                    "median_seconds": 1.0,
                    "consistency_hash": "hash20k",
                }},
            ),
            head_payload=make_product_result(
                revision=HEAD_SHA,
                metrics={"projection_20k_total_seconds": {
                    "samples_seconds": [0.95, 0.95, 0.95],
                    "median_seconds": 0.95,
                    "consistency_hash": "hash20k",
                }},
            ),
        )
        report = comparison_module._build_comparison(
            scenario="20k_activities",
            baseline_dir=baseline_dir,
            head_dir=head_dir,
            baseline_sha=BASELINE_SHA,
            head_sha=HEAD_SHA,
            tolerance_pct=10.0,
        )
        assert report["outcome"] == "comparison_passed"
        assert report["gated_metric"] is not None
        assert report["gated_metric"]["gate_passed"] is True
        assert report["consistency_match"] is True

    def test_comparison_gate_failed_when_head_regressed(
        self, comparison_module, tmp_path: Path
    ) -> None:
        # 15% regression (1.0 -> 1.15) — exceeds 10% tolerance.
        baseline_dir, head_dir = self._make_dirs(
            tmp_path,
            baseline_payload=make_product_result(
                revision=BASELINE_SHA,
                metrics={"projection_20k_total_seconds": {
                    "samples_seconds": [1.0, 1.0, 1.0],
                    "median_seconds": 1.0,
                    "consistency_hash": "hash20k",
                }},
            ),
            head_payload=make_product_result(
                revision=HEAD_SHA,
                metrics={"projection_20k_total_seconds": {
                    "samples_seconds": [1.15, 1.15, 1.15],
                    "median_seconds": 1.15,
                    "consistency_hash": "hash20k",
                }},
            ),
        )
        report = comparison_module._build_comparison(
            scenario="20k_activities",
            baseline_dir=baseline_dir,
            head_dir=head_dir,
            baseline_sha=BASELINE_SHA,
            head_sha=HEAD_SHA,
            tolerance_pct=10.0,
        )
        assert report["outcome"] == "comparison_gate_failed"
        assert report["gated_metric"]["gate_passed"] is False
        assert report["gated_metric"]["delta_pct"] == pytest.approx(15.0)

    def test_baseline_invalid_when_baseline_result_missing(
        self, comparison_module, tmp_path: Path
    ) -> None:
        """Missing result.json on baseline (progress present) →
        baseline_invalid.  The artifact is still produced."""
        baseline_dir, head_dir = self._make_dirs(
            tmp_path,
            baseline_progress=make_product_progress(revision=BASELINE_SHA),
            head_payload=make_product_result(revision=HEAD_SHA),
        )
        report = comparison_module._build_comparison(
            scenario="20k_activities",
            baseline_dir=baseline_dir,
            head_dir=head_dir,
            baseline_sha=BASELINE_SHA,
            head_sha=HEAD_SHA,
            tolerance_pct=10.0,
        )
        assert report["outcome"] == "baseline_invalid"
        assert report["gated_metric"] is None
        assert report["baseline"]["valid"] is False
        assert report["head"]["valid"] is True

    def test_head_invalid_when_head_result_missing(
        self, comparison_module, tmp_path: Path
    ) -> None:
        baseline_dir, head_dir = self._make_dirs(
            tmp_path,
            baseline_payload=make_product_result(revision=BASELINE_SHA),
            head_progress=make_product_progress(revision=HEAD_SHA),
        )
        report = comparison_module._build_comparison(
            scenario="20k_activities",
            baseline_dir=baseline_dir,
            head_dir=head_dir,
            baseline_sha=BASELINE_SHA,
            head_sha=HEAD_SHA,
            tolerance_pct=10.0,
        )
        assert report["outcome"] == "head_invalid"
        assert report["gated_metric"] is None
        assert report["baseline"]["valid"] is True
        assert report["head"]["valid"] is False

    def test_both_invalid_when_neither_result_present(
        self, comparison_module, tmp_path: Path
    ) -> None:
        baseline_dir, head_dir = self._make_dirs(
            tmp_path,
            baseline_progress=make_product_progress(revision=BASELINE_SHA),
            head_progress=make_product_progress(revision=HEAD_SHA),
        )
        report = comparison_module._build_comparison(
            scenario="20k_activities",
            baseline_dir=baseline_dir,
            head_dir=head_dir,
            baseline_sha=BASELINE_SHA,
            head_sha=HEAD_SHA,
            tolerance_pct=10.0,
        )
        assert report["outcome"] == "both_invalid"
        assert report["gated_metric"] is None
        assert report["baseline"]["valid"] is False
        assert report["head"]["valid"] is False

    def test_both_invalid_on_consistency_error(
        self, comparison_module, tmp_path: Path
    ) -> None:
        """When both sides are valid but consistency checks fail, the
        outcome is both_invalid with a consistency_error message."""
        baseline_dir, head_dir = self._make_dirs(
            tmp_path,
            baseline_payload=make_product_result(
                revision=BASELINE_SHA, driver_version="1.0"
            ),
            head_payload=make_product_result(
                revision=HEAD_SHA, driver_version="2.0"
            ),
        )
        report = comparison_module._build_comparison(
            scenario="20k_activities",
            baseline_dir=baseline_dir,
            head_dir=head_dir,
            baseline_sha=BASELINE_SHA,
            head_sha=HEAD_SHA,
            tolerance_pct=10.0,
        )
        assert report["outcome"] == "both_invalid"
        assert report["gated_metric"] is None
        assert "consistency_error" in report
        assert "driver_version" in report["consistency_error"]

    def test_both_invalid_on_isolation_error(
        self, comparison_module, tmp_path: Path
    ) -> None:
        """Scenario isolation failure on one side also produces
        both_invalid with a consistency_error message."""
        bad_audit = make_product_fixture_audit(preexisting_activity_count=5)
        baseline_dir, head_dir = self._make_dirs(
            tmp_path,
            baseline_payload=make_product_result(
                revision=BASELINE_SHA, fixture_audit=bad_audit
            ),
            head_payload=make_product_result(revision=HEAD_SHA),
        )
        report = comparison_module._build_comparison(
            scenario="20k_activities",
            baseline_dir=baseline_dir,
            head_dir=head_dir,
            baseline_sha=BASELINE_SHA,
            head_sha=HEAD_SHA,
            tolerance_pct=10.0,
        )
        assert report["outcome"] == "both_invalid"
        assert "consistency_error" in report
        assert "preexisting_activity_count" in report["consistency_error"]

    def test_unknown_scenario_raises(
        self, comparison_module, tmp_path: Path
    ) -> None:
        baseline_dir, head_dir = self._make_dirs(
            tmp_path,
            baseline_payload=make_product_result(revision=BASELINE_SHA),
            head_payload=make_product_result(revision=HEAD_SHA),
        )
        with pytest.raises(
            comparison_module.ComparisonError, match="unknown scenario"
        ):
            comparison_module._build_comparison(
                scenario="bogus",
                baseline_dir=baseline_dir,
                head_dir=head_dir,
                baseline_sha=BASELINE_SHA,
                head_sha=HEAD_SHA,
                tolerance_pct=10.0,
            )

    def test_sample_count_mismatch_raises(
        self, comparison_module, tmp_path: Path
    ) -> None:
        baseline_dir, head_dir = self._make_dirs(
            tmp_path,
            baseline_payload=make_product_result(
                revision=BASELINE_SHA,
                metrics={"projection_20k_total_seconds": {
                    "samples_seconds": [1.0, 1.0],
                    "median_seconds": 1.0,
                    "consistency_hash": "hash20k",
                }},
            ),
            head_payload=make_product_result(
                revision=HEAD_SHA,
                metrics={"projection_20k_total_seconds": {
                    "samples_seconds": [1.0],
                    "median_seconds": 1.0,
                    "consistency_hash": "hash20k",
                }},
            ),
        )
        with pytest.raises(comparison_module.ComparisonError, match="sample count"):
            comparison_module._build_comparison(
                scenario="20k_activities",
                baseline_dir=baseline_dir,
                head_dir=head_dir,
                baseline_sha=BASELINE_SHA,
                head_sha=HEAD_SHA,
                tolerance_pct=10.0,
            )

    def test_artifact_structure(
        self, comparison_module, tmp_path: Path
    ) -> None:
        baseline_dir, head_dir = self._make_dirs(
            tmp_path,
            baseline_payload=make_product_result(revision=BASELINE_SHA),
            head_payload=make_product_result(revision=HEAD_SHA),
        )
        report = comparison_module._build_comparison(
            scenario="20k_activities",
            baseline_dir=baseline_dir,
            head_dir=head_dir,
            baseline_sha=BASELINE_SHA,
            head_sha=HEAD_SHA,
            tolerance_pct=10.0,
        )
        assert report["schema_version"] == 3
        assert report["scenario"] == "20k_activities"
        assert report["metric_key"] == "projection_20k_total_seconds"
        assert report["baseline_sha"] == BASELINE_SHA
        assert report["head_sha"] == HEAD_SHA
        assert report["tolerance_pct"] == 10.0
        assert "baseline" in report
        assert "head" in report
        assert "gated_metric" in report
        assert "consistency_match" in report
        row = report["gated_metric"]
        assert row["metric"] == "projection_20k_total_seconds"
        assert row["unit"] == "seconds"
        for field in (
            "baseline_samples", "head_samples",
            "baseline_median", "head_median",
            "baseline_min", "baseline_max",
            "head_min", "head_max",
            "delta", "delta_pct",
            "baseline_consistency_hash", "head_consistency_hash",
            "gate_passed", "tolerance_pct",
        ):
            assert field in row

    def test_10k_contributions_scenario(
        self, comparison_module, tmp_path: Path
    ) -> None:
        baseline_dir, head_dir = self._make_dirs(
            tmp_path,
            baseline_payload=make_product_result(
                revision=BASELINE_SHA, scenario="10k_contributions",
                metrics={"projection_10k_contributions_seconds": {
                    "samples_seconds": [0.5, 0.5, 0.5],
                    "median_seconds": 0.5,
                    "consistency_hash": "hash10k",
                }},
            ),
            head_payload=make_product_result(
                revision=HEAD_SHA, scenario="10k_contributions",
                metrics={"projection_10k_contributions_seconds": {
                    "samples_seconds": [0.48, 0.48, 0.48],
                    "median_seconds": 0.48,
                    "consistency_hash": "hash10k",
                }},
            ),
        )
        report = comparison_module._build_comparison(
            scenario="10k_contributions",
            baseline_dir=baseline_dir,
            head_dir=head_dir,
            baseline_sha=BASELINE_SHA,
            head_sha=HEAD_SHA,
            tolerance_pct=10.0,
        )
        assert report["outcome"] == "comparison_passed"
        assert report["metric_key"] == "projection_10k_contributions_seconds"
        assert report["gated_metric"]["metric"] == (
            "projection_10k_contributions_seconds"
        )

    def test_consistency_hash_mismatch_recorded(
        self, comparison_module, tmp_path: Path
    ) -> None:
        """When the per-metric consistency_hash differs between baseline
        and head, consistency_match is False but the gate can still
        pass (the hash is diagnostic, not gating)."""
        baseline_dir, head_dir = self._make_dirs(
            tmp_path,
            baseline_payload=make_product_result(
                revision=BASELINE_SHA,
                metrics={"projection_20k_total_seconds": {
                    "samples_seconds": [1.0, 1.0, 1.0],
                    "median_seconds": 1.0,
                    "consistency_hash": "hashA",
                }},
            ),
            head_payload=make_product_result(
                revision=HEAD_SHA,
                metrics={"projection_20k_total_seconds": {
                    "samples_seconds": [0.95, 0.95, 0.95],
                    "median_seconds": 0.95,
                    "consistency_hash": "hashB",
                }},
            ),
        )
        report = comparison_module._build_comparison(
            scenario="20k_activities",
            baseline_dir=baseline_dir,
            head_dir=head_dir,
            baseline_sha=BASELINE_SHA,
            head_sha=HEAD_SHA,
            tolerance_pct=10.0,
        )
        assert report["consistency_match"] is False
        assert report["outcome"] == "comparison_passed"

    def test_side_diagnostics_in_artifact(
        self, comparison_module, tmp_path: Path
    ) -> None:
        """The artifact includes per-side diagnostics with result_present,
        valid, last_phase, fixture_audit, and revision fields."""
        baseline_dir, head_dir = self._make_dirs(
            tmp_path,
            baseline_payload=make_product_result(revision=BASELINE_SHA),
            head_payload=make_product_result(revision=HEAD_SHA),
        )
        report = comparison_module._build_comparison(
            scenario="20k_activities",
            baseline_dir=baseline_dir,
            head_dir=head_dir,
            baseline_sha=BASELINE_SHA,
            head_sha=HEAD_SHA,
            tolerance_pct=10.0,
        )
        for side_label in ("baseline", "head"):
            side = report[side_label]
            assert side["label"] == side_label
            assert side["result_present"] is True
            assert side["valid"] is True
            assert side["last_phase"] == "result_completed"
            assert side["requested_revision"] != ""
            assert side["actual_target_revision"] != ""
            assert side["expected_revision"] != ""
            assert "fixture_audit" in side
            assert "output_dir" in side
