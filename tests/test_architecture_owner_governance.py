from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.contract]

ROOT = Path(__file__).resolve().parents[1]
PRODUCTION = ROOT / "worktrace"
TESTS = ROOT / "tests"

RETIRED_PRODUCTION_SYMBOLS = {
    "mark_inference_retry",
    "mark_inference_retry_with_uow",
    "INFERENCE_RETRY_CONFIDENCE",
    "retry_pending_inference",
    "_synchronize_core_hooks",
}
RETIRED_FILES = {
    PRODUCTION / "schema_migrations.py",
    PRODUCTION / "runtime" / "app_runtime_core.py",
    PRODUCTION / "services" / "secure_backup_core.py",
}
DYNAMIC_TEST_PATTERNS = (
    "runpy.run_path(",
    "globals()[name] = test",
    "globals()[_name] =",
    "for _name in dir(_contracts)",
)
_DML_PATTERN = re.compile(
    r"\b(?:INSERT(?:\s+OR\s+\w+)?\s+INTO|REPLACE\s+INTO|UPDATE|DELETE\s+FROM)"
    r"\s+activity_inference_job\b",
    re.IGNORECASE,
)
_INFERENCE_JOB_DML_OWNERS = {
    "worktrace/services/activity_inference_job_repository.py",
    "worktrace/services/database_maintenance_service.py",
    "worktrace/services/secure_backup_service.py",
}


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


def test_inference_job_runtime_dml_has_only_canonical_owners() -> None:
    offenders: list[str] = []
    covered: set[str] = set()
    for path in _python_files(PRODUCTION):
        relative = path.relative_to(ROOT).as_posix()
        source = path.read_text(encoding="utf-8")
        if not _DML_PATTERN.search(source):
            continue
        covered.add(relative)
        if relative not in _INFERENCE_JOB_DML_OWNERS:
            offenders.append(relative)
    assert covered == _INFERENCE_JOB_DML_OWNERS
    assert offenders == []


def test_current_schema_declares_inference_job_and_index_directly() -> None:
    schema = (PRODUCTION / "schema_internal.sql").read_text(encoding="utf-8")
    indexes = (PRODUCTION / "schema_indexes.sql").read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS activity_inference_job" in schema
    assert "reason TEXT NOT NULL CHECK(reason = 'closed_activity')" in schema
    assert "status TEXT NOT NULL CHECK(status IN ('pending', 'failed'))" in schema
    assert "activity_inference_job" in indexes
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
    assert "start_inference_worker" in runtime
    assert "database_maintenance_service.register_collector_pause_handler" in runtime
    assert "from . import database_maintenance_service" in backup
    assert "maintenance_operation(" in backup
    assert "class DatabaseMaintenanceCoordinator" in maintenance
    assert "__getattr__" not in runtime
    assert "__getattr__" not in backup


def test_non_windows_production_adapter_fails_closed() -> None:
    source = (PRODUCTION / "runtime" / "app_runtime.py").read_text(encoding="utf-8")
    assert "raise RuntimeError(\"unsupported_platform\")" in source
    assert "fake_adapter" not in source.casefold()


def test_dynamic_test_forwarding_is_absent() -> None:
    offenders: list[str] = []
    for path in _python_files(TESTS):
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
