"""Static contract tests for the validation infrastructure.

Guards the Standard CI and Standard timing validation workflows against
regressions in their declared contracts.  Asserts on workflow YAML so a
future edit cannot silently re-introduce a success-state timing artifact
into Standard CI, collapse baseline/HEAD timing directories, weaken the
timing acceptance gates, or remove the PR-label trigger that lets the
timing workflow run before merge.

The frozen CI contract for ``_validation.yml`` is enforced separately in
``tests/test_pytest_diagnostics.py``; WebView render harness and
Performance Validation WebView job contracts are enforced in
``tests/test_webview_render_harness_contract.py``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.contract, pytest.mark.parallel_safe]

ROOT = Path(__file__).resolve().parents[1]
VALIDATION_WORKFLOW = ROOT / ".github" / "workflows" / "_validation.yml"
TIMING_WORKFLOW = ROOT / ".github" / "workflows" / "standard-timing-validation.yml"


def test_standard_ci_keeps_benchmark_exclusion() -> None:
    """Standard CI must keep ``-m "not benchmark"`` so large benchmarks
    do not gate pull requests while performance correctness tests remain.
    """
    workflow = VALIDATION_WORKFLOW.read_text(encoding="utf-8")
    assert '-m "not benchmark"' in workflow


def test_standard_ci_does_not_generate_success_state_timing_artifact() -> None:
    """Standard CI must NOT generate or upload a success-state timing
    summary artifact (reserved for performance and timing workflows).
    """
    workflow = VALIDATION_WORKFLOW.read_text(encoding="utf-8")
    assert "name: Generate pytest timing summary" not in workflow
    assert "name: Upload pytest timing summary" not in workflow
    assert "pytest-timing-summary" not in workflow
    assert "scripts/pytest_timing_summary.py" not in workflow


def test_standard_ci_still_generates_failure_diagnostics() -> None:
    """Standard CI must keep the failure-diagnostics artifact contract.

    A failure must produce a canonical ``diagnostics.json`` and upload it
    so the job log never has to surface failure details inline.
    """
    workflow = VALIDATION_WORKFLOW.read_text(encoding="utf-8")
    assert "name: Generate diagnostic artifact" in workflow
    assert "name: Upload diagnostic artifact" in workflow
    assert 'if: failure()' in workflow
    assert "if-no-files-found: error" in workflow
    assert "continue-on-error: true" in workflow


def test_timing_workflow_uses_git_worktree_for_isolation() -> None:
    """Baseline and HEAD must run in independent git worktrees so they
    do not pollute each other's ``__pycache__`` or untracked files.
    """
    workflow = TIMING_WORKFLOW.read_text(encoding="utf-8")
    assert "git worktree add" in workflow
    assert "baseline-worktree" in workflow
    assert "head-worktree" in workflow


def test_timing_workflow_uses_independent_result_directories() -> None:
    """Each run writes to its own ``results/<baseline|head>/run-N/``
    directory.  The workflow must NOT delete the shared parent.
    """
    workflow = TIMING_WORKFLOW.read_text(encoding="utf-8")
    assert "results" in workflow
    assert r"baseline\run-" in workflow
    assert r"head\run-" in workflow
    assert "Remove-Item -Recurse test-results" not in workflow
    assert "Remove-Item -Recurse -Force $resultsDir" not in workflow


def test_timing_workflow_writes_run_result_json_per_run() -> None:
    """Every run must persist a ``run-result.json`` so the comparison
    step can read structured data instead of relying on PowerShell arrays.
    """
    workflow = TIMING_WORKFLOW.read_text(encoding="utf-8")
    assert "run-result.json" in workflow
    assert "elapsed_seconds" in workflow
    assert "exit_code" in workflow
    assert "test_count" in workflow
    assert "failure_count" in workflow
    assert "error_count" in workflow
    assert "skipped_count" in workflow
    assert "junit_present" in workflow
    assert "valid" in workflow


def test_timing_workflow_enforces_real_acceptance_gates() -> None:
    """Acceptance gates must actually affect the job exit status.

    Gates (``exit 1`` on failure): HEAD median <= 240s, improvement >=
    20%, test count not reduced, no failures, no unexplained skipped
    growth, dependency match.  A workflow that only prints booleans and
    never exits non-zero is a contract violation.
    """
    workflow = TIMING_WORKFLOW.read_text(encoding="utf-8")
    assert "head_median" in workflow
    assert "240" in workflow
    assert "pctImprovement" in workflow
    assert "20" in workflow
    assert "test_count" in workflow
    assert "all_gates_passed" in workflow
    assert "exit 1" in workflow
    assert "timing_validation=FAILED" in workflow


def test_timing_workflow_any_pytest_failure_fails_job() -> None:
    """Any pytest failure (non-zero exit, missing JUnit, or non-zero
    failure/error counts) must mark the run as ``valid=false`` and the
    final gate check must fail the job.
    """
    workflow = TIMING_WORKFLOW.read_text(encoding="utf-8")
    assert "$exitCode -eq 0" in workflow
    assert "$failureCount -eq 0" in workflow
    assert "$errorCount -eq 0" in workflow
    assert "$junitPresent" in workflow
    assert "$valid =" in workflow or "$valid=" in workflow
    assert "allValid" in workflow
    assert "$allGatesPassed" in workflow


def test_timing_workflow_head_cleanup_does_not_delete_baseline() -> None:
    """HEAD cleanup must be scoped to the HEAD result subtree only.

    Guards against a regression where ``Remove-Item -Recurse`` is called
    on the shared ``results`` parent, deleting baseline data.
    """
    workflow = TIMING_WORKFLOW.read_text(encoding="utf-8")
    forbidden_parent_deletions = (
        'Remove-Item -Recurse -Force $resultsDir',
        'Remove-Item -Recurse $resultsDir',
        'Remove-Item -Recurse -Force "results"',
        'Remove-Item -Recurse "results"',
    )
    for forbidden in forbidden_parent_deletions:
        assert forbidden not in workflow, f"forbidden parent deletion: {forbidden}"


def test_timing_workflow_supports_pr_label_trigger() -> None:
    """The workflow must be triggerable before merge via a PR label so
    validation is not deferred until after merge.  Uses ``pull_request``
    (not ``pull_request_target``) so the workflow runs on the PR branch's
    own code.
    """
    workflow = TIMING_WORKFLOW.read_text(encoding="utf-8")
    assert "pull_request:" in workflow
    assert "types: [labeled]" in workflow
    assert "run-standard-timing" in workflow
    lines = workflow.splitlines()
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("pull_request_target:"):
            pytest.fail("timing workflow must not use pull_request_target trigger")
    assert "workflow_dispatch:" in workflow


def test_timing_workflow_uses_same_pytest_contract_as_standard_ci() -> None:
    """Both baseline and HEAD must use the same pytest arguments as
    Standard CI, including ``-m "not benchmark"`` and ``--cache-clear``.
    """
    workflow = TIMING_WORKFLOW.read_text(encoding="utf-8")
    assert '-m "not benchmark"' in workflow
    assert "--cache-clear" in workflow
    assert "--timeout=90" in workflow
    assert "--junitxml=" in workflow


def test_timing_workflow_checks_dependency_consistency() -> None:
    """If baseline and HEAD have different requirements files, the
    comparison must record ``dependency_mismatch`` and fail unless the
    operator explicitly allows it.
    """
    workflow = TIMING_WORKFLOW.read_text(encoding="utf-8")
    assert "requirements.txt" in workflow
    assert "requirements-dev.txt" in workflow
    assert "Get-FileHash" in workflow
    assert "dependency_match" in workflow
    assert "allow_dependency_changes" in workflow


def test_timing_workflow_uploads_artifact_always() -> None:
    """The comparison artifact must be uploaded even on failure so the
    diagnostic data is preserved.
    """
    workflow = TIMING_WORKFLOW.read_text(encoding="utf-8")
    assert "Upload timing comparison artifact" in workflow
    assert "if: always()" in workflow
    assert "standard-timing-validation-" in workflow
