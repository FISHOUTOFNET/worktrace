from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.contract, pytest.mark.collector_runtime]

ROOT = Path(__file__).resolve().parents[1]
PRODUCTION = ROOT / "worktrace"


def test_phase_a_startup_and_enqueue_are_bounded() -> None:
    runtime_source = (PRODUCTION / "runtime" / "app_runtime.py").read_text(
        encoding="utf-8"
    )
    runtime_tree = ast.parse(runtime_source)
    runtime_class = next(
        node
        for node in runtime_tree.body
        if isinstance(node, ast.ClassDef) and node.name == "AppRuntime"
    )
    initialize = next(
        node
        for node in runtime_class.body
        if isinstance(node, ast.FunctionDef) and node.name == "initialize"
    )
    initialize_source = ast.get_source_segment(runtime_source, initialize) or ""
    assert "recover_unclosed_records" in initialize_source
    assert "repair_missing_activity_resources" not in initialize_source
    assert "while " not in initialize_source

    repository_source = (
        PRODUCTION / "services" / "activity_inference_job_repository.py"
    ).read_text(encoding="utf-8")
    assert "COUNT(*) FROM activity_inference_job" not in repository_source
    assert "INSERT OR IGNORE INTO activity_inference_job" in repository_source


def test_phase_a_has_no_retired_paths_or_secondary_thread_owner() -> None:
    retired = (
        "schema_migrations.py",
        "runtime/app_runtime_core.py",
        "services/secure_backup_core.py",
    )
    assert not any((PRODUCTION / relative).exists() for relative in retired)

    runtime_source = (PRODUCTION / "runtime" / "app_runtime.py").read_text(
        encoding="utf-8"
    )
    assert runtime_source.count("def _start_owned_worker(") == 1
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


def test_phase_a_current_contract_versions_and_internal_progress() -> None:
    db_source = (PRODUCTION / "db.py").read_text(encoding="utf-8")
    backup_source = (
        PRODUCTION / "services" / "secure_backup_service.py"
    ).read_text(encoding="utf-8")
    schema = (PRODUCTION / "schema_internal.sql").read_text(encoding="utf-8")
    indexes = (PRODUCTION / "schema_indexes.sql").read_text(encoding="utf-8")

    assert "CURRENT_SCHEMA_VERSION = 11" in db_source
    assert "PAYLOAD_VERSION = 5" in backup_source
    assert '"startup_recovery_job",' in backup_source
    assert "CREATE TABLE IF NOT EXISTS startup_recovery_job" in schema
    assert "idx_startup_recovery_job_runnable" in indexes
    assert "retry_pending_inference" not in runtime_source_for_contract()


def runtime_source_for_contract() -> str:
    return (PRODUCTION / "runtime" / "app_runtime.py").read_text(encoding="utf-8")
