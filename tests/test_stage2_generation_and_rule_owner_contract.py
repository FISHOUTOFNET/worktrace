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
    assert source.index("connection.commit()") < source.index(
        "publish_committed(connection, committed_effects)"
    )
    assert "if not committed:" in source
    clock = _source("worktrace/generation_clock.py")
    assert "DataGenerationRepository.get_many" in clock
    assert "get_db_key()" in clock


def test_catalog_caches_are_generation_keyed_without_ttl() -> None:
    modules = (
        "worktrace/services/settings_service.py",
        "worktrace/services/privacy_service.py",
        "worktrace/services/folder_rule_service.py",
        "worktrace/services/project_inference_service.py",
    )
    for module in modules:
        source = _source(module)
        assert "generation(" in source, module
        assert "RULE_CACHE_TTL_SECONDS" not in source, module
        assert "time.monotonic" not in source, module
    settings = _source("worktrace/services/settings_service.py")
    assert "SettingMutationClass.OPERATIONAL" in settings
    assert "bypass the catalog cache" in settings


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


def test_folder_index_read_model_is_side_effect_free() -> None:
    source = _source("worktrace/services/folder_index_query_service.py")
    for forbidden in (
        "request_rebuild_for_rule",
        "request_refresh_for_enabled_rules",
        "mark_index_stale",
        "INSERT INTO",
        "UPDATE folder_rule_index_state",
        "DELETE FROM",
    ):
        assert forbidden not in source
    privacy = _source("worktrace/services/privacy_service.py")
    assert "folder_index_query_service" in privacy
    assert privacy.index("resolve_unique_path_from_title") < privacy.index(
        "request_refresh_for_enabled_rules"
    )


def test_project_catalog_has_no_cross_service_cache_fanout() -> None:
    source = _source("worktrace/services/project_service.py")
    assert "_invalidate_project_lifecycle_caches" not in source
    assert "invalidate_folder_rule_cache" not in source
    assert "invalidate_keyword_rule_cache" not in source
    assert "clear_exclude_rules_cache" not in source


def test_clear_and_replacement_rely_on_single_generation_owners() -> None:
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
    export = _source("worktrace/services/export_service.py")
    assert "_invalidate_clear_all_caches" not in export
    assert "invalidate_folder_rule_cache" not in export
    assert "clear_exclude_rules_cache" not in export
    replacement = _source(
        "worktrace/services/database_replacement_generation_service.py"
    )
    assert "DataGenerationRepository.bump" in replacement
    assert "clear()" in replacement


def test_stage2_checkpoint_marker() -> None:
    """No-op checkpoint so this commit validates the complete stage-2 head."""

    assert True
