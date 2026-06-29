"""Pure-function tests for the affected-test runner (Phase TG1).

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


# ---------------------------------------------------------------------------
# A / C. rules.js -> Project Rules static contract + bridge + boundary + webview
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# B. bridge.py -> bridge tests + boundary
# ---------------------------------------------------------------------------


def test_bridge_py_selects_bridge_tests_and_boundary(runner):
    sel = runner.select_targets(["worktrace/webview_ui/bridge.py"])
    assert "tests/test_webview_bridge.py" in sel.pytest_targets
    assert "tests/test_webview_project_rules_bridge.py" in sel.pytest_targets
    assert "tests/test_webview_bridge_merge.py" in sel.pytest_targets
    assert "tests/test_webview_bridge_batch_project.py" in sel.pytest_targets
    assert "tests/test_webview_bridge_batch_note.py" in sel.pytest_targets
    assert "tests/test_webview_bridge_restore.py" in sel.pytest_targets
    assert "tests/test_ui_backend_boundary.py" in sel.pytest_targets
    # Phase 6A: bridge.py is also a K1 trigger (Settings / Privacy WebView),
    # so K1 contributes the import smoke command and the Settings tests /
    # boundary. bridge.py itself is not a frontend resource, so the smoke
    # is added only because K1 matches the path.
    assert "tests/test_settings_privacy_status.py" in sel.pytest_targets
    assert "tests/webview/test_settings_static_contract.py" in sel.pytest_targets
    assert any(
        "import worktrace.webview_main" in " ".join(s) for s in sel.smoke_commands
    )


# ---------------------------------------------------------------------------
# C. rule_api.py -> Project Rules keyword + folder API/service/bridge tests
# (Phase TG2: rule_api.py no longer triggers frontend/static contract tests;
#  it triggers C2 keyword + C3 folder + bridge + boundary only.)
# ---------------------------------------------------------------------------


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
    # Phase TG2: rule_api.py changes must NOT unconditionally run frontend
    # static contract tests; those run only when bridge_rules.py or rules*.js
    # change (sections C5 / C6 / A).
    sel = runner.select_targets(["worktrace/api/rule_api.py"])
    assert "tests/webview/test_project_rules_static_contract.py" not in sel.pytest_targets


def test_rule_api_py_does_not_trigger_project_lifecycle_tests(runner):
    # Phase TG2: rule_api.py (keyword/folder facades) must NOT trigger
    # project lifecycle tests; those run only when project_api.py or
    # project_service.py change (section C4).
    sel = runner.select_targets(["worktrace/api/rule_api.py"])
    assert "tests/test_project_rules_project_lifecycle.py" not in sel.pytest_targets


# ---------------------------------------------------------------------------
# C1. _write_contract.py -> broad Project Rules suite (shared helper)
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# C2. rule_service.py -> keyword rule tests (no folder, no lifecycle, no static)
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# C3. folder_rule_service.py -> folder rule tests (no keyword, no lifecycle)
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# C4. project_api.py / project_service.py -> project lifecycle tests only
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# C5. bridge_rules.py -> Project Rules bridge tests + boundary only
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# C6. rules_project_actions.js -> Project Rules static contract + smoke
# ---------------------------------------------------------------------------


def test_rules_project_actions_js_selects_static_contract_and_smoke(runner):
    sel = runner.select_targets(["worktrace/webview_ui/js/rules_project_actions.js"])
    # rules_project_actions.js triggers section A (frontend resources, broad)
    # AND section C6 (Project Rules static contract). Both contribute the
    # static contract target; dedup ensures it appears once.
    assert "tests/webview/test_project_rules_static_contract.py" in sel.pytest_targets
    assert "tests/webview/" in sel.pytest_targets
    assert "tests/test_webview_bridge.py" in sel.pytest_targets
    assert "tests/test_ui_backend_boundary.py" in sel.pytest_targets
    assert any(
        "import worktrace.webview_main" in " ".join(s) for s in sel.smoke_commands
    )


# ---------------------------------------------------------------------------
# C6 (Phase MC2). New split modules -> Project Rules static contract + smoke
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("js_module", [
    "worktrace/webview_ui/js/rules_render.js",
    "worktrace/webview_ui/js/rules_rule_actions.js",
    "worktrace/webview_ui/js/rules_keyword_actions.js",
    "worktrace/webview_ui/js/rules_folder_actions.js",
])
def test_mc2_split_module_selects_static_contract_and_smoke(runner, js_module):
    # Phase MC2: each new split module must trigger section A (frontend
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
def test_mc2_split_module_does_not_trigger_api_or_service_tests(runner, js_module):
    # Phase MC2: a pure frontend JS change must not unconditionally
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


# ---------------------------------------------------------------------------
# C7. rule_impact_service.py -> rule impact tests + bridge + boundary (Phase 5H)
# ---------------------------------------------------------------------------


def test_rule_impact_service_py_selects_impact_tests(runner):
    # Phase 5H: the new rule_impact_service.py triggers the impact test
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


# ---------------------------------------------------------------------------
# C8. rule_automation_service.py -> automatic rules tests + bridge + boundary
# (Phase 5I)
# ---------------------------------------------------------------------------


def test_rule_automation_service_py_selects_automatic_rules_tests(runner):
    # Phase 5I: the new rule_automation_service.py (thin facade delegating to
    # project_inference_service.process_new_activity) triggers the automatic
    # rules test file plus the bridge and boundary tests. It must not trigger
    # keyword/folder CRUD/lifecycle/impact/static tests since the facade is
    # scoped to the automatic application path only.
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


# ---------------------------------------------------------------------------
# C9. rule_batch_service.py -> batch operations tests + bridge + boundary
# (Phase 5I)
# ---------------------------------------------------------------------------


def test_rule_batch_service_py_selects_batch_operations_tests(runner):
    # Phase 5I: the new rule_batch_service.py triggers the batch operations
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


# ---------------------------------------------------------------------------
# I. docs-only -> not full pytest
# ---------------------------------------------------------------------------


def test_docs_only_does_not_select_full_pytest(runner):
    sel = runner.select_targets(["docs/some-note.md"])
    # Finite target set, not a bare full-suite invocation.
    assert sel.pytest_targets, "docs-only should select a finite target set"
    assert "tests/test_release_docs.py" in sel.pytest_targets
    cmd = runner.build_pytest_command(sel.pytest_targets, [])
    assert cmd != ["python", "-m", "pytest"], "docs-only must not be full suite"


def test_docs_directory_prefix_matches(runner):
    sel = runner.select_targets(["docs/current-state.md"])
    assert "tests/test_release_docs.py" in sel.pytest_targets


# ---------------------------------------------------------------------------
# F. DB/schema -> broad suite + warning
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# L. test file changes -> run that test file directly
# ---------------------------------------------------------------------------


def test_changed_test_file_runs_directly(runner):
    sel = runner.select_targets(["tests/test_rule_service.py"])
    assert "tests/test_rule_service.py" in sel.pytest_targets


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


# ---------------------------------------------------------------------------
# K. unknown worktrace/ source -> smoke + boundary + warning
# ---------------------------------------------------------------------------


def test_unknown_worktrace_source_selects_smoke_and_boundary(runner):
    sel = runner.select_targets(["worktrace/formatters.py"])
    assert "tests/test_startup_imports.py" in sel.pytest_targets
    assert "tests/test_ui_backend_boundary.py" in sel.pytest_targets
    assert any("Unknown worktrace/" in w for w in sel.warnings), (
        "expected unknown-source warning"
    )


# ---------------------------------------------------------------------------
# H. collector / platform / resource model
# ---------------------------------------------------------------------------


def test_resource_helper_change_selects_resource_tests(runner):
    sel = runner.select_targets(["worktrace/resources/resource_helpers.py"])
    assert "tests/test_resource_helpers.py" in sel.pytest_targets
    assert "tests/test_resource_model.py" in sel.pytest_targets
    assert "tests/test_startup_imports.py" in sel.pytest_targets


def test_collector_directory_prefix_matches(runner):
    sel = runner.select_targets(["worktrace/collector/state_machine.py"])
    assert "tests/test_collector.py" in sel.pytest_targets


# ---------------------------------------------------------------------------
# existing_targets filtering
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# De-duplication + stable order
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# build_pytest_command
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# No changed files -> light smoke set (not full suite)
# ---------------------------------------------------------------------------


def test_no_changed_files_uses_smoke_set(runner):
    sel = runner.select_targets([])
    assert "tests/test_startup_imports.py" in sel.pytest_targets
    assert "tests/test_ui_backend_boundary.py" in sel.pytest_targets
    assert "tests/webview/" in sel.pytest_targets
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


# ---------------------------------------------------------------------------
# Normalization + misc invariants
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# K1 (Phase 6A). Settings / Privacy WebView -> settings + boundary + packaging
# ---------------------------------------------------------------------------


def test_settings_api_py_selects_settings_tests(runner):
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


def test_settings_html_css_init_select_settings_tests(runner):
    """Phase 6A: index.html / styles.css / init.js triggers all share the
    K1 settings target set."""
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
    """Phase 6A: K1 must NOT trigger the Project Rules C-series suite."""
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
