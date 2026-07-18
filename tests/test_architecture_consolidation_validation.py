from __future__ import annotations

import ast
from pathlib import Path

import pytest

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
WORKFLOW_ALLOWLIST = {"_validation.yml", "acceptance.yml", "ci.yml"}
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


def test_page_and_heartbeat_use_one_revision_owner(temp_db):
    runtime_activity_state_service.clear_runtime_activity_state(
        "architecture_validation"
    )
    today = timeline_service.get_default_report_date()
    page = view_model_service.get_overview_view_model(today)
    heartbeat = refresh_state_view_model_service.get_refresh_state_view_model(
        today
    )
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
        return {"ok": True, "summary_rows": []}

    monkeypatch.setattr(
        view_model_service,
        "get_session_activity_summary_view_model",
        fake_summary,
    )

    result = view_model_api.get_session_activity_summary_view_model(
        report_date="2026-07-16",
        projection_instance_key="session:1",
        expected_projection_revision="a" * 40,
    )

    assert result["ok"] is True
    assert result["summary_rows"] == []
    assert result["runtime"]["schema_version"] == 1
    assert result["runtime"]["surface"] == "details"
    assert result["runtime"]["scope_report_date"] == "2026-07-16"
    assert captured == {
        "report_date": "2026-07-16",
        "projection_instance_key": "session:1",
        "expected_projection_revision": "a" * 40,
    }


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


def test_permanent_ci_and_acceptance_workflows_are_read_only():
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

    combined_source = ""
    for workflow in workflows:
        source = workflow.read_text(encoding="utf-8")
        combined_source += "\n" + source
        lowered = source.lower()
        for command in FORBIDDEN_WORKFLOW_COMMANDS:
            assert command.lower() not in lowered, (
                f"{workflow.name} must validate code, not run {command}"
            )
        assert "contents: write" not in lowered
        assert "worktrace-ci-diagnostics" not in source
        assert "github-actions[bot]" not in source
        assert "agent/" not in source
        assert "contents: read" in source

    assert "3.12" not in combined_source
    assert "run_python312" not in combined_source

    reusable_source = (workflow_dir / "_validation.yml").read_text(encoding="utf-8")
    checkout_count = reusable_source.count("uses: actions/checkout@")
    assert checkout_count == 3
    assert reusable_source.count("persist-credentials: false") == checkout_count
    assert reusable_source.count("git rev-parse HEAD") == checkout_count
    assert reusable_source.count("Capture tested revision") == checkout_count
    assert "workflow_call:" in reusable_source
    assert 'python-version: "3.11"' in reusable_source
    assert "node --test tests/webview/*.test.js" in reusable_source
    assert "python -m PyInstaller --noconfirm --clean WorkTrace.spec" in reusable_source
    assert "scripts\\build_windows_installer.ps1" in reusable_source

    ci_source = (workflow_dir / "ci.yml").read_text(encoding="utf-8")
    assert "pull_request:" in ci_source
    assert "push:" in ci_source
    assert "./.github/workflows/_validation.yml" in ci_source
    assert "github.event.pull_request.head.sha || github.sha" in ci_source
    assert "run_node_tests: false" in ci_source
    assert "run_build_smoke: false" in ci_source
    assert "cancel-in-progress: false" in ci_source

    acceptance_source = (workflow_dir / "acceptance.yml").read_text(encoding="utf-8")
    for event_type in ("ready_for_review", "synchronize", "reopened"):
        assert event_type in acceptance_source
    assert "github.event.pull_request.draft == false" in acceptance_source
    assert "github.event.pull_request.head.sha" in acceptance_source
    assert "run_node_tests: true" in acceptance_source
    assert "run_build_smoke: true" in acceptance_source
    assert "cancel-in-progress: false" in acceptance_source


def test_live_semantics_harness_recent_reuses_overview_projection(
    temp_db,
    monkeypatch,
):
    live = LiveSemanticsHarness(monkeypatch)
    live.record("A", "09:00:00")

    pages = live.pages()

    assert pages["overview"]["ok"] is True
    assert pages["recent"]["items"]
    assert pages["recent"]["items"] == pages["overview"]["activities"]
    assert pages["recent"]["runtime"] == pages["overview"]["runtime"]
