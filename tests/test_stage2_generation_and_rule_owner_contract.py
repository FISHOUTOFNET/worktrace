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


def test_batch_service_has_no_mutation_or_cache_owner() -> None:
    source = _source("worktrace/services/rule_batch_service.py")
    for forbidden in (
        "DomainUnitOfWork",
        "activity_project_assignment",
        "UPDATE project_rule",
        "UPDATE folder_project_rule",
        "invalidate_keyword_rule_cache",
        "invalidate_folder_rule_cache",
        "clear_exclude_rules_cache",
    ):
        assert forbidden not in source
    assert "submit_rule_batch_job" in source
    assert "set_rules_enabled" in source


def test_rule_facades_delegate_all_catalog_writes() -> None:
    keyword = _source("worktrace/services/rule_service.py")
    folder = _source("worktrace/services/folder_rule_service.py")
    owner = _source("worktrace/services/rule_catalog_command_service.py")
    for facade in (keyword, folder):
        assert "DomainUnitOfWork" not in facade
        assert "UPDATE project_rule" not in facade
        assert "UPDATE folder_project_rule" not in facade
        assert "DELETE FROM project_rule" not in facade
        assert "DELETE FROM folder_project_rule" not in facade
    assert "create_keyword_rule" in owner
    assert "create_or_update_folder_rule" in owner
    assert "set_rules_enabled" in owner
    assert "delete_rule_in_transaction" in owner


def test_history_jobs_are_durable_before_candidate_scans() -> None:
    source = _source("worktrace/services/history_mutation_job_service.py")
    single_start = source.index("def submit_rule_job(")
    batch_start = source.index("def submit_rule_batch_job(")
    compensation_start = source.index("def compensate_failed_synchronous_job(")
    single_body = source[single_start:batch_start]
    batch_body = source[batch_start:compensation_start]
    assert "planner.load_candidate_activities" not in single_body
    assert "planner.classify_activities" not in single_body
    assert "planner.load_candidate_activities" not in batch_body
    assert "planner.classify_activities" not in batch_body
    assert "run_job_batch(job_id" in single_body
    assert "run_job_batch(job_id" in batch_body


def test_recovery_service_only_plans_lifecycle_commands() -> None:
    recovery = _source("worktrace/services/recovery_service.py")
    lifecycle = _source("worktrace/services/activity_lifecycle_service.py")
    assert "UPDATE activity_log" not in recovery
    assert "recover_activity_batch(commands, boundaries)" in recovery
    assert "mark_activity_error" in recovery
    assert "def recover_activity_batch(" in lifecycle
    assert "session_boundary_service.insert_boundary" in lifecycle


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
    planning = _source("worktrace/services/rule_planning_service.py")
    resources = _source("worktrace/resources/resource_helpers.py")
    assert "folder_index_query_service" in inference
    assert "folder_index_query_service" in planning
    assert "folder_index_query_service" not in resources
    assert "folder_index_service.find_matching_folder_rule_for_file_name" not in inference


def test_project_catalog_has_no_cross_service_cache_fanout() -> None:
    source = _source("worktrace/services/project_service.py")
    assert "_invalidate_project_lifecycle_caches" not in source
    assert "invalidate_folder_rule_cache" not in source
    assert "invalidate_keyword_rule_cache" not in source
    assert "clear_exclude_rules_cache" not in source


def test_clear_and_replacement_publish_through_transaction_owners() -> None:
    maintenance = _source("worktrace/services/database_maintenance_service.py")
    assert "publish_database_replacement(conn)" in maintenance
    for duplicate in (
        "DataGenerationNamespace.CLASSIFICATION_CATALOG",
        "DataGenerationNamespace.SETTINGS",
        "DataGenerationNamespace.PRIVACY_CATALOG",
        "DataGenerationNamespace.DATABASE_REPLACEMENT",
    ):
        assert duplicate not in maintenance
    assert "publish_database_replacement(conn)" in maintenance
    assert "privacy_gate_service" not in maintenance

    replacement = _source(
        "worktrace/services/database_replacement_generation_service.py"
    )
    assert "uow.add_effects(*_REPLACEMENT_NAMESPACES)" in replacement
    assert "DataGenerationRepository.bump" in replacement
    assert "generation_clock" not in replacement
    assert "clear()" not in replacement

    gate = _source("worktrace/services/privacy_gate_service.py")
    assert "clear_settings_cache" not in gate


def test_database_replacement_generation_docstring_matches_commit_protocol() -> None:
    path = ROOT / "worktrace/services/database_replacement_generation_service.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "publish_database_replacement"
    )
    docstring = " ".join((ast.get_docstring(function) or "").split())
    for required in (
        "DomainUnitOfWork",
        "after its transaction commits",
        "writes durable replacement generations",
        "exact committed values",
        "Only a failure",
        "clears the process clock",
        "reload the already durable values",
    ):
        assert required in docstring
