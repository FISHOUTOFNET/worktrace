from __future__ import annotations

import json
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


def test_get_project_rules_malformed_rows_are_safe_and_json_serializable(monkeypatch):
    monkeypatch.setattr(
        bridge_module.project_api,
        "list_project_bindings",
        lambda: [
            {
                "id": "bad-id",
                "name": "",
                "enabled": "not-a-bool",
                "created_by": None,
                "folder_rules": [
                    {
                        "id": "bad-rule-id",
                        "enabled": "nope",
                        "recursive": "bad-recursive",
                    },
                    "unexpected folder row",
                ],
                "keyword_rules": [
                    {
                        "id": None,
                        "enabled": None,
                    },
                    None,
                ],
            },
            "unexpected project row",
        ],
    )

    result = WebViewBridge().get_project_rules()

    json.dumps(result, ensure_ascii=False)
    assert result["ok"] is True
    assert len(result["projects"]) == 2

    project = result["projects"][0]
    assert project["id"] == 0
    assert project["name"] == "未知项目"
    assert project["description"] == ""
    assert project["enabled"] is True
    assert project["created_by"] == ""
    assert project["rule_count"] == 4
    assert project["folder_rule_count"] == 2
    assert project["keyword_rule_count"] == 2

    folder = project["rules"][0]
    assert folder["id"] == 0
    assert folder["target"] == ""
    assert folder["enabled"] is True
    assert folder["recursive"] is True
    assert "包含子文件夹" in folder["detail"]

    keyword = project["rules"][2]
    assert keyword["id"] == 0
    assert keyword["target"] == ""
    assert keyword["enabled"] is True
    assert keyword["recursive"] is None

    fallback_project = result["projects"][1]
    assert fallback_project["id"] == 0
    assert fallback_project["name"] == "未知项目"
    assert fallback_project["rules"] == []
    assert fallback_project["summary"] == "暂无规则"


def test_get_project_rules_missing_rule_lists_and_description(monkeypatch):
    monkeypatch.setattr(
        bridge_module.project_api,
        "list_project_bindings",
        lambda: [{"id": 1, "name": "Client", "enabled": 1, "created_by": "user"}],
    )

    result = WebViewBridge().get_project_rules()

    project = result["projects"][0]
    assert project["description"] == ""
    assert project["folder_rule_count"] == 0
    assert project["keyword_rule_count"] == 0
    assert project["rule_count"] == 0
    assert project["rules"] == []
    assert project["summary"] == "暂无规则"


def test_get_project_rules_bool_type_normalization(monkeypatch):
    monkeypatch.setattr(
        bridge_module.project_api,
        "list_project_bindings",
        lambda: [
            {
                "id": 1,
                "name": "OffInt",
                "enabled": 0,
                "folder_rules": [{"id": 10, "enabled": 0, "recursive": 0}],
                "keyword_rules": [],
            },
            {
                "id": 2,
                "name": "OnInt",
                "enabled": 1,
                "folder_rules": [{"id": 20, "enabled": 1, "recursive": 1}],
                "keyword_rules": [],
            },
            {
                "id": 3,
                "name": "OffString",
                "enabled": "0",
                "folder_rules": [{"id": 30, "enabled": "0", "recursive": "0"}],
                "keyword_rules": [],
            },
            {
                "id": 4,
                "name": "OnString",
                "enabled": "1",
                "folder_rules": [{"id": 40, "enabled": "1", "recursive": "1"}],
                "keyword_rules": [],
            },
            {
                "id": 5,
                "name": "NoneDefaults",
                "enabled": None,
                "folder_rules": [{"id": 50, "enabled": None, "recursive": None}],
                "keyword_rules": [],
            },
        ],
    )

    result = WebViewBridge().get_project_rules()

    projects = result["projects"]
    assert [project["enabled"] for project in projects] == [
        False,
        True,
        False,
        True,
        True,
    ]
    assert [project["rules"][0]["enabled"] for project in projects] == [
        False,
        True,
        False,
        True,
        True,
    ]
    assert [project["rules"][0]["recursive"] for project in projects] == [
        False,
        True,
        False,
        True,
        True,
    ]


def test_get_project_rules_missing_targets_use_safe_empty_fallback(monkeypatch):
    monkeypatch.setattr(
        bridge_module.project_api,
        "list_project_bindings",
        lambda: [
            {
                "id": 1,
                "name": "Client",
                "enabled": 1,
                "folder_rules": [{"id": 10, "enabled": 1, "recursive": 1}],
                "keyword_rules": [{"id": 20, "enabled": 1}],
            }
        ],
    )

    result = WebViewBridge().get_project_rules()

    folder, keyword = result["projects"][0]["rules"]
    assert folder["target"] == ""
    assert keyword["target"] == ""
    assert "Traceback" not in repr(result)


def test_get_project_rules_sensitive_tokens_absent_from_success_payload(monkeypatch):
    monkeypatch.setattr(
        bridge_module.project_api,
        "list_project_bindings",
        lambda: [
            {
                "id": 1,
                "name": "Client",
                "description": "",
                "enabled": 1,
                "created_by": "user",
                "window_title": "Sensitive Window",
                "clipboard": "Sensitive Clipboard",
                "note": "Sensitive Note",
                "folder_rules": [],
                "keyword_rules": [],
            }
        ],
    )

    result = WebViewBridge().get_project_rules()

    rendered = repr(result)
    for forbidden in (
        "traceback",
        "Traceback",
        "sqlite",
        "SELECT",
        "window_title",
        "clipboard",
        "note",
        "Sensitive Window",
        "Sensitive Clipboard",
        "Sensitive Note",
    ):
        assert forbidden not in rendered


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
        "sqlite",
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
