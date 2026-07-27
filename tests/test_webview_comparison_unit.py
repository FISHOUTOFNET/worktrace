"""Unit tests for the WebView comparison layer and metric extraction.

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
    fixture_audit: dict[str, Any] | None = None,
    actual_target_revision: str | None = None,
    github_workflow_sha: str | None = None,
    failure_category: str = "",
    failure_reason: str = "",
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
        "fixture_audit": fixture_audit,
        "metrics": metrics,
        "failure_category": failure_category,
        "failure_reason": failure_reason,
    }


def _write_driver_result(
    output_dir: Path,
    payload: dict[str, Any],
) -> Path:
    """Write a driver result to ``webview-benchmark.json`` in ``output_dir``.

    Returns the path to the written artifact.  The filename matches what
    the comparison script's ``SideResult`` looks for.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "webview-benchmark.json"
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def _make_side(
    comparison_module,
    output_dir: Path,
    *,
    label: str,
    payload: dict[str, Any] | None,
    expected_sha: str,
) -> Any:
    """Create a ``SideResult`` by writing ``payload`` to disk (or leaving
    the artifact missing when ``payload is None``)."""
    if payload is not None:
        artifact_path = _write_driver_result(output_dir, payload)
    else:
        output_dir.mkdir(parents=True, exist_ok=True)
        artifact_path = output_dir / "webview-benchmark.json"
    return comparison_module.SideResult(
        label=label,
        artifact_path=artifact_path,
        expected_sha=expected_sha,
    )


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
            expected_sha=_BASELINE_SHA,
        )
        assert side.present is False
        assert side.valid is False
        assert side.payload is None
        assert side.status == "missing"
        assert "missing" in side.invalid_reason
        # failure_reason falls back to invalid_reason when no payload.
        assert side.failure_reason == side.invalid_reason
        assert side.expected_sha == _BASELINE_SHA

    def test_invalid_json_is_not_valid(
        self, comparison_module, tmp_path: Path
    ) -> None:
        path = tmp_path / "webview-benchmark.json"
        path.write_text("{not valid json", encoding="utf-8")
        side = comparison_module.SideResult(
            label="baseline",
            artifact_path=path,
            expected_sha=_BASELINE_SHA,
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
            expected_sha=_BASELINE_SHA,
        )
        assert side.present is True
        assert side.valid is False
        assert side.payload is None
        assert "not an object" in side.invalid_reason

    def test_status_not_ok_is_not_valid(
        self, comparison_module, tmp_path: Path
    ) -> None:
        path = _write_driver_result(
            tmp_path,
            _make_driver_payload(revision=_BASELINE_SHA, status="failed"),
        )
        side = comparison_module.SideResult(
            label="baseline",
            artifact_path=path,
            expected_sha=_BASELINE_SHA,
        )
        assert side.present is True
        assert side.valid is False
        assert side.status == "failed"

    def test_missing_metrics_is_not_valid(
        self, comparison_module, tmp_path: Path
    ) -> None:
        payload = _make_driver_payload(revision=_BASELINE_SHA)
        del payload["metrics"]
        path = _write_driver_result(tmp_path, payload)
        side = comparison_module.SideResult(
            label="baseline",
            artifact_path=path,
            expected_sha=_BASELINE_SHA,
        )
        assert side.valid is False

    def test_metrics_not_dict_is_not_valid(
        self, comparison_module, tmp_path: Path
    ) -> None:
        payload = _make_driver_payload(revision=_BASELINE_SHA)
        payload["metrics"] = "not-a-dict"
        path = _write_driver_result(tmp_path, payload)
        side = comparison_module.SideResult(
            label="baseline",
            artifact_path=path,
            expected_sha=_BASELINE_SHA,
        )
        assert side.valid is False

    def test_valid_payload_exposes_all_properties(
        self, comparison_module, tmp_path: Path
    ) -> None:
        path = _write_driver_result(
            tmp_path,
            _make_driver_payload(
                revision=_BASELINE_SHA,
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
            expected_sha=_BASELINE_SHA,
        )
        assert side.present is True
        assert side.valid is True
        assert side.status == "ok"
        assert side.requested_revision == _BASELINE_SHA
        assert side.actual_target_revision == _BASELINE_SHA
        assert side.driver_version == "1.0"
        assert side.fixture_hash == "fixedhash"
        assert side.python_version == "3.11.5"
        assert side.activity_count == 20000
        assert side.expected_sha == _BASELINE_SHA
        assert isinstance(side.fixture_audit, dict)
        assert side.fixture_audit["scenario"] == "webview_render"
        # Valid side has empty failure_reason.
        assert side.failure_reason == ""

    def test_optional_fields_default_to_empty_when_missing(
        self, comparison_module, tmp_path: Path
    ) -> None:
        """A payload missing optional fields still loads; properties default."""
        path = _write_driver_result(
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
            expected_sha=_BASELINE_SHA,
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
        path = _write_driver_result(
            tmp_path,
            _make_driver_payload(
                revision=_BASELINE_SHA,
                status="failed",
                failure_category="missing_runtime",
                failure_reason="WebView2 Runtime is missing",
            ),
        )
        side = comparison_module.SideResult(
            label="baseline",
            artifact_path=path,
            expected_sha=_BASELINE_SHA,
        )
        assert side.valid is False
        assert side.status == "failed"
        assert side.failure_category == "missing_runtime"
        assert side.failure_reason == "WebView2 Runtime is missing"


# ---------------------------------------------------------------------------
# _validate_revision_identity (webview_comparison.py)
# ---------------------------------------------------------------------------

class TestValidateRevisionIdentity:
    """Tests for per-side revision identity validation."""

    def _make_side(
        self,
        comparison_module,
        tmp_path: Path,
        *,
        revision: str,
        actual_target_revision: str,
        expected_sha: str,
    ) -> Any:
        path = _write_driver_result(
            tmp_path,
            _make_driver_payload(
                revision=revision,
                actual_target_revision=actual_target_revision,
            ),
        )
        return comparison_module.SideResult(
            label="baseline",
            artifact_path=path,
            expected_sha=expected_sha,
        )

    def test_missing_requested_revision_raises(
        self, comparison_module, tmp_path: Path
    ) -> None:
        payload = _make_driver_payload(revision=_BASELINE_SHA)
        payload["requested_revision"] = ""
        path = _write_driver_result(tmp_path, payload)
        side = comparison_module.SideResult(
            label="baseline", artifact_path=path, expected_sha=_BASELINE_SHA,
        )
        with pytest.raises(comparison_module.ComparisonError, match="missing"):
            comparison_module._validate_revision_identity(side)

    def test_missing_actual_target_revision_raises(
        self, comparison_module, tmp_path: Path
    ) -> None:
        payload = _make_driver_payload(revision=_BASELINE_SHA)
        payload["actual_target_revision"] = ""
        path = _write_driver_result(tmp_path, payload)
        side = comparison_module.SideResult(
            label="baseline", artifact_path=path, expected_sha=_BASELINE_SHA,
        )
        with pytest.raises(comparison_module.ComparisonError, match="missing"):
            comparison_module._validate_revision_identity(side)

    def test_requested_actual_mismatch_raises(
        self, comparison_module, tmp_path: Path
    ) -> None:
        """requested_revision != actual_target_revision means the driver
        did not verify target worktree identity."""
        side = self._make_side(
            comparison_module, tmp_path,
            revision=_BASELINE_SHA,
            actual_target_revision=_BASELINE_SHA + "deadbeef",
            expected_sha=_BASELINE_SHA,
        )
        with pytest.raises(
            comparison_module.ComparisonError, match="requested_revision"
        ):
            comparison_module._validate_revision_identity(side)

    def test_actual_expected_mismatch_raises(
        self, comparison_module, tmp_path: Path
    ) -> None:
        """actual_target_revision must match the expected SHA supplied on the CLI."""
        side = self._make_side(
            comparison_module, tmp_path,
            revision=_BASELINE_SHA,
            actual_target_revision=_BASELINE_SHA,
            expected_sha="wrongsha",
        )
        with pytest.raises(comparison_module.ComparisonError, match="expected"):
            comparison_module._validate_revision_identity(side)

    def test_matching_revisions_pass(
        self, comparison_module, tmp_path: Path
    ) -> None:
        side = self._make_side(
            comparison_module, tmp_path,
            revision=_BASELINE_SHA,
            actual_target_revision=_BASELINE_SHA,
            expected_sha=_BASELINE_SHA,
        )
        # Should not raise.
        comparison_module._validate_revision_identity(side)

    def test_github_workflow_sha_not_used_for_identity(
        self, comparison_module, tmp_path: Path
    ) -> None:
        """github_workflow_sha may differ from actual_target_revision
        (it can be a merge commit SHA in pull_request workflows) and must
        NOT cause an identity mismatch."""
        path = _write_driver_result(
            tmp_path,
            _make_driver_payload(
                revision=_BASELINE_SHA,
                github_workflow_sha="mergecommitsha1234",
            ),
        )
        side = comparison_module.SideResult(
            label="baseline", artifact_path=path, expected_sha=_BASELINE_SHA,
        )
        comparison_module._validate_revision_identity(side)


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
        path = _write_driver_result(
            tmp_path / label,
            _make_driver_payload(
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
            revision=_BASELINE_SHA, driver_version="1.0",
        )
        head = self._make_side(
            comparison_module, tmp_path, label="head",
            revision=_HEAD_SHA, driver_version="2.0",
        )
        with pytest.raises(comparison_module.ComparisonError, match="driver_version"):
            comparison_module._validate_cross_revision_consistency(baseline, head)

    def test_fixture_hash_mismatch_raises(
        self, comparison_module, tmp_path: Path
    ) -> None:
        baseline = self._make_side(
            comparison_module, tmp_path, label="baseline",
            revision=_BASELINE_SHA, fixture_hash="hashA",
        )
        head = self._make_side(
            comparison_module, tmp_path, label="head",
            revision=_HEAD_SHA, fixture_hash="hashB",
        )
        with pytest.raises(comparison_module.ComparisonError, match="fixture_hash"):
            comparison_module._validate_cross_revision_consistency(baseline, head)

    def test_empty_fixture_hash_skipped(
        self, comparison_module, tmp_path: Path
    ) -> None:
        """If one side has empty fixture_hash, the check is skipped."""
        baseline = self._make_side(
            comparison_module, tmp_path, label="baseline",
            revision=_BASELINE_SHA, fixture_hash="",
        )
        head = self._make_side(
            comparison_module, tmp_path, label="head",
            revision=_HEAD_SHA, fixture_hash="hashB",
        )
        # Should not raise — empty fixture_hash on baseline skips the check.
        comparison_module._validate_cross_revision_consistency(baseline, head)

    def test_python_major_minor_mismatch_raises(
        self, comparison_module, tmp_path: Path
    ) -> None:
        baseline = self._make_side(
            comparison_module, tmp_path, label="baseline",
            revision=_BASELINE_SHA, python_version="3.11.5",
        )
        head = self._make_side(
            comparison_module, tmp_path, label="head",
            revision=_HEAD_SHA, python_version="3.12.1",
        )
        with pytest.raises(comparison_module.ComparisonError, match="python_version"):
            comparison_module._validate_cross_revision_consistency(baseline, head)

    def test_python_patch_difference_allowed(
        self, comparison_module, tmp_path: Path
    ) -> None:
        baseline = self._make_side(
            comparison_module, tmp_path, label="baseline",
            revision=_BASELINE_SHA, python_version="3.11.5",
        )
        head = self._make_side(
            comparison_module, tmp_path, label="head",
            revision=_HEAD_SHA, python_version="3.11.9",
        )
        comparison_module._validate_cross_revision_consistency(baseline, head)

    def test_activity_count_mismatch_raises(
        self, comparison_module, tmp_path: Path
    ) -> None:
        baseline = self._make_side(
            comparison_module, tmp_path, label="baseline",
            revision=_BASELINE_SHA, activity_count=20000,
        )
        head = self._make_side(
            comparison_module, tmp_path, label="head",
            revision=_HEAD_SHA, activity_count=10000,
        )
        with pytest.raises(comparison_module.ComparisonError, match="activity_count"):
            comparison_module._validate_cross_revision_consistency(baseline, head)

    def test_consistent_sides_pass(
        self, comparison_module, tmp_path: Path
    ) -> None:
        baseline = self._make_side(
            comparison_module, tmp_path, label="baseline",
            revision=_BASELINE_SHA,
        )
        head = self._make_side(
            comparison_module, tmp_path, label="head",
            revision=_HEAD_SHA,
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
        revision: str = _BASELINE_SHA,
    ) -> Any:
        path = _write_driver_result(
            tmp_path,
            _make_driver_payload(revision=revision, fixture_audit=fixture_audit),
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
        audit = _make_fixture_audit(preexisting_activity_count=5)
        side = self._make_side(comparison_module, tmp_path, fixture_audit=audit)
        with pytest.raises(
            comparison_module.ComparisonError, match="preexisting_activity_count"
        ):
            comparison_module._validate_scenario_isolation(side)

    def test_inserted_count_mismatch_raises(
        self, comparison_module, tmp_path: Path
    ) -> None:
        audit = _make_fixture_audit(inserted_count=19999)
        side = self._make_side(comparison_module, tmp_path, fixture_audit=audit)
        with pytest.raises(
            comparison_module.ComparisonError, match="inserted_count"
        ):
            comparison_module._validate_scenario_isolation(side)

    def test_connection_count_zero_raises(
        self, comparison_module, tmp_path: Path
    ) -> None:
        audit = _make_fixture_audit(connection_count=0)
        side = self._make_side(comparison_module, tmp_path, fixture_audit=audit)
        with pytest.raises(
            comparison_module.ComparisonError, match="connection_count"
        ):
            comparison_module._validate_scenario_isolation(side)

    def test_commit_count_zero_raises(
        self, comparison_module, tmp_path: Path
    ) -> None:
        audit = _make_fixture_audit(commit_count=0)
        side = self._make_side(comparison_module, tmp_path, fixture_audit=audit)
        with pytest.raises(
            comparison_module.ComparisonError, match="commit_count"
        ):
            comparison_module._validate_scenario_isolation(side)

    def test_clean_audit_passes(
        self, comparison_module, tmp_path: Path
    ) -> None:
        audit = _make_fixture_audit()
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
        revision: str = _BASELINE_SHA,
    ) -> Any:
        path = _write_driver_result(
            tmp_path,
            _make_driver_payload(revision=revision, metrics=metrics),
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
            _write_driver_result(baseline_dir, baseline_payload)
        if head_payload is not None:
            _write_driver_result(head_dir, head_payload)
        return baseline_dir, head_dir

    def _build(
        self,
        comparison_module,
        baseline_dir: Path,
        head_dir: Path,
        *,
        baseline_sha: str = _BASELINE_SHA,
        head_sha: str = _HEAD_SHA,
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
            baseline_payload=_make_driver_payload(
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
            head_payload=_make_driver_payload(
                revision=_HEAD_SHA,
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
            baseline_payload=_make_driver_payload(
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
            head_payload=_make_driver_payload(
                revision=_HEAD_SHA,
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
            baseline_payload=_make_driver_payload(
                revision=_BASELINE_SHA,
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
            head_payload=_make_driver_payload(
                revision=_HEAD_SHA,
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
            head_payload=_make_driver_payload(revision=_HEAD_SHA),
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
            baseline_payload=_make_driver_payload(revision=_BASELINE_SHA),
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
            baseline_payload=_make_driver_payload(
                revision=_BASELINE_SHA, status="failed",
                failure_category="missing_runtime",
                failure_reason="WebView2 Runtime is missing",
            ),
            head_payload=_make_driver_payload(revision=_HEAD_SHA),
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
            baseline_payload=_make_driver_payload(
                revision=_BASELINE_SHA, driver_version="1.0",
            ),
            head_payload=_make_driver_payload(
                revision=_HEAD_SHA, driver_version="2.0",
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
            baseline_payload=_make_driver_payload(
                revision=_BASELINE_SHA,
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
            head_payload=_make_driver_payload(
                revision=_HEAD_SHA,
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
            baseline_payload=_make_driver_payload(revision=_BASELINE_SHA),
            head_payload=_make_driver_payload(revision=_HEAD_SHA),
        )
        report = self._build(comparison_module, baseline_dir, head_dir)
        assert report["baseline_sha"] == _BASELINE_SHA
        assert report["head_sha"] == _HEAD_SHA
        assert report["tolerance_pct"] == 10.0
        assert report["schema_version"] == 2
        # Per-side diagnostics (NEW: nested under baseline/head, not top-level).
        assert report["baseline"]["driver_version"] == "1.0"
        assert report["baseline"]["fixture_hash"] == "fixedhash"
        assert report["baseline"]["activity_count"] == 20000
        assert report["baseline"]["expected_revision"] == _BASELINE_SHA
        assert report["head"]["driver_version"] == "1.0"
        assert report["head"]["expected_revision"] == _HEAD_SHA
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
            baseline_payload=_make_driver_payload(revision=_BASELINE_SHA),
            head_payload=_make_driver_payload(revision=_HEAD_SHA),
        )
        report = self._build(comparison_module, baseline_dir, head_dir)
        assert "note" in report
        assert "absolute" in report["note"].lower()
        assert "fully validated" in report["note"].lower()


# ---------------------------------------------------------------------------
# Exit code semantics (webview_comparison.py main)
# ---------------------------------------------------------------------------

class TestExitCodes:
    """Verify the fail-closed exit codes and artifact writing from main()."""

    def _run_main(
        self,
        comparison_module,
        monkeypatch,
        *,
        baseline_dir: Path,
        head_dir: Path,
        output_path: Path,
        tolerance_pct: str = "10",
        extra_argv: list[str] | None = None,
    ) -> int:
        monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
        argv = [
            "webview_comparison.py",
            "--baseline-dir", str(baseline_dir),
            "--head-dir", str(head_dir),
            "--baseline-sha", _BASELINE_SHA,
            "--head-sha", _HEAD_SHA,
            "--tolerance-pct", tolerance_pct,
            "--output", str(output_path),
        ]
        if extra_argv:
            argv.extend(extra_argv)
        monkeypatch.setattr(sys, "argv", argv)
        return comparison_module.main()

    def test_output_is_required(
        self, comparison_module, tmp_path: Path, monkeypatch
    ) -> None:
        """Omitting --output must cause argparse to raise SystemExit."""
        monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
        monkeypatch.setattr(sys, "argv", [
            "webview_comparison.py",
            "--baseline-dir", str(tmp_path / "baseline"),
            "--head-dir", str(tmp_path / "head"),
            "--baseline-sha", _BASELINE_SHA,
            "--head-sha", _HEAD_SHA,
            "--tolerance-pct", "10",
        ])
        with pytest.raises(SystemExit):
            comparison_module.main()

    def test_main_returns_0_and_writes_artifact_when_gates_pass(
        self, comparison_module, tmp_path: Path, monkeypatch
    ) -> None:
        baseline_dir = tmp_path / "baseline"
        head_dir = tmp_path / "head"
        output_path = tmp_path / "out" / "comparison.json"
        _write_driver_result(
            baseline_dir, _make_driver_payload(revision=_BASELINE_SHA)
        )
        _write_driver_result(
            head_dir, _make_driver_payload(revision=_HEAD_SHA)
        )
        exit_code = self._run_main(
            comparison_module, monkeypatch,
            baseline_dir=baseline_dir, head_dir=head_dir,
            output_path=output_path,
        )
        assert exit_code == 0
        # Fail-closed: artifact is always written.
        assert output_path.is_file()
        report = json.loads(output_path.read_text(encoding="utf-8"))
        assert report["outcome"] == "comparison_passed"
        assert report["baseline_sha"] == _BASELINE_SHA
        assert report["head_sha"] == _HEAD_SHA

    def test_main_returns_4_on_gate_failure(
        self, comparison_module, tmp_path: Path, monkeypatch
    ) -> None:
        baseline_dir = tmp_path / "baseline"
        head_dir = tmp_path / "head"
        output_path = tmp_path / "out" / "comparison.json"
        _write_driver_result(
            baseline_dir,
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
            head_dir,
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
        exit_code = self._run_main(
            comparison_module, monkeypatch,
            baseline_dir=baseline_dir, head_dir=head_dir,
            output_path=output_path,
        )
        assert exit_code == 4
        # Fail-closed: artifact is always written even on gate failure.
        assert output_path.is_file()
        report = json.loads(output_path.read_text(encoding="utf-8"))
        assert report["outcome"] == "comparison_gate_failed"

    def test_main_returns_0_when_baseline_missing_and_writes_artifact(
        self, comparison_module, tmp_path: Path, monkeypatch
    ) -> None:
        """Missing baseline artifact is fail-closed: outcome=baseline_invalid,
        exit 0, and an artifact is still written."""
        baseline_dir = tmp_path / "baseline"  # no artifact written
        head_dir = tmp_path / "head"
        output_path = tmp_path / "out" / "comparison.json"
        _write_driver_result(head_dir, _make_driver_payload(revision=_HEAD_SHA))
        exit_code = self._run_main(
            comparison_module, monkeypatch,
            baseline_dir=baseline_dir, head_dir=head_dir,
            output_path=output_path,
        )
        assert exit_code == 0
        assert output_path.is_file()
        report = json.loads(output_path.read_text(encoding="utf-8"))
        assert report["outcome"] == "baseline_invalid"
        assert report["baseline"]["present"] is False
        assert report["head"]["valid"] is True

    def test_main_returns_0_when_head_missing_and_writes_artifact(
        self, comparison_module, tmp_path: Path, monkeypatch
    ) -> None:
        """Missing head artifact is fail-closed: outcome=head_invalid, exit 0."""
        baseline_dir = tmp_path / "baseline"
        head_dir = tmp_path / "head"  # no artifact written
        output_path = tmp_path / "out" / "comparison.json"
        _write_driver_result(
            baseline_dir, _make_driver_payload(revision=_BASELINE_SHA)
        )
        exit_code = self._run_main(
            comparison_module, monkeypatch,
            baseline_dir=baseline_dir, head_dir=head_dir,
            output_path=output_path,
        )
        assert exit_code == 0
        assert output_path.is_file()
        report = json.loads(output_path.read_text(encoding="utf-8"))
        assert report["outcome"] == "head_invalid"
        assert report["head"]["present"] is False
        assert report["baseline"]["valid"] is True

    def test_main_returns_0_when_both_missing_and_writes_artifact(
        self, comparison_module, tmp_path: Path, monkeypatch
    ) -> None:
        baseline_dir = tmp_path / "baseline"  # no artifact
        head_dir = tmp_path / "head"  # no artifact
        output_path = tmp_path / "out" / "comparison.json"
        exit_code = self._run_main(
            comparison_module, monkeypatch,
            baseline_dir=baseline_dir, head_dir=head_dir,
            output_path=output_path,
        )
        assert exit_code == 0
        assert output_path.is_file()
        report = json.loads(output_path.read_text(encoding="utf-8"))
        assert report["outcome"] == "both_invalid"
        assert report["baseline"]["present"] is False
        assert report["head"]["present"] is False

    def test_main_returns_2_on_sample_count_mismatch_and_writes_failure_artifact(
        self, comparison_module, tmp_path: Path, monkeypatch
    ) -> None:
        """Sample count mismatch raises ComparisonError in _build_comparison;
        main catches it, writes a failure artifact (fail-closed), returns 2."""
        baseline_dir = tmp_path / "baseline"
        head_dir = tmp_path / "head"
        output_path = tmp_path / "out" / "comparison.json"
        _write_driver_result(
            baseline_dir,
            _make_driver_payload(
                revision=_BASELINE_SHA,
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
        )
        _write_driver_result(
            head_dir,
            _make_driver_payload(
                revision=_HEAD_SHA,
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
        exit_code = self._run_main(
            comparison_module, monkeypatch,
            baseline_dir=baseline_dir, head_dir=head_dir,
            output_path=output_path,
        )
        assert exit_code == 2
        # Fail-closed: artifact is written even on input/schema error.
        assert output_path.is_file()
        report = json.loads(output_path.read_text(encoding="utf-8"))
        assert report["outcome"] == "both_invalid"
        assert "comparison_error" in report
        assert "sample count" in report["comparison_error"]

    def test_main_writes_artifact_on_consistency_error(
        self, comparison_module, tmp_path: Path, monkeypatch
    ) -> None:
        """When both sides are valid but consistency fails, _build_comparison
        returns a report (does not raise); main writes it and returns 0
        (not a gate failure or schema error)."""
        baseline_dir = tmp_path / "baseline"
        head_dir = tmp_path / "head"
        output_path = tmp_path / "out" / "comparison.json"
        _write_driver_result(
            baseline_dir,
            _make_driver_payload(revision=_BASELINE_SHA, driver_version="1.0"),
        )
        _write_driver_result(
            head_dir,
            _make_driver_payload(revision=_HEAD_SHA, driver_version="2.0"),
        )
        exit_code = self._run_main(
            comparison_module, monkeypatch,
            baseline_dir=baseline_dir, head_dir=head_dir,
            output_path=output_path,
        )
        # Consistency error → outcome both_invalid → exit 0 (not gate failure).
        assert exit_code == 0
        assert output_path.is_file()
        report = json.loads(output_path.read_text(encoding="utf-8"))
        assert report["outcome"] == "both_invalid"
        assert "consistency_error" in report
        assert "driver_version" in report["consistency_error"]

    def test_main_does_not_accept_scenario_argument(
        self, comparison_module, tmp_path: Path, monkeypatch
    ) -> None:
        """WebView comparison does NOT take --scenario (unlike product
        benchmark comparison).  Passing it must be rejected by argparse."""
        baseline_dir = tmp_path / "baseline"
        head_dir = tmp_path / "head"
        output_path = tmp_path / "out" / "comparison.json"
        _write_driver_result(
            baseline_dir, _make_driver_payload(revision=_BASELINE_SHA)
        )
        _write_driver_result(
            head_dir, _make_driver_payload(revision=_HEAD_SHA)
        )
        monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
        monkeypatch.setattr(sys, "argv", [
            "webview_comparison.py",
            "--baseline-dir", str(baseline_dir),
            "--head-dir", str(head_dir),
            "--baseline-sha", _BASELINE_SHA,
            "--head-sha", _HEAD_SHA,
            "--tolerance-pct", "10",
            "--output", str(output_path),
            "--scenario", "webview_render",  # should be rejected
        ])
        with pytest.raises(SystemExit):
            comparison_module.main()
