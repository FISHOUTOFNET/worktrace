from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from worktrace.webview_ui.bridge import SHIPPING_METHODS, WebViewBridge

pytestmark = [pytest.mark.contract, pytest.mark.webview]

ROOT = Path(__file__).resolve().parents[1]


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


def test_bridge_modules_import_api_not_backend_layers() -> None:
    forbidden = (
        "worktrace.constants",
        "worktrace.formatters",
        "worktrace.services",
        "worktrace.db",
        "worktrace.runtime",
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


def test_webview_bridge_public_methods_equal_shipping_allowlist() -> None:
    actual = {
        name
        for name, value in inspect.getmembers(WebViewBridge)
        if not name.startswith("_") and callable(value)
    }
    assert actual == set(SHIPPING_METHODS)
    assert "set_window" not in actual
    assert hasattr(WebViewBridge, "_set_window")
