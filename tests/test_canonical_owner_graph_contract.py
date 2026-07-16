from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = [pytest.mark.architecture, pytest.mark.contract]

ROOT = Path(__file__).resolve().parents[1]


def _module(path: str) -> ast.Module:
    return ast.parse((ROOT / path).read_text(encoding="utf-8"), filename=path)


def test_timeline_mutation_has_one_service_owner():
    assert not (ROOT / "worktrace/services/report_session_edit_service.py").exists()
    timeline_api = _module("worktrace/api/timeline_api.py")
    imported = {
        alias.name
        for node in ast.walk(timeline_api)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    assert "report_session_operation_service" in imported
    assert "report_session_edit_service" not in imported


def test_dead_timeline_snapshot_helpers_are_absent():
    tree = _module("worktrace/api/timeline_api.py")
    exported_functions = {
        node.name for node in tree.body if isinstance(node, ast.FunctionDef)
    }
    assert exported_functions.isdisjoint(
        {
            "get_snapshot_elapsed_seconds",
            "get_snapshot_extra_seconds",
            "get_snapshot_persisted_id",
            "get_snapshot_seconds_for_date_range",
        }
    )


def test_collector_checkpoint_uses_lifecycle_owner():
    tree = _module("worktrace/collector/activity_session_recorder.py")
    calls = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "lifecycle_checkpoint_activity" in calls


def test_application_instance_lease_has_no_collector_alias():
    tree = _module("worktrace/api/app_api.py")
    functions = {
        node.name for node in tree.body if isinstance(node, ast.FunctionDef)
    }
    assert "owns_collector" not in functions


def test_view_model_api_calls_keyword_only_summary_contract():
    tree = _module("worktrace/api/view_model_api.py")
    target = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "get_session_activity_summary_view_model"
    )
    assert target.args == []
    assert {keyword.arg for keyword in target.keywords} == {
        "report_date",
        "projection_instance_key",
        "expected_projection_revision",
    }
