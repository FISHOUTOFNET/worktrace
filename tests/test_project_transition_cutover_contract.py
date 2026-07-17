from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = [pytest.mark.contract, pytest.mark.live_display, pytest.mark.parallel_safe]

ROOT = Path(__file__).resolve().parents[1]


def _text(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def _top_level_definitions(relative: str) -> set[str]:
    tree = ast.parse(_text(relative), filename=relative)
    return {
        node.name
        for node in tree.body
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
    }


def test_project_transition_model_is_physically_removed() -> None:
    relative = "worktrace/services/project_ownership_service.py"
    definitions = _top_level_definitions(relative)
    assert definitions.isdisjoint(
        {
            "ProjectTransition",
            "advance_ownership",
            "empty_state",
            "serialize_project_ownership",
        }
    )
    source = _text(relative)
    for retired in (
        "last_confirmed_project",
        "project_transition",
        "threshold_seconds",
    ):
        assert retired not in source


def test_public_live_contract_has_one_project_field_and_one_elapsed_fact() -> None:
    public_paths = (
        "worktrace/contracts/live_display_contracts.py",
        "worktrace/api/dto.py",
        "worktrace/collector/snapshot_publisher.py",
        "worktrace/services/live_display_service.py",
        "worktrace/services/activity_display_policy.py",
        "worktrace/services/activity_display_span.py",
        "worktrace/services/activity_row_overlay.py",
        "worktrace/services/activity_display_projection.py",
        "worktrace/services/view_model_service.py",
    )
    retired = (
        "ProjectTransition",
        "candidate_project",
        "project_transition",
        "project_transition_pending",
        "inferred_project_name",
        "extra_seconds",
        "checkpoint_seconds",
        "snapshot_extra_seconds",
    )
    offenders = [
        f"{relative}: {token}"
        for relative in public_paths
        for token in retired
        if token in _text(relative)
    ]
    assert offenders == []

    snapshot_source = _text("worktrace/collector/snapshot_publisher.py")
    assert '"display_project": display_label.to_dict()' in snapshot_source
    assert '"elapsed_seconds": elapsed' in snapshot_source
    assert '"persisted_activity_id": persisted_activity_id' in snapshot_source


def test_checkpoint_progress_stays_inside_recorder() -> None:
    recorder = _text("worktrace/collector/activity_session_recorder.py")
    publisher = _text("worktrace/collector/snapshot_publisher.py")
    assert "persisted_checkpoint_seconds" in recorder
    assert "persisted_checkpoint_seconds" not in publisher
    assert "checkpoint_seconds" not in publisher
