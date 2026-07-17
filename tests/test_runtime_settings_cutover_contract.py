"""Contracts for the typed runtime-state / durable-settings cutover."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = [pytest.mark.contract, pytest.mark.unit]
ROOT = Path(__file__).resolve().parents[1]
RUNTIME_KEYS = {
    "current_activity_snapshot",
    "pending_short_seconds",
    "pending_short_carry_provenance",
}
FORBIDDEN_RUNTIME_SYMBOLS = {
    "CURRENT_ACTIVITY_SNAPSHOT_KEY",
    "PENDING_SHORT_SECONDS_KEY",
    "PENDING_CARRY_PROVENANCE_KEY",
    "read_runtime_activity_snapshot_raw",
    "restore_runtime_activity_snapshot",
    "get_legacy_runtime_setting",
    "set_legacy_runtime_setting",
}


def _definitions(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }


def test_runtime_owner_has_no_raw_or_pending_compatibility_surface() -> None:
    path = ROOT / "worktrace" / "services" / "runtime_activity_state_service.py"
    source = path.read_text(encoding="utf-8")
    assert _definitions(path).isdisjoint(FORBIDDEN_RUNTIME_SYMBOLS)
    for value in FORBIDDEN_RUNTIME_SYMBOLS | RUNTIME_KEYS:
        assert value not in source


def test_settings_service_has_no_runtime_key_router() -> None:
    source = (
        ROOT / "worktrace" / "services" / "settings_service.py"
    ).read_text(encoding="utf-8")
    assert "_RUNTIME_ONLY_KEYS" not in source
    assert "runtime_activity_state_service" not in source
    for key in RUNTIME_KEYS:
        assert key not in source


def test_secure_backup_never_restores_pre_import_runtime_snapshot() -> None:
    source = (
        ROOT / "worktrace" / "services" / "secure_backup_service.py"
    ).read_text(encoding="utf-8")
    assert "restore_runtime_activity_snapshot" not in source
    assert "_snapshot_is_safe_to_restore" not in source
    assert "prior_snapshot" not in source


def _runtime_setting_calls(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    direct: dict[str, str] = {}
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module == "worktrace.services.settings_service":
                for item in node.names:
                    if item.name in {"get_setting", "set_setting"}:
                        direct[item.asname or item.name] = item.name
            elif node.module == "worktrace.services":
                for item in node.names:
                    if item.name == "settings_service":
                        modules.add(item.asname or item.name)
        elif isinstance(node, ast.Import):
            for item in node.names:
                if item.name == "worktrace.services.settings_service":
                    modules.add(item.asname or "settings_service")
    violations: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        name = None
        if isinstance(node.func, ast.Name):
            name = direct.get(node.func.id)
        elif (
            isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id in modules
            and node.func.attr in {"get_setting", "set_setting"}
        ):
            name = node.func.attr
        first = node.args[0]
        if (
            name is not None
            and isinstance(first, ast.Constant)
            and first.value in RUNTIME_KEYS
        ):
            violations.append(f"{path.relative_to(ROOT)}:{node.lineno}: {name}({first.value})")
    return violations


def test_production_and_tests_do_not_route_runtime_state_through_settings() -> None:
    violations: list[str] = []
    for root_name in ("worktrace", "tests"):
        for path in sorted((ROOT / root_name).rglob("*.py")):
            if path.name in {
                "runtime_state_fixture.py",
                "test_runtime_settings_cutover_contract.py",
            }:
                continue
            violations.extend(_runtime_setting_calls(path))
    assert not violations, "runtime settings calls remain:\n" + "\n".join(violations)
