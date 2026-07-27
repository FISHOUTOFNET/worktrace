"""Contract tests for performance validation workflow governance.

The expensive Performance Validation and Standard Timing Validation
workflows must NOT run on every push to performance-sensitive paths.
Repeated pushes would cause unbounded CI trial-and-error on expensive
20k/10k baseline-vs-HEAD runs.

Governance contract:
  * Performance Validation triggers only on schedule,
    workflow_dispatch, or when the PR carries the explicit
    ``run-performance-validation`` label.
  * Standard Timing Validation triggers only on workflow_dispatch or
    when the PR carries the ``run-standard-timing`` label.
  * Both workflows define a concurrency group keyed by PR number/ref
    with ``cancel-in-progress: true`` so accidental double-triggers
    cannot waste runner minutes.
  * Both workflows use the ``--profile full`` driver invocation (the
    workflow never runs smoke — smoke is for local validation only).
  * Neither workflow uses ``continue-on-error`` on the gate/comparison
    steps. It IS allowed on ``baseline_driver``/``head_driver`` steps
    so baseline failure does not block HEAD execution; the
    comparison/finalize step always runs via ``if: always()`` and is
    the sole determinant of job success.
  * The product-benchmark job uses a matrix strategy with two
    cross-revision latency scenarios (``20k_activities`` and
    ``10k_contributions``), each with its own timeout.
    ``fail-fast: false`` ensures one scenario's failure does not cancel
    the other.
  * A HEAD-only ``compact-memory`` job runs the compact-storage memory
    gate at 5000 entries — NOT a baseline-vs-HEAD comparison.
  * The Standard CI workflow (``_validation.yml``) excludes benchmark
    tests via ``-m "not benchmark"``.
  * Neither workflow increases timeout above the historical ceiling,
    and neither lowers the data scale or the tolerance to pass.

These tests parse the YAML files as text (not via ``yaml.safe_load``)
to avoid depending on PyYAML and to make the assertions robust against
structural reformatting.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.contract, pytest.mark.parallel_safe]

ROOT = Path(__file__).resolve().parents[1]
PERF_VALIDATION_YML = (
    ROOT / ".github" / "workflows" / "performance-validation.yml"
)
STANDARD_TIMING_YML = (
    ROOT / ".github" / "workflows" / "standard-timing-validation.yml"
)
STANDARD_CI_YML = (
    ROOT / ".github" / "workflows" / "_validation.yml"
)
PRODUCT_DRIVER_PATH = ROOT / "scripts" / "ci" / "product_benchmark_driver.py"
WEBVIEW_DRIVER_PATH = ROOT / "scripts" / "webview_render_perf.py"

# Step ids that are permitted to use ``continue-on-error`` so baseline
# failure does not block HEAD driver execution.
_ALLOWED_CONTINUE_ON_ERROR_STEP_IDS = {"baseline_driver", "head_driver"}


# ---------------------------------------------------------------------------
# Module-level YAML helpers
# ---------------------------------------------------------------------------

def _extract_job_section(source: str, job_name: str) -> str | None:
    """Extract the YAML text of one job by job key.

    Returns the job's body (from the job key to the next top-level
    key at the same indentation, or end of file).
    """
    pattern = re.compile(
        r"^  " + re.escape(job_name) + r":\s*\n((?:(?:    |\n).*\n)*)",
        re.MULTILINE,
    )
    match = pattern.search(source)
    if match is None:
        return None
    body = match.group(1)
    return body.rstrip() + "\n"


def _find_steps_with_continue_on_error(
    source: str,
) -> list[dict[str, str | None]]:
    """Find all steps that set ``continue-on-error``.

    Returns a list of dicts with keys ``id``, ``name``, ``value``.
    ``id`` and ``name`` are ``None`` if not found in the step block.
    """
    results: list[dict[str, str | None]] = []
    lines = source.split("\n")
    for i, line in enumerate(lines):
        coe_match = re.match(r"^        continue-on-error:\s*(.+)", line)
        if not coe_match:
            continue
        value = coe_match.group(1).strip()
        step_id: str | None = None
        step_name: str | None = None
        for j in range(i - 1, max(i - 30, -1), -1):
            prev = lines[j]
            if re.match(r"^      - ", prev):
                name_match = re.match(r"^      - name:\s*(.+)", prev)
                if name_match:
                    step_name = name_match.group(1).strip()
                break
            id_match = re.match(r"^        id:\s*(\S+)", prev)
            if id_match and step_id is None:
                step_id = id_match.group(1)
        results.append(
            {"id": step_id, "name": step_name, "value": value}
        )
    return results


# ---------------------------------------------------------------------------
# Performance Validation: trigger policy
# ---------------------------------------------------------------------------

class TestPerformanceValidationTriggers:
    """The Performance Validation workflow must NOT trigger on every
    push to performance-sensitive paths."""

    def test_workflow_file_exists(self) -> None:
        assert PERF_VALIDATION_YML.is_file(), (
            "performance-validation.yml must exist"
        )

    def test_does_not_trigger_on_push(self) -> None:
        """The workflow must NOT use ``on: push`` — that would cause
        unbounded CI trial-and-error on every small commit."""
        source = PERF_VALIDATION_YML.read_text(encoding="utf-8")
        on_match = re.search(
            r"^on:\s*\n((?:\s{2,}\S.*\n)*)",
            source,
            re.MULTILINE,
        )
        assert on_match is not None, "could not find on: block"
        on_block = on_match.group(1)
        # ``push:`` may appear as a top-level key under on: — reject it.
        # But ``push`` may legitimately appear inside
        # ``github.event.pull_request`` conditions, so we check the
        # indentation: a 2-space-indented ``push:`` is a trigger type.
        assert not re.search(r"^  push:", on_block, re.MULTILINE), (
            "performance-validation.yml must NOT trigger on push — "
            "that would cause unbounded CI trial-and-error"
        )

    def test_triggers_on_workflow_dispatch(self) -> None:
        source = PERF_VALIDATION_YML.read_text(encoding="utf-8")
        assert "workflow_dispatch:" in source

    def test_triggers_on_schedule(self) -> None:
        source = PERF_VALIDATION_YML.read_text(encoding="utf-8")
        assert "schedule:" in source
        assert "cron:" in source

    def test_triggers_on_pull_request_labeled(self) -> None:
        """The workflow must trigger on ``pull_request`` ``labeled``
        events so the explicit ``run-performance-validation`` label
        can launch the expensive run."""
        source = PERF_VALIDATION_YML.read_text(encoding="utf-8")
        assert "pull_request:" in source
        assert "types: [labeled]" in source or "types:\n      - labeled" in source

    def test_job_if_checks_label_name(self) -> None:
        """The job-level ``if`` condition must re-check the label
        name so an unrelated label cannot launch the expensive run."""
        source = PERF_VALIDATION_YML.read_text(encoding="utf-8")
        assert "github.event.label.name == 'run-performance-validation'" in source
        label_count = source.count(
            "github.event.label.name == 'run-performance-validation'"
        )
        assert label_count >= 2, (
            f"expected label check in at least 2 jobs, found {label_count}"
        )


# ---------------------------------------------------------------------------
# Performance Validation: concurrency group
# ---------------------------------------------------------------------------

class TestPerformanceValidationConcurrency:
    """The workflow must define a concurrency group so accidental
    double-triggers cancel the older run in-place."""

    def test_concurrency_block_exists(self) -> None:
        source = PERF_VALIDATION_YML.read_text(encoding="utf-8")
        assert "concurrency:" in source

    def test_concurrency_group_keyed_by_pr_or_ref(self) -> None:
        source = PERF_VALIDATION_YML.read_text(encoding="utf-8")
        assert "group: performance-validation-" in source
        assert (
            "github.event.pull_request.number || github.ref" in source
        ), (
            "concurrency group must key by PR number or ref so distinct "
            "PRs are not cancelled against each other"
        )

    def test_cancel_in_progress_true(self) -> None:
        source = PERF_VALIDATION_YML.read_text(encoding="utf-8")
        assert "cancel-in-progress: true" in source


# ---------------------------------------------------------------------------
# Performance Validation: profile and gate discipline
# ---------------------------------------------------------------------------

class TestPerformanceValidationProfileAndGates:
    """The workflow must run the ``full`` profile (never smoke), must
    NOT use ``continue-on-error`` on the gate/comparison steps (it IS
    allowed on driver steps so baseline failure does not block HEAD),
    and must NOT increase timeout above the historical ceiling."""

    def test_workflow_runs_full_profile(self) -> None:
        """Both baseline and HEAD driver invocations must pass
        ``--profile full`` so the workflow measures the real
        performance-gate data sizes."""
        source = PERF_VALIDATION_YML.read_text(encoding="utf-8")
        full_count = source.count("--profile full")
        assert full_count >= 4, (
            f"expected at least 4 '--profile full' invocations "
            f"(2 baseline + 2 HEAD across 2 jobs), found {full_count}"
        )

    def test_workflow_does_not_run_smoke_profile(self) -> None:
        """The workflow must NEVER run ``--profile smoke`` — smoke is
        for local infrastructure validation only, not the performance
        gate."""
        source = PERF_VALIDATION_YML.read_text(encoding="utf-8")
        assert "--profile smoke" not in source, (
            "performance-validation.yml must not invoke --profile smoke — "
            "smoke is for local validation only"
        )

    def test_no_continue_on_error_on_gate_steps(self) -> None:
        """``continue-on-error: true`` is only allowed on driver steps
        (id: baseline_driver, head_driver) so baseline failure does not
        block HEAD execution. Gate/comparison steps must NOT use it."""
        source = PERF_VALIDATION_YML.read_text(encoding="utf-8")
        steps_with_coe = _find_steps_with_continue_on_error(source)
        for step in steps_with_coe:
            if step["value"] != "true":
                continue
            assert step["id"] in _ALLOWED_CONTINUE_ON_ERROR_STEP_IDS, (
                "continue-on-error: true is only allowed on driver steps "
                f"(id: baseline_driver or head_driver), but found on step "
                f"'{step.get('name', step.get('id'))}'"
            )
        # Job-level continue-on-error (4-space indent) is prohibited.
        job_level_coe = re.findall(
            r"^    continue-on-error:", source, re.MULTILINE
        )
        assert len(job_level_coe) == 0, (
            "continue-on-error at job level is prohibited"
        )

    def test_no_continue_on_error_with_bool_shorthand(self) -> None:
        """Same check for the YAML boolean shorthand — only allowed on
        driver steps."""
        source = PERF_VALIDATION_YML.read_text(encoding="utf-8")
        steps_with_coe = _find_steps_with_continue_on_error(source)
        for step in steps_with_coe:
            if "${{" not in (step["value"] or ""):
                continue
            assert step["id"] in _ALLOWED_CONTINUE_ON_ERROR_STEP_IDS, (
                "continue-on-error with ${{...}} shorthand is only allowed "
                "on driver steps (id: baseline_driver or head_driver), but "
                f"found on step '{step.get('name', step.get('id'))}'"
            )

    def test_webview_job_timeout_within_ceiling(self) -> None:
        """The WebView comparison job's ``timeout-minutes`` must NOT
        exceed 30 — increasing timeout to bypass a slow workflow is
        explicitly prohibited."""
        source = PERF_VALIDATION_YML.read_text(encoding="utf-8")
        webview_section = _extract_job_section(
            source, "webview-comparison"
        )
        assert webview_section is not None, (
            "webview-comparison job not found"
        )
        timeout_match = re.search(
            r"timeout-minutes:\s*(\d+)", webview_section
        )
        assert timeout_match is not None, (
            "webview-comparison job must specify timeout-minutes"
        )
        timeout = int(timeout_match.group(1))
        assert timeout <= 30, (
            f"webview-comparison timeout-minutes={timeout} exceeds the "
            f"30-minute ceiling — increasing timeout to bypass a slow "
            f"workflow is prohibited"
        )

    def test_benchmark_job_timeout_within_ceiling(self) -> None:
        """The product-benchmark job's per-matrix ``timeout_minutes``
        must NOT exceed 40 — increasing timeout to bypass a slow
        workflow is explicitly prohibited."""
        source = PERF_VALIDATION_YML.read_text(encoding="utf-8")
        benchmark_section = _extract_job_section(
            source, "product-benchmark"
        )
        assert benchmark_section is not None, (
            "product-benchmark job not found"
        )
        timeout_matches = re.findall(
            r"timeout_minutes:\s*(\d+)", benchmark_section
        )
        assert timeout_matches, (
            "product-benchmark matrix must specify timeout_minutes "
            "per scenario"
        )
        for timeout_str in timeout_matches:
            timeout = int(timeout_str)
            assert timeout <= 40, (
                f"product-benchmark timeout_minutes={timeout} exceeds the "
                f"40-minute ceiling — increasing timeout to bypass a slow "
                f"workflow is prohibited"
            )


# ---------------------------------------------------------------------------
# Performance Validation: driver invocations include required args
# ---------------------------------------------------------------------------

class TestPerformanceValidationDriverInvocations:
    """Each driver invocation in the workflow must pass the required
    arguments for revision-identity verification and profile selection."""

    def test_baseline_product_driver_uses_target_root_and_revision(
        self,
    ) -> None:
        source = PERF_VALIDATION_YML.read_text(encoding="utf-8")
        assert "--target-root $baselineWt" in source or \
               "--target-root ${{ steps.paths.outputs.baseline_worktree }}" in source
        assert "--revision" in source

    def test_head_product_driver_uses_target_root_and_revision(self) -> None:
        source = PERF_VALIDATION_YML.read_text(encoding="utf-8")
        assert "--target-root $headWt" in source or \
               "--target-root ${{ steps.paths.outputs.head_worktree }}" in source

    def test_product_comparison_invocation_passes_shas(self) -> None:
        source = PERF_VALIDATION_YML.read_text(encoding="utf-8")
        assert "--baseline-sha" in source
        assert "--head-sha" in source
        assert "scripts/benchmark_comparison.py" in source

    def test_webview_comparison_invocation_passes_shas(self) -> None:
        source = PERF_VALIDATION_YML.read_text(encoding="utf-8")
        assert "scripts/webview_comparison.py" in source

    def test_tolerance_default_is_10(self) -> None:
        """The default tolerance must remain at 10% — lowering the
        gate to pass is prohibited."""
        source = PERF_VALIDATION_YML.read_text(encoding="utf-8")
        assert "default: \"10\"" in source, (
            "benchmark_comparison_tolerance_pct default must be 10 — "
            "lowering the gate to pass is prohibited"
        )


# ---------------------------------------------------------------------------
# Standard Timing Validation: trigger policy
# ---------------------------------------------------------------------------

class TestStandardTimingTriggers:
    """The Standard Timing Validation workflow must NOT trigger on
    every push."""

    def test_workflow_file_exists(self) -> None:
        assert STANDARD_TIMING_YML.is_file(), (
            "standard-timing-validation.yml must exist"
        )

    def test_does_not_trigger_on_push(self) -> None:
        source = STANDARD_TIMING_YML.read_text(encoding="utf-8")
        on_match = re.search(
            r"^on:\s*\n((?:\s{2,}\S.*\n)*)",
            source,
            re.MULTILINE,
        )
        assert on_match is not None, "could not find on: block"
        on_block = on_match.group(1)
        assert not re.search(r"^  push:", on_block, re.MULTILINE), (
            "standard-timing-validation.yml must NOT trigger on push"
        )

    def test_triggers_on_workflow_dispatch(self) -> None:
        source = STANDARD_TIMING_YML.read_text(encoding="utf-8")
        assert "workflow_dispatch:" in source

    def test_triggers_on_pull_request_labeled(self) -> None:
        source = STANDARD_TIMING_YML.read_text(encoding="utf-8")
        assert "pull_request:" in source
        assert "types: [labeled]" in source or "types:\n      - labeled" in source

    def test_job_if_checks_label_name(self) -> None:
        """The job ``if`` condition must check for the
        ``run-standard-timing`` label."""
        source = STANDARD_TIMING_YML.read_text(encoding="utf-8")
        assert "github.event.label.name == 'run-standard-timing'" in source


# ---------------------------------------------------------------------------
# Standard Timing Validation: concurrency group
# ---------------------------------------------------------------------------

class TestStandardTimingConcurrency:
    """Standard Timing Validation must have its own concurrency group
    independent from Performance Validation so the two expensive
    workflows can run in parallel if needed, but duplicate runs of
    the same workflow on the same PR/ref are cancelled."""

    def test_concurrency_block_exists(self) -> None:
        source = STANDARD_TIMING_YML.read_text(encoding="utf-8")
        assert "concurrency:" in source

    def test_concurrency_group_keyed_by_pr_or_ref(self) -> None:
        source = STANDARD_TIMING_YML.read_text(encoding="utf-8")
        assert "group: standard-timing-validation-" in source
        assert (
            "github.event.pull_request.number || github.ref" in source
        )

    def test_cancel_in_progress_true(self) -> None:
        source = STANDARD_TIMING_YML.read_text(encoding="utf-8")
        assert "cancel-in-progress: true" in source

    def test_concurrency_group_distinct_from_performance_validation(
        self,
    ) -> None:
        """The two workflows must use distinct concurrency group names
        so they can run in parallel."""
        perf_source = PERF_VALIDATION_YML.read_text(encoding="utf-8")
        timing_source = STANDARD_TIMING_YML.read_text(encoding="utf-8")
        perf_match = re.search(
            r"group:\s*(performance-validation-\S+)", perf_source
        )
        timing_match = re.search(
            r"group:\s*(standard-timing-validation-\S+)", timing_source
        )
        assert perf_match is not None
        assert timing_match is not None
        assert perf_match.group(1).startswith("performance-validation-")
        assert timing_match.group(1).startswith("standard-timing-validation-")


# ---------------------------------------------------------------------------
# Driver profile support
# ---------------------------------------------------------------------------

class TestDriverProfileSupport:
    """Both drivers must define ``smoke`` and ``full`` profiles with
    the canonical data sizes for each."""

    def test_product_driver_defines_smoke_and_full(self) -> None:
        source = PRODUCT_DRIVER_PATH.read_text(encoding="utf-8")
        assert '"smoke"' in source
        assert '"full"' in source
        assert "_PROFILES" in source

    def test_product_driver_smoke_uses_small_data(self) -> None:
        """Smoke profile must use small data sizes (<= 1000) for
        infrastructure validation, NOT the real gate sizes."""
        source = PRODUCT_DRIVER_PATH.read_text(encoding="utf-8")
        smoke_match = re.search(
            r'"smoke":\s*\{[^}]*"activity_count":\s*(\d+)[^}]*\}',
            source,
        )
        assert smoke_match is not None, "smoke profile not found"
        smoke_activity = int(smoke_match.group(1))
        assert smoke_activity <= 1000, (
            f"smoke profile activity_count={smoke_activity} exceeds 1000 — "
            f"smoke is for infrastructure validation, not the gate"
        )

    def test_product_driver_full_uses_real_data(self) -> None:
        """Full profile must use the real gate data sizes
        (20000 activities, 10000 contributions)."""
        source = PRODUCT_DRIVER_PATH.read_text(encoding="utf-8")
        full_match = re.search(
            r'"full":\s*\{[^}]*"activity_count":\s*(\d+)[^}]*\}',
            source,
        )
        assert full_match is not None, "full profile not found"
        full_activity = int(full_match.group(1))
        assert full_activity == 20000, (
            f"full profile activity_count={full_activity} must be 20000 "
            f"for the real performance gate"
        )
        full_contrib_match = re.search(
            r'"full":\s*\{[^}]*"contribution_count":\s*(\d+)[^}]*\}',
            source,
        )
        assert full_contrib_match is not None
        full_contrib = int(full_contrib_match.group(1))
        assert full_contrib == 10000, (
            f"full profile contribution_count={full_contrib} must be 10000"
        )

    def test_webview_driver_defines_smoke_and_full(self) -> None:
        source = WEBVIEW_DRIVER_PATH.read_text(encoding="utf-8")
        assert '"smoke"' in source
        assert '"full"' in source
        assert "_PROFILES" in source

    def test_webview_driver_smoke_uses_small_data(self) -> None:
        source = WEBVIEW_DRIVER_PATH.read_text(encoding="utf-8")
        smoke_match = re.search(
            r'"smoke":\s*\{[^}]*"activity_count":\s*(\d+)[^}]*\}',
            source,
        )
        assert smoke_match is not None, "smoke profile not found"
        smoke_activity = int(smoke_match.group(1))
        assert smoke_activity <= 1000, (
            f"smoke profile activity_count={smoke_activity} exceeds 1000"
        )

    def test_webview_driver_full_uses_real_data(self) -> None:
        source = WEBVIEW_DRIVER_PATH.read_text(encoding="utf-8")
        full_match = re.search(
            r'"full":\s*\{[^}]*"activity_count":\s*(\d+)[^}]*\}',
            source,
        )
        assert full_match is not None, "full profile not found"
        full_activity = int(full_match.group(1))
        assert full_activity == 20000, (
            f"full profile activity_count={full_activity} must be 20000"
        )

    def test_product_driver_accepts_profile_arg(self) -> None:
        """The driver's argparse must accept ``--profile`` with
        ``smoke`` and ``full`` choices."""
        source = PRODUCT_DRIVER_PATH.read_text(encoding="utf-8")
        assert '"--profile"' in source
        assert "choices=(\"smoke\", \"full\")" in source

    def test_webview_driver_accepts_profile_arg(self) -> None:
        source = WEBVIEW_DRIVER_PATH.read_text(encoding="utf-8")
        assert '"--profile"' in source
        assert "choices=(\"smoke\", \"full\")" in source


# ---------------------------------------------------------------------------
# Workflow does not weaken the merge gate
# ---------------------------------------------------------------------------

class TestWorkflowDoesNotWeakenMergeGate:
    """The workflow must not weaken the merge gate by lowering
    tolerance, deleting baseline comparison, deleting detail metrics,
    or marking failing steps as continue-on-error."""

    def test_no_continue_on_error_anywhere(self) -> None:
        """``continue-on-error: true`` is only allowed on driver steps
        (id: baseline_driver, head_driver). Gate/comparison steps must
        NOT use it, and job-level continue-on-error is prohibited."""
        for yml_path in (PERF_VALIDATION_YML, STANDARD_TIMING_YML):
            source = yml_path.read_text(encoding="utf-8")
            steps_with_coe = _find_steps_with_continue_on_error(source)
            for step in steps_with_coe:
                if step["value"] != "true":
                    continue
                assert step["id"] in _ALLOWED_CONTINUE_ON_ERROR_STEP_IDS, (
                    f"{yml_path.name}: continue-on-error: true is only "
                    f"allowed on driver steps (id: baseline_driver or "
                    f"head_driver), but found on step "
                    f"'{step.get('name', step.get('id'))}'"
                )
            # Job-level continue-on-error (4-space indent) is prohibited.
            job_level_coe = re.findall(
                r"^    continue-on-error:", source, re.MULTILINE
            )
            assert len(job_level_coe) == 0, (
                f"{yml_path.name}: continue-on-error at job level is "
                f"prohibited"
            )

    def test_no_lowered_tolerance_default(self) -> None:
        """The default tolerance must remain at 10% — lowering the
        gate to pass is prohibited."""
        source = PERF_VALIDATION_YML.read_text(encoding="utf-8")
        default_match = re.search(
            r'benchmark_comparison_tolerance_pct.*?default:\s*"(\d+)"',
            source,
            re.DOTALL,
        )
        assert default_match is not None
        default_tolerance = int(default_match.group(1))
        assert default_tolerance == 10, (
            f"benchmark_comparison_tolerance_pct default="
            f"{default_tolerance} must be 10 — lowering the gate to "
            f"pass is prohibited"
        )

    def test_no_baseline_comparison_removal(self) -> None:
        """The workflow must still run the baseline driver and the
        comparison step — deleting baseline comparison is prohibited."""
        source = PERF_VALIDATION_YML.read_text(encoding="utf-8")
        assert (
            "baseline benchmark driver" in source
            or "baseline WebView driver" in source
            or "baseline_driver" in source
        ), (
            "workflow must retain a baseline driver invocation — "
            "deleting baseline comparison is prohibited"
        )
        assert "benchmark_comparison" in source
        assert "webview_comparison" in source

    def test_no_detail_metric_removal(self) -> None:
        """The WebView comparison must still gate on all four detail
        metrics — deleting detail metrics is prohibited."""
        comparison_source = (ROOT / "scripts" / "webview_comparison.py").read_text(
            encoding="utf-8"
        )
        assert "cold_timeline_seconds" in comparison_source
        assert "warm_timeline_seconds" in comparison_source
        assert "detail_payload_seconds" in comparison_source
        assert "detail_total_seconds" in comparison_source

    def test_no_data_scale_reduction_in_workflow(self) -> None:
        """The workflow must NOT reduce data scale to pass — it must
        run the full 20k/10k data sizes via ``--profile full``."""
        source = PERF_VALIDATION_YML.read_text(encoding="utf-8")
        driver_invocations = re.findall(
            r"python(?:\s+-u)?\s+scripts/(?:ci/product_benchmark_driver|webview_render_perf)\.py",
            source,
        )
        assert len(driver_invocations) >= 4, (
            f"expected at least 4 driver invocations in workflow, "
            f"found {len(driver_invocations)}"
        )
        full_count = source.count("--profile full")
        assert full_count >= 4, (
            f"expected at least 4 '--profile full' invocations, "
            f"found {full_count} — the workflow must NOT reduce data "
            f"scale to pass"
        )


# ---------------------------------------------------------------------------
# Workflow uploads artifacts for diagnostics
# ---------------------------------------------------------------------------

class TestWorkflowUploadsArtifacts:
    """Both workflows must upload artifacts so reviewers can audit
    the baseline/HEAD results and the comparison report."""

    def test_performance_validation_uploads_artifacts(self) -> None:
        source = PERF_VALIDATION_YML.read_text(encoding="utf-8")
        assert "actions/upload-artifact" in source
        assert "if-no-files-found: error" in source

    def test_standard_timing_uploads_artifacts(self) -> None:
        source = STANDARD_TIMING_YML.read_text(encoding="utf-8")
        assert "actions/upload-artifact" in source

    def test_artifact_retention_is_bounded(self) -> None:
        """Artifact retention must be bounded so old runs do not
        accumulate indefinitely."""
        perf_source = PERF_VALIDATION_YML.read_text(encoding="utf-8")
        timing_source = STANDARD_TIMING_YML.read_text(encoding="utf-8")
        perf_retention = re.findall(
            r"retention-days:\s*(\d+)", perf_source
        )
        timing_retention = re.findall(
            r"retention-days:\s*(\d+)", timing_source
        )
        assert perf_retention, (
            "performance-validation.yml must specify retention-days"
        )
        assert timing_retention, (
            "standard-timing-validation.yml must specify retention-days"
        )
        for days_str in perf_retention + timing_retention:
            days = int(days_str)
            assert days <= 30, (
                f"retention-days={days} exceeds 30 — old artifacts "
                f"should not accumulate indefinitely"
            )


# ---------------------------------------------------------------------------
# Product benchmark matrix structure
# ---------------------------------------------------------------------------

class TestProductBenchmarkMatrix:
    """The ``product-benchmark`` job must use a matrix strategy with
    two cross-revision latency scenarios, each with its own timeout."""

    def test_product_benchmark_uses_matrix(self) -> None:
        source = PERF_VALIDATION_YML.read_text(encoding="utf-8")
        product_section = _extract_job_section(source, "product-benchmark")
        assert product_section is not None, (
            "product-benchmark job not found"
        )
        assert "strategy:" in product_section, (
            "product-benchmark job must use a matrix strategy"
        )
        assert "matrix:" in product_section, (
            "product-benchmark job must define a matrix"
        )

    def test_matrix_fail_fast_false(self) -> None:
        source = PERF_VALIDATION_YML.read_text(encoding="utf-8")
        product_section = _extract_job_section(source, "product-benchmark")
        assert product_section is not None, (
            "product-benchmark job not found"
        )
        assert "fail-fast: false" in product_section, (
            "product-benchmark matrix must use fail-fast: false so one "
            "scenario's failure does not cancel the other"
        )

    def test_matrix_has_two_scenarios(self) -> None:
        source = PERF_VALIDATION_YML.read_text(encoding="utf-8")
        product_section = _extract_job_section(source, "product-benchmark")
        assert product_section is not None, (
            "product-benchmark job not found"
        )
        assert "20k_activities" in product_section, (
            "product-benchmark matrix must include the 20k_activities scenario"
        )
        assert "10k_contributions" in product_section, (
            "product-benchmark matrix must include the 10k_contributions scenario"
        )

    def test_matrix_scenarios_are_cross_revision_latency_only(self) -> None:
        """The product-benchmark matrix must only include cross-revision
        latency scenarios — NOT peak_memory or compact_memory."""
        source = PERF_VALIDATION_YML.read_text(encoding="utf-8")
        product_section = _extract_job_section(source, "product-benchmark")
        assert product_section is not None, (
            "product-benchmark job not found"
        )
        assert "scenario: peak_memory" not in product_section, (
            "product-benchmark matrix must NOT include a peak_memory "
            "scenario — peak_memory is not a cross-revision latency gate"
        )
        assert "scenario: compact_memory" not in product_section, (
            "product-benchmark matrix must NOT include a compact_memory "
            "scenario — compact-memory is a HEAD-only job"
        )

    def test_matrix_has_per_scenario_timeout(self) -> None:
        """Each matrix item must specify its own ``timeout_minutes`` so
        scenarios with different data scales have appropriate ceilings."""
        source = PERF_VALIDATION_YML.read_text(encoding="utf-8")
        product_section = _extract_job_section(source, "product-benchmark")
        assert product_section is not None, (
            "product-benchmark job not found"
        )
        timeout_matches = re.findall(
            r"timeout_minutes:\s*(\d+)", product_section
        )
        assert len(timeout_matches) >= 2, (
            f"expected at least 2 per-scenario timeout_minutes values, "
            f"found {len(timeout_matches)}"
        )
        for timeout_str in timeout_matches:
            timeout = int(timeout_str)
            assert timeout > 0, (
                f"timeout_minutes={timeout} must be a positive integer"
            )


# ---------------------------------------------------------------------------
# HEAD-only compact-storage memory gate job
# ---------------------------------------------------------------------------

class TestCompactMemoryJob:
    """The ``compact-memory`` job is a HEAD-only compact-storage memory
    gate at 5000 entries. It is NOT a baseline-vs-HEAD comparison."""

    def test_compact_memory_job_exists(self) -> None:
        source = PERF_VALIDATION_YML.read_text(encoding="utf-8")
        compact_section = _extract_job_section(source, "compact-memory")
        assert compact_section is not None, (
            "compact-memory job must exist in performance-validation.yml"
        )

    def test_compact_memory_job_is_head_only(self) -> None:
        """The compact-memory job must NOT create a baseline worktree
        or resolve a baseline revision — it is HEAD-only."""
        source = PERF_VALIDATION_YML.read_text(encoding="utf-8")
        compact_section = _extract_job_section(source, "compact-memory")
        assert compact_section is not None, (
            "compact-memory job not found"
        )
        assert "baseline-worktree" not in compact_section, (
            "compact-memory job must NOT create a baseline worktree — "
            "it is HEAD-only"
        )
        assert "baseline_sha" not in compact_section, (
            "compact-memory job must NOT resolve a baseline revision — "
            "it is HEAD-only"
        )

    def test_compact_memory_uses_compact_memory_driver(self) -> None:
        source = PERF_VALIDATION_YML.read_text(encoding="utf-8")
        compact_section = _extract_job_section(source, "compact-memory")
        assert compact_section is not None, (
            "compact-memory job not found"
        )
        assert "scripts/ci/compact_memory_driver.py" in compact_section, (
            "compact-memory job must invoke scripts/ci/compact_memory_driver.py"
        )

    def test_compact_memory_size_is_5000(self) -> None:
        """The compact-memory gate must target 5000 entries (either in
        the workflow-state.json or the driver default)."""
        source = PERF_VALIDATION_YML.read_text(encoding="utf-8")
        assert "5000" in source, (
            "compact-memory job must reference size 5000 — the gate "
            "target is 5000 entries"
        )

    def test_compact_memory_no_baseline_comparison(self) -> None:
        """The compact-memory job must NOT invoke
        ``benchmark_comparison.py`` or any baseline driver — it is
        a HEAD-only structural acceptance gate."""
        source = PERF_VALIDATION_YML.read_text(encoding="utf-8")
        compact_section = _extract_job_section(source, "compact-memory")
        assert compact_section is not None, (
            "compact-memory job not found"
        )
        assert "benchmark_comparison.py" not in compact_section, (
            "compact-memory job must NOT invoke benchmark_comparison.py — "
            "it is not a baseline-vs-HEAD comparison"
        )
        assert "baseline_driver" not in compact_section, (
            "compact-memory job must NOT have a baseline_driver step — "
            "it is HEAD-only"
        )

    def test_compact_memory_has_artifact_upload(self) -> None:
        """The compact-memory job must upload an artifact with
        ``if: always()`` and ``if-no-files-found: error`` so the
        memory gate result is always auditable."""
        source = PERF_VALIDATION_YML.read_text(encoding="utf-8")
        compact_section = _extract_job_section(source, "compact-memory")
        assert compact_section is not None, (
            "compact-memory job not found"
        )
        assert "actions/upload-artifact" in compact_section, (
            "compact-memory job must upload an artifact"
        )
        assert "if: always()" in compact_section, (
            "compact-memory artifact upload must use if: always() so the "
            "artifact is uploaded even on gate failure"
        )
        assert "if-no-files-found: error" in compact_section, (
            "compact-memory artifact upload must use if-no-files-found: error"
        )


# ---------------------------------------------------------------------------
# Scenario and workflow-state structure
# ---------------------------------------------------------------------------

class TestScenarioAndWorkflowState:
    """The workflow must pass ``--scenario`` to the product driver,
    pre-create ``workflow-state.json``, use ``python -u`` for
    unbuffered output, and must NOT invoke a serial controller."""

    def test_product_driver_invocations_include_scenario(self) -> None:
        """The product driver invocations must include ``--scenario``
        so each matrix job runs exactly one scenario."""
        source = PERF_VALIDATION_YML.read_text(encoding="utf-8")
        product_section = _extract_job_section(source, "product-benchmark")
        assert product_section is not None, (
            "product-benchmark job not found"
        )
        assert "--scenario ${{ matrix.scenario }}" in product_section, (
            "product driver invocations must include "
            "--scenario ${{ matrix.scenario }}"
        )

    def test_workflow_state_pre_created(self) -> None:
        """Each job must pre-create ``workflow-state.json`` in the
        results directory before any driver runs, so
        ``upload-artifact`` with ``if-no-files-found: error`` always
        has at least one file."""
        source = PERF_VALIDATION_YML.read_text(encoding="utf-8")
        assert "workflow-state.json" in source, (
            "workflow must pre-create workflow-state.json before driver "
            "execution so upload-artifact always has at least one file"
        )

    def test_python_unbuffered(self) -> None:
        """All Python driver invocations must use ``python -u``
        (unbuffered output) so driver progress is visible in job logs
        without buffering delays."""
        source = PERF_VALIDATION_YML.read_text(encoding="utf-8")
        bare_python_pattern = re.compile(r"python\s+scripts/")
        bare_matches = bare_python_pattern.findall(source)
        assert len(bare_matches) == 0, (
            f"found {len(bare_matches)} Python invocations without -u "
            f"(unbuffered) flag — all driver invocations must use "
            f"'python -u'"
        )
        unbuffered_count = source.count("python -u")
        assert unbuffered_count >= 4, (
            f"expected at least 4 'python -u' invocations, found "
            f"{unbuffered_count} — all driver invocations must use "
            f"unbuffered output"
        )

    def test_no_product_controller_invocation(self) -> None:
        """The workflow must NOT invoke a controller that runs all
        scenarios serially — the matrix strategy runs each scenario
        as an independent job."""
        source = PERF_VALIDATION_YML.read_text(encoding="utf-8")
        assert "--scenario all" not in source, (
            "workflow must not invoke a controller that runs all "
            "scenarios serially — use the matrix strategy instead"
        )
        assert "benchmark_controller" not in source, (
            "workflow must not invoke a benchmark controller script — "
            "use the matrix strategy instead"
        )


# ---------------------------------------------------------------------------
# Standard CI excludes benchmark tests
# ---------------------------------------------------------------------------

class TestStandardCIExcludesBenchmark:
    """The Standard CI workflow (``_validation.yml``) must exclude
    benchmark tests via ``-m "not benchmark"`` so the standard CI run
    does not execute the expensive performance-gate benchmarks."""

    def test_standard_ci_file_exists(self) -> None:
        assert STANDARD_CI_YML.is_file(), (
            "_validation.yml must exist"
        )

    def test_standard_ci_excludes_benchmark(self) -> None:
        source = STANDARD_CI_YML.read_text(encoding="utf-8")
        assert "not benchmark" in source, (
            "_validation.yml must use '-m \"not benchmark\"' to exclude "
            "benchmark tests from the standard CI run"
        )
