from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.contract

REPO_ROOT = Path(__file__).resolve().parents[1]

REPORT_PROJECTION_MODULES = [
    "worktrace/services/statistics_service.py",
    "worktrace/services/export_service.py",
    "worktrace/exports/excel_exporter.py",
    "worktrace/services/view_model_service.py",
]

OFFICIAL_ONLY_ACTIVITY_HELPERS = {
    "get_activities_by_range",
    "get_activities_by_date",
}


def test_report_projection_modules_do_not_use_activity_service_official_only_queries():
    violations: list[str] = []
    for relative_path in REPORT_PROJECTION_MODULES:
        path = REPO_ROOT / relative_path
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                imported = {alias.name for alias in node.names}
                if (
                    str(node.module or "").endswith("activity_service")
                    and imported & OFFICIAL_ONLY_ACTIVITY_HELPERS
                ):
                    names = ", ".join(sorted(imported & OFFICIAL_ONLY_ACTIVITY_HELPERS))
                    violations.append(f"{relative_path}: imports {names}")
            elif isinstance(node, ast.Call):
                func = node.func
                if (
                    isinstance(func, ast.Attribute)
                    and func.attr in OFFICIAL_ONLY_ACTIVITY_HELPERS
                    and isinstance(func.value, ast.Name)
                    and func.value.id == "activity_service"
                ):
                    violations.append(
                        f"{relative_path}:{node.lineno} calls activity_service.{func.attr}"
                    )
                elif (
                    isinstance(func, ast.Name)
                    and func.id in OFFICIAL_ONLY_ACTIVITY_HELPERS
                ):
                    violations.append(f"{relative_path}:{node.lineno} calls {func.id}")

    assert violations == []
