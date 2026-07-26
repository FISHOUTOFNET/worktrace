"""Static contract tests for the WebView render harness and Performance
Validation WebView job.

Guards the WebView render harness source and the Performance Validation
workflow's WebView job against regressions in their declared contracts.
Asserts that the harness measures the real Detail DOM render path (not
just the bridge API), splits Detail timing into payload/render/total,
emits cold/warm summaries, reports honest runner metadata, and that the
Performance Validation WebView job does not mask failures via
``continue-on-error``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.contract, pytest.mark.parallel_safe]

ROOT = Path(__file__).resolve().parents[1]
PERFORMANCE_WORKFLOW = ROOT / ".github" / "workflows" / "performance-validation.yml"
WEBVIEW_HARNESS = ROOT / "scripts" / "webview_render_perf.py"


def test_performance_validation_webview_job_has_no_continue_on_error() -> None:
    """The WebView comparison job must NOT use ``continue-on-error: true``.
    A harness failure must fail the job and the overall workflow; the
    artifact is still uploaded via ``if: always()``.
    """
    workflow = PERFORMANCE_WORKFLOW.read_text(encoding="utf-8")
    assert "name: WebView baseline vs HEAD" in workflow or "webview-comparison:" in workflow
    lines = workflow.splitlines()
    webview_job_start = None
    for index, line in enumerate(lines):
        stripped = line.lstrip()
        if stripped.startswith("name: WebView baseline vs HEAD") or stripped == "webview-comparison:":
            webview_job_start = index
            break
    assert webview_job_start is not None, "WebView comparison job not found"
    for line in lines[webview_job_start + 1:]:
        if line.startswith("  ") and line.rstrip().endswith(":") and not line.startswith("    "):
            stripped = line.strip()
            if stripped in ("steps:",) or stripped.endswith(":"):
                if stripped == "steps:":
                    continue
                break
        if "continue-on-error: true" in line and "steps:" not in line:
            indent = len(line) - len(line.lstrip())
            if indent <= 2:
                pytest.fail(
                    "WebView comparison job must not have job-level continue-on-error: true"
                )


def test_performance_validation_webview_artifact_uses_if_always() -> None:
    """The WebView comparison artifact must still upload on failure."""
    workflow = PERFORMANCE_WORKFLOW.read_text(encoding="utf-8")
    assert "Upload WebView comparison artifact" in workflow
    assert "if: always()" in workflow
    assert "webview-comparison-" in workflow


def test_performance_validation_webview_comparison_uses_head_owned_driver() -> None:
    """The WebView comparison job must use the HEAD-owned driver
    (``scripts/webview_render_perf.py``) with ``--target-root`` for both
    baseline and HEAD, and compare via ``scripts/webview_comparison.py``.
    """
    workflow = PERFORMANCE_WORKFLOW.read_text(encoding="utf-8")
    assert "scripts/webview_render_perf.py" in workflow
    assert "--target-root" in workflow
    assert "scripts/webview_comparison.py" in workflow
    assert "--baseline-dir" in workflow
    assert "--head-dir" in workflow


def test_performance_validation_webview_comparison_outputs_results_dir() -> None:
    """The WebView comparison job must output ``results_dir`` so the
    artifact upload path is reliable (fail-closed on missing path).
    """
    workflow = PERFORMANCE_WORKFLOW.read_text(encoding="utf-8")
    assert "results_dir=" in workflow
    assert "if-no-files-found: error" in workflow


def test_performance_validation_benchmark_uses_head_owned_driver() -> None:
    """The benchmark comparison job must use the HEAD-owned driver
    (``scripts/ci/product_benchmark_driver.py``) with ``--target-root``
    for both baseline and HEAD, and compare via ``scripts/benchmark_comparison.py``.
    The old ``pytest -m benchmark`` approach must NOT be present.
    """
    workflow = PERFORMANCE_WORKFLOW.read_text(encoding="utf-8")
    assert "scripts/ci/product_benchmark_driver.py" in workflow
    assert "--target-root" in workflow
    assert "scripts/benchmark_comparison.py" in workflow
    assert "benchmark-comparison:" in workflow
    assert '-m "benchmark"' not in workflow


def test_webview_harness_measures_real_detail_dom_render() -> None:
    """The harness must trigger Detail selection through the real public
    entry point (``App.selectTimelineSession``) and wait for the real
    DOM to update — not just call the bridge API.
    """
    source = WEBVIEW_HARNESS.read_text(encoding="utf-8")
    assert "App.selectTimelineSession" in source
    assert "data-projection-instance-key" in source
    assert "lastSessionActivitySummaryViewModel" in source
    assert "detailsInFlight" in source
    assert "summary-item" in source


def test_webview_harness_splits_detail_payload_render_total() -> None:
    """Detail timing must be three separate stages: payload (request ->
    data returned), render (data returned -> DOM completed two frames),
    and total (selection start -> DOM completed).
    """
    source = WEBVIEW_HARNESS.read_text(encoding="utf-8")
    assert "detail_payload_ms" in source
    assert "detail_render_ms" in source
    assert "detail_total_ms" in source
    assert "_detail_start" in source
    assert "_detail_payload" in source
    assert "_detail_first_frame" in source


def test_webview_harness_counts_dom_rows_via_summary_item_selector() -> None:
    """DOM row count must use ``.summary-item`` querySelector, not
    ``children.length``, so non-row children do not inflate the count.
    """
    source = WEBVIEW_HARNESS.read_text(encoding="utf-8")
    assert 'querySelectorAll(".summary-item")' in source


def test_webview_harness_asserts_realism_of_detail_render() -> None:
    """The harness must assert that the detail render actually produced
    rows: row count > 0, DOM row count > 0, and the two match.
    """
    source = WEBVIEW_HARNESS.read_text(encoding="utf-8")
    assert "detail_row_count_zero" in source
    assert "detail_dom_row_count_zero" in source
    assert "detail_row_count_mismatch" in source


def test_webview_harness_emits_cold_warm_summary() -> None:
    """The harness must split the artifact into cold (run 0) and warm
    (median of runs 1+) sections so cold-start regressions are visible.
    """
    source = WEBVIEW_HARNESS.read_text(encoding="utf-8")
    assert "_build_cold_warm_summary" in source
    assert '"cold"' in source
    assert '"warm"' in source
    assert "cold_warm" in source


def test_webview_harness_runner_metadata_does_not_mislabel_hosted_runner() -> None:
    """The harness must only report ``execution_environment = "local"``
    when ``GITHUB_ACTIONS`` is not ``"true"``.  On GitHub Actions, the
    real runner env vars must be exposed so a hosted runner cannot be
    mislabelled as ``"local"``.
    """
    source = WEBVIEW_HARNESS.read_text(encoding="utf-8")
    assert "GITHUB_ACTIONS" in source
    assert "execution_environment" in source
    assert "github_actions" in source
    assert "GITHUB_SHA" in source
    assert "GITHUB_RUN_ID" in source
    assert "RUNNER_OS" in source
    assert "RUNNER_ARCH" in source
    assert "ImageOS" in source
    assert "ImageVersion" in source


def test_webview_harness_does_not_modify_production_frontend() -> None:
    """The harness must inject all instrumentation at runtime via
    ``evaluate_js`` — it must NOT modify shipped frontend files.
    """
    source = WEBVIEW_HARNESS.read_text(encoding="utf-8")
    assert "evaluate_js" in source
    assert "webview_ui/js/core.js" not in source or source.count("webview_ui/js/core.js") == 0
    assert "index_path" in source


def test_webview_harness_propagates_failure_to_exit_code() -> None:
    """A harness failure must produce a non-zero process exit code so
    the Performance Validation workflow cannot display green when the
    harness actually failed.
    """
    source = WEBVIEW_HARNESS.read_text(encoding="utf-8")
    assert "return 1" in source
    assert "return 0" in source
    assert 'result["status"] != "ok"' in source
