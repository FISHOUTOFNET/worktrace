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
        'id="page-date-context"',
        'id="previous-day"',
        'id="next-day"',
        'id="page-work-date" placeholder="请选择日期"',
        'form id="basic"',
        'class="ant-form-item"',
        'name="workhours/matter/selector"',
        'class="ant-select-selector"',
        'class="ant-select-selection-wrap"',
        'class="ant-select-selection-search"',
        'id="basic_caseId"',
        'role="combobox"',
        'aria-controls="basic_caseId_list"',
        'aria-owns="basic_caseId_list"',
        'class="ant-select-selection-item"',
        'popup.id = "basic_caseId_list"',
        'popup.setAttribute("role", "listbox")',
        'option.setAttribute("role", "option")',
        'option.setAttribute("aria-selected"',
        'id="basic_hoursWorked"',
        'id="basic_narrative"',
        'queueMicrotask(function () { renderPopup(query); })',
        'if (config.durationAccepted) state.duration = proposed',
        'if (config.narrativeAccepted) state.narrative = proposed',
        "TEST MATTER A",
    ):
        assert fragment in source
    assert "../../../worktrace/integrations/fd_work/fd_work_adapter.js" in source
    assert "data-worktrace-fdwork-hidden" not in source
    assert 'id="basic_workDate"' not in source
    assert 'document.body.appendChild(popup)' in source
    assert 'renderForm();' in source
    assert 'check("unrelated_dom_churn_not_observed"' in source
    assert 'check("complete_four_field_readback"' in source
    assert 'check("never_auto_saves_or_submits"' in source
    assert "worktrace-result" in source


def test_edge_runner_is_hard_failure_and_windows_node_scope_runs_it() -> None:
    runner = RUNNER.read_text(encoding="utf-8")
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert 'fail("edge_unavailable"' in runner
    assert "process.exitCode = 1" in runner
    assert "worktrace-fdwork-edge-" in runner
    assert "--allow-file-access-from-files" in runner
    assert "--remote-debugging-port=0" in runner
    assert "DevToolsActivePort" in runner
    assert '"Runtime.evaluate"' in runner
    assert "MutationObserver" in runner
    assert "--dump-dom" not in runner
    assert "existsSync(resolvedProfile)" in runner
    assert "skip" not in runner.casefold()
    assert "node scripts/run_fd_work_edge_fixture.mjs" in workflow
