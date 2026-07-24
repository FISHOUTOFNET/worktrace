from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tests.support.application import TestRuntime
from tests.support.live_semantics_harness import LiveSemanticsHarness
from worktrace import db
from worktrace.api import view_model_api
from worktrace.services import (
    refresh_state_view_model_service,
    runtime_activity_state_service,
    timeline_service,
    view_model_service,
)

pytestmark = [pytest.mark.db, pytest.mark.integration, pytest.mark.serial]

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_ALLOWLIST = {"_validation.yml", "ci.yml"}
FORBIDDEN_WORKFLOW_COMMANDS = (
    "git push",
    "git merge",
    "git commit",
    "git checkout -B",
)
FORBIDDEN_HELPER_PREFIXES = (
    "agent_",
    "apply_patch_",
    "one_time_",
)
RUNTIME_TOP_LEVEL_ALIASES = {
    "activity_display_model",
    "collection_status",
    "collector_status",
    "current_activity",
    "current_activity_display_span_id",
    "current_activity_elapsed_seconds",
    "current_resource_identity_hash",
    "display_span_id",
    "live_clock",
    "live_revision",
    "page_revision",
    "paused",
    "sample_epoch_ms",
    "sample_id",
    "stable_live_key_hash",
    "status_display",
    "structure_revision",
}


def _runtime_context() -> tuple[TestRuntime, dict[str, object]]:
    return TestRuntime(), {
        "collector_status": "running",
        "collector_last_failure_code": None,
    }


def test_page_and_heartbeat_use_one_revision_owner(temp_db):
    runtime_activity_state_service.clear_runtime_activity_state(
        "architecture_validation"
    )
    today = timeline_service.get_default_report_date()
    page = view_model_service.get_overview_view_model(today)
    heartbeat = refresh_state_view_model_service.get_refresh_state_view_model(today)
    assert page["structure_revision"] == heartbeat["structure_revision"]
    assert page["page_revision"] == heartbeat["page_revision"]


def test_session_summary_api_calls_keyword_only_service(monkeypatch):
    captured: dict[str, object] = {}

    def fake_summary(
        *,
        report_date: str | None = None,
        projection_instance_key: str,
        expected_projection_revision: str | None = None,
    ) -> dict[str, object]:
        captured.update(
            {
                "report_date": report_date,
                "projection_instance_key": projection_instance_key,
                "expected_projection_revision": expected_projection_revision,
            }
        )
        return {
            "ok": True,
            "date": report_date,
            "summary_rows": [],
            "live_clock": {
                "sampled_at_epoch_ms": 0,
                "started_at_epoch_ms": 0,
                "elapsed_seconds_at_sample": 0,
                "aggregate_base_seconds": 0,
                "duration_semantic": "static_closed",
                "is_live": False,
                "live_state": "none",
                "display_span_id": "",
                "stable_live_key_hash": "",
            },
        }

    monkeypatch.setattr(
        view_model_service,
        "get_session_activity_summary_view_model",
        fake_summary,
    )
    runtime, collector_status = _runtime_context()

    result = view_model_api.get_session_activity_summary_view_model(
        report_date="2026-07-16",
        projection_instance_key="session:1",
        expected_projection_revision="a" * 40,
        runtime=runtime,
        collector_status=collector_status,
    )

    assert result["ok"] is True
    assert result["summary_rows"] == []
    assert result["runtime"]["schema_version"] == 2
    assert result["runtime"]["surface"] == "details"
    assert result["runtime"]["scope_report_date"] == "2026-07-16"
    assert not RUNTIME_TOP_LEVEL_ALIASES.intersection(result)
    assert captured == {
        "report_date": "2026-07-16",
        "projection_instance_key": "session:1",
        "expected_projection_revision": "a" * 40,
    }


def test_overview_api_exposes_one_v2_runtime_transport(temp_db):
    runtime, collector_status = _runtime_context()
    result = view_model_api.get_overview_view_model(
        runtime=runtime,
        collector_status=collector_status,
    )

    assert result["ok"] is True
    envelope = result["runtime"]
    assert envelope["schema_version"] == 2
    assert set(envelope) == {
        "schema_version",
        "surface",
        "scope_report_date",
        "live_report_date",
        "snapshot",
        "current_activity",
        "clock",
        "current_project",
        "collector",
        "runtime_phase",
        "workers",
        "generations",
        "database_replacement_epoch",
        "error_codes",
        "revisions",
        "runtime_consistent",
        "needs_full_refresh",
    }
    assert not RUNTIME_TOP_LEVEL_ALIASES.intersection(result)
    assert set(envelope["clock"]) == {
        "sampled_at_epoch_ms",
        "started_at_epoch_ms",
        "elapsed_seconds_at_sample",
        "aggregate_base_seconds",
        "duration_semantic",
        "is_live",
        "live_state",
        "display_span_id",
        "stable_live_key_hash",
    }
    current = envelope["current_activity"] or {}
    if current.get("active") and current.get("is_persisted"):
        assert envelope["clock"]["display_span_id"]
        assert envelope["clock"]["stable_live_key_hash"]
        assert "display_span_id" not in current
        assert "stable_live_key_hash" not in current


def test_schema_trigger_surface_is_constraint_only(temp_db):
    with db.get_connection() as conn:
        names = {
            str(row["name"])
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'trigger'"
            ).fetchall()
        }
    assert names == {
        "project_reserved_name_insert",
        "project_reserved_name_update",
        "validate_report_split_operation",
        "validate_report_operation_receipt_members",
    }


def test_frontend_uses_explicit_bridge_and_settings_bindings():
    init_source = (REPO_ROOT / "worktrace/webview_ui/js/init.js").read_text(
        encoding="utf-8"
    )
    assert "App.callBridge =" not in init_source
    assert "MutationObserver" not in init_source
    assert 'bind("settings-clear-local-data-btn", "click", App.clearAllLocalData)' in init_source
    assert "schema_version || 0) !== 1" not in init_source
    assert "bundle.current_activity" not in init_source
    assert "bundle.live_clock" not in init_source
    assert "state.collector_status" not in init_source


def test_composition_root_imports_canonical_windows_adapter():
    tree = ast.parse(
        (REPO_ROOT / "worktrace/runtime/app_runtime.py").read_text(encoding="utf-8")
    )
    imports = {
        (node.module, alias.name)
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    assert ("platforms.windows_adapter", "WindowsAdapter") in imports
    assert all("hardened_windows_adapter" not in str(module) for module, _ in imports)
    assert not (REPO_ROOT / "worktrace/platforms/hardened_windows_adapter.py").exists()


def test_continuity_reads_typed_runtime_state_not_settings_json():
    tree = ast.parse(
        (REPO_ROOT / "worktrace/services/page_read_context.py").read_text(
            encoding="utf-8"
        )
    )
    imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and node.module == "runtime_activity_state_service"
        for alias in node.names
    }
    assert "sample_runtime_activity_state" in imports
    assert not any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "get_setting"
        for node in ast.walk(tree)
    )


def test_page_wrapper_services_are_removed():
    for name in (
        "overview_view_model_service.py",
        "timeline_view_model_service.py",
        "session_detail_view_model_service.py",
    ):
        assert not (REPO_ROOT / "worktrace/services" / name).exists()


def test_permanent_ci_workflows_are_read_only():
    workflow_dir = REPO_ROOT / ".github" / "workflows"
    workflows = sorted(
        path
        for pattern in ("*.yml", "*.yaml")
        for path in workflow_dir.glob(pattern)
    )
    assert {path.name for path in workflows} == WORKFLOW_ALLOWLIST

    github_dir = REPO_ROOT / ".github"
    one_time_helpers = [
        path.relative_to(REPO_ROOT).as_posix()
        for path in github_dir.rglob("*.py")
        if path.name.startswith(FORBIDDEN_HELPER_PREFIXES)
    ]
    assert not one_time_helpers, "one-time GitHub helpers remain: " + ", ".join(
        one_time_helpers
    )

    for path in workflows:
        source = path.read_text(encoding="utf-8")
        assert not any(command in source for command in FORBIDDEN_WORKFLOW_COMMANDS)
