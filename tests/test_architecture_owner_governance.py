from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.unit,
    pytest.mark.contract,
    pytest.mark.collector_runtime,
]

ROOT = Path(__file__).resolve().parents[1]
PRODUCTION = ROOT / "worktrace"
TESTS = ROOT / "tests"

RETIRED_PRODUCTION_SYMBOLS = {
    "mark_inference_retry",
    "mark_inference_retry_with_uow",
    "INFERENCE_RETRY_CONFIDENCE",
    "retry_pending_inference",
    "process_new_activity",
    "start_folder_index_worker",
    "start_history_worker",
    "start_inference_worker",
    "_synchronize_core_hooks",
    "register_collector_pause_handler",
    "register_collector_reset_handler",
    "register_maintenance_thread",
    "unregister_maintenance_thread",
}
RETIRED_FILES = {
    PRODUCTION / "schema_migrations.py",
    PRODUCTION / "runtime" / "app_runtime_core.py",
    PRODUCTION / "services" / "secure_backup_core.py",
    PRODUCTION / "services" / "runtime_snapshot_barrier.py",
}
DYNAMIC_TEST_PATTERNS = (
    "runpy." + "run_path(",
    "globals()[name]" + " = test",
    "globals()[_name]" + " =",
    "for _name in " + "dir(_contracts)",
)
_INFERENCE_DML_PATTERN = re.compile(
    r"\b(?:INSERT(?:\s+OR\s+\w+)?\s+INTO|REPLACE\s+INTO|UPDATE|DELETE\s+FROM)"
    r"\s+activity_inference_job\b",
    re.IGNORECASE,
)
_RECOVERY_DML_PATTERN = re.compile(
    r"\b(?:INSERT(?:\s+OR\s+\w+)?\s+INTO|REPLACE\s+INTO|UPDATE|DELETE\s+FROM)"
    r"\s+startup_recovery_job\b",
    re.IGNORECASE,
)
_INFERENCE_JOB_RUNTIME_DML_OWNER = (
    "worktrace/services/activity_inference_job_repository.py"
)
_RECOVERY_JOB_RUNTIME_DML_OWNER = (
    "worktrace/services/startup_recovery_job_repository.py"
)


def _python_files(root: Path) -> list[Path]:
    return sorted(root.rglob("*.py"))


def test_retired_owner_files_are_absent() -> None:
    assert [
        path.relative_to(ROOT).as_posix()
        for path in RETIRED_FILES
        if path.exists()
    ] == []


def test_retired_inference_and_hook_symbols_are_absent_from_production() -> None:
    offenders: list[str] = []
    for path in _python_files(PRODUCTION):
        source = path.read_text(encoding="utf-8")
        for symbol in RETIRED_PRODUCTION_SYMBOLS:
            if symbol in source:
                offenders.append(f"{path.relative_to(ROOT).as_posix()}:{symbol}")
        if re.search(r"confidence\s*(?:=|<)\s*-1\b", source):
            offenders.append(f"{path.relative_to(ROOT).as_posix()}:negative-confidence")
    assert offenders == []


def test_durable_job_runtime_dml_has_one_canonical_owner_each() -> None:
    inference_owners: set[str] = set()
    recovery_owners: set[str] = set()
    for path in _python_files(PRODUCTION):
        relative = path.relative_to(ROOT).as_posix()
        source = path.read_text(encoding="utf-8")
        if _INFERENCE_DML_PATTERN.search(source):
            inference_owners.add(relative)
        if _RECOVERY_DML_PATTERN.search(source):
            recovery_owners.add(relative)
    assert inference_owners == {_INFERENCE_JOB_RUNTIME_DML_OWNER}
    assert recovery_owners == {_RECOVERY_JOB_RUNTIME_DML_OWNER}


def test_destructive_owners_use_canonical_job_cleanup_interfaces() -> None:
    maintenance = (
        PRODUCTION / "services" / "database_maintenance_service.py"
    ).read_text(encoding="utf-8")
    backup = (
        PRODUCTION / "services" / "secure_backup_service.py"
    ).read_text(encoding="utf-8")
    assert "activity_inference_job_repository.clear_all_jobs(conn)" in maintenance
    assert "startup_recovery_job_repository.clear_all_jobs(conn)" in maintenance
    assert "clear_all_worker_progress_in_transaction(live)" in backup
    assert '"activity_inference_job",' in backup
    assert '"startup_recovery_job",' in backup
    assert not _INFERENCE_DML_PATTERN.search(maintenance)
    assert not _INFERENCE_DML_PATTERN.search(backup)
    assert not _RECOVERY_DML_PATTERN.search(maintenance)
    assert not _RECOVERY_DML_PATTERN.search(backup)


def test_current_schema_declares_durable_jobs_directly() -> None:
    schema = (PRODUCTION / "schema_internal.sql").read_text(encoding="utf-8")
    indexes = (PRODUCTION / "schema_indexes.sql").read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS activity_inference_job" in schema
    assert "reason TEXT NOT NULL CHECK(reason = 'closed_activity')" in schema
    assert "status TEXT NOT NULL CHECK(status IN ('pending', 'failed'))" in schema
    assert "activity_inference_job" in indexes
    assert "CREATE TABLE IF NOT EXISTS startup_recovery_job" in schema
    assert "legacy_retry" not in schema


def test_runtime_and_backup_have_single_lifecycle_owners() -> None:
    runtime = (PRODUCTION / "runtime" / "app_runtime.py").read_text(encoding="utf-8")
    backup = (PRODUCTION / "services" / "secure_backup_service.py").read_text(
        encoding="utf-8"
    )
    maintenance = (
        PRODUCTION / "services" / "database_maintenance_service.py"
    ).read_text(encoding="utf-8")

    assert "class AppRuntime" in runtime
    assert "activity_inference_job_service.run_inference_worker" in runtime
    assert "activity_fact_repair_service.run_activity_resource_repair_worker" in runtime
    assert "recovery_service.run_startup_recovery_worker" in runtime
    assert runtime.count("database_maintenance_service.register_runtime_control(self)") >= 1
    assert "from . import database_maintenance_service" in backup
    assert "database_maintenance_service.consistent_snapshot(" in backup
    assert "database_maintenance_service.database_replacement(" in backup
    assert "class RuntimeMaintenanceCoordinator" in maintenance
    assert "class DatabaseMaintenanceCoordinator" not in maintenance
    assert "__getattr__" not in runtime
    assert "__getattr__" not in backup


def test_app_runtime_has_exactly_one_thread_creation_site_for_derived_workers() -> None:
    runtime = (PRODUCTION / "runtime" / "app_runtime.py").read_text(encoding="utf-8")
    assert runtime.count("def _start_owned_worker(") == 1
    assert runtime.count("activity_inference_job_service.run_inference_worker") == 1
    assert "process_pending_inference_jobs(" not in runtime
    for relative in (
        "services/folder_index_service.py",
        "services/history_mutation_job_service.py",
        "services/activity_inference_job_service.py",
        "services/activity_fact_repair_service.py",
        "services/recovery_service.py",
    ):
        source = (PRODUCTION / relative).read_text(encoding="utf-8")
        assert "_WORKER_THREAD" not in source
        assert "threading.Thread(" not in source


def test_non_windows_production_adapter_fails_closed() -> None:
    source = (PRODUCTION / "runtime" / "app_runtime.py").read_text(encoding="utf-8")
    assert 'raise RuntimeError("unsupported_platform")' in source
    assert "fake_adapter" not in source.casefold()


def test_dynamic_test_forwarding_is_absent() -> None:
    offenders: list[str] = []
    for path in _python_files(TESTS):
        if path == Path(__file__).resolve():
            continue
        source = path.read_text(encoding="utf-8")
        for pattern in DYNAMIC_TEST_PATTERNS:
            if pattern in source:
                offenders.append(f"{path.relative_to(ROOT).as_posix()}:{pattern}")
    assert offenders == []


def test_test_functions_are_defined_in_collectable_modules() -> None:
    for filename in (
        "test_architecture_owner_governance.py",
        "test_app_runtime_privacy_gate.py",
        "test_secure_backup_service.py",
    ):
        path = TESTS / filename
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        assert any(
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name.startswith("test_")
            for node in tree.body
        )


def test_current_only_schema_and_backup_versions_are_explicit() -> None:
    db_source = (PRODUCTION / "db.py").read_text(encoding="utf-8")
    backup_source = (
        PRODUCTION / "services" / "secure_backup_service.py"
    ).read_text(encoding="utf-8")
    assert "CURRENT_SCHEMA_VERSION = 11" in db_source
    assert "database_schema_incompatible" in db_source
    assert "PAYLOAD_VERSION = 5" in backup_source
    assert "_normalize_v4_payload" not in backup_source
    assert "LEGACY" not in backup_source
