"""SideResult loader and metric extraction tests for the WebView comparison layer.

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
    make_webview_result,
    write_webview_result,
)

pytestmark = [pytest.mark.unit, pytest.mark.contract, pytest.mark.parallel_safe]

ROOT = Path(__file__).resolve().parents[2]
COMPARISON_PATH = ROOT / "scripts" / "webview_comparison.py"
HARNESS_PATH = ROOT / "scripts" / "webview_render_perf.py"


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
# _extract_webview_metrics (in webview_render_perf.py)
# ---------------------------------------------------------------------------

class TestExtractWebviewMetrics:
    """Pure-function tests for ``_extract_webview_metrics``."""

    def _run(self, stages: dict[str, float]) -> dict[str, Any]:
        return {"stages": stages}

    def test_empty_runs_raises_value_error(self, harness_module) -> None:
        with pytest.raises(ValueError, match="no runs"):
            harness_module._extract_webview_metrics([])

    def test_single_run_only_cold_timeline(self, harness_module) -> None:
        """A single run produces a cold sample but no warm samples."""
        runs = [
            self._run({
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
            self._run({
                "timeline_total_ms": 1000.0,  # cold
                "detail_payload_ms": 50.0,
                "detail_total_ms": 200.0,
            }),
            self._run({
                "timeline_total_ms": 800.0,
                "detail_payload_ms": 60.0,
                "detail_total_ms": 220.0,
            }),
            self._run({
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
            self._run({
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
        runs = [self._run({"timeline_total_ms": 1000.0})]
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
# SideResult (webview_comparison.py)
# ---------------------------------------------------------------------------

class TestSideResult:
    """Tests for the SideResult tolerant side loader."""

    def test_missing_file_is_not_present_and_not_valid(
        self, comparison_module, tmp_path: Path
    ) -> None:
        side = comparison_module.SideResult(
            label="baseline",
            artifact_path=tmp_path / "webview-benchmark.json",
            expected_sha=BASELINE_SHA,
        )
        assert side.present is False
        assert side.valid is False
        assert side.payload is None
        assert side.status == "missing"
        assert "missing" in side.invalid_reason
        # failure_reason falls back to invalid_reason when no payload.
        assert side.failure_reason == side.invalid_reason
        assert side.expected_sha == BASELINE_SHA

    def test_invalid_json_is_not_valid(
        self, comparison_module, tmp_path: Path
    ) -> None:
        path = tmp_path / "webview-benchmark.json"
        path.write_text("{not valid json", encoding="utf-8")
        side = comparison_module.SideResult(
            label="baseline",
            artifact_path=path,
            expected_sha=BASELINE_SHA,
        )
        assert side.present is True
        assert side.valid is False
        assert side.payload is None
        assert "cannot parse" in side.invalid_reason

    def test_root_not_object_is_not_valid(
        self, comparison_module, tmp_path: Path
    ) -> None:
        path = tmp_path / "webview-benchmark.json"
        path.write_text("[1, 2, 3]", encoding="utf-8")
        side = comparison_module.SideResult(
            label="baseline",
            artifact_path=path,
            expected_sha=BASELINE_SHA,
        )
        assert side.present is True
        assert side.valid is False
        assert side.payload is None
        assert "not an object" in side.invalid_reason

    def test_status_not_ok_is_not_valid(
        self, comparison_module, tmp_path: Path
    ) -> None:
        path = write_webview_result(
            tmp_path,
            make_webview_result(revision=BASELINE_SHA, status="failed"),
        )
        side = comparison_module.SideResult(
            label="baseline",
            artifact_path=path,
            expected_sha=BASELINE_SHA,
        )
        assert side.present is True
        assert side.valid is False
        assert side.status == "failed"

    def test_missing_metrics_is_not_valid(
        self, comparison_module, tmp_path: Path
    ) -> None:
        payload = make_webview_result(revision=BASELINE_SHA)
        del payload["metrics"]
        path = write_webview_result(tmp_path, payload)
        side = comparison_module.SideResult(
            label="baseline",
            artifact_path=path,
            expected_sha=BASELINE_SHA,
        )
        assert side.valid is False

    def test_metrics_not_dict_is_not_valid(
        self, comparison_module, tmp_path: Path
    ) -> None:
        payload = make_webview_result(revision=BASELINE_SHA)
        payload["metrics"] = "not-a-dict"
        path = write_webview_result(tmp_path, payload)
        side = comparison_module.SideResult(
            label="baseline",
            artifact_path=path,
            expected_sha=BASELINE_SHA,
        )
        assert side.valid is False

    def test_valid_payload_exposes_all_properties(
        self, comparison_module, tmp_path: Path
    ) -> None:
        path = write_webview_result(
            tmp_path,
            make_webview_result(
                revision=BASELINE_SHA,
                driver_version="1.0",
                fixture_hash="fixedhash",
                python_version="3.11.5",
                activity_count=20000,
                github_workflow_sha="mergecommitsha",
            ),
        )
        side = comparison_module.SideResult(
            label="baseline",
            artifact_path=path,
            expected_sha=BASELINE_SHA,
        )
        assert side.present is True
        assert side.valid is True
        assert side.status == "ok"
        assert side.requested_revision == BASELINE_SHA
        assert side.actual_target_revision == BASELINE_SHA
        assert side.driver_version == "1.0"
        assert side.fixture_hash == "fixedhash"
        assert side.python_version == "3.11.5"
        assert side.activity_count == 20000
        assert side.expected_sha == BASELINE_SHA
        assert isinstance(side.fixture_audit, dict)
        assert side.fixture_audit["scenario"] == "webview_render"
        # Valid side has empty failure_reason.
        assert side.failure_reason == ""

    def test_optional_fields_default_to_empty_when_missing(
        self, comparison_module, tmp_path: Path
    ) -> None:
        """A payload missing optional fields still loads; properties default."""
        path = write_webview_result(
            tmp_path,
            {
                "schema_version": 2,
                "status": "ok",
                "metrics": {"cold_timeline_seconds": {
                    "samples_seconds": [1.0], "median_seconds": 1.0,
                }},
            },
        )
        side = comparison_module.SideResult(
            label="baseline",
            artifact_path=path,
            expected_sha=BASELINE_SHA,
        )
        assert side.valid is True
        assert side.requested_revision == ""
        assert side.actual_target_revision == ""
        assert side.driver_version == ""
        assert side.fixture_hash == ""
        assert side.python_version == ""
        assert side.activity_count == 0
        assert side.fixture_audit == {}

    def test_failure_properties_from_failed_payload(
        self, comparison_module, tmp_path: Path
    ) -> None:
        """A failed payload exposes failure_category and failure_reason."""
        path = write_webview_result(
            tmp_path,
            make_webview_result(
                revision=BASELINE_SHA,
                status="failed",
                failure_category="missing_runtime",
                failure_reason="WebView2 Runtime is missing",
            ),
        )
        side = comparison_module.SideResult(
            label="baseline",
            artifact_path=path,
            expected_sha=BASELINE_SHA,
        )
        assert side.valid is False
        assert side.status == "failed"
        assert side.failure_category == "missing_runtime"
        assert side.failure_reason == "WebView2 Runtime is missing"
