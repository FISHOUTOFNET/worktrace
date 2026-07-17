from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from worktrace.api import settings_api
from worktrace.webview_ui.bridge import SHIPPING_METHODS, WebViewBridge

pytestmark = [pytest.mark.contract, pytest.mark.parallel_safe]

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
