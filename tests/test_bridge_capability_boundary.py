from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from worktrace.api import settings_api
from worktrace.webview_ui.bridge import SHIPPING_METHODS, WebViewBridge

pytestmark = [pytest.mark.contract, pytest.mark.parallel_safe]

ROOT = Path(__file__).resolve().parents[1]

EXPECTED_SHIPPING_METHODS = frozenset(
    {
        "accept_first_run_notice",
        "archive_project_for_rules",
        "automatic_rules_status",
        "backfill_project_rule",
        "backfill_project_rules_batch",
        "clear_all_local_data",
        "copy_timeline_session",
        "create_excluded_folder_rule",
        "create_excluded_keyword_rule",
        "create_project_folder_rule",
        "create_project_for_rules",
        "create_project_keyword_rule",
        "delete_project_folder_rule",
        "delete_project_for_rules",
        "delete_project_keyword_rule",
        "export_encrypted_backup",
        "export_statistics_csv",
        "get_first_run_notice",
        "get_overview",
        "get_project_rules",
        "get_refresh_state",
        "get_settings_privacy_status",
        "get_statistics_export_summary",
        "get_status",
        "get_timeline",
        "get_timeline_session_activity_summary",
        "hide_timeline_session",
        "hide_timeline_session_activity",
        "import_encrypted_backup",
        "list_projects_for_timeline",
        "merge_timeline_session",
        "preview_encrypted_backup_manifest",
        "preview_project_rule_impact",
        "preview_project_rules_batch_impact",
        "save_timeline_session_edit",
        "set_clipboard_capture_enabled",
        "set_excluded_rules_enabled",
        "set_project_enabled_for_rules",
        "set_project_rule_enabled",
        "set_project_rules_batch_enabled",
        "split_timeline_session",
        "toggle_pause",
        "update_project_folder_rule",
        "update_project_for_rules",
        "update_project_keyword_rule",
    }
)


def _definitions(relative: str) -> set[str]:
    path = ROOT / relative
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }


def test_settings_api_has_named_capabilities_only() -> None:
    definitions = _definitions("worktrace/api/settings_api.py")
    assert definitions.isdisjoint(
        {
            "get_setting_value",
            "set_setting_value",
            "get_bool_setting_value",
            "get_int_setting_value",
            "get_list_setting_value",
            "set_list_setting_value",
            "clear_runtime_activity_state",
        }
    )
    assert not callable(settings_api.set_setting_value)
    assert "set_setting_value" not in settings_api.__all__


def test_bridge_modules_import_api_not_backend_layers() -> None:
    runtime_module = "worktrace." + "runtime"
    forbidden = (
        "worktrace.constants",
        "worktrace.formatters",
        "worktrace.services",
        "worktrace.db",
        runtime_module,
        "worktrace.collector",
        "worktrace.security",
        "worktrace.config",
    )
    offenders: list[str] = []
    for path in sorted((ROOT / "worktrace" / "webview_ui").glob("bridge*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            module = ""
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if node.level == 2 and module:
                    module = "worktrace." + module
            elif isinstance(node, ast.Import):
                for item in node.names:
                    if item.name.startswith(forbidden):
                        offenders.append(f"{path.name}:{node.lineno}:{item.name}")
                continue
            if any(module == value or module.startswith(value + ".") for value in forbidden):
                offenders.append(f"{path.name}:{node.lineno}:{module}")
    assert offenders == []


def test_shipping_bridge_public_methods_equal_allowlist() -> None:
    assert SHIPPING_METHODS == EXPECTED_SHIPPING_METHODS
    bridge = WebViewBridge()
    shipping = bridge.shipping_api
    actual = {
        name
        for name, value in inspect.getmembers(shipping)
        if not name.startswith("_") and callable(value)
    }
    assert actual == set(SHIPPING_METHODS)
    assert not hasattr(shipping, "set_window")
    assert hasattr(bridge, "set_window")
