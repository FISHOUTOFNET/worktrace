from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.contract, pytest.mark.parallel_safe]

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"


def _root_name(node: ast.AST) -> str | None:
    current = node
    while isinstance(current, ast.Attribute):
        current = current.value
    return current.id if isinstance(current, ast.Name) else None


def _production_imports(tree: ast.Module) -> tuple[set[str], set[str]]:
    modules: set[str] = set()
    symbols: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "worktrace" or alias.name.startswith("worktrace."):
                    modules.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module == "worktrace" or module.startswith("worktrace."):
                for alias in node.names:
                    if alias.name != "*":
                        symbols.add(alias.asname or alias.name)
    return modules, symbols


def test_tests_use_static_explicit_composition() -> None:
    offenders: list[str] = []
    for path in sorted(TESTS.rglob("*.py")):
        if path == Path(__file__).resolve():
            continue
        relative = path.relative_to(ROOT).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        production_modules, production_symbols = _production_imports(tree)

        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and any(
                alias.name == "*" for alias in node.names
            ):
                offenders.append(f"{relative}:{node.lineno}:import-star")

            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id == "globals":
                    offenders.append(f"{relative}:{node.lineno}:globals-injection")
                if (
                    isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "runpy"
                    and node.func.attr == "run_path"
                ):
                    offenders.append(f"{relative}:{node.lineno}:runpy-forwarding")

            targets: list[ast.expr] = []
            if isinstance(node, ast.Assign):
                targets.extend(node.targets)
            elif isinstance(node, ast.AnnAssign):
                targets.append(node.target)
            elif isinstance(node, ast.AugAssign):
                targets.append(node.target)
            for target in targets:
                if isinstance(target, ast.Name) and target.id in production_symbols:
                    offenders.append(
                        f"{relative}:{node.lineno}:production-symbol-reassignment"
                    )
                elif isinstance(target, ast.Attribute):
                    root = _root_name(target)
                    if root in production_modules or target.attr == "WebViewBridge":
                        offenders.append(
                            f"{relative}:{node.lineno}:production-attribute-reassignment"
                        )

    assert offenders == []


def test_support_modules_do_not_construct_no_arg_production_bridge() -> None:
    offenders: list[str] = []
    support = TESTS / "support"
    for path in sorted(support.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        bridge_names: set[str] = set()
        for node in tree.body:
            if (
                isinstance(node, ast.ImportFrom)
                and node.module == "worktrace.webview_ui.bridge"
            ):
                bridge_names.update(
                    alias.asname or alias.name
                    for alias in node.names
                    if alias.name == "WebViewBridge"
                )
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in bridge_names
                and not node.args
                and not node.keywords
            ):
                offenders.append(
                    f"{path.relative_to(ROOT).as_posix()}:{node.lineno}"
                )
    assert offenders == []


def test_project_rules_bridge_tests_are_defined_in_the_collectable_file() -> None:
    path = TESTS / "test_webview_project_rules_bridge.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports = {
        alias.asname or alias.name
        for node in tree.body
        if isinstance(node, ast.ImportFrom)
        and node.module == "tests.support.application"
        for alias in node.names
    }
    assert "build_test_bridge" in imports
    assert not any(
        isinstance(node, ast.ImportFrom)
        and node.module == "worktrace.webview_ui.bridge"
        and any(alias.name == "WebViewBridge" for alias in node.names)
        for node in tree.body
    )
    assert all(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        for node in tree.body
        if getattr(node, "name", "").startswith("test_")
    )
    assert any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name.startswith("test_")
        for node in tree.body
    )
    assert not (TESTS / "support" / "project_rules_bridge_contract_cases.py").exists()
