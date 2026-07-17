from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.contract, pytest.mark.parallel_safe]

ROOT = Path(__file__).resolve().parents[1]


def _source(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def _module(relative: str) -> ast.Module:
    return ast.parse(_source(relative), filename=relative)


def test_project_inference_delegates_assignment_writes() -> None:
    source = _source("worktrace/services/project_inference_service.py")
    tree = _module("worktrace/services/project_inference_service.py")
    functions = {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert "_upsert_assignment" not in functions
    assert "assignment_command_service.upsert_assignment" in source
    assert "INSERT INTO activity_project_assignment" not in source
    assert "UPDATE activity_project_assignment" not in source


def test_persisted_activity_inference_requires_resource_fact() -> None:
    source = _source("worktrace/services/project_inference_service.py")
    assert 'raise ValueError("data_repair_required")' in source
    resource_loader = next(
        node
        for node in _module("worktrace/services/project_inference_service.py").body
        if isinstance(node, ast.FunctionDef) and node.name == "_resource_for_activity"
    )
    function_source = ast.get_source_segment(source, resource_loader) or ""
    assert "infer_resource_for_activity" not in function_source


def test_activity_queries_do_not_create_system_projects() -> None:
    source = _source("worktrace/services/activity_service.py")
    assert "get_or_create_uncategorized_project" not in source
    assert "require_uncategorized_project_id" in source
    system_source = _source("worktrace/services/system_project_service.py")
    require_function = next(
        node
        for node in _module("worktrace/services/system_project_service.py").body
        if isinstance(node, ast.FunctionDef) and node.name == "require_system_project_id"
    )
    require_source = ast.get_source_segment(system_source, require_function) or ""
    assert "INSERT INTO project" not in require_source


def test_runtime_boundaries_use_lifecycle_transaction() -> None:
    state_machine = _source("worktrace/collector/state_machine.py")
    assert "activity_lifecycle_service.close_at_boundary" in state_machine
    assert "session_boundary_service" not in state_machine
    assert "record_hard_boundary" not in state_machine
    lifecycle = _source("worktrace/services/activity_lifecycle_service.py")
    assert "session_boundary_service.insert_boundary(conn" in lifecycle
    assert "close_all_open_activities(\n            conn" in lifecycle


def test_retired_short_buffer_hooks_are_absent() -> None:
    recorder = _source("worktrace/collector/activity_session_recorder.py")
    state_machine = _source("worktrace/collector/state_machine.py")
    assert "clear_short_buffers" not in recorder
    assert "clear_short_buffers" not in state_machine
    assert "_update_persisted_progress" not in recorder
