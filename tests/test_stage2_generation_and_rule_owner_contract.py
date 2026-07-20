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


def _tree(relative: str) -> ast.Module:
    return ast.parse(_source(relative), filename=relative)


def _functions(relative: str) -> set[str]:
    return {
        node.name
        for node in _tree(relative).body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _function(relative: str, name: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
    return next(
        node
        for node in ast.walk(_tree(relative))
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == name
    )


def _called_names(node: ast.AST) -> set[str]:
    result: set[str] = set()
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        if isinstance(child.func, ast.Name):
            result.add(child.func.id)
        elif isinstance(child.func, ast.Attribute):
            result.add(child.func.attr)
    return result


def _namespace_attributes(relative: str) -> set[str]:
    return {
        node.attr
        for node in ast.walk(_tree(relative))
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "DataGenerationNamespace"
    }


def test_generation_publication_is_owned_by_unit_of_work() -> None:
    repository = _source("worktrace/data_generation_repository.py")
    replacement = _source(
        "worktrace/services/database_replacement_generation_service.py"
    )
    assert "generation_clock" not in repository
    assert "generation_clock" not in replacement

    uow = _source("worktrace/domain_unit_of_work.py")
    assert "publish_committed" in uow
    assert "publish_replacement_committed" in uow
    assert "connection.commit()" in uow


def test_database_derived_caches_use_domain_and_replacement_identity() -> None:
    direct_generation_caches = {
        "settings": "worktrace/services/settings_service.py",
        "folders": "worktrace/services/folder_rule_service.py",
        "keywords": "worktrace/services/project_inference_service.py",
        "report_revision": "worktrace/services/report_revision_service.py",
    }
    for name, relative in direct_generation_caches.items():
        source = _source(relative)
        assert "DataGenerationNamespace.DATABASE_REPLACEMENT" in source, name
        assert (
            "generation_tuple(" in source
            or "DataGenerationRepository.get_many(" in source
        ), name
        assert "RULE_CACHE_TTL_SECONDS" not in source, name

    privacy = _source("worktrace/services/privacy_service.py")
    assert "active_database_epoch_key" in privacy
    assert "generation_tuple(" in privacy
    assert "DataGenerationNamespace.PRIVACY_CATALOG" in privacy
    assert "DataGenerationNamespace.DATABASE_REPLACEMENT" not in privacy
    assert "RULE_CACHE_TTL_SECONDS" not in privacy


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
    relative = "worktrace/services/history_mutation_job_service.py"
    source = _source(relative)
    assert "rule_impact_planner" not in source
    assert "rule_planning_service as planner" in source

    single = _function(relative, "submit_rule_job")
    assert [argument.arg for argument in single.args.args] == [
        "rule_type",
        "rule_id",
    ]
    assert [argument.arg for argument in single.args.kwonlyargs] == [
        "kind",
        "synchronous_scan_limit",
    ]
    assert "restore_enabled" not in {
        argument.arg
        for argument in (*single.args.args, *single.args.kwonlyargs)
    }

    for function_name in ("submit_rule_job", "submit_rule_batch_job"):
        calls = _called_names(_function(relative, function_name))
        assert "load_candidate_activities" not in calls
        assert "classify_activities" not in calls
        assert "run_job_batch" in calls


def test_recovery_service_only_plans_lifecycle_commands() -> None:
    recovery = _source("worktrace/services/recovery_service.py")
    lifecycle = _source("worktrace/services/activity_lifecycle_service.py")
    assert "UPDATE activity_log" not in recovery
    assert "activity_lifecycle_service.recover_activity_batch(" in recovery
    assert "activity_lifecycle_service.recover_continuation_batch(" in recovery
    assert "UPDATE activity_log" in lifecycle
