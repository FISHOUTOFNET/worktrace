from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.contract, pytest.mark.parallel_safe]

ROOT = Path(__file__).resolve().parents[1]
PRODUCTION = ROOT / "worktrace"
MAINTENANCE = "worktrace/services/database_maintenance_service.py"


def _python_files() -> list[Path]:
    return sorted(PRODUCTION.rglob("*.py"))


def _relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _attribute_callers(attribute: str) -> set[str]:
    callers: set[str] = set()
    for path in _python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        if any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == attribute
            for node in ast.walk(tree)
        ):
            callers.add(_relative(path))
    return callers


def _method(path: Path, class_name: str, method_name: str) -> ast.FunctionDef:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    owner = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == class_name
    )
    return next(
        node
        for node in owner.body
        if isinstance(node, ast.FunctionDef) and node.name == method_name
    )


def _function(path: Path, function_name: str) -> ast.FunctionDef:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == function_name
    )


def _called_attributes(node: ast.AST) -> set[str]:
    return {
        call.func.attr
        for call in ast.walk(node)
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
    }


def test_recovery_write_capability_has_one_production_owner() -> None:
    assert _attribute_callers("_maintenance_recovery_write_scope") == {MAINTENANCE}
    assert _attribute_callers("_set_recovery_block") == {MAINTENANCE}
    assert _attribute_callers("_clear_recovery_block") == {MAINTENANCE}


def test_write_gate_has_current_only_state_queries() -> None:
    path = PRODUCTION / "write_gate.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    gate = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "ProcessDatabaseWriteGate"
    )
    methods = {
        node.name
        for node in gate.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert {"operation_active", "recovery_blocked", "writes_blocked"}.issubset(methods)
    assert "active" not in methods
    assert "allow_recovery_write" not in methods


def test_coordinator_does_not_duplicate_recovery_reason_state() -> None:
    path = PRODUCTION / "services" / "database_maintenance_service.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    coordinator = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "RuntimeMaintenanceCoordinator"
    )
    attributes = {
        node.attr
        for node in ast.walk(coordinator)
        if isinstance(node, ast.Attribute)
    }
    assert "_blocked_reason" not in attributes


def test_app_runtime_hydrates_latch_before_startup_recovery() -> None:
    path = PRODUCTION / "runtime" / "app_runtime.py"
    initialize = _method(path, "AppRuntime", "initialize")
    calls = {
        node.func.attr: node.lineno
        for node in ast.walk(initialize)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr
        in {
            "initialize_database",
            "register_runtime_control",
            "hydrate_fail_closed_from_durable",
            "recover_unclosed_records",
        }
    }
    assert calls.keys() == {
        "initialize_database",
        "register_runtime_control",
        "hydrate_fail_closed_from_durable",
        "recover_unclosed_records",
    }
    assert (
        calls["initialize_database"]
        < calls["register_runtime_control"]
        < calls["hydrate_fail_closed_from_durable"]
        < calls["recover_unclosed_records"]
    )


def test_no_production_caller_uses_retired_write_gate_active_alias() -> None:
    offenders: list[str] = []
    for path in _python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr != "active":
                continue
            value = node.func.value
            if isinstance(value, ast.Name) and value.id == "DATABASE_WRITE_GATE":
                offenders.append(f"{_relative(path)}:{node.lineno}")
    assert offenders == []


def test_durable_latch_repository_is_only_imported_by_maintenance_owner() -> None:
    importers: set[str] = set()
    for path in _python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and any(
                alias.name == "maintenance_recovery_latch_repository"
                for alias in node.names
            ):
                importers.add(_relative(path))
            if isinstance(node, ast.Import) and any(
                alias.name.endswith("maintenance_recovery_latch_repository")
                for alias in node.names
            ):
                importers.add(_relative(path))
    assert importers == {MAINTENANCE}


def test_explicit_recovery_surface_routes_to_the_single_maintenance_owner() -> None:
    settings_path = PRODUCTION / "api" / "settings_api.py"
    settings_recovery = _function(
        settings_path,
        "recover_database_maintenance_for_webview",
    )
    assert "recover_fail_closed" in _called_attributes(settings_recovery)

    bridge_path = PRODUCTION / "webview_ui" / "bridge_settings.py"
    bridge_recovery = _method(
        bridge_path,
        "SettingsBridgeMixin",
        "recover_database_maintenance",
    )
    assert (
        "recover_database_maintenance_for_webview"
        in _called_attributes(bridge_recovery)
    )

    shipping = (PRODUCTION / "webview_ui" / "bridge.py").read_text(encoding="utf-8")
    assert '"recover_database_maintenance"' in shipping
