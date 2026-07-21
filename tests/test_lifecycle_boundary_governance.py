from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = [pytest.mark.contract, pytest.mark.architecture]

_ROOT = Path(__file__).resolve().parents[1]


def _source(relative: str) -> str:
    return (_ROOT / relative).read_text(encoding="utf-8")


def _function_source(relative: str, function_name: str) -> str:
    source = _source(relative)
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function_name:
            return ast.get_source_segment(source, node) or ""
    raise AssertionError(f"function not found: {relative}:{function_name}")


def test_public_file_outputs_share_canonical_atomic_owner():
    expected = {
        "worktrace/services/secure_backup_service.py": "atomic_write_bytes",
        "worktrace/services/export_service.py": "AtomicFileOutput",
        "worktrace/exports/excel_exporter.py": "AtomicFileOutput",
        "worktrace/security/key_manager.py": "OwnedTemporaryFile",
    }
    for relative, owner in expected.items():
        source = _source(relative)
        assert owner in source, f"{relative} must use {owner}"
        assert "with_suffix(\".tmp\")" not in source
        assert "with_suffix('.tmp')" not in source


def test_replacement_records_durable_commit_before_process_publication():
    source = _function_source(
        "worktrace/database_replacement_unit_of_work.py",
        "__exit__",
    )
    commit = source.index("connection.commit()")
    committed_state = source.index("DURABLE_COMMITTED")
    coordinator_handoff = source.index("record_database_replacement_committed")
    publication = source.index("publish_replacement_committed")
    assert commit < committed_state < coordinator_handoff < publication


def test_fail_closed_recovery_clear_requires_exact_epoch():
    source = _function_source(
        "worktrace/services/maintenance_recovery_latch_repository.py",
        "clear_latch",
    )
    assert "expected_epoch" in source
    assert "maintenance_recovery_epoch_mismatch" in source
    assert source.index("set_settings") < source.index("marker_path().unlink")


def test_folder_activation_is_committed_before_generation_gc():
    source = _function_source(
        "worktrace/services/folder_index_service.py",
        "rebuild_folder_index",
    )
    assert source.index("_activate_generation") < source.index("_cleanup_old_generations")
    assert "_fail_generation" not in source[source.index("_activate_generation") :]


def test_setting_contract_exposes_semantic_and_operational_changes():
    source = _source("worktrace/services/settings_service.py")
    assert "class SettingChangeResult" in source
    assert "operational_keys" in source
    assert "generation_effects" in source
    assert '"collector_status"' in source
