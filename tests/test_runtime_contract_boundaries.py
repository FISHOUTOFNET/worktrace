from __future__ import annotations

import ast
import importlib
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.contract, pytest.mark.collector_runtime]

ROOT = Path(__file__).resolve().parents[1]


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
    return imported


def test_api_layer_does_not_import_concrete_app_runtime() -> None:
    api_root = ROOT / "worktrace" / "api"
    violations: list[str] = []
    for path in sorted(api_root.rglob("*.py")):
        if "worktrace.runtime.app_runtime" in _imports(path):
            violations.append(path.relative_to(ROOT).as_posix())
    assert violations == []


def test_runtime_contracts_have_only_neutral_dependencies() -> None:
    path = ROOT / "worktrace" / "runtime" / "contracts.py"
    assert _imports(path) <= {"__future__", "dataclasses", "enum"}


def test_retired_app_runtime_contract_exports_do_not_exist() -> None:
    module = importlib.import_module("worktrace.runtime.app_runtime")
    for retired_name in (
        "RuntimeStartResult",
        "WorkerStartupState",
        "WorkerStartupStatus",
    ):
        assert not hasattr(module, retired_name)


def test_application_composition_imports_without_runtime_cycle() -> None:
    importlib.import_module("tests.support.application")
    importlib.import_module("worktrace.api.application_services")
