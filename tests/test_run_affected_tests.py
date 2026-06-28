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
    # bridge.py is not a frontend resource, so no import smoke.
    assert sel.smoke_commands == []


# ---------------------------------------------------------------------------
# C. rule_api.py -> Project Rules API/service/bridge/static tests
# ---------------------------------------------------------------------------


def test_rule_api_py_selects_project_rules_suite(runner):
    sel = runner.select_targets(["worktrace/api/rule_api.py"])
    for expected in [
        "tests/test_rule_service.py",
        "tests/test_folder_rule_service.py",
        "tests/test_project_rules_keyword_create.py",
        "tests/test_project_rules_keyword_delete.py",
        "tests/test_webview_project_rules_bridge.py",
        "tests/test_project_rules_view.py",
        "tests/webview/test_project_rules_static_contract.py",
        "tests/test_ui_backend_boundary.py",
    ]:
        assert expected in sel.pytest_targets, f"missing {expected}"


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
