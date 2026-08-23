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
        'popup.className = "ant-select-dropdown"',
        'accessibilityList.id = "basic_caseId_list"',
        'accessibilityList.setAttribute("role", "listbox")',
        'accessibilityList.style.cssText = "height:0;width:0;overflow:hidden"',
        'option.className = interactive ? "ant-select-item ant-select-item-option" : ""',
        'option.setAttribute("role", "option")',
        'option.setAttribute("aria-selected"',
        'id="basic_hoursWorked"',
        'id="basic_narrative"',
        'requestAnimationFrame(next)',
        'queueMicrotask(next)',
        'if (config.durationAccepted) state.duration = proposed',
        'if (config.narrativeAccepted) state.narrative = proposed',
        "TEST MATTER A",
        "#26IP0165 IPDD_Miragene",
        'case_label: canonicalLabel, case_query: "26IP0165"',
    ):
        assert fragment in source
    assert "../../../worktrace/integrations/fd_work/fd_work_adapter.js" in source
    assert "data-worktrace-fdwork-hidden" not in source
    assert 'id="basic_workDate"' not in source
    assert 'document.body.appendChild(popup)' in source
    assert 'renderForm();' in source
    assert 'check("unrelated_dom_churn_not_observed"' in source
    assert 'check("complete_four_field_readback"' in source
    assert 'check("canonical_case_query_written"' in source
    assert 'check("canonical_query_exact_full_label_selected"' in source
    assert 'check("delayed_results_complete_actual_fill"' in source
    assert 'check("delayed_results_were_awaited_before_commit"' in source
    assert 'check("delayed_fill_saves_once_without_form_submit"' in source
    assert 'check("auto_save_uses_button_without_form_submit_or_private_api"' in source
    assert 'check("success_releases_fill_mode"' in source
    assert 'check("five_consecutive_fill_save_transactions"' in source
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
    assert 'command("Page.bringToFront")' in runner
    assert runner.index('command("Page.bringToFront")') < runner.index('"Runtime.evaluate"')
    assert '"Runtime.evaluate"' in runner
    assert "MutationObserver" in runner
    assert "--dump-dom" not in runner
    assert "existsSync(resolvedProfile)" in runner
    assert "skip" not in runner.casefold()
    assert "node scripts/run_fd_work_edge_fixture.mjs" in workflow
