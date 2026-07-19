from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.contract, pytest.mark.collector_runtime]

ROOT = Path(__file__).resolve().parents[1]


def _source(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def _tree(relative: str) -> ast.Module:
    return ast.parse(_source(relative), filename=relative)


def _function(relative: str, name: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
    return next(
        node
        for node in ast.walk(_tree(relative))
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == name
    )


def _called_names(node: ast.AST) -> set[str]:
    names: set[str] = set()
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        if isinstance(child.func, ast.Name):
            names.add(child.func.id)
        elif isinstance(child.func, ast.Attribute):
            names.add(child.func.attr)
    return names


def _thread_constructor_calls(relative: str) -> list[ast.Call]:
    result: list[ast.Call] = []
    for node in ast.walk(_tree(relative)):
        if not isinstance(node, ast.Call):
            continue
        if (
            isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "threading"
            and node.func.attr == "Thread"
        ):
            result.append(node)
    return result


def test_maintenance_coordinator_is_the_only_semantic_owner() -> None:
    maintenance = _source("worktrace/services/database_maintenance_service.py")
    backup = _source("worktrace/services/secure_backup_service.py")
    runtime = _source("worktrace/runtime/app_runtime.py")

    assert "class RuntimeMaintenanceCoordinator" in maintenance
    assert "class DatabaseMaintenanceCoordinator" not in maintenance
    assert "class MaintenanceState" not in maintenance
    assert "mark_succeeded" not in maintenance
    assert "mark_succeeded" not in backup
    assert "runtime_snapshot_barrier" not in runtime

    quiesce = _function(
        "worktrace/runtime/app_runtime.py",
        "quiesce_collection_for_maintenance",
    )
    reset = _function(
        "worktrace/runtime/app_runtime.py",
        "reset_after_database_replacement",
    )
    forbidden = {
        "set_setting",
        "set_settings",
        "get_setting",
        "get_bool_setting",
        "clear_runtime_activity_state",
    }
    assert _called_names(quiesce).isdisjoint(forbidden)
    assert _called_names(reset).isdisjoint(forbidden)
    assert "request_pause" in _called_names(quiesce)
    assert "request_reset" in _called_names(reset)


def test_database_replacement_is_one_independent_epoch() -> None:
    relative = "worktrace/services/database_replacement_generation_service.py"
    namespaces = {
        node.attr
        for node in ast.walk(_tree(relative))
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "DataGenerationNamespace"
    }
    assert namespaces == {"DATABASE_REPLACEMENT"}


def test_all_cross_database_caches_listen_to_replacement_epoch() -> None:
    cache_modules = (
        "worktrace/services/settings_service.py",
        "worktrace/services/folder_rule_service.py",
        "worktrace/services/project_inference_service.py",
        "worktrace/services/privacy_service.py",
        "worktrace/services/report_revision_service.py",
    )
    for relative in cache_modules:
        source = _source(relative)
        assert "DataGenerationNamespace.DATABASE_REPLACEMENT" in source, relative
        assert (
            "generation_tuple(" in source
            or "DataGenerationRepository.get_many(" in source
        ), relative


def test_all_derived_workers_are_blocking_entrypoints() -> None:
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
        definition = _function(relative, function_name)
        argument_names = {
            argument.arg
            for argument in (*definition.args.args, *definition.args.kwonlyargs)
        }
        assert "stop_event" in argument_names, relative
        assert "health" in argument_names, relative
        assert not _thread_constructor_calls(relative), relative


def test_worker_health_is_process_local_and_runtime_owned() -> None:
    health_tree = _tree("worktrace/worker_health.py")
    module_level_registry = [
        node
        for node in health_tree.body
        if isinstance(node, (ast.Assign, ast.AnnAssign))
        and any(
            isinstance(call, ast.Call)
            and (
                (isinstance(call.func, ast.Name) and call.func.id == "WorkerHealthRegistry")
                or (
                    isinstance(call.func, ast.Attribute)
                    and call.func.attr == "WorkerHealthRegistry"
                )
            )
            for call in ast.walk(node)
        )
    ]
    assert module_level_registry == []
    init = _function("worktrace/runtime/app_runtime.py", "__init__")
    assert "WorkerHealthRegistry" in _called_names(init)
    start = _function("worktrace/runtime/app_runtime.py", "_start_owned_worker")
    assert "Thread" in _called_names(start)


def test_worker_progress_cleanup_uses_canonical_owners() -> None:
    maintenance = _function(
        "worktrace/services/database_maintenance_service.py",
        "clear_all_worker_progress_in_transaction",
    )
    called = _called_names(maintenance)
    assert "clear_all_jobs_in_transaction" in called
    assert "clear_all_jobs" in called

    backup_source = _source("worktrace/services/secure_backup_service.py")
    backup_replace = _function(
        "worktrace/services/secure_backup_service.py",
        "_replace_import",
    )
    assert "clear_all_worker_progress_in_transaction" in _called_names(backup_replace)
    for table_name in (
        "history_mutation_job_rule",
        "history_mutation_job",
        "activity_inference_job",
        "activity_resource_repair_job",
        "startup_recovery_job",
    ):
        assert f"DELETE FROM {table_name}" not in backup_source
