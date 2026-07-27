"""Unit tests for the WebView comparison layer and metric extraction.

Covers the pure-Python functions in ``scripts/webview_comparison.py`` and
the ``_extract_webview_metrics`` function in ``scripts/webview_render_perf.py``.

These tests do NOT launch WebView2 or any subprocess — they exercise the
schema validation, consistency checks, metric extraction, gate computation,
and fail-closed exit-code semantics against synthetic JSON payloads.

The scripts are loaded from their file paths because ``scripts/`` is not a
Python package; using ``importlib`` keeps the test hermetic and avoids
mutating ``sys.path`` globally.
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
COMPARISON_PATH = ROOT / "scripts" / "webview_comparison.py"
HARNESS_PATH = ROOT / "scripts" / "webview_render_perf.py"

_BASELINE_SHA = "a" * 40
_HEAD_SHA = "b" * 40


# ---------------------------------------------------------------------------
# Module loading fixtures
# ---------------------------------------------------------------------------

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


@pytest.fixture(scope="module")
def harness_module():
    """Load scripts/webview_render_perf.py as a module.

    The harness module imports ``worktrace.*`` at module load time (via
    ``_REPO_ROOT`` sys.path insertion), so this fixture assumes the
    worktrace package is importable from the test environment.
    """
    spec = importlib.util.spec_from_file_location(
        "webview_render_perf_under_test", HARNESS_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["webview_render_perf_under_test"] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop("webview_render_perf_under_test", None)
        raise
    return module


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_fixture_audit(
    *,
    requested_count: int = 20000,
    inserted_count: int | None = None,
    preexisting_activity_count: int = 0,
    connection_count: int = 1,
    commit_count: int = 41,
) -> dict[str, Any]:
    """Build a synthetic but contract-valid WebView fixture_audit entry."""
    return {
        "scenario": "webview_render",
        "requested_count": requested_count,
        "inserted_count": inserted_count if inserted_count is not None else requested_count,
        "preexisting_activity_count": preexisting_activity_count,
        "fixture_build_seconds": 1.0,
        "connection_count": connection_count,
        "commit_count": commit_count,
        "chunk_size": 500,
        "builder_version": "1.0",
        "report_date": "2026-07-15",
    }


def _make_driver_payload(
    *,
    revision: str,
    status: str = "ok",
    metrics: dict[str, Any] | None = None,
    driver_version: str = "1.0",
    fixture_hash: str = "fixedhash",
    python_version: str = "3.11.5",
    activity_count: int = 20000,
    target_root: str = "/tmp/worktree",
    fixture_audit: dict[str, Any] | None = None,
    actual_target_revision: str | None = None,
    github_workflow_sha: str | None = None,
) -> dict[str, Any]:
    """Build a synthetic but schema-valid WebView driver result.

    Schema v2 records both ``requested_revision`` (from ``--revision``) and
    ``actual_target_revision`` (from ``git rev-parse HEAD`` on the target
    worktree).  The two must match within an artifact and must match the
    expected SHA supplied on the CLI.  ``github_workflow_sha`` is recorded
    for diagnostics only and is never used for identity comparison.
    """
    if metrics is None:
        metrics = {
            "cold_timeline_seconds": {
                "samples_seconds": [1.0],
                "median_seconds": 1.0,
            },
            "warm_timeline_seconds": {
                "samples_seconds": [0.8, 0.9, 0.85],
                "median_seconds": 0.85,
            },
            "detail_payload_seconds": {
                "samples_seconds": [0.05, 0.06, 0.055],
                "median_seconds": 0.055,
            },
            "detail_total_seconds": {
                "samples_seconds": [0.2, 0.22, 0.21],
                "median_seconds": 0.21,
            },
        }
    if fixture_audit is None:
        fixture_audit = _make_fixture_audit(requested_count=activity_count)
    return {
        "schema_version": 2,
        "requested_revision": revision,
        "actual_target_revision": actual_target_revision or revision,
        "github_workflow_sha": github_workflow_sha,
        "status": status,
        "driver_version": driver_version,
        "fixture_hash": fixture_hash,
        "python_version": python_version,
        "activity_count": activity_count,
        "target_root": target_root,
        "fixture_audit": fixture_audit,
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
# _extract_webview_metrics (in webview_render_perf.py)
# ---------------------------------------------------------------------------

class TestExtractWebviewMetrics:
    """Pure-function tests for ``_extract_webview_metrics``."""

    def _run(self, harness_module, stages: dict[str, float]) -> dict[str, Any]:
        return {"stages": stages}

    def test_empty_runs_raises_value_error(self, harness_module) -> None:
        with pytest.raises(ValueError, match="no runs"):
            harness_module._extract_webview_metrics([])

    def test_single_run_only_cold_timeline(self, harness_module) -> None:
        """A single run produces a cold sample but no warm samples."""
        runs = [
            self._run(harness_module, {
                "timeline_total_ms": 1000.0,
                "detail_payload_ms": 50.0,
                "detail_total_ms": 200.0,
            }),
        ]
        metrics = harness_module._extract_webview_metrics(runs)
        assert metrics["cold_timeline_seconds"]["samples_seconds"] == [1.0]
        assert metrics["cold_timeline_seconds"]["median_seconds"] == 1.0
        # No warm runs -> empty samples, median 0.0.
        assert metrics["warm_timeline_seconds"]["samples_seconds"] == []
        assert metrics["warm_timeline_seconds"]["median_seconds"] == 0.0
        # Detail metrics use ALL runs (cold + warm), so they have one sample.
        assert metrics["detail_payload_seconds"]["samples_seconds"] == [0.05]
        assert metrics["detail_total_seconds"]["samples_seconds"] == [0.2]

    def test_multiple_runs_extracts_all_four_metrics(self, harness_module) -> None:
        runs = [
            self._run(harness_module, {
                "timeline_total_ms": 1000.0,  # cold
                "detail_payload_ms": 50.0,
                "detail_total_ms": 200.0,
            }),
            self._run(harness_module, {
                "timeline_total_ms": 800.0,
                "detail_payload_ms": 60.0,
                "detail_total_ms": 220.0,
            }),
            self._run(harness_module, {
                "timeline_total_ms": 900.0,
                "detail_payload_ms": 55.0,
                "detail_total_ms": 210.0,
            }),
        ]
        metrics = harness_module._extract_webview_metrics(runs)
        # cold_timeline: single sample from run 0.
        assert metrics["cold_timeline_seconds"]["samples_seconds"] == [1.0]
        # warm_timeline: samples from runs 1 and 2.
        assert metrics["warm_timeline_seconds"]["samples_seconds"] == [0.8, 0.9]
        assert metrics["warm_timeline_seconds"]["median_seconds"] == round(0.85, 6)
        # detail_payload: all 3 runs.
        assert metrics["detail_payload_seconds"]["samples_seconds"] == [
            0.05, 0.06, 0.055
        ]
        assert metrics["detail_payload_seconds"]["median_seconds"] == round(0.055, 6)
        # detail_total: all 3 runs.
        assert metrics["detail_total_seconds"]["samples_seconds"] == [
            0.2, 0.22, 0.21
        ]
        assert metrics["detail_total_seconds"]["median_seconds"] == round(0.21, 6)

    def test_missing_stage_values_are_skipped(self, harness_module) -> None:
        """A run missing a stage must not contribute a sample for that stage."""
        runs = [
            {"stages": {"timeline_total_ms": 1000.0}},  # no detail metrics
            {"stages": {
                "timeline_total_ms": 800.0,
                "detail_payload_ms": 60.0,
                "detail_total_ms": 220.0,
            }},
        ]
        metrics = harness_module._extract_webview_metrics(runs)
        # cold_timeline still has the cold run's sample.
        assert metrics["cold_timeline_seconds"]["samples_seconds"] == [1.0]
        # warm_timeline has run 1.
        assert metrics["warm_timeline_seconds"]["samples_seconds"] == [0.8]
        # detail_payload: only run 1 contributed (run 0 missing).
        assert metrics["detail_payload_seconds"]["samples_seconds"] == [0.06]
        # detail_total: only run 1 contributed.
        assert metrics["detail_total_seconds"]["samples_seconds"] == [0.22]

    def test_none_stage_values_are_skipped(self, harness_module) -> None:
        """A stage value of None (or non-numeric) must be skipped."""
        runs = [
            {"stages": {
                "timeline_total_ms": None,
                "detail_payload_ms": "not-a-number",
                "detail_total_ms": 200.0,
            }},
        ]
        metrics = harness_module._extract_webview_metrics(runs)
        assert metrics["cold_timeline_seconds"]["samples_seconds"] == []
        assert metrics["cold_timeline_seconds"]["median_seconds"] == 0.0
        assert metrics["detail_payload_seconds"]["samples_seconds"] == []
        assert metrics["detail_total_seconds"]["samples_seconds"] == [0.2]

    def test_ms_to_seconds_conversion(self, harness_module) -> None:
        """Stage values in milliseconds must be converted to seconds."""
        runs = [
            self._run(harness_module, {
                "timeline_total_ms": 2500.0,
                "detail_payload_ms": 125.0,
                "detail_total_ms": 500.0,
            }),
        ]
        metrics = harness_module._extract_webview_metrics(runs)
        assert metrics["cold_timeline_seconds"]["samples_seconds"] == [2.5]
        assert metrics["detail_payload_seconds"]["samples_seconds"] == [0.125]
        assert metrics["detail_total_seconds"]["samples_seconds"] == [0.5]

    def test_returns_all_four_gated_metric_keys(self, harness_module) -> None:
        runs = [self._run(harness_module, {"timeline_total_ms": 1000.0})]
        metrics = harness_module._extract_webview_metrics(runs)
        assert set(metrics.keys()) == {
            "cold_timeline_seconds",
            "warm_timeline_seconds",
            "detail_payload_seconds",
            "detail_total_seconds",
        }
        for key, entry in metrics.items():
            assert "samples_seconds" in entry
            assert "median_seconds" in entry


# ---------------------------------------------------------------------------
# _load_driver_result (webview_comparison.py)
# ---------------------------------------------------------------------------

class TestLoadDriverResult:
    """Tests for the fail-closed loading of a single driver result."""

    def test_missing_file_raises_comparison_error(
        self, comparison_module, tmp_path: Path
    ) -> None:
        with pytest.raises(comparison_module.ComparisonError, match="missing"):
            comparison_module._load_driver_result(tmp_path / "webview-benchmark.json")

    def test_invalid_json_raises_comparison_error(
        self, comparison_module, tmp_path: Path
    ) -> None:
        path = tmp_path / "webview-benchmark.json"
        path.write_text("{not valid json", encoding="utf-8")
        with pytest.raises(comparison_module.ComparisonError, match="cannot parse"):
            comparison_module._load_driver_result(path)

    def test_root_not_object_raises_comparison_error(
        self, comparison_module, tmp_path: Path
    ) -> None:
        path = tmp_path / "webview-benchmark.json"
        path.write_text("[1, 2, 3]", encoding="utf-8")
        with pytest.raises(comparison_module.ComparisonError, match="not an object"):
            comparison_module._load_driver_result(path)

    def test_wrong_schema_version_raises_comparison_error(
        self, comparison_module, tmp_path: Path
    ) -> None:
        payload = _make_driver_payload(revision=_BASELINE_SHA)
        payload["schema_version"] = 99
        path = _write_driver_result(tmp_path / "webview-benchmark.json", payload)
        with pytest.raises(comparison_module.ComparisonError, match="schema_version"):
            comparison_module._load_driver_result(path)

    def test_status_not_ok_raises_comparison_error(
        self, comparison_module, tmp_path: Path
    ) -> None:
        payload = _make_driver_payload(revision=_BASELINE_SHA, status="error")
        path = _write_driver_result(tmp_path / "webview-benchmark.json", payload)
        with pytest.raises(comparison_module.ComparisonError, match="status"):
            comparison_module._load_driver_result(path)

    def test_missing_metrics_raises_comparison_error(
        self, comparison_module, tmp_path: Path
    ) -> None:
        payload = _make_driver_payload(revision=_BASELINE_SHA)
        del payload["metrics"]
        path = _write_driver_result(tmp_path / "webview-benchmark.json", payload)
        with pytest.raises(comparison_module.ComparisonError, match="metrics"):
            comparison_module._load_driver_result(path)

    def test_valid_payload_returns_dict(
        self, comparison_module, tmp_path: Path
    ) -> None:
        payload = _make_driver_payload(revision=_BASELINE_SHA)
        path = _write_driver_result(tmp_path / "webview-benchmark.json", payload)
        result = comparison_module._load_driver_result(path)
        assert result["requested_revision"] == _BASELINE_SHA
        assert result["actual_target_revision"] == _BASELINE_SHA
        assert result["status"] == "ok"
        assert "metrics" in result
        assert "fixture_audit" in result


# ---------------------------------------------------------------------------
# _validate_consistency (webview_comparison.py)
# ---------------------------------------------------------------------------

class TestValidateConsistency:
    """Tests for the cross-revision consistency checks."""

    def test_driver_version_mismatch_raises(
        self, comparison_module
    ) -> None:
        baseline = _make_driver_payload(
            revision=_BASELINE_SHA, driver_version="1.0"
        )
        head = _make_driver_payload(revision=_HEAD_SHA, driver_version="2.0")
        with pytest.raises(comparison_module.ComparisonError, match="driver_version"):
            comparison_module._validate_consistency(
                baseline, head,
                expected_baseline_sha=_BASELINE_SHA,
                expected_head_sha=_HEAD_SHA,
            )

    def test_fixture_hash_mismatch_raises(
        self, comparison_module
    ) -> None:
        baseline = _make_driver_payload(
            revision=_BASELINE_SHA, fixture_hash="hashA"
        )
        head = _make_driver_payload(revision=_HEAD_SHA, fixture_hash="hashB")
        with pytest.raises(comparison_module.ComparisonError, match="fixture_hash"):
            comparison_module._validate_consistency(
                baseline, head,
                expected_baseline_sha=_BASELINE_SHA,
                expected_head_sha=_HEAD_SHA,
            )

    def test_python_major_minor_mismatch_raises(
        self, comparison_module
    ) -> None:
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

    def test_python_patch_difference_allowed(
        self, comparison_module
    ) -> None:
        baseline = _make_driver_payload(
            revision=_BASELINE_SHA, python_version="3.11.5"
        )
        head = _make_driver_payload(revision=_HEAD_SHA, python_version="3.11.9")
        # Should NOT raise — patch versions may differ.
        comparison_module._validate_consistency(
            baseline, head,
            expected_baseline_sha=_BASELINE_SHA,
            expected_head_sha=_HEAD_SHA,
        )

    def test_baseline_revision_mismatch_raises(
        self, comparison_module
    ) -> None:
        """Baseline's actual_target_revision must match expected_baseline_sha."""
        baseline = _make_driver_payload(
            revision=_BASELINE_SHA, actual_target_revision="wrongsha"
        )
        head = _make_driver_payload(revision=_HEAD_SHA)
        with pytest.raises(comparison_module.ComparisonError, match="baseline"):
            comparison_module._validate_consistency(
                baseline, head,
                expected_baseline_sha=_BASELINE_SHA,
                expected_head_sha=_HEAD_SHA,
            )

    def test_head_revision_mismatch_raises(
        self, comparison_module
    ) -> None:
        """HEAD's actual_target_revision must match expected_head_sha."""
        baseline = _make_driver_payload(revision=_BASELINE_SHA)
        head = _make_driver_payload(
            revision=_HEAD_SHA, actual_target_revision="wrongsha"
        )
        with pytest.raises(comparison_module.ComparisonError, match="head"):
            comparison_module._validate_consistency(
                baseline, head,
                expected_baseline_sha=_BASELINE_SHA,
                expected_head_sha=_HEAD_SHA,
            )

    def test_baseline_requested_actual_mismatch_raises(
        self, comparison_module
    ) -> None:
        """requested_revision != actual_target_revision within an artifact
        means the driver did not verify target worktree identity."""
        baseline = _make_driver_payload(
            revision=_BASELINE_SHA,
            actual_target_revision=_BASELINE_SHA + "deadbeef",
        )
        head = _make_driver_payload(revision=_HEAD_SHA)
        with pytest.raises(comparison_module.ComparisonError, match="requested_revision"):
            comparison_module._validate_consistency(
                baseline, head,
                expected_baseline_sha=_BASELINE_SHA,
                expected_head_sha=_HEAD_SHA,
            )

    def test_github_workflow_sha_not_used_for_identity(
        self, comparison_module
    ) -> None:
        """github_workflow_sha may differ from actual_target_revision
        (it can be a merge commit SHA in pull_request workflows) and must
        NOT cause an identity mismatch."""
        baseline = _make_driver_payload(
            revision=_BASELINE_SHA,
            github_workflow_sha="mergecommitsha1234",
        )
        head = _make_driver_payload(
            revision=_HEAD_SHA,
            github_workflow_sha="differentmergesha5678",
        )
        comparison_module._validate_consistency(
            baseline, head,
            expected_baseline_sha=_BASELINE_SHA,
            expected_head_sha=_HEAD_SHA,
        )

    def test_activity_count_mismatch_raises(
        self, comparison_module
    ) -> None:
        baseline = _make_driver_payload(
            revision=_BASELINE_SHA, activity_count=20000
        )
        head = _make_driver_payload(revision=_HEAD_SHA, activity_count=10000)
        with pytest.raises(comparison_module.ComparisonError, match="activity_count"):
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
# _validate_scenario_isolation (webview_comparison.py)
# ---------------------------------------------------------------------------

class TestValidateScenarioIsolation:
    """Tests for the WebView fixture_audit isolation contract.

    The WebView driver runs a single scenario, so ``fixture_audit`` is a
    single object (not keyed by scenario name like the product driver).
    It must report:
      * ``preexisting_activity_count == 0`` (no carryover),
      * ``inserted_count == requested_count`` (every row inserted),
      * ``connection_count >= 1`` (the O(1) connection contract held),
      * ``commit_count >= 1`` (at least one commit happened).
    """

    def test_missing_fixture_audit_raises(self, comparison_module) -> None:
        payload = _make_driver_payload(revision=_BASELINE_SHA)
        del payload["fixture_audit"]
        with pytest.raises(comparison_module.ComparisonError, match="fixture_audit"):
            comparison_module._validate_scenario_isolation(
                payload, label="baseline"
            )

    def test_fixture_audit_not_object_raises(self, comparison_module) -> None:
        payload = _make_driver_payload(revision=_BASELINE_SHA)
        payload["fixture_audit"] = "not-an-object"
        with pytest.raises(comparison_module.ComparisonError, match="fixture_audit"):
            comparison_module._validate_scenario_isolation(
                payload, label="baseline"
            )

    def test_empty_fixture_audit_raises(self, comparison_module) -> None:
        payload = _make_driver_payload(revision=_BASELINE_SHA)
        payload["fixture_audit"] = {}
        with pytest.raises(comparison_module.ComparisonError, match="empty"):
            comparison_module._validate_scenario_isolation(
                payload, label="baseline"
            )

    def test_preexisting_activity_count_nonzero_raises(
        self, comparison_module
    ) -> None:
        """A non-zero preexisting_activity_count means the WebView fixture
        inherited data from a prior run — isolation violated."""
        payload = _make_driver_payload(revision=_BASELINE_SHA)
        payload["fixture_audit"]["preexisting_activity_count"] = 5
        with pytest.raises(
            comparison_module.ComparisonError,
            match="preexisting_activity_count",
        ):
            comparison_module._validate_scenario_isolation(
                payload, label="baseline"
            )

    def test_inserted_count_mismatch_raises(self, comparison_module) -> None:
        """inserted_count != requested_count means the builder dropped rows."""
        payload = _make_driver_payload(revision=_BASELINE_SHA)
        payload["fixture_audit"]["inserted_count"] = 19999
        with pytest.raises(
            comparison_module.ComparisonError,
            match="inserted_count",
        ):
            comparison_module._validate_scenario_isolation(
                payload, label="baseline"
            )

    def test_connection_count_zero_raises(self, comparison_module) -> None:
        payload = _make_driver_payload(revision=_BASELINE_SHA)
        payload["fixture_audit"]["connection_count"] = 0
        with pytest.raises(
            comparison_module.ComparisonError,
            match="connection_count",
        ):
            comparison_module._validate_scenario_isolation(
                payload, label="baseline"
            )

    def test_commit_count_zero_raises(self, comparison_module) -> None:
        payload = _make_driver_payload(revision=_BASELINE_SHA)
        payload["fixture_audit"]["commit_count"] = 0
        with pytest.raises(
            comparison_module.ComparisonError,
            match="commit_count",
        ):
            comparison_module._validate_scenario_isolation(
                payload, label="baseline"
            )

    def test_clean_fixture_audit_passes(self, comparison_module) -> None:
        payload = _make_driver_payload(revision=_BASELINE_SHA)
        comparison_module._validate_scenario_isolation(
            payload, label="baseline"
        )


# ---------------------------------------------------------------------------
# _extract_metric (webview_comparison.py)
# ---------------------------------------------------------------------------

class TestExtractMetric:
    """Tests for extracting a single gated metric from a driver result."""

    def test_missing_metric_raises_comparison_error(
        self, comparison_module
    ) -> None:
        payload = _make_driver_payload(revision=_BASELINE_SHA, metrics={})
        with pytest.raises(comparison_module.ComparisonError, match="missing"):
            comparison_module._extract_metric(payload, "cold_timeline_seconds", "baseline")

    def test_metric_not_object_raises_comparison_error(
        self, comparison_module
    ) -> None:
        payload = _make_driver_payload(
            revision=_BASELINE_SHA,
            metrics={"cold_timeline_seconds": "not-an-object"},
        )
        with pytest.raises(comparison_module.ComparisonError, match="not object"):
            comparison_module._extract_metric(payload, "cold_timeline_seconds", "baseline")

    def test_missing_median_seconds_raises_comparison_error(
        self, comparison_module
    ) -> None:
        payload = _make_driver_payload(
            revision=_BASELINE_SHA,
            metrics={"cold_timeline_seconds": {"samples_seconds": [1.0]}},
        )
        with pytest.raises(comparison_module.ComparisonError, match="median_seconds"):
            comparison_module._extract_metric(payload, "cold_timeline_seconds", "baseline")

    def test_missing_samples_seconds_raises_comparison_error(
        self, comparison_module
    ) -> None:
        payload = _make_driver_payload(
            revision=_BASELINE_SHA,
            metrics={"cold_timeline_seconds": {"median_seconds": 1.0}},
        )
        with pytest.raises(comparison_module.ComparisonError, match="samples_seconds"):
            comparison_module._extract_metric(payload, "cold_timeline_seconds", "baseline")

    def test_samples_not_list_raises_comparison_error(
        self, comparison_module
    ) -> None:
        payload = _make_driver_payload(
            revision=_BASELINE_SHA,
            metrics={"cold_timeline_seconds": {
                "median_seconds": 1.0,
                "samples_seconds": "not-a-list",
            }},
        )
        with pytest.raises(comparison_module.ComparisonError, match="not a list"):
            comparison_module._extract_metric(payload, "cold_timeline_seconds", "baseline")

    def test_zero_samples_raises_incomplete_error(
        self, comparison_module
    ) -> None:
        payload = _make_driver_payload(
            revision=_BASELINE_SHA,
            metrics={"cold_timeline_seconds": {
                "median_seconds": 0.0,
                "samples_seconds": [],
            }},
        )
        with pytest.raises(comparison_module.IncompleteError, match="zero samples"):
            comparison_module._extract_metric(payload, "cold_timeline_seconds", "baseline")

    def test_valid_metric_returns_median_and_samples(
        self, comparison_module
    ) -> None:
        payload = _make_driver_payload(revision=_BASELINE_SHA)
        median, samples = comparison_module._extract_metric(
            payload, "cold_timeline_seconds", "baseline"
        )
        assert median == 1.0
        assert samples == [1.0]


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
            baseline_dir / "webview-benchmark.json",
            _make_driver_payload(revision=_BASELINE_SHA, metrics=baseline_metrics),
        )
        _write_driver_result(
            head_dir / "webview-benchmark.json",
            _make_driver_payload(revision=_HEAD_SHA, metrics=head_metrics),
        )
        return baseline_dir, head_dir

    def test_all_gates_pass_when_head_not_regressed(
        self, comparison_module, tmp_path: Path
    ) -> None:
        baseline_dir, head_dir = self._make_dirs(
            tmp_path,
            baseline_metrics={
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
            head_metrics={
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
        )
        report = comparison_module._build_comparison(
            baseline_dir, head_dir,
            baseline_sha=_BASELINE_SHA,
            head_sha=_HEAD_SHA,
            tolerance_pct=10.0,
        )
        assert report["all_gates_passed"] is True
        assert len(report["gated_metrics"]) == 4
        for row in report["gated_metrics"]:
            assert row["gate_passed"] is True

    def test_gate_fails_when_head_regressed_beyond_tolerance(
        self, comparison_module, tmp_path: Path
    ) -> None:
        # 15% regression on cold_timeline (1.0 -> 1.15) — exceeds 10%.
        baseline_dir, head_dir = self._make_dirs(
            tmp_path,
            baseline_metrics={
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
            head_metrics={
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
        )
        report = comparison_module._build_comparison(
            baseline_dir, head_dir,
            baseline_sha=_BASELINE_SHA,
            head_sha=_HEAD_SHA,
            tolerance_pct=10.0,
        )
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

    def test_regression_just_under_10pct_passes(
        self, comparison_module, tmp_path: Path
    ) -> None:
        """A regression of ~9% must pass (gate uses ``<=`` with 10% tolerance).

        We use 9% instead of exactly 10% because floating-point arithmetic
        makes the exact boundary fragile (``1.10 - 1.0`` is not exactly
        ``0.1`` in IEEE 754).  The gate semantics are verified by the
        ``test_gate_fails_when_head_regressed_beyond_tolerance`` test
        which uses 15%.
        """
        baseline_dir, head_dir = self._make_dirs(
            tmp_path,
            baseline_metrics={
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
            head_metrics={
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
        )
        report = comparison_module._build_comparison(
            baseline_dir, head_dir,
            baseline_sha=_BASELINE_SHA,
            head_sha=_HEAD_SHA,
            tolerance_pct=10.0,
        )
        assert report["all_gates_passed"] is True

    def test_sample_count_mismatch_raises_incomplete_error(
        self, comparison_module, tmp_path: Path
    ) -> None:
        baseline_dir, head_dir = self._make_dirs(
            tmp_path,
            baseline_metrics={
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
            head_metrics={
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
        )
        with pytest.raises(comparison_module.IncompleteError, match="sample count"):
            comparison_module._build_comparison(
                baseline_dir, head_dir,
                baseline_sha=_BASELINE_SHA,
                head_sha=_HEAD_SHA,
                tolerance_pct=10.0,
            )

    def test_report_includes_raw_samples_and_metadata(
        self, comparison_module, tmp_path: Path
    ) -> None:
        """The report must preserve raw samples, medians, and metadata
        for auditability."""
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
        assert report["activity_count"] == 20000
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

    def test_note_disclaims_absolute_cold_target(
        self, comparison_module, tmp_path: Path
    ) -> None:
        """The report must include a note that no absolute cold Timeline
        target exists, so the comparison does not claim the original
        performance issue is fully validated."""
        baseline_dir, head_dir = self._make_dirs(tmp_path)
        report = comparison_module._build_comparison(
            baseline_dir, head_dir,
            baseline_sha=_BASELINE_SHA,
            head_sha=_HEAD_SHA,
            tolerance_pct=10.0,
        )
        assert "note" in report
        assert "absolute" in report["note"].lower()
        assert "fully validated" in report["note"].lower()


# ---------------------------------------------------------------------------
# Exit code semantics (webview_comparison.py main)
# ---------------------------------------------------------------------------

class TestExitCodes:
    """Verify the fail-closed exit codes from main()."""

    def test_main_returns_0_when_all_gates_pass(
        self, comparison_module, tmp_path: Path, monkeypatch
    ) -> None:
        baseline_dir = tmp_path / "baseline"
        head_dir = tmp_path / "head"
        _write_driver_result(
            baseline_dir / "webview-benchmark.json",
            _make_driver_payload(revision=_BASELINE_SHA),
        )
        _write_driver_result(
            head_dir / "webview-benchmark.json",
            _make_driver_payload(revision=_HEAD_SHA),
        )
        # Suppress step-summary writes.
        monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
        monkeypatch.setattr(sys, "argv", [
            "webview_comparison.py",
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
            baseline_dir / "webview-benchmark.json",
            _make_driver_payload(revision=_BASELINE_SHA),
        )
        monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
        monkeypatch.setattr(sys, "argv", [
            "webview_comparison.py",
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
            baseline_dir / "webview-benchmark.json",
            _make_driver_payload(
                revision=_BASELINE_SHA,
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
        )
        # 50% regression on every metric — exceeds 10%.
        _write_driver_result(
            head_dir / "webview-benchmark.json",
            _make_driver_payload(
                revision=_HEAD_SHA,
                metrics={
                    "cold_timeline_seconds": {
                        "samples_seconds": [1.5], "median_seconds": 1.5,
                    },
                    "warm_timeline_seconds": {
                        "samples_seconds": [1.35, 1.35, 1.35], "median_seconds": 1.35,
                    },
                    "detail_payload_seconds": {
                        "samples_seconds": [0.075, 0.075, 0.075], "median_seconds": 0.075,
                    },
                    "detail_total_seconds": {
                        "samples_seconds": [0.3, 0.3, 0.3], "median_seconds": 0.3,
                    },
                },
            ),
        )
        monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
        monkeypatch.setattr(sys, "argv", [
            "webview_comparison.py",
            "--baseline-dir", str(baseline_dir),
            "--head-dir", str(head_dir),
            "--baseline-sha", _BASELINE_SHA,
            "--head-sha", _HEAD_SHA,
            "--tolerance-pct", "10",
        ])
        exit_code = comparison_module.main()
        assert exit_code == 4
