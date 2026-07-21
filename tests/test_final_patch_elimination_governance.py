from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.unit,
    pytest.mark.contract,
    pytest.mark.parallel_safe,
    pytest.mark.db,
]
ROOT = Path(__file__).resolve().parents[1]
MAINTENANCE_FIELDS = {
    "maintenance_in_progress",
    "maintenance_restored",
    "recovery_blocked",
    "blocked_reason",
    "collector_running",
    "collector_status",
    "user_paused",
}


def _source(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def _tree(relative: str) -> ast.Module:
    path = ROOT / relative
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _function(relative: str, name: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
    return next(
        node
        for node in ast.walk(_tree(relative))
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name
    )


def _called_names(node: ast.AST) -> set[str]:
    result: set[str] = set()
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        if isinstance(child.func, ast.Name):
            result.add(child.func.id)
        elif isinstance(child.func, ast.Attribute):
            result.add(child.func.attr)
    return result


def test_folder_index_cooldown_reads_database_key_and_replacement_epoch() -> None:
    identity = _function(
        "worktrace/services/folder_index_service.py",
        "_replacement_cache_identity",
    )
    calls = _called_names(identity)
    assert "get_db_path" in calls
    assert "get_connection" in calls
    assert "get" in calls
    namespaces = {
        node.attr
        for node in ast.walk(identity)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "DataGenerationNamespace"
    }
    assert namespaces == {"DATABASE_REPLACEMENT"}

    refresh = _function(
        "worktrace/services/folder_index_service.py",
        "request_refresh_for_enabled_rules",
    )
    assert "_replacement_cache_identity" in _called_names(refresh)


def test_folder_index_worker_health_is_required() -> None:
    worker = _function(
        "worktrace/services/folder_index_service.py",
        "run_folder_index_worker",
    )
    keyword_only = worker.args.kwonlyargs
    health_index = next(
        index for index, argument in enumerate(keyword_only) if argument.arg == "health"
    )
    assert worker.args.kw_defaults[health_index] is None
    annotation = ast.unparse(keyword_only[health_index].annotation)
    assert "None" not in annotation


def test_maintenance_dto_is_single_exact_contract_across_backend_and_ui() -> None:
    tree = _tree("worktrace/services/database_maintenance_service.py")
    status_class = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "MaintenanceStatus"
    )
    backend_fields = {
        node.target.id
        for node in status_class.body
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
    }
    assert backend_fields == MAINTENANCE_FIELDS

    html = _source("worktrace/webview_ui/index.html")
    javascript = _source("worktrace/webview_ui/js/settings.js")
    for field in MAINTENANCE_FIELDS:
        assert f'data-settings-key="{field}"' in html
        assert f'"{field}"' in javascript
    assert "secure_import_in_progress" not in html
    assert "secure_import_in_progress" not in javascript


def test_failed_closed_is_distinct_from_active_maintenance() -> None:
    status = _function(
        "worktrace/services/database_maintenance_service.py",
        "status",
    )
    recovery_blocked = _function(
        "worktrace/services/database_maintenance_service.py",
        "recovery_blocked",
    )
    status_calls = _called_names(status)
    recovery_source = ast.unparse(recovery_blocked)

    assert "operation_active" in status_calls
    assert "recovery_blocked" in status_calls
    assert "MaintenancePhase.FAILED_CLOSED" in recovery_source
    assert "DATABASE_WRITE_GATE.recovery_blocked" in recovery_source
