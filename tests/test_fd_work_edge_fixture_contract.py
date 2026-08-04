from __future__ import annotations

from pathlib import Path

import pytest


pytestmark = [pytest.mark.unit, pytest.mark.contract, pytest.mark.parallel_safe]

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "fd_work" / "anonymous_work_shell.html"
RUNNER = ROOT / "scripts" / "run_fd_work_edge_fixture.mjs"
WORKFLOW = ROOT / ".github" / "workflows" / "_validation.yml"


def test_anonymous_fixture_preserves_minimum_real_ant_contract() -> None:
    source = FIXTURE.read_text(encoding="utf-8")

    for fragment in (
        'form id="basic"',
        'class="ant-form-item"',
        'class="ant-select" name="workhours/matter/selector"',
        'class="ant-select-selector"',
        'class="ant-select-selection-wrap"',
        'class="ant-select-selection-search"',
        'id="basic_caseId" role="combobox"',
        'aria-controls="case-listbox"',
        'class="ant-select-selection-item"',
        'role="listbox"',
        'role="option"',
        'aria-selected=',
        'id="basic_hoursWorked"',
        'id="basic_narrative"',
        'id="basic_workDate"',
        "TEST MATTER A",
    ):
        assert fragment in source
    assert "../../../worktrace/integrations/fd_work/fd_work_adapter.js" in source
    assert "data-worktrace-fdwork-hidden" in source
    assert "worktrace-result" in source


def test_edge_runner_is_hard_failure_and_windows_node_scope_runs_it() -> None:
    runner = RUNNER.read_text(encoding="utf-8")
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert 'fail("edge_unavailable"' in runner
    assert "process.exitCode = 1" in runner
    assert "worktrace-fdwork-edge-" in runner
    assert "--allow-file-access-from-files" in runner
    assert "--dump-dom" in runner
    assert "status: resultCaptured ? 0 : status" in runner
    assert "skip" not in runner.casefold()
    assert "node scripts/run_fd_work_edge_fixture.mjs" in workflow
