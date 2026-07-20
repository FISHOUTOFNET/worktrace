from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from tests.support.application import build_test_bridge
from worktrace.webview_ui import bridge as bridge_module
from worktrace.webview_ui import bridge_rules as bridge_rules_module
from worktrace.webview_ui import project_rules_presenter as presenter_module

_PROJECT_LIFECYCLE_SUMMARY = {
    "id": 1, "name": "Client", "description": "billable", "language": "中文",
    "enabled": True, "archived": False,
}


def _patch_project_api(monkeypatch, method_name, result):
    calls: list = []

    def _spy(*args, **kwargs):
        calls.append((args, kwargs))
        return result

    monkeypatch.setattr(bridge_rules_module.project_api, method_name, _spy)
    return calls


def _forbidden_rule_api_replacement(name: str, calls: list[str], path_label: str):
    message = f"{name} must not be called by {path_label}"
    if name == "delete_project_keyword_rule":
        def _delete_keyword(rule_id, apply_to_history):
            calls.append(name)
            raise AssertionError(message)
        return _delete_keyword
    if name == "delete_project_folder_rule":
        def _delete_folder(rule_id, apply_to_history):
            calls.append(name)
            raise AssertionError(message)
        return _delete_folder

    def _generic(*args, **kwargs):
        calls.append(name)
        raise AssertionError(message)
    return _generic


_SENSITIVE_FORBIDDEN_TOKENS = (
    "traceback", "sqlite", "select ", "insert ", "update ", "window_title",
    "file_path_hint", "path_hint", "clipboard", "note", "secret", "details", "C:\\",
)


def _assert_no_sensitive_tokens(result) -> None:
    lowered = repr(result).lower()
    for forbidden in _SENSITIVE_FORBIDDEN_TOKENS:
        assert forbidden not in lowered, f"bridge payload must not leak {forbidden!r}: {result!r}"
