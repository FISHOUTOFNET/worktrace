"""Stable architecture boundaries that are worth enforcing permanently.

This module deliberately avoids migration-stage assertions and blacklists of
retired private names. It protects current ownership, layering, fail-closed
maintenance, and durable data-contract boundaries.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from worktrace import db
from worktrace.services import secure_backup_service

pytestmark = [pytest.mark.unit, pytest.mark.contract, pytest.mark.parallel_safe]

ROOT = Path(__file__).resolve().parents[1]


def _source(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def _function_calls(relative: str, function_name: str) -> set[str]:
    tree = ast.parse(_source(relative), filename=relative)
    function = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == function_name
    )
    calls: set[str] = set()
    for node in ast.walk(function):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name):
            calls.add(node.func.id)
        elif isinstance(node.func, ast.Attribute):
            calls.add(node.func.attr)
    return calls


def test_app_runtime_owns_worker_lifecycle_notifications() -> None:
    workers = (
        ("worktrace/services/folder_index_service.py", "run_folder_index_worker"),
        ("worktrace/services/history_mutation_job_service.py", "run_history_worker"),
        ("worktrace/services/activity_inference_job_service.py", "run_inference_worker"),
        (
            "worktrace/services/activity_fact_repair_service.py",
            "run_activity_resource_repair_worker",
        ),
        ("worktrace/services/recovery_service.py", "run_startup_recovery_worker"),
    )
    for relative, function_name in workers:
        calls = _function_calls(relative, function_name)
        assert "started" not in calls, relative
        assert "stopped" not in calls, relative

    wrapper_calls = _function_calls("worktrace/runtime/app_runtime.py", "_run_owned_worker")
    assert {"started", "stopped"}.issubset(wrapper_calls)


def test_current_database_and_backup_versions_match_public_contract() -> None:
    assert db.CURRENT_SCHEMA_VERSION == 13
    assert secure_backup_service.PAYLOAD_VERSION == 6


def test_database_maintenance_resolves_unknown_command_state() -> None:
    maintenance = _source("worktrace/services/database_maintenance_service.py")
    collector = _source("worktrace/collector/collector.py")

    assert "query_command" in maintenance
    assert "command_state_unknown" in maintenance
    assert "terminal_state" in maintenance
    assert "def query_command" in collector


def test_application_composition_has_no_runtime_service_locator() -> None:
    production = "\n".join(
        _source(path)
        for path in (
            "worktrace/api/app_api.py",
            "worktrace/api/application_services.py",
            "worktrace/webview_main.py",
            "worktrace/webview_ui/bridge.py",
        )
    )
    assert "def get_runtime(" not in production
    assert "def set_runtime(" not in production
    assert "_RUNTIME =" not in production
    assert "service_registry" not in production


def test_rule_facades_do_not_execute_sql() -> None:
    dml_pattern = re.compile(
        r"\b(?:INSERT(?:\s+OR\s+\w+)?\s+INTO|REPLACE\s+INTO|UPDATE\s+\w+\s+SET|"
        r"DELETE\s+FROM|SELECT\s+.+\s+FROM)\b",
        re.IGNORECASE,
    )
    execute_pattern = re.compile(r"\.execute\s*\(")

    for relative in (
        "worktrace/api/rule_api.py",
        "worktrace/webview_ui/bridge_rules.py",
    ):
        source = _source(relative)
        assert not dml_pattern.search(source), relative
        assert not execute_pattern.search(source), relative
