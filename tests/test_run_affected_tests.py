"""Pure-function tests for the affected-test runner.

These tests import the selection logic from ``scripts/run_affected_tests.py``
without invoking git or pytest. They cover the mapping rules (sections A..L),
de-duplication / ordering, target existence filtering, command construction,
and the no-changed-files smoke fallback.

The module is loaded from its file path because ``scripts/`` is not a Python
package (no ``__init__.py``); using ``importlib`` keeps the test hermetic
and avoids mutating ``sys.path`` globally.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.parallel_safe]

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = REPO_ROOT / "scripts" / "run_affected_tests.py"
MODULE_NAME = "run_affected_tests"


@pytest.fixture(scope="module")
def runner():
    """Load the runner module from its file path.

    The module is registered in ``sys.modules`` before execution so the
    ``@dataclass`` decorator (which uses ``from __future__ import
    annotations`` and therefore string annotations) can resolve field types
    via a global lookup. This mirrors how Python loads a normal module.
    """
    assert RUNNER_PATH.is_file(), f"expected runner at {RUNNER_PATH}"
    spec = importlib.util.spec_from_file_location(MODULE_NAME, RUNNER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[MODULE_NAME] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(MODULE_NAME, None)
        raise
    return module


# A / C. rules.js -> Project Rules static contract + bridge + boundary + webview


def test_rules_js_selects_project_rules_bridge_boundary_and_webview(runner):
    sel = runner.select_targets(["worktrace/webview_ui/js/rules.js"])
    # rules.js triggers rule A (frontend resources) and rule C (Project Rules).
    assert "tests/webview/test_project_rules_static_contract.py" in sel.pytest_targets
    assert "tests/test_webview_bridge.py" in sel.pytest_targets
    assert "tests/test_ui_backend_boundary.py" in sel.pytest_targets
    assert "tests/webview/" in sel.pytest_targets


def test_rules_js_adds_import_smoke(runner):
    sel = runner.select_targets(["worktrace/webview_ui/js/rules.js"])
    # Rule A carries the import smoke command (separate from pytest targets).
    assert any(
        "import worktrace.webview_main" in " ".join(s) for s in sel.smoke_commands
    )


# B. bridge.py -> bridge tests + boundary


def test_bridge_py_selects_bridge_tests_and_boundary(runner):
    sel = runner.select_targets(["worktrace/webview_ui/bridge.py"])
    assert "tests/test_webview_bridge.py" in sel.pytest_targets
    assert "tests/test_webview_project_rules_bridge.py" in sel.pytest_targets
    assert "tests/test_ui_backend_boundary.py" in sel.pytest_targets
    # bridge.py is also a K1 trigger (Settings / Privacy WebView),
    # so K1 contributes the import smoke command and the Settings tests /
    # boundary. bridge.py itself is not a frontend resource, so the smoke
    # is added only because K1 matches the path.
    assert "tests/test_settings_privacy_status.py" in sel.pytest_targets
    assert "tests/webview/test_settings_static_contract.py" in sel.pytest_targets
    assert any(
        "import worktrace.webview_main" in " ".join(s) for s in sel.smoke_commands
    )


# B (the page module mapping). New split mixin files -> bridge tests + boundary


@pytest.mark.parametrize("bridge_file", [
    "worktrace/webview_ui/bridge_common.py",
    "worktrace/webview_ui/bridge_dialogs.py",
    "worktrace/webview_ui/bridge_overview.py",
    "worktrace/webview_ui/bridge_statistics.py",
    "worktrace/webview_ui/bridge_timeline.py",
])
def test_bridge_mixin_file_selects_bridge_tests_and_boundary(runner, bridge_file):
    # csv_export) plus the settings-privacy / default-entry / app-runtime
    sel = runner.select_targets([bridge_file])
    for expected in [
        "tests/test_webview_bridge.py",
        "tests/test_webview_project_rules_bridge.py",
        "tests/test_webview_bridge_statistics.py",
        "tests/test_statistics_csv_export.py",
        "tests/test_settings_privacy_status.py",
        "tests/test_webview_entry.py",
        "tests/test_app_runtime_privacy_gate.py",
        "tests/test_ui_backend_boundary.py",
    ]:
        assert expected in sel.pytest_targets, (
            f"{bridge_file} must select: {expected}"
        )


def test_m4_bridge_settings_py_also_selects_k1_settings_suite(runner):
    """bridge_settings.py carries the first-run notice, settings /
    privacy status, clipboard toggle, backup export / import / manifest, and
    clear-all-local-data bridge methods.
    It must trigger K1 (Settings / Privacy WebView) in addition to section B
    so the settings-specific static contract, privacy status, packaging, and
    frontend boundary tests run, plus the import smoke command.

    the page module mapping: K1 now also carries the entry test and the
    app-runtime privacy gate test because bridge_settings.py owns the
    first-run notice accept flow that the startup gate depends on."""
    sel = runner.select_targets(["worktrace/webview_ui/bridge_settings.py"])
    for expected in (
        "tests/test_settings_privacy_status.py",
        "tests/webview/test_settings_static_contract.py",
        "tests/test_webview_entry.py",
        "tests/test_app_runtime_privacy_gate.py",
        "tests/test_ui_backend_boundary.py",
        "tests/webview/test_frontend_global_boundaries.py",
        "tests/test_webview_packaging.py",
        "tests/test_run_affected_tests.py",
    ):
        assert expected in sel.pytest_targets, (
            f"bridge_settings.py must select K1 target: {expected}"
        )
    assert any(
        "import worktrace.webview_main" in " ".join(s) for s in sel.smoke_commands
    )


# B/D/E/K1 (the page module mapping). Per-split-file specialized test locks.
# Each split mixin file is a trigger for its own feature section (D / E / K1)
# in addition to section B. These tests lock the feature-specific specialized
# tests so a future runner refactor cannot silently drop them.


def test_bridge_timeline_py_selects_timeline_specialized_tests(runner):
    """bridge_timeline.py is a D trigger (in addition to
    a B trigger). It must select the Timeline-specialized bridge + static
    contract tests, not just the broad bridge suite."""
    sel = runner.select_targets(["worktrace/webview_ui/bridge_timeline.py"])
    for expected in (
        "tests/test_timeline_service.py",
        "tests/test_timeline_api_editing.py",
        "tests/webview/test_timeline_static_contract.py",
    ):
        assert expected in sel.pytest_targets, (
            f"bridge_timeline.py must select Timeline specialized test: {expected}"
        )


def test_bridge_statistics_py_selects_statistics_specialized_tests(runner):
    """bridge_statistics.py is an E trigger (in addition
    to a B trigger). It must select the Statistics-specialized bridge +
    export tests, not just the broad bridge suite."""
    sel = runner.select_targets(["worktrace/webview_ui/bridge_statistics.py"])
    for expected in (
        "tests/test_webview_bridge_statistics.py",
        "tests/test_statistics_csv_export.py",
        "tests/test_statistics_service.py",
        "tests/test_export_service.py",
        "tests/webview/test_statistics_static_contract.py",
    ):
        assert expected in sel.pytest_targets, (
            f"bridge_statistics.py must select Statistics specialized test: {expected}"
        )


def test_bridge_dialogs_py_selects_statistics_and_settings_tests(runner):
    """bridge_dialogs.py holds the native save / open
    file dialog helpers used by both the Statistics CSV export (E) and the
    Settings backup export / import / manifest preview (K1). It must trigger
    both E and K1 in addition to B, so the Statistics export tests AND the
    Settings / privacy tests all run when the shared dialog mixin changes."""
    sel = runner.select_targets(["worktrace/webview_ui/bridge_dialogs.py"])
    # Statistics / export (E) specialized tests.
    for expected in (
        "tests/test_statistics_csv_export.py",
        "tests/test_webview_bridge_statistics.py",
        "tests/test_export_service.py",
        "tests/webview/test_statistics_static_contract.py",
    ):
        assert expected in sel.pytest_targets, (
            f"bridge_dialogs.py must select Statistics/export test: {expected}"
        )
    # Settings / privacy (K1) specialized tests.
    for expected in (
        "tests/test_settings_privacy_status.py",
        "tests/test_app_runtime_privacy_gate.py",
        "tests/webview/test_settings_static_contract.py",
        "tests/test_webview_entry.py",
    ):
        assert expected in sel.pytest_targets, (
            f"bridge_dialogs.py must select Settings/privacy test: {expected}"
        )


def test_bridge_settings_py_selects_entry_and_privacy_gate_tests(runner):
    """bridge_settings.py owns the first-run notice
    accept flow (the first-run notice) that the startup gate and app-runtime privacy
    gate depend on. In addition to the K1 settings static contract /
    privacy status tests, it must select the default entry test and the
    app-runtime privacy gate test."""
    sel = runner.select_targets(["worktrace/webview_ui/bridge_settings.py"])
    for expected in (
        "tests/test_settings_privacy_status.py",
        "tests/test_webview_entry.py",
        "tests/test_app_runtime_privacy_gate.py",
    ):
        assert expected in sel.pytest_targets, (
            f"bridge_settings.py must select Settings/privacy test: {expected}"
        )


def test_bridge_py_and_bridge_overview_py_select_broad_bridge_and_boundary(runner):
    """bridge.py (the composition class) and
    bridge_overview.py (the Overview mixin) are B triggers and must still
    select the broad bridge + boundary tests. bridge.py is also a K1
    trigger, so it additionally selects the Settings / privacy suite."""
    for changed in (
        "worktrace/webview_ui/bridge.py",
        "worktrace/webview_ui/bridge_overview.py",
    ):
        sel = runner.select_targets([changed])
        assert "tests/test_webview_bridge.py" in sel.pytest_targets, (
            f"{changed} must select broad bridge test"
        )
        assert "tests/test_ui_backend_boundary.py" in sel.pytest_targets, (
            f"{changed} must select boundary test"
        )


# C. rule_api.py -> Project Rules keyword + folder API/service/bridge tests
# (rule_api.py no longer triggers frontend/static contract tests;
# it triggers C2 keyword + C3 folder + bridge + boundary only.)


def test_rule_api_py_selects_project_rules_suite(runner):
    sel = runner.select_targets(["worktrace/api/rule_api.py"])
    for expected in [
        "tests/test_rule_service.py",
        "tests/test_folder_rule_service.py",
        "tests/test_project_rules_keyword_create.py",
        "tests/test_project_rules_keyword_delete.py",
        "tests/test_project_rules_keyword_edit.py",
        "tests/test_project_rules_folder_crud.py",
        "tests/test_project_rules_enable_disable.py",
        "tests/test_project_rules_rule_impact.py",
        "tests/test_webview_project_rules_bridge.py",
        "tests/test_project_rules_view.py",
        "tests/test_ui_backend_boundary.py",
    ]:
        assert expected in sel.pytest_targets, f"missing {expected}"


def test_rule_api_py_does_not_trigger_frontend_static_contract(runner):
    # rule_api.py changes must NOT unconditionally run frontend
    # static contract tests; those run only when bridge_rules.py or rules*.js
    # change (sections C5 / C6 / A).
    sel = runner.select_targets(["worktrace/api/rule_api.py"])
    assert "tests/webview/test_project_rules_static_contract.py" not in sel.pytest_targets


def test_rule_api_py_does_not_trigger_project_lifecycle_tests(runner):
    # rule_api.py (keyword/folder facades) must NOT trigger
    # project lifecycle tests; those run only when project_api.py or
    # project_service.py change (section C4).
    sel = runner.select_targets(["worktrace/api/rule_api.py"])
    assert "tests/test_project_rules_project_lifecycle.py" not in sel.pytest_targets


# C1. _write_contract.py -> broad Project Rules suite (shared helper)


def test_write_contract_helper_selects_broad_project_rules_suite(runner):
    sel = runner.select_targets(["worktrace/api/_write_contract.py"])
    for expected in [
        "tests/test_api_write_contract.py",
        "tests/test_project_rules_keyword_create.py",
        "tests/test_project_rules_keyword_delete.py",
        "tests/test_project_rules_keyword_edit.py",
        "tests/test_project_rules_folder_crud.py",
        "tests/test_project_rules_enable_disable.py",
        "tests/test_project_rules_project_lifecycle.py",
        "tests/test_project_rules_rule_impact.py",
        "tests/test_webview_project_rules_bridge.py",
        "tests/test_ui_backend_boundary.py",
    ]:
        assert expected in sel.pytest_targets, f"missing {expected}"
    assert any("Shared Project Rules contract helper" in w for w in sel.warnings)


# C2. rule_service.py -> keyword rule tests (no folder, no lifecycle, no static)


def test_rule_service_py_selects_keyword_tests_only(runner):
    sel = runner.select_targets(["worktrace/services/rule_service.py"])
    for expected in [
        "tests/test_rule_service.py",
        "tests/test_project_rules_keyword_create.py",
        "tests/test_project_rules_keyword_delete.py",
        "tests/test_project_rules_keyword_edit.py",
        "tests/test_project_rules_enable_disable.py",
        "tests/test_project_rules_rule_impact.py",
        "tests/test_project_rules_view.py",
        "tests/test_webview_project_rules_bridge.py",
        "tests/test_ui_backend_boundary.py",
    ]:
        assert expected in sel.pytest_targets, f"missing {expected}"
    # rule_service.py must NOT trigger folder rule tests or lifecycle tests.
    assert "tests/test_folder_rule_service.py" not in sel.pytest_targets
    assert "tests/test_project_rules_project_lifecycle.py" not in sel.pytest_targets
    assert "tests/webview/test_project_rules_static_contract.py" not in sel.pytest_targets


# C3. folder_rule_service.py -> folder rule tests (no keyword, no lifecycle)


def test_folder_rule_service_py_selects_folder_tests_only(runner):
    sel = runner.select_targets(["worktrace/services/folder_rule_service.py"])
    for expected in [
        "tests/test_folder_rule_service.py",
        "tests/test_project_rules_folder_crud.py",
        "tests/test_project_rules_view.py",
        "tests/test_project_rules_rule_impact.py",
        "tests/test_webview_project_rules_bridge.py",
        "tests/test_ui_backend_boundary.py",
    ]:
        assert expected in sel.pytest_targets, f"missing {expected}"
    assert "tests/test_rule_service.py" not in sel.pytest_targets
    assert "tests/test_project_rules_project_lifecycle.py" not in sel.pytest_targets
    assert "tests/webview/test_project_rules_static_contract.py" not in sel.pytest_targets


# C4. project_api.py / project_service.py -> project lifecycle tests only


def test_project_api_py_selects_lifecycle_tests_only(runner):
    sel = runner.select_targets(["worktrace/api/project_api.py"])
    for expected in [
        "tests/test_project_rules_project_lifecycle.py",
        "tests/test_project_rules_view.py",
        "tests/test_project_rules_rule_impact.py",
        "tests/test_webview_project_rules_bridge.py",
        "tests/test_ui_backend_boundary.py",
    ]:
        assert expected in sel.pytest_targets, f"missing {expected}"
    # project_api.py must NOT trigger keyword/folder rule tests or static tests.
    assert "tests/test_rule_service.py" not in sel.pytest_targets
    assert "tests/test_folder_rule_service.py" not in sel.pytest_targets
    assert "tests/test_project_rules_keyword_create.py" not in sel.pytest_targets
    assert "tests/webview/test_project_rules_static_contract.py" not in sel.pytest_targets


def test_project_service_py_selects_lifecycle_tests_only(runner):
    sel = runner.select_targets(["worktrace/services/project_service.py"])
    for expected in [
        "tests/test_project_rules_project_lifecycle.py",
        "tests/test_project_rules_view.py",
        "tests/test_project_rules_rule_impact.py",
        "tests/test_webview_project_rules_bridge.py",
        "tests/test_ui_backend_boundary.py",
    ]:
        assert expected in sel.pytest_targets, f"missing {expected}"
    assert "tests/test_rule_service.py" not in sel.pytest_targets
    assert "tests/webview/test_project_rules_static_contract.py" not in sel.pytest_targets


# C5. bridge_rules.py -> Project Rules bridge tests + boundary only


def test_bridge_rules_py_selects_project_rules_bridge_tests_only(runner):
    sel = runner.select_targets(["worktrace/webview_ui/bridge_rules.py"])
    for expected in [
        "tests/test_webview_project_rules_bridge.py",
        "tests/test_project_rules_rule_impact.py",
        "tests/test_ui_backend_boundary.py",
    ]:
        assert expected in sel.pytest_targets, f"missing {expected}"
    # bridge_rules.py must NOT trigger all bridge tests (timeline, statistics,
    # etc.) since it only contains Project Rules methods.
    assert "tests/test_webview_bridge.py" not in sel.pytest_targets
    assert "tests/test_webview_bridge_merge.py" not in sel.pytest_targets
    assert "tests/test_webview_bridge_batch_project.py" not in sel.pytest_targets
    assert "tests/test_webview_bridge_batch_note.py" not in sel.pytest_targets
    assert "tests/test_webview_bridge_restore.py" not in sel.pytest_targets
    # bridge_rules.py is not a frontend resource, so no import smoke.
    assert sel.smoke_commands == []


# C6 (the modular split). New split modules -> Project Rules static contract + smoke


@pytest.mark.parametrize("js_module", [
    "worktrace/webview_ui/js/rules_render.js",
    "worktrace/webview_ui/js/rules_rule_actions.js",
    "worktrace/webview_ui/js/rules_keyword_actions.js",
    "worktrace/webview_ui/js/rules_folder_actions.js",
])
def test_rules_split_module_selects_static_contract_and_smoke(runner, js_module):
    # each new split module must trigger section A (frontend
    # resources, broad) AND section C6 (Project Rules static contract).
    # Both contribute the static contract target; dedup ensures it
    # appears once. The import smoke command must also be selected.
    sel = runner.select_targets([js_module])
    assert "tests/webview/test_project_rules_static_contract.py" in sel.pytest_targets
    assert "tests/webview/" in sel.pytest_targets
    assert "tests/test_webview_bridge.py" in sel.pytest_targets
    assert "tests/test_ui_backend_boundary.py" in sel.pytest_targets
    assert any(
        "import worktrace.webview_main" in " ".join(s) for s in sel.smoke_commands
    )


@pytest.mark.parametrize("js_module", [
    "worktrace/webview_ui/js/rules_render.js",
    "worktrace/webview_ui/js/rules_rule_actions.js",
    "worktrace/webview_ui/js/rules_keyword_actions.js",
    "worktrace/webview_ui/js/rules_folder_actions.js",
])
def test_rules_split_module_does_not_trigger_api_or_service_tests(runner, js_module):
    # a pure frontend JS change must not unconditionally
    # trigger the keyword/folder/project API or service tests. Those run
    # only when the API / service / bridge source files change (sections
    # C1..C5). Section A's broad frontend mapping is preserved.
    sel = runner.select_targets([js_module])
    for unexpected in (
        "tests/test_rule_service.py",
        "tests/test_folder_rule_service.py",
        "tests/test_project_rules_keyword_create.py",
        "tests/test_project_rules_keyword_delete.py",
        "tests/test_project_rules_keyword_edit.py",
        "tests/test_project_rules_folder_crud.py",
        "tests/test_project_rules_enable_disable.py",
        "tests/test_project_rules_project_lifecycle.py",
        "tests/test_project_rules_view.py",
        "tests/test_webview_project_rules_bridge.py",
        "tests/test_api_write_contract.py",
    ):
        assert unexpected not in sel.pytest_targets, (
            f"{js_module} must not trigger API/service test: {unexpected}"
        )


# C7. rule_impact_service.py -> rule impact tests + bridge + boundary (the impact)


def test_rule_impact_service_py_selects_impact_tests(runner):
    # the new rule_impact_service.py triggers the impact test
    # file plus the bridge and boundary tests. It must not trigger
    # keyword/folder/lifecycle CRUD tests since the service is scoped to
    # preview + safe backfill only.
    sel = runner.select_targets(["worktrace/services/rule_impact_service.py"])
    for expected in [
        "tests/test_project_rules_rule_impact.py",
        "tests/test_webview_project_rules_bridge.py",
        "tests/test_ui_backend_boundary.py",
    ]:
        assert expected in sel.pytest_targets, f"missing {expected}"
    # rule_impact_service.py must NOT trigger CRUD/lifecycle/static tests.
    assert "tests/test_rule_service.py" not in sel.pytest_targets
    assert "tests/test_folder_rule_service.py" not in sel.pytest_targets
    assert "tests/test_project_rules_keyword_create.py" not in sel.pytest_targets
    assert "tests/test_project_rules_folder_crud.py" not in sel.pytest_targets
    assert "tests/test_project_rules_project_lifecycle.py" not in sel.pytest_targets
    assert "tests/webview/test_project_rules_static_contract.py" not in sel.pytest_targets
    # rule_impact_service.py is not a frontend resource, so no import smoke.
    assert sel.smoke_commands == []


# C8. rule_automation_service.py -> automatic rules tests + bridge + boundary
# (the rule automation)


def test_rule_automation_service_py_selects_automatic_rules_tests(runner):
    # rule_automation_service.py (thin facade delegating to
    # project_inference_service.process_new_activity) triggers automatic
    # rules + bridge + boundary tests only; CRUD/lifecycle/impact/static
    # tests must NOT trigger since the facade is scoped to automatic path.
    sel = runner.select_targets(["worktrace/services/rule_automation_service.py"])
    for expected in [
        "tests/test_project_rules_automatic_rules.py",
        "tests/test_webview_project_rules_bridge.py",
        "tests/test_ui_backend_boundary.py",
    ]:
        assert expected in sel.pytest_targets, f"missing {expected}"
    # rule_automation_service.py must NOT trigger CRUD/lifecycle/impact/static
    # tests; those run only when their own API/service sources change.
    assert "tests/test_rule_service.py" not in sel.pytest_targets
    assert "tests/test_folder_rule_service.py" not in sel.pytest_targets
    assert "tests/test_project_rules_keyword_create.py" not in sel.pytest_targets
    assert "tests/test_project_rules_folder_crud.py" not in sel.pytest_targets
    assert "tests/test_project_rules_project_lifecycle.py" not in sel.pytest_targets
    assert "tests/test_project_rules_rule_impact.py" not in sel.pytest_targets
    assert "tests/test_project_rules_batch_operations.py" not in sel.pytest_targets
    assert "tests/webview/test_project_rules_static_contract.py" not in sel.pytest_targets
    # rule_automation_service.py is not a frontend resource, so no import smoke.
    assert sel.smoke_commands == []


# C9. rule_batch_service.py -> batch operations tests + bridge + boundary
# (the rule automation)


def test_rule_batch_service_py_selects_batch_operations_tests(runner):
    # the new rule_batch_service.py triggers the batch operations
    # test file plus the bridge and boundary tests. It must not trigger
    # keyword/folder CRUD/lifecycle/automatic/static tests since the service
    # is scoped to selected-rule batch preview/apply/toggle only.
    sel = runner.select_targets(["worktrace/services/rule_batch_service.py"])
    for expected in [
        "tests/test_project_rules_batch_operations.py",
        "tests/test_webview_project_rules_bridge.py",
        "tests/test_ui_backend_boundary.py",
    ]:
        assert expected in sel.pytest_targets, f"missing {expected}"
    # rule_batch_service.py must NOT trigger CRUD/lifecycle/automatic/impact/
    # static tests; those run only when their own API/service sources change.
    assert "tests/test_rule_service.py" not in sel.pytest_targets
    assert "tests/test_folder_rule_service.py" not in sel.pytest_targets
    assert "tests/test_project_rules_keyword_create.py" not in sel.pytest_targets
    assert "tests/test_project_rules_folder_crud.py" not in sel.pytest_targets
    assert "tests/test_project_rules_project_lifecycle.py" not in sel.pytest_targets
    assert "tests/test_project_rules_automatic_rules.py" not in sel.pytest_targets
    assert "tests/test_project_rules_rule_impact.py" not in sel.pytest_targets
    assert "tests/webview/test_project_rules_static_contract.py" not in sel.pytest_targets
    # rule_batch_service.py is not a frontend resource, so no import smoke.
    assert sel.smoke_commands == []


# I. docs-only -> not full pytest


def test_docs_only_does_not_select_full_pytest(runner):
    sel = runner.select_targets(["docs/some-note.md"])
    # Finite target set, not a bare full-suite invocation.
    assert sel.pytest_targets, "docs-only should select a finite target set"
    assert "tests/test_release_docs.py" in sel.pytest_targets
    assert "tests/test_comment_hygiene.py" in sel.pytest_targets
    cmd = runner.build_pytest_command(sel.pytest_targets, [])
    assert cmd != ["python", "-m", "pytest"], "docs-only must not be full suite"


def test_docs_directory_prefix_matches(runner):
    sel = runner.select_targets(["docs/current-state.md"])
    assert "tests/test_release_docs.py" in sel.pytest_targets
    assert "tests/test_comment_hygiene.py" in sel.pytest_targets


# F. DB/schema -> broad suite + warning


def test_db_schema_change_gives_broad_suite_and_warning(runner):
    sel = runner.select_targets(["worktrace/schema.sql"])
    for expected in [
        "tests/test_db_migration.py",
        "tests/test_activity_service.py",
        "tests/test_timeline_service.py",
        "tests/test_statistics_service.py",
        "tests/test_rule_service.py",
        "tests/test_folder_rule_service.py",
        "tests/test_project_rules_keyword_create.py",
        "tests/test_project_rules_keyword_delete.py",
        "tests/test_project_rules_rule_impact.py",
        "tests/test_ui_backend_boundary.py",
    ]:
        assert expected in sel.pytest_targets, f"missing {expected}"
    assert any("DB/schema" in w for w in sel.warnings), (
        "expected DB/schema full-suite recommendation warning"
    )


def test_db_py_triggers_same_broad_suite(runner):
    sel = runner.select_targets(["worktrace/db.py"])
    assert "tests/test_db_migration.py" in sel.pytest_targets
    assert any("DB/schema" in w for w in sel.warnings)


# L. test file changes -> run that test file directly


def test_changed_test_file_runs_directly(runner):
    sel = runner.select_targets(["tests/test_rule_service.py"])
    assert "tests/test_rule_service.py" in sel.pytest_targets
    assert "tests/test_comment_hygiene.py" in sel.pytest_targets


def test_changed_webview_test_file_also_runs_webview_suite(runner):
    sel = runner.select_targets(["tests/webview/test_timeline_static_contract.py"])
    assert "tests/webview/test_timeline_static_contract.py" in sel.pytest_targets
    assert "tests/webview/" in sel.pytest_targets


def test_changed_conftest_selects_broad_suite(runner):
    sel = runner.select_targets(["tests/conftest.py"])
    for expected in [
        "tests/test_db_migration.py",
        "tests/test_activity_service.py",
        "tests/test_rule_service.py",
        "tests/test_statistics_service.py",
        "tests/webview/",
    ]:
        assert expected in sel.pytest_targets, f"missing {expected}"


# K. unknown worktrace/ source -> smoke + boundary + warning


def test_unknown_worktrace_source_selects_smoke_and_boundary(runner):
    sel = runner.select_targets(["worktrace/formatters.py"])
    assert "tests/test_startup_imports.py" in sel.pytest_targets
    assert "tests/test_ui_backend_boundary.py" in sel.pytest_targets
    assert "tests/test_comment_hygiene.py" in sel.pytest_targets
    assert any("Unknown worktrace/" in w for w in sel.warnings), (
        "expected unknown-source warning"
    )


# H. collector / platform / resource model


def test_resource_helper_change_selects_resource_tests(runner):
    sel = runner.select_targets(["worktrace/resources/resource_helpers.py"])
    assert "tests/test_resource_helpers.py" in sel.pytest_targets
    assert "tests/test_resource_model.py" in sel.pytest_targets
    assert "tests/test_startup_imports.py" in sel.pytest_targets


def test_collector_directory_prefix_matches(runner):
    sel = runner.select_targets(["worktrace/collector/state_machine.py"])
    assert "tests/test_collector.py" in sel.pytest_targets


# existing_targets filtering


def test_existing_targets_filters_nonexistent(runner, tmp_path):
    # A real test file under the repo root should survive; a fake one should
    # be dropped silently.
    targets = [
        "tests/test_rule_service.py",
        "tests/__totally_fake__.py",
        "tests/webview/",
    ]
    out = runner.existing_targets(targets, REPO_ROOT)
    assert "tests/test_rule_service.py" in out
    assert "tests/webview/" in out
    assert "tests/__totally_fake__.py" not in out


# De-duplication + stable order


def test_targets_are_deduped_and_stable(runner):
    # Two source files that both trigger rule C -> C's targets appear once.
    files = ["worktrace/api/rule_api.py", "worktrace/services/rule_service.py"]
    sel = runner.select_targets(files)
    # No duplicates.
    assert len(sel.pytest_targets) == len(set(sel.pytest_targets))
    # Deterministic for a fixed input.
    sel2 = runner.select_targets(files)
    assert sel.pytest_targets == sel2.pytest_targets


def test_overlapping_rules_dedup(runner):
    # rules.js triggers both A and C; boundary test must appear once.
    sel = runner.select_targets(["worktrace/webview_ui/js/rules.js"])
    assert sel.pytest_targets.count("tests/test_ui_backend_boundary.py") == 1


# build_pytest_command


def test_build_pytest_command_appends_extra_args(runner):
    cmd = runner.build_pytest_command(
        ["tests/test_rule_service.py"], ["--maxfail=1", "-q"]
    )
    assert cmd == [
        "python",
        "-m",
        "pytest",
        "tests/test_rule_service.py",
        "--maxfail=1",
        "-q",
    ]


def test_build_pytest_command_empty_targets_is_full_suite(runner):
    # Shape used by the --all fallback.
    assert runner.build_pytest_command([], []) == ["python", "-m", "pytest"]


# No changed files -> light smoke set (not full suite)


def test_no_changed_files_uses_smoke_set(runner):
    sel = runner.select_targets([])
    assert "tests/test_startup_imports.py" in sel.pytest_targets
    assert "tests/test_ui_backend_boundary.py" in sel.pytest_targets
    assert "tests/webview/" in sel.pytest_targets
    assert "tests/test_comment_hygiene.py" in sel.pytest_targets
    assert any("No changed files" in w for w in sel.warnings)
    cmd = runner.build_pytest_command(sel.pytest_targets, [])
    assert cmd != ["python", "-m", "pytest"], (
        "no-changed-files must not select the full suite"
    )


def test_no_changed_files_adds_import_smoke(runner):
    sel = runner.select_targets([])
    assert any(
        "import worktrace.webview_main" in " ".join(s) for s in sel.smoke_commands
    )


def test_cli_files_option_selects_targets_without_git_diff(runner, capsys):
    rc = runner.main([
        "--files",
        "worktrace/services/activity_display_model_service.py",
        "worktrace/webview_ui/js/core.js",
        "--print-only",
    ])
    assert rc == 0
    out = capsys.readouterr().out
    assert "worktrace/services/activity_display_model_service.py" in out
    assert "worktrace/webview_ui/js/core.js" in out
    assert "tests/test_live_display_projection_contract.py" in out
    assert "tests/webview/test_heartbeat_projection_contract.py" in out


@pytest.mark.parametrize("changed", [
    "worktrace/services/activity_service.py",
    "worktrace/webview_ui/js/core.js",
    "README.md",
])
def test_common_changes_select_comment_hygiene(runner, changed):
    sel = runner.select_targets([changed])
    assert "tests/test_comment_hygiene.py" in sel.pytest_targets


@pytest.mark.parametrize("changed", [
    "comment_policy.json",
    "scripts/comment_hygiene.py",
    ".ai/comment-hygiene-fixer.md",
    "tests/test_comment_hygiene.py",
])
def test_comment_hygiene_owner_changes_select_self_tests(runner, changed):
    sel = runner.select_targets([changed])
    assert "tests/test_comment_hygiene.py" in sel.pytest_targets
    assert "tests/test_run_affected_tests.py" in sel.pytest_targets


# Normalization + misc invariants


def test_backslash_paths_are_normalized(runner):
    sel = runner.select_targets(["worktrace\\webview_ui\\bridge.py"])
    assert "tests/test_webview_bridge.py" in sel.pytest_targets


def test_packaging_files_select_packaging_tests(runner):
    sel = runner.select_targets(["WorkTrace.spec"])
    assert "tests/test_webview_packaging.py" in sel.pytest_targets
    assert "tests/test_startup_imports.py" in sel.pytest_targets
    assert any("PyInstaller" in w for w in sel.warnings)


def test_split_passthrough_extracts_extra_args(runner):
    own, extra = runner._split_passthrough(
        ["--list", "--", "--maxfail=1", "-q"]
    )
    assert own == ["--list"]
    assert extra == ["--maxfail=1", "-q"]


def test_split_passthrough_without_separator(runner):
    own, extra = runner._split_passthrough(["--list"])
    assert own == ["--list"]
    assert extra == []


# K1 Settings / Privacy WebView -> settings + boundary + packaging


def test_settings_api_py_selects_settings_tests(runner):
    # settings_api.py carries read-only status, clipboard capture toggle,
    # encrypted backup export / manifest preview, and encrypted backup
    # import / clear-all-local-data facades, so it must select the full
    # K1 target set.
    sel = runner.select_targets(["worktrace/api/settings_api.py"])
    for expected in (
        "tests/test_settings_privacy_status.py",
        "tests/webview/test_settings_static_contract.py",
        "tests/test_ui_backend_boundary.py",
        "tests/webview/test_frontend_global_boundaries.py",
        "tests/test_webview_packaging.py",
        "tests/test_run_affected_tests.py",
    ):
        assert expected in sel.pytest_targets, (
            f"settings_api.py must select: {expected}"
        )


def test_backup_api_py_selects_settings_tests(runner):
    sel = runner.select_targets(["worktrace/api/backup_api.py"])
    for expected in (
        "tests/test_settings_privacy_status.py",
        "tests/webview/test_settings_static_contract.py",
        "tests/test_ui_backend_boundary.py",
        "tests/test_run_affected_tests.py",
    ):
        assert expected in sel.pytest_targets, (
            f"backup_api.py must select: {expected}"
        )


def test_settings_js_selects_settings_tests_and_smoke(runner):
    # settings.js carries the read-only status loader, clipboard toggle
    # write handler, encrypted backup export / manifest preview handlers,
    # and encrypted backup import / clear-all-local-data handlers, so it
    # must select the full K1 target set plus the import smoke.
    sel = runner.select_targets(["worktrace/webview_ui/js/settings.js"])
    for expected in (
        "tests/test_settings_privacy_status.py",
        "tests/webview/test_settings_static_contract.py",
        "tests/webview/test_frontend_global_boundaries.py",
        "tests/test_webview_packaging.py",
        "tests/test_run_affected_tests.py",
    ):
        assert expected in sel.pytest_targets, (
            f"settings.js must select: {expected}"
        )
    assert any(
        "import worktrace.webview_main" in " ".join(s) for s in sel.smoke_commands
    )


def test_core_js_selects_settings_tests_and_smoke(runner):
    """core.js declares Settings operation flags.

    A change to core.js must select the full K1 target set plus the import
    smoke so the static contract suite verifies the flags and
    ``anySettingsOperationInProgress`` composition.
    """
    sel = runner.select_targets(["worktrace/webview_ui/js/core.js"])
    for expected in (
        "tests/test_settings_privacy_status.py",
        "tests/webview/test_settings_static_contract.py",
        "tests/test_ui_backend_boundary.py",
        "tests/webview/test_frontend_global_boundaries.py",
        "tests/test_webview_packaging.py",
        "tests/test_run_affected_tests.py",
    ):
        assert expected in sel.pytest_targets, (
            f"core.js must select: {expected}"
        )
    assert any(
        "import worktrace.webview_main" in " ".join(s) for s in sel.smoke_commands
    )


def test_settings_html_css_init_select_settings_tests(runner):
    """index.html / styles.css / init.js share the K1 settings target set."""
    for changed in (
        "worktrace/webview_ui/index.html",
        "worktrace/webview_ui/styles.css",
        "worktrace/webview_ui/js/init.js",
    ):
        sel = runner.select_targets([changed])
        assert "tests/webview/test_settings_static_contract.py" in sel.pytest_targets, (
            f"{changed} must select settings static contract"
        )
        assert "tests/test_settings_privacy_status.py" in sel.pytest_targets, (
            f"{changed} must select settings privacy status tests"
        )


def test_k1_does_not_trigger_project_rules_suite(runner):
    """K1 must NOT trigger the Project Rules suite."""
    sel = runner.select_targets(["worktrace/api/settings_api.py"])
    for unexpected in (
        "tests/test_rule_service.py",
        "tests/test_folder_rule_service.py",
        "tests/test_project_rules_keyword_create.py",
        "tests/test_project_rules_keyword_delete.py",
        "tests/test_project_rules_keyword_edit.py",
        "tests/test_project_rules_folder_crud.py",
        "tests/test_project_rules_enable_disable.py",
        "tests/test_project_rules_project_lifecycle.py",
        "tests/test_project_rules_view.py",
        "tests/test_project_rules_rule_impact.py",
        "tests/test_project_rules_automatic_rules.py",
        "tests/test_project_rules_batch_operations.py",
        "tests/test_webview_project_rules_bridge.py",
        "tests/test_api_write_contract.py",
    ):
        assert unexpected not in sel.pytest_targets, (
            f"settings_api.py must not trigger Project Rules suite: {unexpected}"
        )


# K2 (the first-run notice). WebView main / startup gate -> entry + startup + boundary


def test_webview_main_py_selects_startup_tests(runner):
    """webview_main.py carries the first-run notice startup gate,
    so it must select the K2 target set (entry + startup imports + boundary
    + settings privacy status + affected runner self-tests). the heartbeat adds
    the app-runtime privacy gate test to K2 as well."""
    sel = runner.select_targets(["worktrace/webview_main.py"])
    for expected in (
        "tests/test_webview_entry.py",
        "tests/test_startup_imports.py",
        "tests/test_ui_backend_boundary.py",
        "tests/test_settings_privacy_status.py",
        "tests/test_app_runtime_privacy_gate.py",
        "tests/test_run_affected_tests.py",
    ):
        assert expected in sel.pytest_targets, (
            f"webview_main.py must select: {expected}"
        )


def test_webview_main_py_adds_import_smoke(runner):
    """webview_main.py changes must run the import smoke alongside
    pytest targets because the startup gate can break module import."""
    sel = runner.select_targets(["worktrace/webview_main.py"])
    assert any(
        "import worktrace.webview_main" in " ".join(s) for s in sel.smoke_commands
    )


def test_main_py_selects_startup_tests(runner):
    """worktrace/main.py is a K2 trigger because it can alter the
    process entry point that decides whether the WebView main loop starts.
    the heartbeat adds the app-runtime privacy gate test to K2."""
    sel = runner.select_targets(["worktrace/main.py"])
    for expected in (
        "tests/test_webview_entry.py",
        "tests/test_startup_imports.py",
        "tests/test_ui_backend_boundary.py",
        "tests/test_settings_privacy_status.py",
        "tests/test_app_runtime_privacy_gate.py",
        "tests/test_run_affected_tests.py",
    ):
        assert expected in sel.pytest_targets, (
            f"main.py must select: {expected}"
        )


def test_app_api_py_selects_startup_tests(runner):
    """app_api.py carries start_collector / stop_collector, which
    the startup gate and toggle_pause guard depend on; it must select the
    K2 target set so boundary and entry tests run. the heartbeat adds the
    app-runtime privacy gate test to K2."""
    sel = runner.select_targets(["worktrace/api/app_api.py"])
    for expected in (
        "tests/test_webview_entry.py",
        "tests/test_startup_imports.py",
        "tests/test_ui_backend_boundary.py",
        "tests/test_settings_privacy_status.py",
        "tests/test_app_runtime_privacy_gate.py",
        "tests/test_run_affected_tests.py",
    ):
        assert expected in sel.pytest_targets, (
            f"app_api.py must select: {expected}"
        )


def test_app_runtime_py_selects_privacy_gate_tests(runner):
    """app_runtime.py carries the split start_background_workers()
    method that the first-run notice privacy gate depends on. It must select
    the K2 target set so the app-runtime privacy gate test, boundary, and
    entry tests all run."""
    sel = runner.select_targets(["worktrace/runtime/app_runtime.py"])
    for expected in (
        "tests/test_webview_entry.py",
        "tests/test_startup_imports.py",
        "tests/test_ui_backend_boundary.py",
        "tests/test_settings_privacy_status.py",
        "tests/test_app_runtime_privacy_gate.py",
        "tests/test_run_affected_tests.py",
    ):
        assert expected in sel.pytest_targets, (
            f"app_runtime.py must select: {expected}"
        )
    assert any(
        "import worktrace.webview_main" in " ".join(s) for s in sel.smoke_commands
    )


def test_runtime_activity_state_service_selects_runtime_boundary_suites(runner):
    """The transient runtime cleanup owner participates in startup/runtime
    gate, collector/runtime, and activity lifecycle boundary rules."""
    sel = runner.select_targets([
        "worktrace/services/runtime_activity_state_service.py",
    ])
    for expected in (
        "tests/test_app_runtime_privacy_gate.py",
        "tests/test_collector_raw_activity_contract.py",
        "tests/test_bridge_refresh_state_and_projection.py",
        "tests/test_live_display_projection_contract.py",
        "tests/test_display_model_anti_regression.py",
        "tests/webview/test_heartbeat_projection_contract.py",
        "tests/webview/test_frontend_global_boundaries.py",
        "tests/test_activity_lifecycle_service.py",
        "tests/test_activity_lifecycle_boundary.py",
        "tests/test_collector.py",
        "tests/test_state_machine.py",
        "tests/test_run_affected_tests.py",
        "tests/test_ui_backend_boundary.py",
    ):
        assert expected in sel.pytest_targets, (
            f"runtime_activity_state_service.py must select: {expected}"
        )
    assert "collector_runtime and integration" in sel.marker_exprs


def test_k2_does_not_trigger_project_rules_suite(runner):
    """K2 must NOT trigger the Project Rules C-series suite; the
    startup gate is unrelated to Project Rules keyword / folder / lifecycle
    / automatic / batch operations."""
    sel = runner.select_targets(["worktrace/webview_main.py"])
    for unexpected in (
        "tests/test_rule_service.py",
        "tests/test_folder_rule_service.py",
        "tests/test_project_rules_keyword_create.py",
        "tests/test_project_rules_keyword_delete.py",
        "tests/test_project_rules_keyword_edit.py",
        "tests/test_project_rules_folder_crud.py",
        "tests/test_project_rules_enable_disable.py",
        "tests/test_project_rules_project_lifecycle.py",
        "tests/test_project_rules_view.py",
        "tests/test_project_rules_rule_impact.py",
        "tests/test_project_rules_automatic_rules.py",
        "tests/test_project_rules_batch_operations.py",
        "tests/test_webview_project_rules_bridge.py",
        "tests/test_api_write_contract.py",
    ):
        assert unexpected not in sel.pytest_targets, (
            f"webview_main.py must not trigger Project Rules suite: {unexpected}"
        )


def test_k2_does_not_trigger_timeline_static_contract(runner):
    """K2 must NOT trigger the Timeline static contract or the
    Project Rules static contract; the startup gate does not touch those
    frontend resources."""
    sel = runner.select_targets(["worktrace/webview_main.py"])
    assert "tests/webview/test_timeline_static_contract.py" not in sel.pytest_targets
    assert (
        "tests/webview/test_project_rules_static_contract.py"
        not in sel.pytest_targets
    )


# L1. Context assignment service -> context_service tests + timeline service


def test_context_service_py_selects_l1_targets(runner):
    """L1: context_service.py carries the context assignment logic
    (anchor context carry + short-gap same-project bridging), so it
    must select the L1 target set (context_service tests + timeline
    service tests + boundary tests)."""
    sel = runner.select_targets(["worktrace/services/context_service.py"])
    for expected in (
        "tests/test_context_service.py",
        "tests/test_timeline_service.py",
        "tests/test_ui_backend_boundary.py",
    ):
        assert expected in sel.pytest_targets, (
            f"context_service.py must trigger L1 target: {expected}"
        )


# N. Activity lifecycle boundary -> lifecycle + collector + recovery + state
# machine + clipboard + automatic rules + live display + timeline + statistics


def test_activity_lifecycle_service_py_selects_lifecycle_boundary_suite(runner):
    """N: activity_lifecycle_service.py is the open-row state transition
    command facade. Changes must trigger the full lifecycle boundary
    suite so collector / state machine / recovery / clipboard / automatic
    rules / live display / timeline / statistics / boundary tests all
    run. The static boundary test (test_activity_lifecycle_boundary.py)
    and the app-runtime privacy gate test are included so architectural
    invariants and the shutdown close-all path are verified."""
    sel = runner.select_targets([
        "worktrace/services/activity_lifecycle_service.py",
    ])
    for expected in (
        "tests/test_activity_lifecycle_service.py",
        "tests/test_activity_lifecycle_boundary.py",
        "tests/test_activity_service.py",
        "tests/test_collector.py",
        "tests/test_state_machine.py",
        "tests/test_clipboard_service.py",
        "tests/test_recovery_service.py",
        "tests/test_app_runtime_privacy_gate.py",
        "tests/test_project_rules_automatic_rules.py",
        "tests/test_live_display_contract.py",
        "tests/test_timeline_service.py",
        "tests/test_statistics_service.py",
        "tests/test_run_affected_tests.py",
        "tests/test_ui_backend_boundary.py",
    ):
        assert expected in sel.pytest_targets, (
            f"activity_lifecycle_service.py must select N target: {expected}"
        )


def test_recovery_service_py_selects_lifecycle_boundary_suite(runner):
    """N: recovery_service.py carries cross-midnight recovery that now
    routes through the lifecycle facade. Changes must trigger the
    lifecycle boundary suite including the static boundary test."""
    sel = runner.select_targets(["worktrace/services/recovery_service.py"])
    for expected in (
        "tests/test_activity_lifecycle_service.py",
        "tests/test_activity_lifecycle_boundary.py",
        "tests/test_recovery_service.py",
        "tests/test_collector.py",
        "tests/test_state_machine.py",
        "tests/test_live_display_contract.py",
        "tests/test_ui_backend_boundary.py",
    ):
        assert expected in sel.pytest_targets, (
            f"recovery_service.py must select N target: {expected}"
        )


def test_collector_directory_prefix_matches_lifecycle_boundary(runner):
    """N: collector/ changes must trigger the lifecycle boundary suite
    in addition to the H (collector / platform) suite. The lifecycle
    facade is the collector's write path, so collector changes must
    run lifecycle + state machine + clipboard tests. The static
    boundary test is included to verify architectural invariants."""
    sel = runner.select_targets(["worktrace/collector/activity_session_recorder.py"])
    assert "tests/test_activity_lifecycle_service.py" in sel.pytest_targets, (
        "collector changes must select the lifecycle boundary test"
    )
    assert "tests/test_activity_lifecycle_boundary.py" in sel.pytest_targets, (
        "collector changes must select the static lifecycle boundary test"
    )
    assert "tests/test_collector.py" in sel.pytest_targets
    assert "tests/test_state_machine.py" in sel.pytest_targets
    assert "tests/test_clipboard_service.py" in sel.pytest_targets


def test_app_runtime_py_selects_lifecycle_boundary_suite(runner):
    """N: app_runtime.py shutdown now routes close-all through the
    lifecycle facade (activity_lifecycle_service.close_all_open_activities).
    Changes must trigger the Rule N lifecycle boundary suite in addition
    to the K2 startup/privacy-gate suite. This ensures the static
    boundary test verifies the shutdown path routes close-all through the
    lifecycle facade."""
    sel = runner.select_targets(["worktrace/runtime/app_runtime.py"])
    for expected in (
        "tests/test_activity_lifecycle_service.py",
        "tests/test_activity_lifecycle_boundary.py",
        "tests/test_activity_service.py",
        "tests/test_app_runtime_privacy_gate.py",
        "tests/test_run_affected_tests.py",
        "tests/test_ui_backend_boundary.py",
    ):
        assert expected in sel.pytest_targets, (
            f"app_runtime.py must select N target: {expected}"
        )


# M (strengthened). Bridge overview / timeline -> live display contract


def test_bridge_overview_py_selects_live_display_contract(runner):
    """M (strengthened): bridge_overview.py applies the persisted-open
    overlay to recent items, so changes must trigger the live display
    contract test in addition to the B (bridge) suite."""
    sel = runner.select_targets(["worktrace/webview_ui/bridge_overview.py"])
    assert "tests/test_live_display_contract.py" in sel.pytest_targets, (
        "bridge_overview.py must select the live display contract test"
    )
    assert "tests/test_bridge_refresh_state_and_projection.py" in sel.pytest_targets


def test_bridge_timeline_py_selects_live_display_contract(runner):
    """M (strengthened): bridge_timeline.py applies the persisted-open
    overlay to timeline sessions and detail rows, so changes must
    trigger the live display contract test in addition to the B / D
    suites."""
    sel = runner.select_targets(["worktrace/webview_ui/bridge_timeline.py"])
    assert "tests/test_live_display_contract.py" in sel.pytest_targets, (
        "bridge_timeline.py must select the live display contract test"
    )
    assert "tests/test_bridge_refresh_state_and_projection.py" in sel.pytest_targets


def test_live_display_service_py_selects_run_affected_and_timeline_static(runner):
    """M (strengthened): live_display_service.py changes must also select
    the affected-runner self-test and the Timeline static contract so a
    contract helper change is caught by the static scan."""
    sel = runner.select_targets([
        "worktrace/services/live_display_service.py",
    ])
    assert "tests/test_run_affected_tests.py" in sel.pytest_targets, (
        "live_display_service.py must select the affected-runner self-test"
    )
    assert (
        "tests/webview/test_timeline_static_contract.py" in sel.pytest_targets
    ), "live_display_service.py must select the Timeline static contract"


# Section 六: live-display semantic owner triggers (A2 + M strengthened).
# Changes to ``activity_display_model_service.py`` / ``live_display_service.py``
# / ``live_time_service.py`` MUST select the full live-display regression set.


_LIVE_DISPLAY_OWNER_TARGETS = [
    "tests/test_overview_bundle_and_export_contract.py",
    "tests/test_app_runtime_privacy_gate.py",
    "tests/test_collector_raw_activity_contract.py",
    "tests/test_bridge_refresh_state_and_projection.py",
    "tests/test_live_display_contract.py",
    "tests/test_live_display_projection_contract.py",
    "tests/test_display_model_anti_regression.py",
    "tests/scenarios/live_semantics/",
    "tests/test_run_affected_tests.py",
    "tests/webview/test_heartbeat_projection_contract.py",
    "tests/webview/test_frontend_global_boundaries.py",
    "tests/webview/test_frontend_pure_render_contract.py",
    "tests/test_ui_backend_boundary.py",
]


@pytest.mark.parametrize("changed", [
    "worktrace/services/activity_display_model_service.py",
    "worktrace/services/activity_display_policy.py",
    "worktrace/services/activity_live_clock.py",
    "worktrace/services/activity_display_span.py",
    "worktrace/services/activity_row_overlay.py",
    "worktrace/contracts/live_display_contracts.py",
    "worktrace/services/live_display_service.py",
    "worktrace/services/live_time_service.py",
])
def test_live_display_owner_selects_full_live_display_regression_set(runner, changed):
    """Section 六: changing any of the live-display semantic owner files
    (``activity_display_model_service.py`` / ``live_display_service.py`` /
    ``live_time_service.py``) MUST select the full live-display / ViewModel
    / heartbeat regression set via the A2 and M rules."""
    sel = runner.select_targets([changed])
    for expected in _LIVE_DISPLAY_OWNER_TARGETS:
        assert expected in sel.pytest_targets, (
            f"{changed} must select live-display regression target: {expected}"
        )


@pytest.mark.parametrize("changed", [
    "tests/support/live_semantics_harness.py",
    "tests/support/collector_stream.py",
])
def test_live_semantics_support_helpers_select_scenario_matrix(runner, changed):
    sel = runner.select_targets([changed])
    assert "tests/scenarios/live_semantics/" in sel.pytest_targets
    assert "tests/test_live_product_semantics.py" in sel.pytest_targets
    assert "tests/test_display_model_anti_regression.py" in sel.pytest_targets
    if changed.endswith("collector_stream.py"):
        assert "tests/test_collector.py" in sel.pytest_targets
        assert "tests/test_collector_raw_activity_contract.py" in sel.pytest_targets


def test_frontend_pure_render_guard_runs_with_webview_static_suite(runner):
    sel = runner.select_targets(["worktrace/webview_ui/js/core.js"])
    assert "tests/webview/test_frontend_pure_render_contract.py" in sel.pytest_targets


_DB_ONLY_BOUNDARY_TARGETS = [
    "tests/test_timeline_service.py",
    "tests/test_statistics_service.py",
    "tests/test_overview_bundle_and_export_contract.py",
    "tests/test_bridge_refresh_state_and_projection.py",
    "tests/test_live_display_contract.py",
    "tests/test_display_model_anti_regression.py",
    "tests/webview/test_heartbeat_projection_contract.py",
    "tests/webview/test_frontend_global_boundaries.py",
    "tests/test_ui_backend_boundary.py",
    "tests/test_run_affected_tests.py",
]


@pytest.mark.parametrize("changed", [
    "worktrace/services/timeline_service.py",
    "worktrace/services/statistics_service.py",
    "worktrace/services/export_service.py",
])
def test_db_only_service_selects_live_display_boundary_regression_set(runner, changed):
    """Section 六: changing any DB-only / report-only service
    (``timeline_service.py`` / ``statistics_service.py`` /
    ``export_service.py``) MUST select the live-display boundary +
    DB-only contract regression set via the M rule so a regression that
    re-introduces ``current_activity_snapshot`` reads is caught."""
    sel = runner.select_targets([changed])
    for expected in _DB_ONLY_BOUNDARY_TARGETS:
        assert expected in sel.pytest_targets, (
            f"{changed} must select DB-only boundary target: {expected}"
        )


def test_no_stale_trigger_files_in_rules(runner):
    """Section 六: runner rules MUST NOT contain trigger files that do
    not exist on disk. A stale trigger filename (e.g. a removed API
    module) MUST fail this test so the mapping stays clean.

    Directory triggers (trailing ``/``) are accepted when the directory
    exists. File triggers must resolve to an existing file under the
    repo root. The previously-listed ``worktrace/api/live_display_api.py``
    was removed and MUST NOT reappear in any rule.
    """
    repo_root = runner.REPO_ROOT
    stale: list[str] = []
    for rule in runner.RULES:
        for trigger in rule.get("triggers", []):
            clean = trigger.replace("\\", "/").rstrip("/")
            if not clean:
                continue
            candidate = repo_root / clean
            if not candidate.exists():
                stale.append(f"{rule['id']}: {trigger}")
    assert not stale, (
        "Stale trigger files in runner rules (do not exist on disk): "
        + "; ".join(stale)
    )


def test_removed_live_display_api_py_is_not_a_trigger(runner):
    """Section 六: ``worktrace/api/live_display_api.py`` was removed (the
    file does not exist). It MUST NOT appear in any rule's triggers so
    the runner never silently skips it."""
    for rule in runner.RULES:
        assert "worktrace/api/live_display_api.py" not in rule.get("triggers", []), (
            f"{rule['id']} must not reference removed worktrace/api/live_display_api.py"
        )


def test_webview_resource_change_adds_webview_static_marker_shard(runner):
    sel = runner.select_targets(["worktrace/webview_ui/js/timeline.js"])
    assert "tests/webview/" in sel.pytest_targets
    assert "webview_static and contract" in sel.marker_exprs


def test_live_display_owner_adds_live_display_marker_shard(runner):
    sel = runner.select_targets(["worktrace/services/live_display_service.py"])
    assert "tests/test_live_display_contract.py" in sel.pytest_targets
    assert "live_display and contract" in sel.marker_exprs


def test_collector_change_adds_collector_runtime_marker_shard(runner):
    sel = runner.select_targets(["worktrace/collector/collector.py"])
    assert "tests/test_collector.py" in sel.pytest_targets
    assert "collector_runtime and integration" in sel.marker_exprs


def test_security_change_adds_security_privacy_marker_shard(runner):
    sel = runner.select_targets(["worktrace/security/crypto.py"])
    assert "tests/test_security_crypto.py" in sel.pytest_targets
    assert "security_privacy" in sel.marker_exprs


def test_packaging_change_adds_packaging_marker_shard(runner):
    sel = runner.select_targets(["WorkTrace.spec"])
    assert "tests/test_webview_packaging.py" in sel.pytest_targets
    assert "packaging" in sel.marker_exprs


def test_no_changed_files_stays_light_smoke_not_full_suite(runner):
    sel = runner.select_targets([])
    assert sel.pytest_targets == [
        "tests/test_startup_imports.py",
        "tests/test_ui_backend_boundary.py",
        "tests/webview/",
        "tests/test_comment_hygiene.py",
    ]
    assert sel.marker_exprs == []
    command = runner.build_pytest_command(sel.pytest_targets, [])
    assert command != ["python", "-m", "pytest"]


def test_all_command_is_explicit_full_suite(runner):
    assert runner.build_pytest_command([], []) == ["python", "-m", "pytest"]


def test_unknown_worktrace_source_warns_without_full_suite_or_marker_shard(runner):
    sel = runner.select_targets(["worktrace/new_module.py"])
    assert "tests/test_startup_imports.py" in sel.pytest_targets
    assert "tests/test_ui_backend_boundary.py" in sel.pytest_targets
    assert sel.marker_exprs == []
    assert any("Unknown worktrace/ source changed" in w for w in sel.warnings)


def test_fast_suite_command_is_marker_covered_feedback(runner, capsys):
    assert runner.main(["--fast", "--print-only"]) == 0
    out = capsys.readouterr().out
    assert "python -m pytest -m 'unit and not slow'" in out
    assert "marker-covered fast feedback only" in out


def test_governance_suite_stays_focused(runner, capsys):
    assert runner.main(["--governance", "--print-only"]) == 0
    out = capsys.readouterr().out
    assert "python scripts/test_inventory.py --check" in out
    assert "python scripts/comment_hygiene.py --check" in out
    assert "tests/test_run_affected_tests.py" in out
    assert "tests/test_test_inventory.py" in out
    assert "python -m pytest" in out
    assert "python -m pytest'" not in out


def test_canonical_projection_files_select_cross_layer_suite(runner):
    required = {
        "tests/test_report_projection_cutover.py",
        "tests/test_projection_governance_regressions.py",
        "tests/test_projection_plain_dto_contract.py",
        "tests/test_timeline_api_editing.py",
        "tests/test_project_delete_contract.py",
        "tests/test_statistics_service.py",
        "tests/test_statistics_csv_export.py",
    }
    for changed in runner.CANONICAL_REPORT_PROJECTION_TRIGGERS:
        selection = runner.select_targets([changed])
        assert required <= set(selection.pytest_targets), (
            f"{changed} must select the canonical cross-layer suite"
        )


def test_secure_validation_and_write_gate_select_security_regressions(runner):
    for changed in (
        "worktrace/services/secure_backup_validation.py",
        "worktrace/write_gate.py",
    ):
        selection = runner.select_targets([changed])
        assert "tests/test_secure_backup_service.py" in selection.pytest_targets
        assert "tests/test_projection_governance_regressions.py" in selection.pytest_targets

