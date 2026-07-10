"""Fast static guards for retired live-display semantics.

These checks deliberately protect boundaries rather than replaying the old
pending/borrowed scenarios.  Compatibility metadata may be decoded at an
ingress boundary, but it must not regain lifecycle, projection, revision, or
frontend-identity meaning.
"""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RETIRED_STATES = {
    "current_only_pending",
    "borrowed_anchor_pending",
    "virtual_pending",
    "absorbed_pending",
    "current_only_zero",
    "borrowed_anchor_static",
}


def _text(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def _function_text(relative: str, name: str) -> str:
    source = _text(relative)
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return ast.get_source_segment(source, node) or ""
    raise AssertionError(f"{relative} has no {name}()")


def test_production_live_contract_has_no_retired_state_labels():
    modules = (
        "worktrace/contracts/live_display_contracts.py",
        "worktrace/services/live_display_service.py",
        "worktrace/services/activity_display_model_service.py",
        "worktrace/services/activity_display_policy.py",
        "worktrace/services/activity_display_span.py",
        "worktrace/services/activity_row_overlay.py",
        "worktrace/services/view_model_service.py",
    )
    offenders = [
        f"{module}: {state}"
        for module in modules
        for state in RETIRED_STATES
        if state in _text(module)
    ]
    assert offenders == []


def test_active_tests_do_not_assert_retired_states_or_skip_them():
    offenders: list[str] = []
    retired_skip_markers = (
        "pytest.skip(\"virtual",
        "pytest.skip(\"legacy short",
        "snapshot-only pending projection was removed",
        "_RETIRED_SHORT_ACTIVITY_CASES",
        "_retire_",
    )
    for path in sorted((ROOT / "tests").rglob("test_*.py")):
        if path.name == Path(__file__).name:
            continue
        source = path.read_text(encoding="utf-8")
        for marker in retired_skip_markers:
            if marker in source:
                offenders.append(f"{path.relative_to(ROOT)}: {marker}")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Compare) or not node.ops:
                continue
            values = [node.left, *node.comparators]
            if any(
                isinstance(value, ast.Constant) and value.value in RETIRED_STATES
                for value in values
            ) and any(isinstance(op, (ast.Eq, ast.In)) for op in node.ops):
                offenders.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    assert offenders == []


def test_collector_has_no_short_absorption_or_pending_runtime_owner():
    forbidden = (
        "ShortActivityFinalizer",
        "FinishedActivityCandidate",
        "merge_to_anchor",
        "resume_anchor",
        "resume_absorbed_anchor",
        "increment_activity_duration",
        "reopen_activity",
        "pending_short_seconds",
    )
    offenders = [
        f"{path.relative_to(ROOT)}: {token}"
        for path in (ROOT / "worktrace" / "collector").rglob("*.py")
        for token in forbidden
        if token in path.read_text(encoding="utf-8")
    ]
    assert offenders == []


def test_display_model_neither_borrows_rows_nor_mutates_lifecycle():
    modules = (
        "worktrace/services/activity_display_model_service.py",
        "worktrace/services/live_display_service.py",
        "worktrace/services/activity_display_projection.py",
    )
    forbidden = (
        "resolve_borrowed_display_anchor",
        "increment_activity_duration",
        "set_activity_duration",
        "reopen_activity",
        "close_activity",
        "persist_open_activity",
    )
    offenders = [
        f"{module}: {token}"
        for module in modules
        for token in forbidden
        if token in _text(module)
    ]
    assert offenders == []


def test_candidate_metadata_cannot_enter_revision_or_identity_inputs():
    inputs = (
        ("worktrace/services/live_display_service.py", "_live_display_key"),
        ("worktrace/services/live_display_service.py", "_stable_live_key"),
        ("worktrace/services/activity_display_projection.py", "build_revision_parts"),
    )
    metadata = (
        "candidate_project",
        "current_candidate_project",
        "suggested_project_name",
        "inferred_project_name",
        "project_transition",
    )
    offenders = [
        f"{module}.{function}: {token}"
        for module, function in inputs
        for token in metadata
        if token in _function_text(module, function)
    ]
    assert offenders == []


def test_frontend_has_one_live_delta_and_no_legacy_identity_inputs():
    frontend = "\n".join(
        _text(relative)
        for relative in (
            "worktrace/webview_ui/js/core.js",
            "worktrace/webview_ui/js/init.js",
            "worktrace/webview_ui/js/overview.js",
            "worktrace/webview_ui/js/timeline.js",
        )
    )
    forbidden = (
        "baseline_epoch_ms",
        "snapshot_baseline_epoch_ms",
        "App.activeSpanClockByPage",
        "App.liveClockByPage",
        "App.liveClockBySpanId",
        "candidate_project",
        "suggested_project_name",
        "inferred_project_name",
        "project_transition",
        "is_virtual_live === true",
    )
    assert [token for token in forbidden if token in frontend] == []
