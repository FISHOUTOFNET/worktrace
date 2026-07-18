from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from worktrace.collector import collector as collector_module


pytestmark = [pytest.mark.unit, pytest.mark.contract]

ROOT = Path(__file__).resolve().parents[1]
PRODUCTION = ROOT / "worktrace"

_BANNED_FUNCTION_DEFINITIONS = {
    "apply_rules_to_activity",
    "apply_rules_to_unclassified",
    "backfill_missing_assignments",
    "get_activity_structure_marker_by_date",
    "get_activity_structure_markers",
    "get_or_create_excluded_project",
    "get_or_create_uncategorized_project",
    "invalidate_uncategorized_project_cache",
    "record_hard_boundary",
    "record_runtime_boundary",
    "update_project_editable_activities_project",
    "update_project_editable_activity_note",
}


def _python_files() -> list[Path]:
    return sorted(PRODUCTION.rglob("*.py"))


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _call_name(call: ast.Call) -> str:
    target = call.func
    if isinstance(target, ast.Name):
        return target.id
    if isinstance(target, ast.Attribute):
        return target.attr
    return ""


def test_composition_root_imports_only_canonical_windows_adapter() -> None:
    runtime = _tree(PRODUCTION / "runtime" / "app_runtime.py")
    imports = {
        (node.module or "", alias.name)
        for node in ast.walk(runtime)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    assert ("platforms.windows_adapter", "WindowsAdapter") in {
        (module.lstrip("."), name) for module, name in imports
    }
    assert not (PRODUCTION / "platforms" / "hardened_windows_adapter.py").exists()
    assert all(
        "hardened_windows_adapter" not in path.read_text(encoding="utf-8")
        for path in _python_files()
    )


def test_retired_aliases_wrappers_and_backfills_cannot_return() -> None:
    definitions: dict[str, list[str]] = {}
    for path in _python_files():
        relative = path.relative_to(ROOT).as_posix()
        for node in ast.walk(_tree(path)):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                definitions.setdefault(node.name, []).append(relative)
    assert not (_BANNED_FUNCTION_DEFINITIONS & definitions.keys())
    assert not (PRODUCTION / "services" / "folder_index_recovery_service.py").exists()


def test_production_cannot_silently_swallow_broad_exceptions() -> None:
    offenders: list[str] = []
    for path in _python_files():
        relative = path.relative_to(ROOT).as_posix()
        for node in ast.walk(_tree(path)):
            if not isinstance(node, ast.ExceptHandler):
                continue
            if not isinstance(node.type, ast.Name) or node.type.id != "Exception":
                continue
            if len(node.body) == 1 and isinstance(node.body[0], ast.Pass):
                offenders.append(f"{relative}:{node.lineno}")
    assert offenders == []


def test_connection_accepting_boundaries_use_the_supplied_connection() -> None:
    offenders: list[str] = []
    for path in sorted((PRODUCTION / "services").rglob("*.py")):
        relative = path.relative_to(ROOT).as_posix()
        for function in (
            node
            for node in ast.walk(_tree(path))
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ):
            parameter_names = {
                argument.arg
                for argument in (*function.args.posonlyargs, *function.args.args)
                if argument.arg in {"conn", "connection", "business_conn"}
            }
            if not parameter_names:
                continue
            loaded_names = {
                node.id
                for node in ast.walk(function)
                if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
            }
            for parameter in parameter_names:
                if parameter not in loaded_names:
                    offenders.append(f"{relative}:{function.name}:{parameter}")
    assert offenders == []


def test_folder_index_query_has_no_write_or_filesystem_capability() -> None:
    query_path = PRODUCTION / "services" / "folder_index_query_service.py"
    tree = _tree(query_path)
    imported_roots = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imported_roots.update(
        (node.module or "").split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    )
    assert not ({"os", "pathlib", "time"} & imported_roots)
    forbidden_calls = {
        "mark_index_stale",
        "request_rebuild_for_rule",
        "request_refresh_for_enabled_rules",
    }
    assert not {
        _call_name(node)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
    } & forbidden_calls
    dml = re.compile(r"^\s*(INSERT|UPDATE|DELETE|REPLACE|CREATE|DROP|ALTER)\b", re.I)
    assert not {
        value.value
        for value in ast.walk(tree)
        if isinstance(value, ast.Constant)
        and isinstance(value.value, str)
        and dml.match(value.value)
    }


def test_normal_api_cannot_repair_system_catalog() -> None:
    offenders: list[str] = []
    for path in sorted((PRODUCTION / "api").rglob("*.py")):
        relative = path.relative_to(ROOT).as_posix()
        for node in ast.walk(_tree(path)):
            if isinstance(node, ast.Call) and _call_name(node) == "ensure_system_projects":
                offenders.append(relative)
            if isinstance(node, ast.ImportFrom) and any(
                alias.name == "ensure_system_projects" for alias in node.names
            ):
                offenders.append(relative)
    assert offenders == []


def test_business_services_cannot_import_global_sql_classifier() -> None:
    offenders: list[str] = []
    for path in sorted((PRODUCTION / "services").rglob("*.py")):
        for node in ast.walk(_tree(path)):
            if isinstance(node, ast.ImportFrom) and (
                node.module or ""
            ).endswith("report_generation_classifier"):
                offenders.append(path.relative_to(ROOT).as_posix())
            if isinstance(node, ast.Import) and any(
                alias.name.endswith("report_generation_classifier")
                for alias in node.names
            ):
                offenders.append(path.relative_to(ROOT).as_posix())
    assert offenders == []


def test_database_replacement_does_not_enumerate_cache_fanout() -> None:
    replacement_paths = (
        PRODUCTION / "services" / "secure_backup_service.py",
        PRODUCTION / "services" / "database_maintenance_service.py",
    )
    offenders: list[str] = []
    for path in replacement_paths:
        for node in ast.walk(_tree(path)):
            if not isinstance(node, ast.Call):
                continue
            name = _call_name(node)
            if re.match(r"^(clear|invalidate)_.*cache$", name):
                offenders.append(f"{path.name}:{name}")
    assert offenders == []


def test_project_rules_layering_and_capabilities_remain_acyclic() -> None:
    for path in (
        PRODUCTION / "api" / "project_api.py",
        PRODUCTION / "api" / "rule_api.py",
        PRODUCTION / "api" / "rule_history_api.py",
    ):
        modules = {
            node.module or ""
            for node in ast.walk(_tree(path))
            if isinstance(node, ast.ImportFrom)
        }
        assert not any("webview" in module for module in modules)
    for path in sorted((PRODUCTION / "services").rglob("*.py")):
        modules = {
            node.module or ""
            for node in ast.walk(_tree(path))
            if isinstance(node, ast.ImportFrom)
        }
        assert not any(module.endswith("api") or ".api" in module for module in modules)


def test_clipboard_maintenance_failure_is_best_effort(monkeypatch) -> None:
    failures: list[str] = []

    def fail_prune() -> None:
        raise RuntimeError("retention unavailable")

    monkeypatch.setattr(collector_module.clipboard_service, "prune_old_events", fail_prune)
    monkeypatch.setattr(
        collector_module.collector_health,
        "record_transient_failure",
        lambda phase, _exc, _at: failures.append(phase),
    )

    assert collector_module._run_clipboard_maintenance_tick() is None
    assert failures == ["clipboard_maintenance"]
