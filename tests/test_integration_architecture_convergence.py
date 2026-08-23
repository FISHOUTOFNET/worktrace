"""Static ownership contracts for optional integration convergence."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from worktrace.api.application_capabilities import RulesApplicationService


pytestmark = [pytest.mark.contract]

ROOT = Path(__file__).resolve().parents[1]


def _source(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def _imports(module_path: Path) -> set[str]:
    tree = ast.parse(module_path.read_text(encoding="utf-8"), filename=str(module_path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            dots = "." * node.level
            found.add(dots + (node.module or ""))
    return found


def test_api_modules_never_import_fd_work_integration() -> None:
    violations = {}
    for path in sorted((ROOT / "worktrace" / "api").glob("*.py")):
        matches = sorted(
            name for name in _imports(path) if "integrations.fd_work" in name
        )
        if matches:
            violations[path.name] = matches
    assert violations == {}


def test_rules_application_service_has_no_integration_product_knowledge() -> None:
    source = inspect.getsource(RulesApplicationService)
    for forbidden in (
        "FDWork",
        "fd_work",
        "case_selection",
        "picker",
        "adapter_contract_version",
    ):
        assert forbidden not in source


def test_concrete_fd_work_is_instantiated_only_by_composition_root() -> None:
    allowed = {Path("worktrace/runtime/application_services.py")}
    violations = []
    for path in sorted((ROOT / "worktrace").rglob("*.py")):
        relative = path.relative_to(ROOT)
        if relative in allowed:
            continue
        if "FDWorkIntegrationService(" in path.read_text(encoding="utf-8"):
            violations.append(relative.as_posix())
    assert violations == []


def test_fd_work_integration_does_not_own_generic_project_routing() -> None:
    source = _source("worktrace/integrations/fd_work/integration_service.py")
    tree = ast.parse(source)
    service = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "FDWorkIntegrationService"
    )
    methods = {
        node.name
        for node in service.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert methods.isdisjoint(
        {"create_project", "update_project", "list_project_identities"}
    )
    assert {
        "create_bound_project",
        "rebind_project",
        "list_bound_project_ids",
        "clear_project_identity",
    }.issubset(methods)


def test_privacy_coordinator_is_integration_agnostic() -> None:
    source = _source("worktrace/runtime/post_privacy_startup.py")
    assert "fd_work" not in source
    assert "FDWork" not in source
    assert "participants" in source


def test_main_window_delivery_uses_one_typed_sink() -> None:
    source = _source("worktrace/webview_main.py")
    assert "report_fd_work_status" not in source
    assert "report_fd_work_picker_result" not in source
    assert "FDWorkMainWindowSink" in source


def test_generation_reset_delegates_page_state_to_static_lifecycle_hooks() -> None:
    source = _source("worktrace/webview_ui/js/init_fd_work_v5.js")
    start = source.index("function resetClientGeneration")
    end = source.index("App.resetClientGeneration", start)
    body = source[start:end]
    for private_state in (
        "timelineAutosaveQueued",
        "statisticsDraftSelection",
        "rulesLoadPromise",
        "settingsLoaded",
    ):
        assert private_state not in body
    assert "App.pageLifecycle.resetGeneration()" in body
    assert "App.fdWork.resetGeneration" in body
    for page_private_hook in (
        "App.timeline.resetGeneration",
        "App.statistics.resetGeneration",
        "App.rules.resetGeneration",
        "App.settings.resetGeneration",
    ):
        assert page_private_hook not in body


def test_project_rules_uses_narrow_identity_editor_boundary() -> None:
    source = _source("worktrace/webview_ui/js/rules_create_panel_v5.js")
    for leaked_state in (
        "rulesFDWorkSelectionToken",
        "rulesFDWorkSelectedLabel",
        "rulesFDWorkPickerRequestId",
        "rulesFDWorkPickerDrawerSession",
        "rulesFDWorkPickerPending",
    ):
        assert leaked_state not in source
    assert "App.projectIdentity" in source
