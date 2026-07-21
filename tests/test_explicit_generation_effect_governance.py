from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PRODUCTION_ROOT = ROOT / "worktrace"
pytestmark = [pytest.mark.unit, pytest.mark.contract, pytest.mark.parallel_safe]


def _production_python_files() -> list[Path]:
    return sorted(PRODUCTION_ROOT.rglob("*.py"))


def test_domain_unit_of_work_contains_no_connection_counter_inference() -> None:
    source = (PRODUCTION_ROOT / "domain_unit_of_work.py").read_text(encoding="utf-8")
    assert "total_changes" not in source
    assert "_initial_total_changes" not in source


def test_production_mark_changed_calls_always_name_an_effect() -> None:
    violations: list[str] = []
    for path in _production_python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            function = node.func
            name = function.attr if isinstance(function, ast.Attribute) else (
                function.id if isinstance(function, ast.Name) else ""
            )
            if name == "mark_changed" and not node.args:
                violations.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    assert violations == []


def test_generation_effects_are_not_inferred_from_sql_text() -> None:
    forbidden_names = {
        "infer_generation_effect",
        "classify_generation_from_sql",
        "generation_effect_from_sql",
    }
    violations: list[str] = []
    for path in _production_python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name in forbidden_names:
                    violations.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    assert violations == []
