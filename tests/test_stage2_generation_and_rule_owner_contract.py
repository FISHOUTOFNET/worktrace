from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.unit,
    pytest.mark.db,
    pytest.mark.contract,
    pytest.mark.parallel_safe,
]

ROOT = Path(__file__).resolve().parents[1]


def _source(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def _functions(relative: str) -> set[str]:
    tree = ast.parse(_source(relative), filename=relative)
    return {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def test_generation_clock_is_published_only_after_uow_commit() -> None:
    source = _source("worktrace/domain_unit_of_work.py")
    commit_position = source.index("connection.commit()")
    assert commit_position < source.index("publish_committed(connection, committed_effects)")
    assert commit_position < source.index("publish_replacement_committed")
    assert "if not committed:" in source
    clock = _source("worktrace/generation_clock.py")
    assert "max(int(_VALUES.get(key, 0)), int(value))" in clock
    assert "publish_replacement_committed" in clock


def test_catalog_caches_retain_only_one_generation_snapshot() -> None:
    settings = _source("worktrace/services/settings_service.py")
    folders = _source("worktrace/services/folder_rule_service.py")
    keywords = _source("worktrace/services/project_inference_service.py")
    privacy = _source("worktrace/services/privacy_service.py")

    for module, source in (
        ("settings", settings),
        ("folders", folders),
        ("keywords", keywords),
        ("privacy", privacy),
    ):
        assert "generation(" in source, module
        assert "RULE_CACHE_TTL_SECONDS" not in source, module
        assert "time.monotonic" not in source, module

    assert "_SETTING_CACHE_GENERATION" in settings
    assert "dict[tuple[str, int, str]" not in settings
    assert "_FOLDER_RULE_CACHE_GENERATION" in folders
    assert "dict[tuple[str, int]" not in folders
    assert "_KEYWORD_RULE_CACHE_GENERATION" in keywords
    assert "dict[tuple[str, int]" not in keywords
    assert "_EXCLUDE_RULE_CACHE_GENERATION" in privacy
    assert "dict[tuple[str, int]" not in privacy
    assert "SettingMutationClass.OPERATIONAL" in settings


def test_rule_history_facade_has_no_direct_sql_owner() -> None:
    source = _source("worktrace/services/rule_history_application_service.py")
    assert "get_connection" not in source
    assert "BEGIN IMMEDIATE" not in source
    assert "DELETE FROM" not in source
    assert "UPDATE project_rule" not in source
    assert "UPDATE folder_project_rule" not in source
    assert "compensate_failed_synchronous_job" in source


def test_rule_impact_is_preview_only() -> None:
    source = _source("worktrace/services/rule_impact_service.py")
    assert "backfill_rule_impact" not in _functions(
        "worktrace/services/rule_impact_service.py"
    )
    assert "INSERT INTO activity_project_assignment" not in source
    assert "UPDATE activity_project_assignment" not in source
    assert "rule_planning_service" in source


def test_folder_index_read_model_is_deterministic_and_side_effect_free() -> None:
    source = _source("worktrace/services/folder_index_query_service.py")
    for forbidden in (
        "request_rebuild_for_rule",
        "request_refresh_for_enabled_rules",
        "mark_index_stale",
        "os.path.exists",
        "Path.exists",
        "INSERT INTO",
        "UPDATE folder_rule_index_state",
        "DELETE FROM",
    ):
        assert forbidden not in source
    inference = _source("worktrace/services/project_inference_service.py")
    assert "folder_index_query_service" in inference
    assert "folder_index_service.find_matching_folder_rule_for_file_name" not in inference
    privacy = _source("worktrace/services/privacy_service.py")
    assert "folder_index_query_service" in privacy


def test_project_catalog_has_no_cross_service_cache_fanout() -> None:
    source = _source("worktrace/services/project_service.py")
    assert "_invalidate_project_lifecycle_caches" not in source
    assert "invalidate_folder_rule_cache" not in source
    assert "invalidate_keyword_rule_cache" not in source
    assert "clear_exclude_rules_cache" not in source


def test_clear_and_replacement_publish_through_transaction_owners() -> None:
    maintenance = _source("worktrace/services/database_maintenance_service.py")
    assert "DataGenerationNamespace.REPORT_STRUCTURE" in maintenance
    for duplicate in (
        "DataGenerationNamespace.CLASSIFICATION_CATALOG",
        "DataGenerationNamespace.SETTINGS",
        "DataGenerationNamespace.PRIVACY_CATALOG",
        "DataGenerationNamespace.DATABASE_REPLACEMENT",
    ):
        assert duplicate not in maintenance
    assert "privacy_gate_service.restore_installation_privacy_state" in maintenance

    replacement = _source(
        "worktrace/services/database_replacement_generation_service.py"
    )
    assert "uow.add_effects(*_REPLACEMENT_NAMESPACES)" in replacement
    assert "DataGenerationRepository.bump" in replacement
    assert "generation_clock" not in replacement
    assert "clear()" not in replacement

    gate = _source("worktrace/services/privacy_gate_service.py")
    assert "clear_settings_cache" not in gate
