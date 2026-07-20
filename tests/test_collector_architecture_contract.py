from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = [pytest.mark.contract, pytest.mark.collector_runtime]

REPO_ROOT = Path(__file__).resolve().parents[1]
COLLECTOR_DIR = REPO_ROOT / "worktrace" / "collector"
SERVICES_DIR = REPO_ROOT / "worktrace" / "services"


def _source(rel_path: str) -> str:
    return (REPO_ROOT / rel_path).read_text(encoding="utf-8")


def _py_sources(root: Path) -> list[Path]:
    return sorted(root.rglob("*.py"))


def _calls_named(source: str, name: str) -> bool:
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id == name:
            return True
        if isinstance(func, ast.Attribute) and func.attr == name:
            return True
    return False


def _set_setting_keys(source: str) -> list[str]:
    keys: list[str] = []
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (
            (isinstance(func, ast.Name) and func.id == "set_setting")
            or (isinstance(func, ast.Attribute) and func.attr == "set_setting")
        ):
            continue
        if not node.args:
            continue
        first = node.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            keys.append(first.value)
    return keys


def test_current_activity_snapshot_writes_are_owned_by_publisher_or_runtime_cleanup():
    allowed = {
        "worktrace/collector/snapshot_publisher.py",
        "worktrace/services/runtime_activity_state_service.py",
    }
    offenders: list[str] = []
    for py_file in _py_sources(REPO_ROOT / "worktrace"):
        rel = py_file.relative_to(REPO_ROOT).as_posix()
        if rel in allowed:
            continue
        if "current_activity_snapshot" in _set_setting_keys(py_file.read_text(encoding="utf-8")):
            offenders.append(rel)
    assert offenders == []


def test_activity_session_recorder_does_not_build_or_write_snapshot_json():
    source = _source("worktrace/collector/activity_session_recorder.py")
    assert "current_activity_snapshot" not in source
    assert "json.dumps" not in source
    assert "set_setting" not in source


def test_collector_has_no_short_activity_absorption_owner_or_mutation_path():
    policy_symbols = (
        "ShortActivityFinalizer",
        "FinishedActivityCandidate",
        "merge_to_anchor",
        "resume_anchor",
        "resume_absorbed_anchor",
        "increment_activity_duration",
        "reopen_activity",
    )
    offenders: list[str] = []
    for py_file in _py_sources(COLLECTOR_DIR):
        rel = py_file.relative_to(REPO_ROOT).as_posix()
        source = py_file.read_text(encoding="utf-8")
        for symbol in policy_symbols:
            if symbol in source:
                offenders.append(f"{rel}: {symbol}")
    assert offenders == []


def test_collector_state_machine_has_no_activity_db_mutation_or_snapshot_logic():
    source = _source("worktrace/collector/state_machine.py")
    forbidden = (
        "activity_service.",
        "increment_activity_duration",
        "reopen_activity",
        "set_activity_duration",
        "current_activity_snapshot",
        "json.dumps",
        "SnapshotPublisher",
    )
    offenders = [token for token in forbidden if token in source]
    assert offenders == []


def test_collector_loop_stays_free_of_session_policy_and_display_projection():
    source = _source("worktrace/collector/collector.py")
    forbidden = (
        "ShortActivityFinalizer",
        "ActivitySessionRecorder",
        "project_ownership",
        "activity_display_model",
        "view_model_service",
        "pending_short_seconds",
        "current_activity_snapshot",
    )
    offenders = [token for token in forbidden if token in source]
    assert offenders == []


def test_collector_loop_never_turns_transient_failures_into_activity_error():
    source = _source("worktrace/collector/collector.py")
    assert 'transition_to("error"' not in source
    assert 'collector_status", "error"' not in source


def test_collector_loop_does_not_turn_stall_gaps_into_time_jump_boundaries():
    source = _source("worktrace/collector/collector.py")
    assert "detect_time_jump" not in source
    assert "reset_for_time_jump" not in source


def test_production_code_uses_hard_boundary_policy_for_session_boundaries():
    offenders: list[str] = []
    allowed = {"worktrace/services/session_boundary_service.py"}
    for py_file in _py_sources(REPO_ROOT / "worktrace"):
        rel = py_file.relative_to(REPO_ROOT).as_posix()
        if rel in allowed:
            continue
        source = py_file.read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr == "record_boundary":
                offenders.append(rel)
            elif isinstance(func, ast.Name) and func.id == "record_boundary":
                offenders.append(rel)
    assert offenders == []


def test_collector_health_logging_is_sanitized():
    source = _source("worktrace/collector/collector_health.py")
    forbidden = (
        "exc_info=True",
        "format_exc",
        "traceback",
        "window_title",
        "file_path",
        "clipboard",
        "sql",
        "note",
    )
    offenders = [token for token in forbidden if token in source.lower()]
    assert offenders == []


def test_open_row_lifecycle_commands_stay_behind_lifecycle_facade():
    forbidden_low_level = (
        "insert_activity_row",
        "close_activity_row",
        "close_all_open_rows",
    )
    offenders: list[str] = []
    for py_file in _py_sources(COLLECTOR_DIR):
        source = py_file.read_text(encoding="utf-8")
        for symbol in forbidden_low_level:
            if symbol in source:
                offenders.append(f"{py_file.name}: {symbol}")
    assert offenders == []
    lifecycle = _source("worktrace/services/activity_lifecycle_service.py")
    for public_command in (
        "persist_open_activity",
        "force_persist_open_activity_for_clipboard",
        "close_activity",
        "close_all_open_activities",
        "persist_midnight_anchor",
    ):
        assert f"def {public_command}" in lifecycle


def test_activity_display_model_remains_live_display_semantics_owner():
    forbidden_outside_owner = (
        "resolve_borrowed_display_anchor",
        "DisplaySessionPolicy",
        "classify_display_live_state",
    )
    owner_modules = {
        "worktrace/services/activity_display_model_service.py",
        "worktrace/services/activity_display_policy.py",
        "worktrace/services/activity_live_clock.py",
        "worktrace/services/activity_display_span.py",
        "worktrace/services/activity_row_overlay.py",
    }
    offenders: list[str] = []
    for py_file in _py_sources(SERVICES_DIR):
        rel = py_file.relative_to(REPO_ROOT).as_posix()
        if rel in owner_modules:
            continue
        source = py_file.read_text(encoding="utf-8")
        for symbol in forbidden_outside_owner:
            if symbol in source:
                offenders.append(f"{rel}: {symbol}")
    assert offenders == []


def test_report_services_do_not_read_current_activity_snapshot():
    offenders: list[str] = []
    for rel_path in (
        "worktrace/services/timeline_service.py",
        "worktrace/services/statistics_service.py",
        "worktrace/services/export_service.py",
    ):
        if "current_activity_snapshot" in _source(rel_path):
            offenders.append(rel_path)
    assert offenders == []


def test_collector_has_no_persistence_threshold_or_project_confirmation_window():
    lifecycle = _source("worktrace/services/activity_lifecycle_service.py")
    ownership = _source("worktrace/services/project_ownership_service.py")
    assert "HISTORY_PERSIST_THRESHOLD_SECONDS" not in lifecycle
    assert "PROJECT_OWNERSHIP_CONFIRM_SECONDS" not in ownership
    assert "pending=True" not in ownership


def test_live_display_has_no_virtual_or_borrowed_anchor_production_states():
    modules = (
        "worktrace/services/live_display_service.py",
        "worktrace/services/activity_display_model_service.py",
        "worktrace/services/activity_display_policy.py",
        "worktrace/services/activity_display_span.py",
        "worktrace/services/activity_row_overlay.py",
        "worktrace/services/view_model_service.py",
    )
    forbidden_states = (
        "borrowed_anchor_pending",
        "current_only_pending",
        "current_only_zero",
        "borrowed_anchor_static",
    )
    offenders = [
        f"{path}: {token}"
        for path in modules
        for token in forbidden_states
        if token in _source(path)
    ]
    assert offenders == []


def test_display_model_has_no_raw_db_mutation_or_borrowed_anchor_lookup():
    source = _source("worktrace/services/activity_display_model_service.py")
    forbidden = (
        "increment_activity_duration",
        "set_activity_duration",
        "reopen_activity",
        "close_activity",
        "persist_open_activity",
        "resolve_borrowed_display_anchor",
    )
    offenders = [token for token in forbidden if token in source]
    assert offenders == []


def test_pending_short_settings_are_limited_to_compatibility_cleanup():
    allowed = {
        "worktrace/db.py",
        "worktrace/schema_migrations.py",
        "worktrace/services/runtime_activity_state_service.py",
        "worktrace/services/secure_backup_service.py",
    }
    keys = ("pending_short_seconds", "pending_short_carry_provenance")
    offenders = [
        py_file.relative_to(REPO_ROOT).as_posix()
        for py_file in _py_sources(REPO_ROOT / "worktrace")
        if py_file.relative_to(REPO_ROOT).as_posix() not in allowed
        and any(key in py_file.read_text(encoding="utf-8") for key in keys)
    ]
    assert offenders == []


def test_frontend_keeps_single_live_runtime_clock():
    init = _source("worktrace/webview_ui/js/init.js")
    shipping_js = "\n".join(
        _source(f"worktrace/webview_ui/js/{name}")
        for name in ("core.js", "init.js", "overview.js", "timeline.js")
    )
    assert "App.liveRuntimeStore = liveRuntimeStore" in init
    assert 'Object.defineProperty(App, "liveRuntime"' in init
    for token in (
        "App.activeSpanClockByPage",
        "App.liveClockByPage",
        "App.liveClockBySpanId",
        "baseline_epoch_ms",
        "snapshot_baseline_epoch_ms",
    ):
        assert token not in shipping_js
