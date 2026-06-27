from __future__ import annotations

import re
from pathlib import Path

from worktrace.webview_ui import bridge as bridge_module
from worktrace.webview_ui.bridge import WebViewBridge


def test_get_project_rules_success_payload(monkeypatch):
    monkeypatch.setattr(
        bridge_module.project_api,
        "list_project_bindings",
        lambda: [
            {
                "id": 1,
                "name": "Client",
                "description": "Billable work",
                "enabled": 1,
                "created_by": "user",
                "folder_rules": [
                    {
                        "id": 10,
                        "folder_path": r"D:\Client",
                        "enabled": 1,
                        "recursive": 1,
                    }
                ],
                "keyword_rules": [
                    {
                        "id": 11,
                        "keyword": "Spec",
                        "enabled": 0,
                    }
                ],
            },
            {
                "id": 2,
                "name": "Disabled",
                "description": "",
                "enabled": False,
                "created_by": "user",
                "folder_rules": [
                    {
                        "id": 12,
                        "folder_path": r"D:\Disabled",
                        "enabled": False,
                        "recursive": False,
                    }
                ],
                "keyword_rules": [],
            },
            {
                "id": 3,
                "name": "排除规则",
                "description": "命中后匿名记录",
                "enabled": 0,
                "created_by": "system",
                "folder_rules": [],
                "keyword_rules": [],
            },
        ],
    )

    result = WebViewBridge().get_project_rules()

    assert result["ok"] is True
    projects = result["projects"]
    assert len(projects) == 3

    client = projects[0]
    assert client["id"] == 1
    assert isinstance(client["id"], int)
    assert client["name"] == "Client"
    assert client["description"] == "Billable work"
    assert client["enabled"] is True
    assert isinstance(client["enabled"], bool)
    assert client["created_by"] == "user"
    assert client["is_excluded"] is False
    assert isinstance(client["is_excluded"], bool)
    assert client["rule_count"] == 2
    assert isinstance(client["rule_count"], int)
    assert client["folder_rule_count"] == 1
    assert client["keyword_rule_count"] == 1
    assert client["summary"] == "2 条规则：文件夹 1，关键词 1"

    folder = client["rules"][0]
    assert folder["kind"] == "folder"
    assert folder["kind_label"] == "文件夹"
    assert folder["id"] == 10
    assert folder["target"] == r"D:\Client"
    assert folder["enabled"] is True
    assert folder["recursive"] is True
    assert "归属项目：Client" in folder["detail"]
    assert "包含子文件夹" in folder["detail"]
    assert "已启用" in folder["detail"]

    keyword = client["rules"][1]
    assert keyword["kind"] == "keyword"
    assert keyword["kind_label"] == "关键词"
    assert keyword["id"] == 11
    assert keyword["target"] == "Spec"
    assert keyword["enabled"] is False
    assert keyword["recursive"] is None
    assert "归属项目：Client" in keyword["detail"]
    assert "已禁用" in keyword["detail"]

    disabled = projects[1]
    assert disabled["enabled"] is False
    assert disabled["summary"].startswith("已禁用")
    disabled_folder = disabled["rules"][0]
    assert disabled_folder["enabled"] is False
    assert disabled_folder["recursive"] is False
    assert "仅直接文件" in disabled_folder["detail"]
    assert "已禁用" in disabled_folder["detail"]

    excluded = projects[2]
    assert excluded["is_excluded"] is True
    assert excluded["created_by"] == "system"
    assert "命中后匿名记录" in excluded["summary"]


def test_get_project_rules_empty_projects(monkeypatch):
    monkeypatch.setattr(
        bridge_module.project_api,
        "list_project_bindings",
        lambda: [],
    )

    result = WebViewBridge().get_project_rules()

    assert result == {"ok": True, "projects": []}


def test_get_project_rules_exception_collapses_without_sensitive_text(monkeypatch):
    def fail():
        raise RuntimeError(
            "boom SELECT * FROM activity_log traceback window_title clipboard note"
        )

    monkeypatch.setattr(bridge_module.project_api, "list_project_bindings", fail)

    result = WebViewBridge().get_project_rules()

    assert result == {
        "ok": False,
        "error": "加载项目规则失败",
        "projects": [],
    }
    lowered = repr(result).lower()
    for forbidden in (
        "traceback",
        "select",
        "boom",
        "window_title",
        "clipboard",
        "note",
        "activity_log",
    ):
        assert forbidden not in lowered


def test_project_rules_bridge_import_boundary():
    source = Path(bridge_module.__file__).read_text(encoding="utf-8")
    forbidden_patterns = (
        r"^\s*from\s+\.\.services(\s|\.)",
        r"^\s*from\s+\.\.db(\s|\.)",
        r"^\s*from\s+\.\.ui(\s|\.)",
        r"^\s*from\s+worktrace\.services(\s|\.)",
        r"^\s*from\s+worktrace\.db(\s|\.)",
        r"^\s*from\s+worktrace\.ui(\s|\.)",
        r"^\s*import\s+worktrace\.services(\s|$)",
        r"^\s*import\s+worktrace\.db(\s|$)",
        r"^\s*import\s+worktrace\.ui(\s|$)",
    )
    for pattern in forbidden_patterns:
        assert not re.search(pattern, source, re.MULTILINE), (
            "bridge.py must not import forbidden backend/UI module: " + pattern
        )
