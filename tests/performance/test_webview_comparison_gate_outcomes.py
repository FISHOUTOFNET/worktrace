"""Consistency, isolation, metric extraction, and gate outcome tests for WebView comparison.

Covers the pure-Python functions in ``scripts/webview_comparison.py`` and
the ``_extract_webview_metrics`` function in ``scripts/webview_render_perf.py``.

These tests do NOT launch WebView2 or any subprocess — they exercise the
``SideResult`` tolerant loader, per-side revision identity checks,
cross-revision consistency, scenario isolation, metric extraction, gate
computation, fail-closed artifact writing, and exit-code semantics against
synthetic JSON payloads.

The scripts are loaded from their file paths because ``scripts/`` is not a
Python package; using ``importlib`` keeps the test hermetic and avoids
mutating ``sys.path`` globally.
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
    make_webview_fixture_audit,
    make_webview_result,
    write_webview_result,
)

pytestmark = [pytest.mark.unit, pytest.mark.contract, pytest.mark.parallel_safe]

ROOT = Path(__file__).resolve().parents[2]
COMPARISON_PATH = ROOT / "scripts" / "webview_comparison.py"


@pytest.fixture(scope="module")
def comparison_module():
    """Load scripts/webview_comparison.py as a module."""
    spec = importlib.util.spec_from_file_location(
        "webview_comparison_under_test", COMPARISON_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["webview_comparison_under_test"] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop("webview_comparison_under_test", None)
        raise
    return module


# ---------------------------------------------------------------------------
# _validate_cross_revision_consistency (webview_comparison.py)
# ---------------------------------------------------------------------------

class TestValidateCrossRevisionConsistency:
    """Tests for cross-revision driver/fixture/python consistency."""

    def _make_side(
        self,
        comparison_module,
        tmp_path: Path,
        *,
        label: str,
        revision: str,
        driver_version: str = "1.0",
        fixture_hash: str = "fixedhash",
        python_version: str = "3.11.5",
        activity_count: int = 20000,
    ) -> Any:
        path = write_webview_result(
            tmp_path / label,
            make_webview_result(
                revision=revision,
                driver_version=driver_version,
                fixture_hash=fixture_hash,
                python_version=python_version,
                activity_count=activity_count,
            ),
        )
        return comparison_module.SideResult(
            label=label, artifact_path=path, expected_sha=revision,
        )

    def test_driver_version_mismatch_raises(
        self, comparison_module, tmp_path: Path
    ) -> None:
        baseline = self._make_side(
            comparison_module, tmp_path, label="baseline",
            revision=BASELINE_SHA, driver_version="1.0",
        )
        head = self._make_side(
            comparison_module, tmp_path, label="head",
            revision=HEAD_SHA, driver_version="2.0",
        )
        with pytest.raises(comparison_module.ComparisonError, match="driver_version"):
            comparison_module._validate_cross_revision_consistency(baseline, head)

    def test_fixture_hash_mismatch_raises(
        self, comparison_module, tmp_path: Path
    ) -> None:
        baseline = self._make_side(
            comparison_module, tmp_path, label="baseline",
            revision=BASELINE_SHA, fixture_hash="hashA",
        )
        head = self._make_side(
            comparison_module, tmp_path, label="head",
            revision=HEAD_SHA, fixture_hash="hashB",
        )
        with pytest.raises(comparison_module.ComparisonError, match="fixture_hash"):
            comparison_module._validate_cross_revision_consistency(baseline, head)

    def test_empty_fixture_hash_skipped(
        self, comparison_module, tmp_path: Path
    ) -> None:
        """If one side has empty fixture_hash, the check is skipped."""
        baseline = self._make_side(
            comparison_module, tmp_path, label="baseline",
            revision=BASELINE_SHA, fixture_hash="",
        )
        head = self._make_side(
            comparison_module, tmp_path, label="head",
            revision=HEAD_SHA, fixture_hash="hashB",
        )
        # Should not raise — empty fixture_hash on baseline skips the check.
        comparison_module._validate_cross_revision_consistency(baseline, head)

    def test_python_major_minor_mismatch_raises(
        self, comparison_module, tmp_path: Path
    ) -> None:
        baseline = self._make_side(
            comparison_module, tmp_path, label="baseline",
            revision=BASELINE_SHA, python_version="3.11.5",
        )
        head = self._make_side(
            comparison_module, tmp_path, label="head",
            revision=HEAD_SHA, python_version="3.12.1",
        )
        with pytest.raises(comparison_module.ComparisonError, match="python_version"):
            comparison_module._validate_cross_revision_consistency(baseline, head)

    def test_python_patch_difference_allowed(
        self, comparison_module, tmp_path: Path
    ) -> None:
        baseline = self._make_side(
            comparison_module, tmp_path, label="baseline",
            revision=BASELINE_SHA, python_version="3.11.5",
        )
        head = self._make_side(
            comparison_module, tmp_path, label="head",
            revision=HEAD_SHA, python_version="3.11.9",
        )
        comparison_module._validate_cross_revision_consistency(baseline, head)

    def test_activity_count_mismatch_raises(
        self, comparison_module, tmp_path: Path
    ) -> None:
        baseline = self._make_side(
            comparison_module, tmp_path, label="baseline",
            revision=BASELINE_SHA, activity_count=20000,
        )
        head = self._make_side(
            comparison_module, tmp_path, label="head",
            revision=HEAD_SHA, activity_count=10000,
        )
        with pytest.raises(comparison_module.ComparisonError, match="activity_count"):
            comparison_module._validate_cross_revision_consistency(baseline, head)

    def test_consistent_sides_pass(
        self, comparison_module, tmp_path: Path
    ) -> None:
        baseline = self._make_side(
            comparison_module, tmp_path, label="baseline",
            revision=BASELINE_SHA,
        )
        head = self._make_side(
            comparison_module, tmp_path, label="head",
            revision=HEAD_SHA,
        )
        comparison_module._validate_cross_revision_consistency(baseline, head)


# ---------------------------------------------------------------------------
# _validate_scenario_isolation (webview_comparison.py)
# ---------------------------------------------------------------------------

class TestValidateScenarioIsolation:
    """Tests for the WebView fixture_audit isolation contract.

    The WebView driver runs a single scenario, so ``fixture_audit`` is a
    single object.  It must report:
      * ``preexisting_activity_count == 0`` (no carryover),
      * ``inserted_count == requested_count`` (every row inserted),
      * ``connection_count >= 1`` (the O(1) connection contract held),
      * ``commit_count >= 1`` (at least one commit happened).
    """

    def _make_side(
        self,
        comparison_module,
        tmp_path: Path,
        *,
        fixture_audit: dict[str, Any],
        revision: str = BASELINE_SHA,
    ) -> Any:
        path = write_webview_result(
            tmp_path,
            make_webview_result(revision=revision, fixture_audit=fixture_audit),
        )
        return comparison_module.SideResult(
            label="baseline", artifact_path=path, expected_sha=revision,
        )

    def test_empty_audit_raises(
        self, comparison_module, tmp_path: Path
    ) -> None:
        side = self._make_side(
            comparison_module, tmp_path, fixture_audit={},
        )
        with pytest.raises(comparison_module.ComparisonError, match="empty"):
            comparison_module._validate_scenario_isolation(side)

    def test_preexisting_activity_count_nonzero_raises(
        self, comparison_module, tmp_path: Path
    ) -> None:
        audit = make_webview_fixture_audit(preexisting_activity_count=5)
        side = self._make_side(comparison_module, tmp_path, fixture_audit=audit)
        with pytest.raises(
            comparison_module.ComparisonError, match="preexisting_activity_count"
        ):
            comparison_module._validate_scenario_isolation(side)

    def test_inserted_count_mismatch_raises(
        self, comparison_module, tmp_path: Path
    ) -> None:
        audit = make_webview_fixture_audit(inserted_count=19999)
        side = self._make_side(comparison_module, tmp_path, fixture_audit=audit)
        with pytest.raises(
            comparison_module.ComparisonError, match="inserted_count"
        ):
            comparison_module._validate_scenario_isolation(side)

    def test_connection_count_zero_raises(
        self, comparison_module, tmp_path: Path
    ) -> None:
        audit = make_webview_fixture_audit(connection_count=0)
        side = self._make_side(comparison_module, tmp_path, fixture_audit=audit)
        with pytest.raises(
            comparison_module.ComparisonError, match="connection_count"
        ):
            comparison_module._validate_scenario_isolation(side)

    def test_commit_count_zero_raises(
        self, comparison_module, tmp_path: Path
    ) -> None:
        audit = make_webview_fixture_audit(commit_count=0)
        side = self._make_side(comparison_module, tmp_path, fixture_audit=audit)
        with pytest.raises(
            comparison_module.ComparisonError, match="commit_count"
        ):
            comparison_module._validate_scenario_isolation(side)

    def test_clean_audit_passes(
        self, comparison_module, tmp_path: Path
    ) -> None:
        audit = make_webview_fixture_audit()
        side = self._make_side(comparison_module, tmp_path, fixture_audit=audit)
        comparison_module._validate_scenario_isolation(side)


# ---------------------------------------------------------------------------
# _extract_metric (webview_comparison.py)
# ---------------------------------------------------------------------------

class TestExtractMetric:
    """Tests for extracting a single gated metric from a SideResult."""

    def _make_side(
        self,
        comparison_module,
        tmp_path: Path,
        *,
        metrics: dict[str, Any],
        revision: str = BASELINE_SHA,
    ) -> Any:
        path = write_webview_result(
            tmp_path,
            make_webview_result(revision=revision, metrics=metrics),
        )
        return comparison_module.SideResult(
            label="baseline", artifact_path=path, expected_sha=revision,
        )

    def test_missing_metric_raises_comparison_error(
        self, comparison_module, tmp_path: Path
    ) -> None:
        side = self._make_side(comparison_module, tmp_path, metrics={})
        with pytest.raises(comparison_module.ComparisonError, match="missing"):
            comparison_module._extract_metric(side, "cold_timeline_seconds")

    def test_metric_not_object_raises_comparison_error(
        self, comparison_module, tmp_path: Path
    ) -> None:
        side = self._make_side(
            comparison_module, tmp_path,
            metrics={"cold_timeline_seconds": "not-an-object"},
        )
        with pytest.raises(comparison_module.ComparisonError, match="not object"):
            comparison_module._extract_metric(side, "cold_timeline_seconds")

    def test_missing_median_seconds_raises_comparison_error(
        self, comparison_module, tmp_path: Path
    ) -> None:
        side = self._make_side(
            comparison_module, tmp_path,
            metrics={"cold_timeline_seconds": {"samples_seconds": [1.0]}},
        )
        with pytest.raises(
            comparison_module.ComparisonError, match="median_seconds"
        ):
            comparison_module._extract_metric(side, "cold_timeline_seconds")

    def test_missing_samples_seconds_raises_comparison_error(
        self, comparison_module, tmp_path: Path
    ) -> None:
        side = self._make_side(
            comparison_module, tmp_path,
            metrics={"cold_timeline_seconds": {"median_seconds": 1.0}},
        )
        with pytest.raises(
            comparison_module.ComparisonError, match="samples_seconds"
        ):
            comparison_module._extract_metric(side, "cold_timeline_seconds")

    def test_samples_not_list_raises_comparison_error(
        self, comparison_module, tmp_path: Path
    ) -> None:
        side = self._make_side(
            comparison_module, tmp_path,
            metrics={"cold_timeline_seconds": {
                "median_seconds": 1.0,
                "samples_seconds": "not-a-list",
            }},
        )
        with pytest.raises(comparison_module.ComparisonError, match="not a list"):
            comparison_module._extract_metric(side, "cold_timeline_seconds")

    def test_zero_samples_raises_comparison_error(
        self, comparison_module, tmp_path: Path
    ) -> None:
        """An empty samples list is an error (no IncompleteError anymore)."""
        side = self._make_side(
            comparison_module, tmp_path,
            metrics={"cold_timeline_seconds": {
                "median_seconds": 0.0,
                "samples_seconds": [],
            }},
        )
        with pytest.raises(comparison_module.ComparisonError, match="zero samples"):
            comparison_module._extract_metric(side, "cold_timeline_seconds")

    def test_valid_metric_returns_median_and_samples(
        self, comparison_module, tmp_path: Path
    ) -> None:
        side = self._make_side(
            comparison_module, tmp_path,
            metrics={"cold_timeline_seconds": {
                "median_seconds": 1.0, "samples_seconds": [1.0, 1.1],
            }},
        )
        median, samples = comparison_module._extract_metric(
            side, "cold_timeline_seconds"
        )
        assert median == 1.0
        assert samples == [1.0, 1.1]

    def test_returns_floats_even_for_int_inputs(
        self, comparison_module, tmp_path: Path
    ) -> None:
        """Median and samples are coerced to float."""
        side = self._make_side(
            comparison_module, tmp_path,
            metrics={"cold_timeline_seconds": {
                "median_seconds": 1, "samples_seconds": [1, 2, 3],
            }},
        )
        median, samples = comparison_module._extract_metric(
            side, "cold_timeline_seconds"
        )
        assert isinstance(median, float)
        assert all(isinstance(s, float) for s in samples)
        assert median == 1.0
        assert samples == [1.0, 2.0, 3.0]


# ---------------------------------------------------------------------------
# _percent_delta (webview_comparison.py)
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

    def test_positive_baseline_improvement_returns_negative(
        self, comparison_module
    ) -> None:
        # head=0.8, baseline=1.0 -> -20%
        assert comparison_module._percent_delta(1.0, 0.8) == pytest.approx(-20.0)

    def test_positive_baseline_regression_returns_positive(
        self, comparison_module
    ) -> None:
        # head=1.15, baseline=1.0 -> +15%
        assert comparison_module._percent_delta(1.0, 1.15) == pytest.approx(15.0)

    def test_boundary_10pct_regression(self, comparison_module) -> None:
        # head=1.10, baseline=1.0 -> exactly +10% (gate passes with <= 10)
        assert comparison_module._percent_delta(1.0, 1.10) == pytest.approx(10.0)


# ---------------------------------------------------------------------------
# _build_comparison (webview_comparison.py)
# ---------------------------------------------------------------------------

class TestBuildComparison:
    """Tests for the full comparison builder including outcome categories."""

    def _make_dirs(
        self,
        tmp_path: Path,
        *,
        baseline_payload: dict[str, Any] | None = None,
        head_payload: dict[str, Any] | None = None,
    ) -> tuple[Path, Path]:
        baseline_dir = tmp_path / "baseline"
        head_dir = tmp_path / "head"
        if baseline_payload is not None:
            write_webview_result(baseline_dir, baseline_payload)
        if head_payload is not None:
            write_webview_result(head_dir, head_payload)
        return baseline_dir, head_dir

    def _build(
        self,
        comparison_module,
        baseline_dir: Path,
        head_dir: Path,
        *,
        baseline_sha: str = BASELINE_SHA,
        head_sha: str = HEAD_SHA,
        tolerance_pct: float = 10.0,
    ) -> dict[str, Any]:
        return comparison_module._build_comparison(
            baseline_dir=baseline_dir,
            head_dir=head_dir,
            baseline_sha=baseline_sha,
            head_sha=head_sha,
            tolerance_pct=tolerance_pct,
        )

    def test_comparison_passed_when_head_not_regressed(
        self, comparison_module, tmp_path: Path
    ) -> None:
        baseline_dir, head_dir = self._make_dirs(
            tmp_path,
            baseline_payload=make_webview_result(
                revision=BASELINE_SHA,
                metrics={
                    "cold_timeline_seconds": {
                        "samples_seconds": [1.0], "median_seconds": 1.0,
                    },
                    "warm_timeline_seconds": {
                        "samples_seconds": [0.9, 0.9, 0.9], "median_seconds": 0.9,
                    },
                    "detail_payload_seconds": {
                        "samples_seconds": [0.05, 0.05, 0.05], "median_seconds": 0.05,
                    },
                    "detail_total_seconds": {
                        "samples_seconds": [0.2, 0.2, 0.2], "median_seconds": 0.2,
                    },
                },
            ),
            head_payload=make_webview_result(
                revision=HEAD_SHA,
                metrics={
                    "cold_timeline_seconds": {
                        "samples_seconds": [0.95], "median_seconds": 0.95,
                    },
                    "warm_timeline_seconds": {
                        "samples_seconds": [0.85, 0.85, 0.85], "median_seconds": 0.85,
                    },
                    "detail_payload_seconds": {
                        "samples_seconds": [0.045, 0.045, 0.045], "median_seconds": 0.045,
                    },
                    "detail_total_seconds": {
                        "samples_seconds": [0.18, 0.18, 0.18], "median_seconds": 0.18,
                    },
                },
            ),
        )
        report = self._build(comparison_module, baseline_dir, head_dir)
        assert report["outcome"] == "comparison_passed"
        assert report["all_gates_passed"] is True
        assert len(report["gated_metrics"]) == 4
        for row in report["gated_metrics"]:
            assert row["gate_passed"] is True

    def test_comparison_gate_failed_when_head_regressed_beyond_tolerance(
        self, comparison_module, tmp_path: Path
    ) -> None:
        # 15% regression on cold_timeline (1.0 -> 1.15) — exceeds 10%.
        baseline_dir, head_dir = self._make_dirs(
            tmp_path,
            baseline_payload=make_webview_result(
                revision=BASELINE_SHA,
                metrics={
                    "cold_timeline_seconds": {
                        "samples_seconds": [1.0], "median_seconds": 1.0,
                    },
                    "warm_timeline_seconds": {
                        "samples_seconds": [0.9, 0.9, 0.9], "median_seconds": 0.9,
                    },
                    "detail_payload_seconds": {
                        "samples_seconds": [0.05, 0.05, 0.05], "median_seconds": 0.05,
                    },
                    "detail_total_seconds": {
                        "samples_seconds": [0.2, 0.2, 0.2], "median_seconds": 0.2,
                    },
                },
            ),
            head_payload=make_webview_result(
                revision=HEAD_SHA,
                metrics={
                    "cold_timeline_seconds": {
                        "samples_seconds": [1.15], "median_seconds": 1.15,
                    },
                    "warm_timeline_seconds": {
                        "samples_seconds": [0.9, 0.9, 0.9], "median_seconds": 0.9,
                    },
                    "detail_payload_seconds": {
                        "samples_seconds": [0.05, 0.05, 0.05], "median_seconds": 0.05,
                    },
                    "detail_total_seconds": {
                        "samples_seconds": [0.2, 0.2, 0.2], "median_seconds": 0.2,
                    },
                },
            ),
        )
        report = self._build(comparison_module, baseline_dir, head_dir)
        assert report["outcome"] == "comparison_gate_failed"
        assert report["all_gates_passed"] is False
        cold_row = next(
            r for r in report["gated_metrics"]
            if r["metric"] == "cold_timeline_seconds"
        )
        assert cold_row["gate_passed"] is False
        assert cold_row["delta_pct"] == pytest.approx(15.0)
        # Other metrics still pass.
        warm_row = next(
            r for r in report["gated_metrics"]
            if r["metric"] == "warm_timeline_seconds"
        )
        assert warm_row["gate_passed"] is True

    def test_regression_just_under_tolerance_passes(
        self, comparison_module, tmp_path: Path
    ) -> None:
        """A regression of ~9% must pass (gate uses ``<=`` with 10% tolerance).

        We use 9% instead of exactly 10% because floating-point arithmetic
        makes the exact boundary fragile.  The gate semantics are verified
        by ``test_comparison_gate_failed_when_head_regressed_beyond_tolerance``
        which uses 15%.
        """
        baseline_dir, head_dir = self._make_dirs(
            tmp_path,
            baseline_payload=make_webview_result(
                revision=BASELINE_SHA,
                metrics={
                    "cold_timeline_seconds": {
                        "samples_seconds": [1.0], "median_seconds": 1.0,
                    },
                    "warm_timeline_seconds": {
                        "samples_seconds": [1.0, 1.0, 1.0], "median_seconds": 1.0,
                    },
                    "detail_payload_seconds": {
                        "samples_seconds": [0.1, 0.1, 0.1], "median_seconds": 0.1,
                    },
                    "detail_total_seconds": {
                        "samples_seconds": [0.1, 0.1, 0.1], "median_seconds": 0.1,
                    },
                },
            ),
            head_payload=make_webview_result(
                revision=HEAD_SHA,
                metrics={
                    "cold_timeline_seconds": {
                        "samples_seconds": [1.09], "median_seconds": 1.09,
                    },
                    "warm_timeline_seconds": {
                        "samples_seconds": [1.09, 1.09, 1.09], "median_seconds": 1.09,
                    },
                    "detail_payload_seconds": {
                        "samples_seconds": [0.109, 0.109, 0.109], "median_seconds": 0.109,
                    },
                    "detail_total_seconds": {
                        "samples_seconds": [0.109, 0.109, 0.109], "median_seconds": 0.109,
                    },
                },
            ),
        )
        report = self._build(comparison_module, baseline_dir, head_dir)
        assert report["outcome"] == "comparison_passed"
        assert report["all_gates_passed"] is True

    def test_baseline_invalid_when_baseline_missing(
        self, comparison_module, tmp_path: Path
    ) -> None:
        """Missing baseline artifact → outcome=baseline_invalid."""
        baseline_dir, head_dir = self._make_dirs(
            tmp_path,
            baseline_payload=None,  # missing
            head_payload=make_webview_result(revision=HEAD_SHA),
        )
        report = self._build(comparison_module, baseline_dir, head_dir)
        assert report["outcome"] == "baseline_invalid"
        assert report["gated_metrics"] is None
        assert report["all_gates_passed"] is None
        assert report["baseline"]["present"] is False
        assert report["baseline"]["valid"] is False
        assert report["head"]["valid"] is True

    def test_head_invalid_when_head_missing(
        self, comparison_module, tmp_path: Path
    ) -> None:
        """Missing head artifact → outcome=head_invalid."""
        baseline_dir, head_dir = self._make_dirs(
            tmp_path,
            baseline_payload=make_webview_result(revision=BASELINE_SHA),
            head_payload=None,  # missing
        )
        report = self._build(comparison_module, baseline_dir, head_dir)
        assert report["outcome"] == "head_invalid"
        assert report["gated_metrics"] is None
        assert report["baseline"]["valid"] is True
        assert report["head"]["present"] is False
        assert report["head"]["valid"] is False

    def test_both_invalid_when_both_missing(
        self, comparison_module, tmp_path: Path
    ) -> None:
        baseline_dir, head_dir = self._make_dirs(
            tmp_path,
            baseline_payload=None,
            head_payload=None,
        )
        report = self._build(comparison_module, baseline_dir, head_dir)
        assert report["outcome"] == "both_invalid"
        assert report["gated_metrics"] is None
        assert report["all_gates_passed"] is None
        assert report["baseline"]["present"] is False
        assert report["head"]["present"] is False

    def test_baseline_invalid_when_status_failed(
        self, comparison_module, tmp_path: Path
    ) -> None:
        """A baseline with status != ok is invalid even if head is valid."""
        baseline_dir, head_dir = self._make_dirs(
            tmp_path,
            baseline_payload=make_webview_result(
                revision=BASELINE_SHA, status="failed",
                failure_category="missing_runtime",
                failure_reason="WebView2 Runtime is missing",
            ),
            head_payload=make_webview_result(revision=HEAD_SHA),
        )
        report = self._build(comparison_module, baseline_dir, head_dir)
        assert report["outcome"] == "baseline_invalid"
        assert report["baseline"]["valid"] is False
        assert report["baseline"]["status"] == "failed"
        assert report["baseline"]["failure_category"] == "missing_runtime"
        assert report["head"]["valid"] is True

    def test_both_invalid_with_consistency_error_on_driver_version_mismatch(
        self, comparison_module, tmp_path: Path
    ) -> None:
        """When both sides are valid but consistency checks fail, outcome
        is both_invalid with a ``consistency_error`` field, and no gates run."""
        baseline_dir, head_dir = self._make_dirs(
            tmp_path,
            baseline_payload=make_webview_result(
                revision=BASELINE_SHA, driver_version="1.0",
            ),
            head_payload=make_webview_result(
                revision=HEAD_SHA, driver_version="2.0",
            ),
        )
        report = self._build(comparison_module, baseline_dir, head_dir)
        assert report["outcome"] == "both_invalid"
        assert "consistency_error" in report
        assert "driver_version" in report["consistency_error"]
        assert report["gated_metrics"] is None
        assert report["all_gates_passed"] is None

    def test_sample_count_mismatch_raises_comparison_error(
        self, comparison_module, tmp_path: Path
    ) -> None:
        """Sample count mismatch raises ComparisonError out of _build_comparison
        (no more IncompleteError).  main() catches this and writes a
        failure artifact."""
        baseline_dir, head_dir = self._make_dirs(
            tmp_path,
            baseline_payload=make_webview_result(
                revision=BASELINE_SHA,
                metrics={
                    "cold_timeline_seconds": {
                        "samples_seconds": [1.0, 1.0], "median_seconds": 1.0,
                    },
                    "warm_timeline_seconds": {
                        "samples_seconds": [0.9], "median_seconds": 0.9,
                    },
                    "detail_payload_seconds": {
                        "samples_seconds": [0.05], "median_seconds": 0.05,
                    },
                    "detail_total_seconds": {
                        "samples_seconds": [0.2], "median_seconds": 0.2,
                    },
                },
            ),
            head_payload=make_webview_result(
                revision=HEAD_SHA,
                metrics={
                    "cold_timeline_seconds": {
                        "samples_seconds": [1.0], "median_seconds": 1.0,
                    },
                    "warm_timeline_seconds": {
                        "samples_seconds": [0.9], "median_seconds": 0.9,
                    },
                    "detail_payload_seconds": {
                        "samples_seconds": [0.05], "median_seconds": 0.05,
                    },
                    "detail_total_seconds": {
                        "samples_seconds": [0.2], "median_seconds": 0.2,
                    },
                },
            ),
        )
        with pytest.raises(comparison_module.ComparisonError, match="sample count"):
            self._build(comparison_module, baseline_dir, head_dir)

    def test_report_includes_sha_and_per_side_diagnostics(
        self, comparison_module, tmp_path: Path
    ) -> None:
        """The report uses baseline_sha/head_sha (not baseline_revision) and
        includes per-side diagnostics with driver_version, fixture_hash,
        activity_count, etc."""
        baseline_dir, head_dir = self._make_dirs(
            tmp_path,
            baseline_payload=make_webview_result(revision=BASELINE_SHA),
            head_payload=make_webview_result(revision=HEAD_SHA),
        )
        report = self._build(comparison_module, baseline_dir, head_dir)
        assert report["baseline_sha"] == BASELINE_SHA
        assert report["head_sha"] == HEAD_SHA
        assert report["tolerance_pct"] == 10.0
        assert report["schema_version"] == 2
        # Per-side diagnostics (NEW: nested under baseline/head, not top-level).
        assert report["baseline"]["driver_version"] == "1.0"
        assert report["baseline"]["fixture_hash"] == "fixedhash"
        assert report["baseline"]["activity_count"] == 20000
        assert report["baseline"]["expected_revision"] == BASELINE_SHA
        assert report["head"]["driver_version"] == "1.0"
        assert report["head"]["expected_revision"] == HEAD_SHA
        # Gated metric rows include raw samples and stats.
        for row in report["gated_metrics"]:
            assert "baseline_samples" in row
            assert "head_samples" in row
            assert "baseline_min" in row
            assert "baseline_max" in row
            assert "head_min" in row
            assert "head_max" in row
            assert "delta" in row
            assert "delta_pct" in row
            assert "tolerance_pct" in row
            assert "gate_passed" in row

    def test_note_disclaims_absolute_cold_target(
        self, comparison_module, tmp_path: Path
    ) -> None:
        """The report must include a note that no absolute cold Timeline
        target exists, so the comparison does not claim the original
        performance issue is fully validated."""
        baseline_dir, head_dir = self._make_dirs(
            tmp_path,
            baseline_payload=make_webview_result(revision=BASELINE_SHA),
            head_payload=make_webview_result(revision=HEAD_SHA),
        )
        report = self._build(comparison_module, baseline_dir, head_dir)
        assert "note" in report
        assert "absolute" in report["note"].lower()
        assert "fully validated" in report["note"].lower()
