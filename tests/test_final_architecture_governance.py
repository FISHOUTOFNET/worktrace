from __future__ import annotations

import ast
from pathlib import Path

import pytest

from worktrace import db
from worktrace.services import secure_backup_service
from worktrace.services.session_boundary_policy import ALLOWED_HARD_BOUNDARY_REASONS

pytestmark = [pytest.mark.unit, pytest.mark.contract, pytest.mark.parallel_safe]
ROOT = Path(__file__).resolve().parents[1]
PRODUCTION = ROOT / "worktrace"


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


def _boundary_reason_literals(relative: str) -> set[str]:
    """Return literals used as lifecycle reasons, excluding UI state literals."""

    tree = ast.parse(_source(relative), filename=relative)
    boundary_calls = {
        "_commit_boundary",
        "_stop_recording_at_boundary",
        "close_at_boundary",
        "pause_collection",
        "record_boundary",
    }
    literals: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name):
            name = node.func.id
        elif isinstance(node.func, ast.Attribute):
            name = node.func.attr
        else:
            continue
        if name not in boundary_calls:
            continue
        for argument in (*node.args, *(item.value for item in node.keywords)):
            if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                literals.add(argument.value)
    return literals


def _module_string_constant(relative: str, name: str) -> str:
    tree = ast.parse(_source(relative), filename=relative)
    assignment = next(
        node
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == name for target in node.targets)
    )
    assert isinstance(assignment.value, ast.Constant)
    assert isinstance(assignment.value.value, str)
    return assignment.value.value


def _production_string_literals() -> set[str]:
    literals: set[str] = set()
    for path in sorted(PRODUCTION.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        literals.update(
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        )
    return literals


def test_app_runtime_is_the_only_worker_started_stopped_owner():
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

    wrapper_calls = _function_calls(
        "worktrace/runtime/app_runtime.py",
        "_run_owned_worker",
    )
    assert {"started", "stopped"}.issubset(wrapper_calls)


def test_shipping_js_contains_no_retired_liveclock_alias_substrings():
    source = "\n".join(
        _source(f"worktrace/webview_ui/js/{name}")
        for name in ("core.js", "init.js", "overview.js", "timeline.js")
    )
    forbidden = (
        "duration_seconds_at_sample",
        "carry_seconds",
        "live_started_at_epoch_ms",
        "sample_epoch_ms",
        "current_live_duration_seconds",
        "persisted_duration_seconds",
        "active_elapsed_at_sample",
        "current_elapsed_at_sample",
        "current_duration_live",
        "project_duration_live",
        "is_project_duration_live",
        "live_delta_eligible",
        "is_live_projected",
    )
    assert all(name not in source for name in forbidden)
    assert "Math.max(alias" not in source


def test_current_only_schema_backup_and_database_helpers():
    assert db.CURRENT_SCHEMA_VERSION == 13
    assert secure_backup_service.PAYLOAD_VERSION == 6
    assert not hasattr(secure_backup_service, "is_secure_import_in_progress")

    production_db = ast.parse(_source("worktrace/db.py"), filename="worktrace/db.py")
    function_names = {
        node.name
        for node in production_db.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert "reset_database" not in function_names
    assert "drop_all_tables" not in function_names

    test_helper = _source("tests/support/database.py")
    assert "def reset_database" in test_helper
    assert "def drop_all_tables" in test_helper


def test_boundary_reasons_and_pause_command_have_no_compatibility_fallback():
    reason_literals = _boundary_reason_literals("worktrace/collector/state_machine.py")
    assert {"paused", "stopped", "time_jump", "secure_import"}.isdisjoint(
        reason_literals
    )
    assert "pause_fallback" not in ALLOWED_HARD_BOUNDARY_REASONS
    app_api = _source("worktrace/api/app_api.py")
    assert "pause_fallback" not in app_api
    assert "activity_lifecycle_service.pause_collection" not in app_api


def test_maintenance_resume_and_status_are_current_only():
    app_api = _source("worktrace/api/app_api.py")
    backup_api = _source("worktrace/api/backup_api.py")
    settings_api = _source("worktrace/api/settings_api.py")
    combined_status = backup_api + settings_api

    assert "application_runtime_required" in app_api
    assert "DATABASE_RECOVERY_ERROR" in app_api
    assert (
        _module_string_constant("worktrace/write_gate.py", "DATABASE_MAINTENANCE_ERROR")
        == "database_maintenance_in_progress"
    )
    assert (
        _module_string_constant("worktrace/write_gate.py", "DATABASE_RECOVERY_ERROR")
        == "database_maintenance_recovery_required"
    )
    retired_errors = {
        "maintenance_operation_in_progress",
        "maintenance_failed_closed",
        "maintenance_recovery_required",
    }
    assert retired_errors.isdisjoint(_production_string_literals())
    assert "def is_maintenance_in_progress" in backup_api
    assert "database_maintenance_service.maintenance_status()" in settings_api
    assert '"maintenance": maintenance' in settings_api
    assert "secure_import_in_progress" not in combined_status
    assert "is_secure_import_in_progress" not in combined_status


def test_maintenance_unknown_state_requires_terminal_query():
    maintenance = _source("worktrace/services/database_maintenance_service.py")
    collector = _source("worktrace/collector/collector.py")
    assert "query_command" in maintenance
    assert "command_state_unknown" in maintenance
    assert "def query_command" in collector
    assert "terminal_state" in maintenance


def test_no_acceptance_temporary_workflow_or_agent_script():
    workflows = ROOT / ".github" / "workflows"
    assert not (workflows / "acceptance.yml").exists()
    assert not (workflows / "acceptance.yaml").exists()
    assert not list((ROOT / ".github").glob("agent_*.py"))

    workflow_names = {path.name for path in workflows.glob("*.yml")}
    workflow_names.update(path.name for path in workflows.glob("*.yaml"))
    assert workflow_names == {"ci.yml", "_validation.yml"}


def test_production_has_no_runtime_service_locator():
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
