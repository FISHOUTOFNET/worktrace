"""Unit tests for the product benchmark comparison layer.

Covers the pure-Python functions in ``scripts/benchmark_comparison.py``:
schema validation, consistency checks, metric extraction (including the
bytes-valued memory metric), gate computation, and fail-closed exit-code
semantics.

The script is loaded from its file path because ``scripts/`` is not a
Python package; using ``importlib`` keeps the test hermetic.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.contract, pytest.mark.parallel_safe]

ROOT = Path(__file__).resolve().parents[1]
COMPARISON_PATH = ROOT / "scripts" / "benchmark_comparison.py"

_BASELINE_SHA = "a" * 40
_HEAD_SHA = "b" * 40


# ---------------------------------------------------------------------------
# Module loading fixture
# ---------------------------------------------------------------------------

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
# Helpers
# ---------------------------------------------------------------------------

def _make_driver_payload(
    *,
    revision: str,
    metrics: dict[str, Any] | None = None,
    driver_version: str = "1.0",
    fixture_hash: str = "fixedhash",
    python_version: str = "3.11.5",
    target_root: str = "/tmp/worktree",
) -> dict[str, Any]:
    """Build a synthetic but schema-valid product benchmark driver result."""
    if metrics is None:
        metrics = {
            "projection_20k_total_seconds": {
                "samples_seconds": [1.0, 1.05, 0.98],
                "median_seconds": 1.0,
                "consistency_hash": "hash20k",
            },
            "projection_10k_contributions_seconds": {
                "samples_seconds": [0.5, 0.52, 0.48],
                "median_seconds": 0.5,
                "consistency_hash": "hash10k",
            },
            "projection_peak_memory_bytes": {
                "samples_bytes": [100000, 105000, 98000],
                "median_bytes": 100000,
            },
        }
    return {
        "schema_version": 1,
        "revision": revision,
        "driver_version": driver_version,
        "fixture_hash": fixture_hash,
        "python_version": python_version,
        "target_root": target_root,
        "metrics": metrics,
    }


def _write_driver_result(
    path: Path,
    payload: dict[str, Any],
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# _load_driver_result
# ---------------------------------------------------------------------------

class TestLoadDriverResult:
    """Tests for the fail-closed loading of a single driver result."""

    def test_missing_file_raises_comparison_error(
        self, comparison_module, tmp_path: Path
    ) -> None:
        with pytest.raises(comparison_module.ComparisonError, match="missing"):
            comparison_module._load_driver_result(tmp_path / "product-benchmark.json")

    def test_invalid_json_raises_comparison_error(
        self, comparison_module, tmp_path: Path
    ) -> None:
        path = tmp_path / "product-benchmark.json"
        path.write_text("{not valid json", encoding="utf-8")
        with pytest.raises(comparison_module.ComparisonError, match="cannot parse"):
            comparison_module._load_driver_result(path)

    def test_root_not_object_raises_comparison_error(
        self, comparison_module, tmp_path: Path
    ) -> None:
        path = tmp_path / "product-benchmark.json"
        path.write_text("[1, 2, 3]", encoding="utf-8")
        with pytest.raises(comparison_module.ComparisonError, match="not an object"):
            comparison_module._load_driver_result(path)

    def test_wrong_schema_version_raises_comparison_error(
        self, comparison_module, tmp_path: Path
    ) -> None:
        payload = _make_driver_payload(revision=_BASELINE_SHA)
        payload["schema_version"] = 99
        path = _write_driver_result(tmp_path / "product-benchmark.json", payload)
        with pytest.raises(comparison_module.ComparisonError, match="schema_version"):
            comparison_module._load_driver_result(path)

    def test_missing_metrics_raises_comparison_error(
        self, comparison_module, tmp_path: Path
    ) -> None:
        payload = _make_driver_payload(revision=_BASELINE_SHA)
        del payload["metrics"]
        path = _write_driver_result(tmp_path / "product-benchmark.json", payload)
        with pytest.raises(comparison_module.ComparisonError, match="metrics"):
            comparison_module._load_driver_result(path)

    def test_metrics_not_object_raises_comparison_error(
        self, comparison_module, tmp_path: Path
    ) -> None:
        payload = _make_driver_payload(revision=_BASELINE_SHA)
        payload["metrics"] = "not-an-object"
        path = _write_driver_result(tmp_path / "product-benchmark.json", payload)
        with pytest.raises(comparison_module.ComparisonError, match="metrics"):
            comparison_module._load_driver_result(path)

    def test_valid_payload_returns_dict(
        self, comparison_module, tmp_path: Path
    ) -> None:
        payload = _make_driver_payload(revision=_BASELINE_SHA)
        path = _write_driver_result(tmp_path / "product-benchmark.json", payload)
        result = comparison_module._load_driver_result(path)
        assert result["revision"] == _BASELINE_SHA
        assert "metrics" in result


# ---------------------------------------------------------------------------
# _validate_consistency
# ---------------------------------------------------------------------------

class TestValidateConsistency:
    """Tests for the cross-revision consistency checks."""

    def test_driver_version_mismatch_raises(self, comparison_module) -> None:
        baseline = _make_driver_payload(revision=_BASELINE_SHA, driver_version="1.0")
        head = _make_driver_payload(revision=_HEAD_SHA, driver_version="2.0")
        with pytest.raises(comparison_module.ComparisonError, match="driver_version"):
            comparison_module._validate_consistency(
                baseline, head,
                expected_baseline_sha=_BASELINE_SHA,
                expected_head_sha=_HEAD_SHA,
            )

    def test_fixture_hash_mismatch_raises(self, comparison_module) -> None:
        baseline = _make_driver_payload(revision=_BASELINE_SHA, fixture_hash="hashA")
        head = _make_driver_payload(revision=_HEAD_SHA, fixture_hash="hashB")
        with pytest.raises(comparison_module.ComparisonError, match="fixture_hash"):
            comparison_module._validate_consistency(
                baseline, head,
                expected_baseline_sha=_BASELINE_SHA,
                expected_head_sha=_HEAD_SHA,
            )

    def test_python_major_minor_mismatch_raises(self, comparison_module) -> None:
        baseline = _make_driver_payload(
            revision=_BASELINE_SHA, python_version="3.11.5"
        )
        head = _make_driver_payload(revision=_HEAD_SHA, python_version="3.12.1")
        with pytest.raises(comparison_module.ComparisonError, match="python_version"):
            comparison_module._validate_consistency(
                baseline, head,
                expected_baseline_sha=_BASELINE_SHA,
                expected_head_sha=_HEAD_SHA,
            )

    def test_python_patch_difference_allowed(self, comparison_module) -> None:
        baseline = _make_driver_payload(
            revision=_BASELINE_SHA, python_version="3.11.5"
        )
        head = _make_driver_payload(revision=_HEAD_SHA, python_version="3.11.9")
        comparison_module._validate_consistency(
            baseline, head,
            expected_baseline_sha=_BASELINE_SHA,
            expected_head_sha=_HEAD_SHA,
        )

    def test_baseline_revision_mismatch_raises(self, comparison_module) -> None:
        baseline = _make_driver_payload(revision="wrong")
        head = _make_driver_payload(revision=_HEAD_SHA)
        with pytest.raises(comparison_module.ComparisonError, match="baseline revision"):
            comparison_module._validate_consistency(
                baseline, head,
                expected_baseline_sha=_BASELINE_SHA,
                expected_head_sha=_HEAD_SHA,
            )

    def test_head_revision_mismatch_raises(self, comparison_module) -> None:
        baseline = _make_driver_payload(revision=_BASELINE_SHA)
        head = _make_driver_payload(revision="wrong")
        with pytest.raises(comparison_module.ComparisonError, match="HEAD revision"):
            comparison_module._validate_consistency(
                baseline, head,
                expected_baseline_sha=_BASELINE_SHA,
                expected_head_sha=_HEAD_SHA,
            )

    def test_consistent_payloads_pass(self, comparison_module) -> None:
        baseline = _make_driver_payload(revision=_BASELINE_SHA)
        head = _make_driver_payload(revision=_HEAD_SHA)
        comparison_module._validate_consistency(
            baseline, head,
            expected_baseline_sha=_BASELINE_SHA,
            expected_head_sha=_HEAD_SHA,
        )


# ---------------------------------------------------------------------------
# _extract_metric
# ---------------------------------------------------------------------------

class TestExtractMetric:
    """Tests for extracting a single gated metric from a driver result."""

    def test_missing_metric_raises_comparison_error(self, comparison_module) -> None:
        payload = _make_driver_payload(revision=_BASELINE_SHA, metrics={})
        with pytest.raises(comparison_module.ComparisonError, match="missing"):
            comparison_module._extract_metric(
                payload, "projection_20k_total_seconds",
                "median_seconds", "samples_seconds", "baseline",
            )

    def test_metric_not_object_raises_comparison_error(
        self, comparison_module
    ) -> None:
        payload = _make_driver_payload(
            revision=_BASELINE_SHA,
            metrics={"projection_20k_total_seconds": "not-an-object"},
        )
        with pytest.raises(comparison_module.ComparisonError, match="not object"):
            comparison_module._extract_metric(
                payload, "projection_20k_total_seconds",
                "median_seconds", "samples_seconds", "baseline",
            )

    def test_missing_value_field_raises_comparison_error(
        self, comparison_module
    ) -> None:
        payload = _make_driver_payload(
            revision=_BASELINE_SHA,
            metrics={"projection_20k_total_seconds": {"samples_seconds": [1.0]}},
        )
        with pytest.raises(comparison_module.ComparisonError, match="median_seconds"):
            comparison_module._extract_metric(
                payload, "projection_20k_total_seconds",
                "median_seconds", "samples_seconds", "baseline",
            )

    def test_missing_sample_field_raises_comparison_error(
        self, comparison_module
    ) -> None:
        payload = _make_driver_payload(
            revision=_BASELINE_SHA,
            metrics={"projection_20k_total_seconds": {"median_seconds": 1.0}},
        )
        with pytest.raises(comparison_module.ComparisonError, match="samples_seconds"):
            comparison_module._extract_metric(
                payload, "projection_20k_total_seconds",
                "median_seconds", "samples_seconds", "baseline",
            )

    def test_samples_not_list_raises_comparison_error(
        self, comparison_module
    ) -> None:
        payload = _make_driver_payload(
            revision=_BASELINE_SHA,
            metrics={"projection_20k_total_seconds": {
                "median_seconds": 1.0,
                "samples_seconds": "not-a-list",
            }},
        )
        with pytest.raises(comparison_module.ComparisonError, match="not a list"):
            comparison_module._extract_metric(
                payload, "projection_20k_total_seconds",
                "median_seconds", "samples_seconds", "baseline",
            )

    def test_zero_samples_raises_incomplete_error(self, comparison_module) -> None:
        payload = _make_driver_payload(
            revision=_BASELINE_SHA,
            metrics={"projection_20k_total_seconds": {
                "median_seconds": 0.0,
                "samples_seconds": [],
            }},
        )
        with pytest.raises(comparison_module.IncompleteError, match="zero samples"):
            comparison_module._extract_metric(
                payload, "projection_20k_total_seconds",
                "median_seconds", "samples_seconds", "baseline",
            )

    def test_valid_seconds_metric_returns_median_and_samples(
        self, comparison_module
    ) -> None:
        payload = _make_driver_payload(revision=_BASELINE_SHA)
        median, samples = comparison_module._extract_metric(
            payload, "projection_20k_total_seconds",
            "median_seconds", "samples_seconds", "baseline",
        )
        assert median == 1.0
        assert samples == [1.0, 1.05, 0.98]

    def test_valid_bytes_metric_returns_median_and_samples(
        self, comparison_module
    ) -> None:
        """The memory metric uses ``median_bytes`` and ``samples_bytes``
        instead of the seconds-based fields."""
        payload = _make_driver_payload(revision=_BASELINE_SHA)
        median, samples = comparison_module._extract_metric(
            payload, "projection_peak_memory_bytes",
            "median_bytes", "samples_bytes", "baseline",
        )
        assert median == 100000.0
        assert samples == [100000.0, 105000.0, 98000.0]


# ---------------------------------------------------------------------------
# _percent_delta
# ---------------------------------------------------------------------------

class TestPercentDelta:
    """Tests for the percentage delta computation."""

    def test_zero_baseline_zero_head_returns_zero(self, comparison_module) -> None:
        assert comparison_module._percent_delta(0.0, 0.0) == 0.0

    def test_zero_baseline_nonzero_head_returns_100(self, comparison_module) -> None:
        assert comparison_module._percent_delta(0.0, 1.0) == 100.0

    def test_improvement_returns_negative(self, comparison_module) -> None:
        assert comparison_module._percent_delta(1.0, 0.8) == pytest.approx(-20.0)

    def test_regression_returns_positive(self, comparison_module) -> None:
        assert comparison_module._percent_delta(1.0, 1.15) == pytest.approx(15.0)

    def test_memory_improvement_returns_negative(self, comparison_module) -> None:
        """For memory, lower HEAD is an improvement (negative delta)."""
        assert comparison_module._percent_delta(100000.0, 90000.0) == pytest.approx(-10.0)

    def test_memory_regression_returns_positive(self, comparison_module) -> None:
        """For memory, higher HEAD is a regression (positive delta)."""
        assert comparison_module._percent_delta(100000.0, 115000.0) == pytest.approx(15.0)


# ---------------------------------------------------------------------------
# _build_comparison
# ---------------------------------------------------------------------------

class TestBuildComparison:
    """Tests for the full comparison builder including gate semantics."""

    def _make_dirs(
        self,
        tmp_path: Path,
        *,
        baseline_metrics: dict[str, Any] | None = None,
        head_metrics: dict[str, Any] | None = None,
    ) -> tuple[Path, Path]:
        baseline_dir = tmp_path / "baseline"
        head_dir = tmp_path / "head"
        _write_driver_result(
            baseline_dir / "product-benchmark.json",
            _make_driver_payload(revision=_BASELINE_SHA, metrics=baseline_metrics),
        )
        _write_driver_result(
            head_dir / "product-benchmark.json",
            _make_driver_payload(revision=_HEAD_SHA, metrics=head_metrics),
        )
        return baseline_dir, head_dir

    def test_all_gates_pass_when_head_not_regressed(
        self, comparison_module, tmp_path: Path
    ) -> None:
        baseline_dir, head_dir = self._make_dirs(
            tmp_path,
            baseline_metrics={
                "projection_20k_total_seconds": {
                    "samples_seconds": [1.0, 1.0, 1.0],
                    "median_seconds": 1.0,
                    "consistency_hash": "hash20k",
                },
                "projection_10k_contributions_seconds": {
                    "samples_seconds": [0.5, 0.5, 0.5],
                    "median_seconds": 0.5,
                    "consistency_hash": "hash10k",
                },
                "projection_peak_memory_bytes": {
                    "samples_bytes": [100000, 100000, 100000],
                    "median_bytes": 100000,
                },
            },
            head_metrics={
                "projection_20k_total_seconds": {
                    "samples_seconds": [0.95, 0.95, 0.95],
                    "median_seconds": 0.95,
                    "consistency_hash": "hash20k",
                },
                "projection_10k_contributions_seconds": {
                    "samples_seconds": [0.48, 0.48, 0.48],
                    "median_seconds": 0.48,
                    "consistency_hash": "hash10k",
                },
                "projection_peak_memory_bytes": {
                    "samples_bytes": [95000, 95000, 95000],
                    "median_bytes": 95000,
                },
            },
        )
        report = comparison_module._build_comparison(
            baseline_dir, head_dir,
            baseline_sha=_BASELINE_SHA,
            head_sha=_HEAD_SHA,
            tolerance_pct=10.0,
        )
        assert report["all_gates_passed"] is True
        assert len(report["gated_metrics"]) == 3
        for row in report["gated_metrics"]:
            assert row["gate_passed"] is True

    def test_gate_fails_when_seconds_metric_regressed(
        self, comparison_module, tmp_path: Path
    ) -> None:
        """15% regression on projection_20k_total_seconds — exceeds 10%."""
        baseline_dir, head_dir = self._make_dirs(
            tmp_path,
            baseline_metrics={
                "projection_20k_total_seconds": {
                    "samples_seconds": [1.0, 1.0, 1.0],
                    "median_seconds": 1.0,
                    "consistency_hash": "hash20k",
                },
                "projection_10k_contributions_seconds": {
                    "samples_seconds": [0.5, 0.5, 0.5],
                    "median_seconds": 0.5,
                    "consistency_hash": "hash10k",
                },
                "projection_peak_memory_bytes": {
                    "samples_bytes": [100000, 100000, 100000],
                    "median_bytes": 100000,
                },
            },
            head_metrics={
                "projection_20k_total_seconds": {
                    "samples_seconds": [1.15, 1.15, 1.15],
                    "median_seconds": 1.15,
                    "consistency_hash": "hash20k",
                },
                "projection_10k_contributions_seconds": {
                    "samples_seconds": [0.5, 0.5, 0.5],
                    "median_seconds": 0.5,
                    "consistency_hash": "hash10k",
                },
                "projection_peak_memory_bytes": {
                    "samples_bytes": [100000, 100000, 100000],
                    "median_bytes": 100000,
                },
            },
        )
        report = comparison_module._build_comparison(
            baseline_dir, head_dir,
            baseline_sha=_BASELINE_SHA,
            head_sha=_HEAD_SHA,
            tolerance_pct=10.0,
        )
        assert report["all_gates_passed"] is False
        proj_row = next(
            r for r in report["gated_metrics"]
            if r["metric"] == "projection_20k_total_seconds"
        )
        assert proj_row["gate_passed"] is False
        assert proj_row["delta_pct"] == pytest.approx(15.0)
        # Other metrics still pass.
        mem_row = next(
            r for r in report["gated_metrics"]
            if r["metric"] == "projection_peak_memory_bytes"
        )
        assert mem_row["gate_passed"] is True

    def test_gate_fails_when_memory_metric_regressed(
        self, comparison_module, tmp_path: Path
    ) -> None:
        """15% regression on peak memory — exceeds 10%."""
        baseline_dir, head_dir = self._make_dirs(
            tmp_path,
            baseline_metrics={
                "projection_20k_total_seconds": {
                    "samples_seconds": [1.0, 1.0, 1.0],
                    "median_seconds": 1.0,
                    "consistency_hash": "hash20k",
                },
                "projection_10k_contributions_seconds": {
                    "samples_seconds": [0.5, 0.5, 0.5],
                    "median_seconds": 0.5,
                    "consistency_hash": "hash10k",
                },
                "projection_peak_memory_bytes": {
                    "samples_bytes": [100000, 100000, 100000],
                    "median_bytes": 100000,
                },
            },
            head_metrics={
                "projection_20k_total_seconds": {
                    "samples_seconds": [1.0, 1.0, 1.0],
                    "median_seconds": 1.0,
                    "consistency_hash": "hash20k",
                },
                "projection_10k_contributions_seconds": {
                    "samples_seconds": [0.5, 0.5, 0.5],
                    "median_seconds": 0.5,
                    "consistency_hash": "hash10k",
                },
                "projection_peak_memory_bytes": {
                    "samples_bytes": [115000, 115000, 115000],
                    "median_bytes": 115000,
                },
            },
        )
        report = comparison_module._build_comparison(
            baseline_dir, head_dir,
            baseline_sha=_BASELINE_SHA,
            head_sha=_HEAD_SHA,
            tolerance_pct=10.0,
        )
        assert report["all_gates_passed"] is False
        mem_row = next(
            r for r in report["gated_metrics"]
            if r["metric"] == "projection_peak_memory_bytes"
        )
        assert mem_row["gate_passed"] is False
        assert mem_row["delta_pct"] == pytest.approx(15.0)
        # Memory metric uses bytes unit.
        assert mem_row["unit"] == "bytes"

    def test_sample_count_mismatch_raises_incomplete_error(
        self, comparison_module, tmp_path: Path
    ) -> None:
        baseline_dir, head_dir = self._make_dirs(
            tmp_path,
            baseline_metrics={
                "projection_20k_total_seconds": {
                    "samples_seconds": [1.0, 1.0],
                    "median_seconds": 1.0,
                    "consistency_hash": "hash20k",
                },
                "projection_10k_contributions_seconds": {
                    "samples_seconds": [0.5],
                    "median_seconds": 0.5,
                    "consistency_hash": "hash10k",
                },
                "projection_peak_memory_bytes": {
                    "samples_bytes": [100000],
                    "median_bytes": 100000,
                },
            },
            head_metrics={
                "projection_20k_total_seconds": {
                    "samples_seconds": [1.0],
                    "median_seconds": 1.0,
                    "consistency_hash": "hash20k",
                },
                "projection_10k_contributions_seconds": {
                    "samples_seconds": [0.5],
                    "median_seconds": 0.5,
                    "consistency_hash": "hash10k",
                },
                "projection_peak_memory_bytes": {
                    "samples_bytes": [100000],
                    "median_bytes": 100000,
                },
            },
        )
        with pytest.raises(comparison_module.IncompleteError, match="sample count"):
            comparison_module._build_comparison(
                baseline_dir, head_dir,
                baseline_sha=_BASELINE_SHA,
                head_sha=_HEAD_SHA,
                tolerance_pct=10.0,
            )

    def test_report_includes_consistency_hashes(
        self, comparison_module, tmp_path: Path
    ) -> None:
        """The report must include consistency hash cross-checks for the
        20k and 10k scenarios so silent fixture divergence is visible."""
        baseline_dir, head_dir = self._make_dirs(tmp_path)
        report = comparison_module._build_comparison(
            baseline_dir, head_dir,
            baseline_sha=_BASELINE_SHA,
            head_sha=_HEAD_SHA,
            tolerance_pct=10.0,
        )
        assert "consistency" in report
        assert "20k_activities" in report["consistency"]
        assert "10k_contributions" in report["consistency"]
        assert report["consistency"]["20k_activities"]["match"] is True
        assert report["consistency"]["10k_contributions"]["match"] is True

    def test_report_includes_raw_samples_and_metadata(
        self, comparison_module, tmp_path: Path
    ) -> None:
        baseline_dir, head_dir = self._make_dirs(tmp_path)
        report = comparison_module._build_comparison(
            baseline_dir, head_dir,
            baseline_sha=_BASELINE_SHA,
            head_sha=_HEAD_SHA,
            tolerance_pct=10.0,
        )
        assert report["baseline_revision"] == _BASELINE_SHA
        assert report["head_revision"] == _HEAD_SHA
        assert report["driver_version"] == "1.0"
        assert report["fixture_hash"] == "fixedhash"
        assert report["tolerance_pct"] == 10.0
        for row in report["gated_metrics"]:
            assert "baseline_samples" in row
            assert "head_samples" in row
            assert "baseline_min" in row
            assert "baseline_max" in row
            assert "head_min" in row
            assert "head_max" in row
            assert "delta" in row
            assert "delta_pct" in row

    def test_three_gated_metrics_present(
        self, comparison_module, tmp_path: Path
    ) -> None:
        """The comparison must include exactly the three gated metrics."""
        baseline_dir, head_dir = self._make_dirs(tmp_path)
        report = comparison_module._build_comparison(
            baseline_dir, head_dir,
            baseline_sha=_BASELINE_SHA,
            head_sha=_HEAD_SHA,
            tolerance_pct=10.0,
        )
        metric_keys = {r["metric"] for r in report["gated_metrics"]}
        assert metric_keys == {
            "projection_20k_total_seconds",
            "projection_10k_contributions_seconds",
            "projection_peak_memory_bytes",
        }


# ---------------------------------------------------------------------------
# Exit code semantics
# ---------------------------------------------------------------------------

class TestExitCodes:
    """Verify the fail-closed exit codes from main()."""

    def test_main_returns_0_when_all_gates_pass(
        self, comparison_module, tmp_path: Path, monkeypatch
    ) -> None:
        baseline_dir = tmp_path / "baseline"
        head_dir = tmp_path / "head"
        _write_driver_result(
            baseline_dir / "product-benchmark.json",
            _make_driver_payload(revision=_BASELINE_SHA),
        )
        _write_driver_result(
            head_dir / "product-benchmark.json",
            _make_driver_payload(revision=_HEAD_SHA),
        )
        monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
        monkeypatch.setattr(sys, "argv", [
            "benchmark_comparison.py",
            "--baseline-dir", str(baseline_dir),
            "--head-dir", str(head_dir),
            "--baseline-sha", _BASELINE_SHA,
            "--head-sha", _HEAD_SHA,
            "--tolerance-pct", "10",
        ])
        exit_code = comparison_module.main()
        assert exit_code == 0

    def test_main_returns_2_on_missing_artifact(
        self, comparison_module, tmp_path: Path, monkeypatch
    ) -> None:
        baseline_dir = tmp_path / "baseline"
        head_dir = tmp_path / "head"
        # Baseline exists, head is missing.
        _write_driver_result(
            baseline_dir / "product-benchmark.json",
            _make_driver_payload(revision=_BASELINE_SHA),
        )
        monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
        monkeypatch.setattr(sys, "argv", [
            "benchmark_comparison.py",
            "--baseline-dir", str(baseline_dir),
            "--head-dir", str(head_dir),
            "--baseline-sha", _BASELINE_SHA,
            "--head-sha", _HEAD_SHA,
            "--tolerance-pct", "10",
        ])
        exit_code = comparison_module.main()
        assert exit_code == 2

    def test_main_returns_4_on_gate_failure(
        self, comparison_module, tmp_path: Path, monkeypatch
    ) -> None:
        baseline_dir = tmp_path / "baseline"
        head_dir = tmp_path / "head"
        _write_driver_result(
            baseline_dir / "product-benchmark.json",
            _make_driver_payload(
                revision=_BASELINE_SHA,
                metrics={
                    "projection_20k_total_seconds": {
                        "samples_seconds": [1.0, 1.0, 1.0],
                        "median_seconds": 1.0,
                        "consistency_hash": "hash20k",
                    },
                    "projection_10k_contributions_seconds": {
                        "samples_seconds": [0.5, 0.5, 0.5],
                        "median_seconds": 0.5,
                        "consistency_hash": "hash10k",
                    },
                    "projection_peak_memory_bytes": {
                        "samples_bytes": [100000, 100000, 100000],
                        "median_bytes": 100000,
                    },
                },
            ),
        )
        # 50% regression on every metric — exceeds 10%.
        _write_driver_result(
            head_dir / "product-benchmark.json",
            _make_driver_payload(
                revision=_HEAD_SHA,
                metrics={
                    "projection_20k_total_seconds": {
                        "samples_seconds": [1.5, 1.5, 1.5],
                        "median_seconds": 1.5,
                        "consistency_hash": "hash20k",
                    },
                    "projection_10k_contributions_seconds": {
                        "samples_seconds": [0.75, 0.75, 0.75],
                        "median_seconds": 0.75,
                        "consistency_hash": "hash10k",
                    },
                    "projection_peak_memory_bytes": {
                        "samples_bytes": [150000, 150000, 150000],
                        "median_bytes": 150000,
                    },
                },
            ),
        )
        monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
        monkeypatch.setattr(sys, "argv", [
            "benchmark_comparison.py",
            "--baseline-dir", str(baseline_dir),
            "--head-dir", str(head_dir),
            "--baseline-sha", _BASELINE_SHA,
            "--head-sha", _HEAD_SHA,
            "--tolerance-pct", "10",
        ])
        exit_code = comparison_module.main()
        assert exit_code == 4
