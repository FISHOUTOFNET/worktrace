from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = [pytest.mark.contract]

_ROOT = Path(__file__).resolve().parents[1]


def _source(relative: str) -> str:
    return (_ROOT / relative).read_text(encoding="utf-8")


def _function_node(relative: str, function_name: str):
    source = _source(relative)
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function_name:
            return source, node
    raise AssertionError(f"function not found: {relative}:{function_name}")


def _function_source(relative: str, function_name: str) -> str:
    source, node = _function_node(relative, function_name)
    return ast.get_source_segment(source, node) or ""


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
    _source_text, node = _function_node(
        "worktrace/services/folder_index_service.py",
        "rebuild_folder_index",
    )
    calls: dict[str, list[int]] = {}
    for child in ast.walk(node):
        if not isinstance(child, ast.Call) or not isinstance(child.func, ast.Name):
            continue
        calls.setdefault(child.func.id, []).append(child.lineno)
    activation = min(calls["_activate_generation"])
    cleanup = min(calls["_cleanup_old_generations"])
    build_failures = calls["_fail_generation"]
    assert activation < cleanup
    assert max(build_failures) < cleanup


def test_setting_contract_exposes_semantic_and_operational_changes():
    source = _source("worktrace/services/settings_service.py")
    assert "class SettingChangeResult" in source
    assert "operational_keys" in source
    assert "generation_effects" in source
    assert '"collector_status"' in source
