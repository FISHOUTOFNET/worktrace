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
    """Each run writes to its own ``results/pair-N/<baseline|head>/``,
    ``results/head-only/run-N/``, or ``results/head-full/run-N/``
    directory.  The workflow must NOT delete the shared parent.
    """
    workflow = TIMING_WORKFLOW.read_text(encoding="utf-8")
    assert "results" in workflow
    # Interleaved paired execution uses pair-N/baseline and pair-N/head.
    assert r"pair-1\baseline" in workflow
    assert r"pair-1\head" in workflow
    # HEAD-only and full-suite runs use run-N subdirectories.
    assert r"head-only\run-" in workflow
    assert r"head-full\run-" in workflow
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

    The layered gates (enforced by ``scripts/timing_comparison.py`` and
    surfaced via ``exit 1`` in the workflow) are:
      - common-suite paired median regression <= 10%
      - HEAD full-suite median <= 240s
      - test count not reduced, no failures, dependency match

    A workflow that only prints booleans and never exits non-zero is a
    contract violation.
    """
    workflow = TIMING_WORKFLOW.read_text(encoding="utf-8")
    assert "240" in workflow
    assert "common_regression_threshold" in workflow
    assert "10" in workflow
    assert "test_count" in workflow
    assert "all_gates_passed" in workflow
    assert "exit 1" in workflow
    assert "timing_validation=FAILED" in workflow
    # The gate enforcement is delegated to timing_comparison.py, which
    # must be invoked from the workflow and its exit code respected.
    assert "scripts/timing_comparison.py" in workflow
    assert "timing_validation=PASSED" in workflow


def test_timing_workflow_any_pytest_failure_fails_job() -> None:
    """Any pytest failure (non-zero exit, missing JUnit, or non-zero
    failure/error counts) must mark the run as ``valid=false`` and the
    final gate check must fail the job.

    The per-run validity is computed in PowerShell (``$valid``), written
    to ``run-result.json``, and the overall gate enforcement is delegated
    to ``scripts/timing_comparison.py`` which reads those JSON files and
    exits non-zero if any run is invalid or any gate fails.
    """
    workflow = TIMING_WORKFLOW.read_text(encoding="utf-8")
    assert "$exitCode -eq 0" in workflow
    assert "$failureCount -eq 0" in workflow
    assert "$errorCount -eq 0" in workflow
    assert "$junitPresent" in workflow
    assert "$valid =" in workflow or "$valid=" in workflow
    assert "valid" in workflow
    # The comparison script reads run-result.json and enforces gates.
    assert "scripts/timing_comparison.py" in workflow
    assert "all_gates_passed" in workflow


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
    Standard CI, including ``-m not benchmark`` and ``--cache-clear``.

    The marker expression is tokenised as two separate array elements
    (``"-m"``, ``"not benchmark"``) so PowerShell passes them as two
    independent arguments.  The previous single-string form
    ``'-m "not benchmark"'`` was passed as one argument and silently
    dropped by pytest.
    """
    workflow = TIMING_WORKFLOW.read_text(encoding="utf-8")
    assert '"-m", "not benchmark"' in workflow
    assert "--cache-clear" in workflow
    assert "--timeout=90" in workflow
    assert "--junitxml=" in workflow


def test_timing_workflow_uses_head_owned_external_harness() -> None:
    """The timing and selection plugins must load from a HEAD-owned
    harness directory via PYTHONPATH, NOT from the worktree under test.

    This guarantees baseline and HEAD run against the exact same plugin
    implementation, so the measurement instrument is not the variable
    being compared.  The harness directory is populated from the HEAD
    workspace's ``.ci-harness/`` and ``scripts/`` directories.
    """
    workflow = TIMING_WORKFLOW.read_text(encoding="utf-8")
    assert "harness_dir" in workflow
    assert "harness" in workflow
    assert ".ci-harness" in workflow
    assert "pytest_timing_plugin.py" in workflow
    assert "pytest_select_from_file.py" in workflow
    # PYTHONPATH must be set so the plugins load from the harness dir.
    assert "PYTHONPATH" in workflow
    assert "$harnessDir" in workflow


def test_timing_workflow_loads_timing_plugin_via_dash_p() -> None:
    """The timing plugin must be loaded via ``-p pytest_timing_plugin``
    so per-test timing is recorded with the exact ``report.nodeid``.
    """
    workflow = TIMING_WORKFLOW.read_text(encoding="utf-8")
    assert '"-p", "pytest_timing_plugin"' in workflow
    assert '"--timing-json"' in workflow
    assert "WORKTRACE_TIMING_REVISION" in workflow


def test_timing_workflow_uses_explicit_prepare_and_compare_modes() -> None:
    """The workflow must use ``--write-selection-only`` (prepare) and
    ``--compare`` (compare) as explicit modes.  Prepare runs before any
    pytest run and exits 0 on success — it does NOT read timing/JUnit
    results.  Compare runs after all pytest runs and enforces the gates.
    Neither mode relies on exception side effects.
    """
    workflow = TIMING_WORKFLOW.read_text(encoding="utf-8")
    assert "--write-selection-only" in workflow
    assert "--compare" in workflow
    # Prepare must fail-closed on non-zero exit.
    assert "selection prepare failed" in workflow


def test_timing_workflow_does_not_copy_plugin_into_worktrees() -> None:
    """The workflow must NOT copy the selection plugin into the worktrees'
    ``scripts/`` directories.  Both plugins load from the HEAD-owned
    harness directory, so the worktree under test never needs to contain
    the plugin source.
    """
    workflow = TIMING_WORKFLOW.read_text(encoding="utf-8")
    assert "Copy selection plugin into worktrees" not in workflow
    # The old step copied pytest_select_from_file.py into the worktree's
    # scripts/ directory.  The new harness step copies it into the
    # harness dir instead.
    assert "Copy-Item -Force -LiteralPath $plugin" not in workflow


def test_timing_workflow_records_exact_nodeid_timing() -> None:
    """Each run must produce a ``timing.json`` with per-test timing
    keyed by the exact pytest ``report.nodeid``.  The comparison layer
    reads this JSON and never infers node IDs from JUnit classname/name
    pairs (which are ambiguous for parametrised tests).
    """
    workflow = TIMING_WORKFLOW.read_text(encoding="utf-8")
    assert "timing.json" in workflow
    assert "timing_present" in workflow
    assert "selected_count" in workflow


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


def test_timing_workflow_uses_interleaved_paired_execution() -> None:
    """Baseline and HEAD runs must be interleaved (not baseline×3 then
    HEAD×3) so runner fatigue does not systematically favour one revision.

    The deterministic order is:
      Pair 1: baseline → HEAD
      Pair 2: HEAD → baseline
      Pair 3: baseline → HEAD
    """
    workflow = TIMING_WORKFLOW.read_text(encoding="utf-8")
    # The execution order manifest must be written and the pairs must
    # alternate which revision runs first.
    assert "execution-order.json" in workflow
    assert "pair-1" in workflow
    assert "pair-2" in workflow
    assert "pair-3" in workflow
    # Pair 1 starts with baseline; pair 2 starts with HEAD.
    assert "pair-1/baseline" in workflow
    assert "pair-2/head" in workflow


def test_timing_workflow_implements_three_tier_measurement() -> None:
    """The workflow must measure three separate tiers:
      1. Common-suite (tests present in both baseline and HEAD)
      2. HEAD-only (tests added in HEAD)
      3. HEAD full suite (complete Standard CI pytest)

    The selection plugin must be used to run only the common or HEAD-only
    subsets without passing thousands of node IDs on the command line.
    """
    workflow = TIMING_WORKFLOW.read_text(encoding="utf-8")
    assert "head-only" in workflow
    assert "head-full" in workflow
    assert "WORKTRACE_SELECT_FILE" in workflow
    assert "pytest_select_from_file" in workflow
    assert "common.txt" in workflow
    assert "head-only.txt" in workflow
    # Collection must be performed on both revisions to compute the sets.
    assert "collect-only" in workflow
    assert "baseline-node-ids.txt" in workflow
    assert "head-node-ids.txt" in workflow
