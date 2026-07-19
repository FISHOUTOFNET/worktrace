from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.contract, pytest.mark.collector_runtime]

ROOT = Path(__file__).resolve().parents[1]
PRODUCTION = ROOT / "worktrace"


def _source(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def _function_source(relative: str, name: str) -> str:
    source = _source(relative)
    tree = ast.parse(source, filename=relative)
    function = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == name
    )
    return ast.get_source_segment(source, function) or ""


def test_maintenance_coordinator_is_the_only_semantic_owner() -> None:
    maintenance = _source("worktrace/services/database_maintenance_service.py")
    runtime = _source("worktrace/runtime/app_runtime.py")
    backup = _source("worktrace/services/secure_backup_service.py")

    assert "class DatabaseMaintenanceCoordinator" in maintenance
    assert "class MaintenanceState" not in maintenance
    assert "mark_succeeded" not in maintenance
    assert "mark_succeeded" not in backup
    assert "CollectorCommandNotAcknowledgedError" in maintenance
    assert "set_settings(" in maintenance
    assert "SettingMutationClass.OPERATIONAL" in maintenance

    quiesce = _function_source(
        "worktrace/runtime/app_runtime.py",
        "quiesce_collection_now",
    )
    reset = _function_source(
        "worktrace/runtime/app_runtime.py",
        "reset_collection_runtime_now",
    )
    for handler in (quiesce, reset):
        assert "set_setting(" not in handler
        assert "clear_runtime_activity_state" not in handler
    assert "request_pause" in quiesce
    assert "request_reset" in reset


def test_database_replacement_is_one_independent_epoch() -> None:
    replacement = _source(
        "worktrace/services/database_replacement_generation_service.py"
    )
    assert (
        "_REPLACEMENT_NAMESPACE = DataGenerationNamespace.DATABASE_REPLACEMENT"
        in replacement
    )
    assert "uow.add_effects(_REPLACEMENT_NAMESPACE)" in replacement
    assert "DataGenerationNamespace.REPORT_STRUCTURE" not in replacement
    assert "DataGenerationNamespace.CLASSIFICATION_CATALOG" not in replacement
    assert "DataGenerationNamespace.SETTINGS" not in replacement
    assert "DataGenerationNamespace.PRIVACY_CATALOG" not in replacement


def test_all_cross_database_caches_listen_to_replacement_epoch() -> None:
    cache_modules = (
        "worktrace/services/settings_service.py",
        "worktrace/services/folder_rule_service.py",
        "worktrace/services/project_inference_service.py",
        "worktrace/services/privacy_service.py",
    )
    for relative in cache_modules:
        source = _source(relative)
        assert "DataGenerationNamespace.DATABASE_REPLACEMENT" in source, relative
        assert "generation_tuple(" in source, relative


def test_all_derived_workers_are_blocking_bounded_entrypoints() -> None:
    workers = (
        (
            "worktrace/services/folder_index_service.py",
            "run_folder_index_worker",
        ),
        (
            "worktrace/services/history_mutation_job_service.py",
            "run_history_worker",
        ),
        (
            "worktrace/services/activity_inference_job_service.py",
            "run_inference_worker",
        ),
        (
            "worktrace/services/activity_fact_repair_service.py",
            "run_activity_resource_repair_worker",
        ),
        (
            "worktrace/services/recovery_service.py",
            "run_startup_recovery_worker",
        ),
    )
    for relative, function_name in workers:
        source = _source(relative)
        function = _function_source(relative, function_name)
        tree = ast.parse(function)
        definition = tree.body[0]
        argument_names = {
            argument.arg
            for argument in (*definition.args.args, *definition.args.kwonlyargs)
        }
        assert "stop_event" in argument_names, relative
        assert "health" in argument_names, relative
        assert "while" in function, relative
        assert "health.failed(" in function, relative
        assert "health.succeeded()" in function, relative
        assert "threading.Thread(" not in source, relative


def test_worker_health_is_process_local_and_privacy_safe() -> None:
    source = _source("worktrace/worker_health.py")
    runtime = _source("worktrace/runtime/app_runtime.py")
    assert "class WorkerHealthRegistry" in source
    assert "last_successful_iteration_at" in source
    assert "last_failure_code" in source
    assert "consecutive_failures" in source
    assert "maintenance_paused" in source
    assert "traceback" not in source.casefold()
    assert "self._worker_health = WorkerHealthRegistry()" in runtime
    assert "target=self._run_owned_worker" in runtime


def test_clear_resets_all_durable_worker_progress() -> None:
    maintenance = _source("worktrace/services/database_maintenance_service.py")
    backup = _source("worktrace/services/secure_backup_service.py")
    for token in (
        '"history_mutation_job_rule"',
        '"history_mutation_job"',
        '"activity_inference_job"',
        '"activity_resource_repair_job"',
        "startup_recovery_job_repository.clear_all_jobs",
    ):
        assert token in maintenance, token
        assert token in backup, token
