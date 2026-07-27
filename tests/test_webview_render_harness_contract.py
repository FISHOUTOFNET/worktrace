"""Static contract tests for the WebView render harness and Performance
Validation WebView job.

Guards the WebView render harness source and the Performance Validation
workflow's WebView job against regressions in their declared contracts.
Asserts that the harness measures the real Detail DOM render path (not
just the bridge API), splits Detail timing into payload/render/total,
emits cold/warm summaries, reports honest runner metadata, uses profile-
based timeout configuration with a computed outer timeout, two-phase
detail completion failure categories, injects timeout config to JS, and
that baseline driver failure does not block HEAD execution.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.contract, pytest.mark.parallel_safe]

ROOT = Path(__file__).resolve().parents[1]
PERFORMANCE_WORKFLOW = ROOT / ".github" / "workflows" / "performance-validation.yml"
WEBVIEW_HARNESS = ROOT / "scripts" / "webview_render_perf.py"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _webview_job_lines() -> list[str]:
    """Return the lines of the ``webview-comparison`` job section."""
    workflow = PERFORMANCE_WORKFLOW.read_text(encoding="utf-8")
    lines = workflow.splitlines()
    start: int | None = None
    for index, line in enumerate(lines):
        stripped = line.lstrip()
        if stripped.startswith("name: WebView baseline vs HEAD") or stripped == "webview-comparison:":
            start = index
            break
    assert start is not None, "WebView comparison job not found"
    end = len(lines)
    for index in range(start + 1, len(lines)):
        line = lines[index]
        if line.startswith("  ") and not line.startswith("    "):
            stripped = line.strip()
            if stripped.endswith(":") and stripped != "steps:" and not stripped.startswith("#"):
                end = index
                break
    return lines[start:end]


def _load_harness_module():
    """Load ``webview_render_perf`` as an isolated module for behavioral tests."""
    spec = importlib.util.spec_from_file_location(
        "_webview_render_perf_under_test", WEBVIEW_HARNESS
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Workflow contract tests
# ---------------------------------------------------------------------------

def test_performance_validation_webview_job_has_no_continue_on_error() -> None:
    """The WebView comparison job must NOT use ``continue-on-error: true``
    on the comparison step or at the job level.  ``continue-on-error: true``
    IS allowed on the ``baseline_driver`` and ``head_driver`` steps so a
    baseline failure does not block HEAD execution.
    """
    job_lines = _webview_job_lines()
    allowed_ids = {"baseline_driver", "head_driver"}
    current_step_id: str | None = None
    in_steps = False
    for line in job_lines:
        stripped = line.strip()
        if stripped == "steps:":
            in_steps = True
            current_step_id = None
            continue
        if not in_steps:
            indent = len(line) - len(line.lstrip())
            if "continue-on-error: true" in line and indent <= 2:
                pytest.fail(
                    "WebView comparison job must not have job-level continue-on-error: true"
                )
            continue
        if line.startswith("      - "):
            current_step_id = None
        if stripped.startswith("id:"):
            current_step_id = stripped.replace("id:", "").strip()
        if "continue-on-error: true" in line:
            if current_step_id not in allowed_ids:
                pytest.fail(
                    f"Step '{current_step_id}' must not have continue-on-error: true "
                    f"(only baseline_driver and head_driver are allowed)"
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
    """The product benchmark job must use the HEAD-owned driver
    (``scripts/ci/product_benchmark_driver.py``) with ``--target-root``
    and ``--scenario`` for both baseline and HEAD, and compare via
    ``scripts/benchmark_comparison.py``.  The old ``pytest -m benchmark``
    approach and the old ``benchmark-comparison:`` job name must NOT be
    present.
    """
    workflow = PERFORMANCE_WORKFLOW.read_text(encoding="utf-8")
    assert "scripts/ci/product_benchmark_driver.py" in workflow
    assert "--target-root" in workflow
    assert "--scenario" in workflow
    assert "scripts/benchmark_comparison.py" in workflow
    assert "product-benchmark:" in workflow
    assert "benchmark-comparison:" not in workflow
    assert '-m "benchmark"' not in workflow


# ---------------------------------------------------------------------------
# Harness source contract tests
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Timeout profile tests
# ---------------------------------------------------------------------------

class TestTimeoutProfiles:
    """Verify the per-profile timeout configuration."""

    def test_timeout_profiles_defined(self) -> None:
        """``_TIMEOUT_PROFILES`` dict exists with ``smoke`` and ``full`` keys."""
        source = WEBVIEW_HARNESS.read_text(encoding="utf-8")
        assert "_TIMEOUT_PROFILES" in source
        assert '"smoke"' in source
        assert '"full"' in source

    def test_full_profile_timeouts(self) -> None:
        """Full profile has the expected generous timeout values."""
        mod = _load_harness_module()
        full = mod._TIMEOUT_PROFILES["full"]
        assert full["overview_payload_timeout_ms"] == 30000
        assert full["timeline_payload_timeout_ms"] == 60000
        assert full["detail_payload_timeout_ms"] == 60000
        assert full["detail_dom_timeout_ms"] == 10000

    def test_smoke_profile_timeouts(self) -> None:
        """Smoke profile has all four timeout keys defined."""
        mod = _load_harness_module()
        smoke = mod._TIMEOUT_PROFILES["smoke"]
        assert "overview_payload_timeout_ms" in smoke
        assert "timeline_payload_timeout_ms" in smoke
        assert "detail_payload_timeout_ms" in smoke
        assert "detail_dom_timeout_ms" in smoke

    def test_timeout_profiles_are_generous(self) -> None:
        """Full profile detail payload timeout must be >= 30000 ms so it
        is not close to baseline actuals (these are execution guards,
        not performance gates).
        """
        mod = _load_harness_module()
        full = mod._TIMEOUT_PROFILES["full"]
        assert full["detail_payload_timeout_ms"] >= 30000

    def test_no_unified_detail_timeout(self) -> None:
        """The source must NOT contain a unified ``detail_timeout`` string
        as a failure category — it should use ``detail_payload_timeout``,
        ``detail_payload_error``, ``detail_dom_empty``,
        ``detail_dom_unstable``, ``detail_explicit_error`` instead.
        """
        source = WEBVIEW_HARNESS.read_text(encoding="utf-8")
        assert '"detail_timeout"' not in source


# ---------------------------------------------------------------------------
# Outer timeout computation tests
# ---------------------------------------------------------------------------

class TestComputeOuterTimeout:
    """Verify the Python outer timeout computation."""

    def test_compute_outer_timeout_exists(self) -> None:
        """The ``_compute_outer_timeout`` function must exist."""
        source = WEBVIEW_HARNESS.read_text(encoding="utf-8")
        assert "def _compute_outer_timeout" in source

    def test_outer_timeout_proportional_to_runs(self) -> None:
        """More runs must yield a larger outer timeout."""
        mod = _load_harness_module()
        small = mod._compute_outer_timeout(runs=1, profile_name="full")
        large = mod._compute_outer_timeout(runs=5, profile_name="full")
        assert large > small

    def test_outer_timeout_includes_startup_allowance(self) -> None:
        """The timeout must be >= startup allowance + cleanup margin."""
        mod = _load_harness_module()
        timeout = mod._compute_outer_timeout(runs=1, profile_name="smoke")
        assert timeout >= mod._STARTUP_ALLOWANCE_SECONDS + mod._CLEANUP_MARGIN_SECONDS

    def test_outer_timeout_not_fixed_180(self) -> None:
        """The source must NOT use a fixed ``180`` second timeout.  The
        historical 180-second value is only mentioned in a docstring
        explaining why it was replaced.
        """
        source = WEBVIEW_HARNESS.read_text(encoding="utf-8")
        code_source = source.replace("180-second", "")
        assert "180" not in code_source

    def test_outer_timeout_uses_stage_budgets(self) -> None:
        """The timeout must be computed from overview + timeline +
        detail_payload + detail_dom budgets.
        """
        source = WEBVIEW_HARNESS.read_text(encoding="utf-8")
        assert "overview_payload_timeout_ms" in source
        assert "timeline_payload_timeout_ms" in source
        assert "detail_payload_timeout_ms" in source
        assert "detail_dom_timeout_ms" in source
        assert "def _compute_outer_timeout" in source


# ---------------------------------------------------------------------------
# Two-phase detail completion tests
# ---------------------------------------------------------------------------

class TestTwoPhaseDetailCompletion:
    """Verify the two-phase detail completion failure categories."""

    def test_detail_payload_timeout_category(self) -> None:
        """Source contains the ``detail_payload_timeout`` failure category."""
        source = WEBVIEW_HARNESS.read_text(encoding="utf-8")
        assert "detail_payload_timeout" in source

    def test_detail_payload_error_category(self) -> None:
        """Source contains the ``detail_payload_error`` failure category."""
        source = WEBVIEW_HARNESS.read_text(encoding="utf-8")
        assert "detail_payload_error" in source

    def test_detail_dom_empty_category(self) -> None:
        """Source contains the ``detail_dom_empty`` failure category."""
        source = WEBVIEW_HARNESS.read_text(encoding="utf-8")
        assert "detail_dom_empty" in source

    def test_detail_dom_unstable_category(self) -> None:
        """Source contains the ``detail_dom_unstable`` failure category."""
        source = WEBVIEW_HARNESS.read_text(encoding="utf-8")
        assert "detail_dom_unstable" in source

    def test_detail_explicit_error_category(self) -> None:
        """Source contains the ``detail_explicit_error`` failure category."""
        source = WEBVIEW_HARNESS.read_text(encoding="utf-8")
        assert "detail_explicit_error" in source

    def test_no_unified_detail_timeout_category(self) -> None:
        """Source must NOT contain ``"detail_timeout"`` as a failure
        category string (the old unified category).
        """
        source = WEBVIEW_HARNESS.read_text(encoding="utf-8")
        assert '"detail_timeout"' not in source


# ---------------------------------------------------------------------------
# Timeout config injection tests
# ---------------------------------------------------------------------------

class TestTimeoutConfigInjection:
    """Verify the timeout config is injected to the JS runtime."""

    def test_timeout_config_injected_to_js(self) -> None:
        """Python injects the timeout config via ``evaluate_js``."""
        source = WEBVIEW_HARNESS.read_text(encoding="utf-8")
        assert "window.__perfTimeoutConfig = " in source

    def test_timeout_config_uses_profile(self) -> None:
        """The injected config is selected by profile name."""
        source = WEBVIEW_HARNESS.read_text(encoding="utf-8")
        assert "_TIMEOUT_PROFILES[profile_name]" in source

    def test_js_reads_timeout_config(self) -> None:
        """The JS measurement script reads the injected timeout config."""
        source = WEBVIEW_HARNESS.read_text(encoding="utf-8")
        assert "window.__perfTimeoutConfig" in source


# ---------------------------------------------------------------------------
# Baseline failure doesn't block HEAD tests
# ---------------------------------------------------------------------------

class TestBaselineFailureDoesNotBlockHead:
    """Verify baseline driver failure does not block HEAD execution."""

    def test_baseline_driver_has_continue_on_error(self) -> None:
        """The ``baseline_driver`` step must have ``continue-on-error: true``
        so a baseline failure does not block HEAD execution.
        """
        job_lines = _webview_job_lines()
        current_step_id: str | None = None
        found = False
        for line in job_lines:
            stripped = line.strip()
            if line.startswith("      - "):
                current_step_id = None
            if stripped.startswith("id:"):
                current_step_id = stripped.replace("id:", "").strip()
            if "continue-on-error: true" in line and current_step_id == "baseline_driver":
                found = True
                break
        assert found, "baseline_driver step must have continue-on-error: true"

    def test_head_driver_has_continue_on_error(self) -> None:
        """The ``head_driver`` step must have ``continue-on-error: true``."""
        job_lines = _webview_job_lines()
        current_step_id: str | None = None
        found = False
        for line in job_lines:
            stripped = line.strip()
            if line.startswith("      - "):
                current_step_id = None
            if stripped.startswith("id:"):
                current_step_id = stripped.replace("id:", "").strip()
            if "continue-on-error: true" in line and current_step_id == "head_driver":
                found = True
                break
        assert found, "head_driver step must have continue-on-error: true"

    def test_comparison_step_runs_always(self) -> None:
        """The comparison step must have ``if: always()`` so it runs
        regardless of whether the drivers succeeded or failed.
        """
        job_lines = _webview_job_lines()
        current_step_id: str | None = None
        found = False
        for line in job_lines:
            stripped = line.strip()
            if line.startswith("      - "):
                current_step_id = None
            if stripped.startswith("id:"):
                current_step_id = stripped.replace("id:", "").strip()
            if "if: always()" in line and current_step_id == "comparison":
                found = True
                break
        assert found, "comparison step must have if: always()"

    def test_comparison_step_no_continue_on_error(self) -> None:
        """The comparison step must NOT have ``continue-on-error: true``
        — its failure must propagate to the job status.
        """
        job_lines = _webview_job_lines()
        current_step_id: str | None = None
        for line in job_lines:
            stripped = line.strip()
            if line.startswith("      - "):
                current_step_id = None
            if stripped.startswith("id:"):
                current_step_id = stripped.replace("id:", "").strip()
            if "continue-on-error: true" in line and current_step_id == "comparison":
                pytest.fail("comparison step must not have continue-on-error: true")

    def test_artifact_upload_always(self) -> None:
        """The artifact upload step must have ``if: always()`` so results
        are available even when the comparison fails.
        """
        job_text = "\n".join(_webview_job_lines())
        assert "Upload WebView comparison artifact" in job_text
        assert "if: always()" in job_text
        assert "actions/upload-artifact" in job_text
