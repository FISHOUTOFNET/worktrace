from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from tests.support.application import build_test_bridge
from worktrace.webview_ui import bridge as bridge_module
from worktrace.webview_ui import bridge_rules as bridge_rules_module
from worktrace.webview_ui import project_rules_presenter as presenter_module

pytestmark = [pytest.mark.db, pytest.mark.integration, pytest.mark.contract]


def test_get_project_rules_success_payload(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.project_api,
        "list_project_bindings",
        lambda: [
            {
                "id": 1,
                "name": "Client",
                "description": "Billable work",
                "language": "英语",
                "last_used_at": "2026-07-01 10:00:00",
                "enabled": 1,
                "created_by": "user",
                "is_excluded": False,
                "is_system": False,
                "editable": True,
                "can_toggle": True,
                "can_archive": True,
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
                "language": "日语",
                "last_used_at": None,
                "enabled": False,
                "created_by": "user",
                "is_excluded": False,
                "is_system": False,
                "editable": True,
                "can_toggle": True,
                "can_archive": True,
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
                "is_excluded": True,
                "is_system": True,
                "editable": False,
                "can_toggle": False,
                "can_archive": False,
                "folder_rules": [],
                "keyword_rules": [],
            },
        ],
    )

    result = build_test_bridge().get_project_rules()

    assert result["ok"] is True
    projects = result["projects"]
    assert len(projects) == 2
    advanced = result["advanced"]
    assert advanced["excluded_rules_enabled"] is False
    assert advanced["excluded_project"]["name"] == "排除规则"
    assert advanced["excluded_rules"] == []

    client = projects[0]
    assert client["id"] == 1
    assert isinstance(client["id"], int)
    assert client["name"] == "Client"
    assert client["description"] == "Billable work"
    assert client["language"] == "英语"
    assert client["last_used_at"] == "2026-07-01 10:00:00"
    assert client["enabled"] is True
    assert isinstance(client["enabled"], bool)
    assert "created_by" not in client
    assert client["is_system"] is False
    assert client["editable"] is True
    assert client["is_excluded"] is False
    assert isinstance(client["is_excluded"], bool)
    assert client["summary"] == "2 条规则：文件夹 1，关键词 1"

    folder = client["rules"][0]
    assert folder["kind"] == "folder"
    assert folder["kind_label"] == "文件夹"
    assert folder["id"] == 10
    assert folder["target"] == r"D:\Client"
    assert folder["enabled"] is True
    assert folder["recursive"] is True
    assert "包含子文件夹" in folder["detail"]
    assert "已启用" in folder["detail"]

    keyword = client["rules"][1]
    assert keyword["kind"] == "keyword"
    assert keyword["kind_label"] == "关键词"
    assert keyword["id"] == 11
    assert keyword["target"] == "Spec"
    assert keyword["enabled"] is False
    assert keyword["recursive"] is None
    assert "已禁用" in keyword["detail"]

    disabled = projects[1]
    assert disabled["enabled"] is False
    assert disabled["summary"].startswith("已禁用")
    disabled_folder = disabled["rules"][0]
    assert disabled_folder["enabled"] is False
    assert disabled_folder["recursive"] is False
    assert "仅直接文件" in disabled_folder["detail"]
    assert "已禁用" in disabled_folder["detail"]

    excluded = advanced["excluded_project"]
    assert excluded["is_excluded"] is True
    assert "created_by" not in excluded
    assert excluded["is_system"] is True
    assert "命中后匿名记录" in excluded["summary"]


def test_get_project_rules_empty_projects(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.project_api,
        "list_project_bindings",
        lambda: [],
    )

    result = build_test_bridge().get_project_rules()

    assert result == {
        "ok": True,
        "projects": [],
        "advanced": {
            "excluded_rules_enabled": False,
            "excluded_project": None,
            "excluded_rules": [],
        },
    }


def test_get_project_rules_malformed_rows_are_safe_and_json_serializable(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.project_api,
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

    result = build_test_bridge().get_project_rules()

    json.dumps(result, ensure_ascii=False)
    assert result["ok"] is True
    assert len(result["projects"]) == 2

    project = result["projects"][0]
    assert project["id"] == 0
    assert project["name"] == "未知项目"
    assert project["description"] == ""
    assert project["language"] == "中文"
    assert project["last_used_at"] is None
    assert project["enabled"] is True
    assert "created_by" not in project

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
        bridge_rules_module.project_api,
        "list_project_bindings",
        lambda: [{"id": 1, "name": "Client", "enabled": 1, "created_by": "user"}],
    )

    result = build_test_bridge().get_project_rules()
    project = result["projects"][0]
    assert project["description"] == ""
    assert project["language"] == "中文"
    assert project["last_used_at"] is None
    assert project["rules"] == []
    assert project["summary"] == "暂无规则"


def test_get_project_rules_bool_type_normalization(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.project_api,
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

    result = build_test_bridge().get_project_rules()
    projects = result["projects"]
    assert [project["enabled"] for project in projects] == [False, True, False, True, True]
    assert [project["rules"][0]["enabled"] for project in projects] == [False, True, False, True, True]
    assert [project["rules"][0]["recursive"] for project in projects] == [False, True, False, True, True]


def test_get_project_rules_missing_targets_use_safe_empty_fallback(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.project_api,
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
    result = build_test_bridge().get_project_rules()
    folder, keyword = result["projects"][0]["rules"]
    assert folder["target"] == ""
    assert keyword["target"] == ""
    assert "Traceback" not in repr(result)


def test_get_project_rules_sensitive_tokens_absent_from_success_payload(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.project_api,
        "list_project_bindings",
        lambda: [
            {
                "id": 1,
                "name": "Client",
                "description": "",
                "enabled": 1,
                "created_by": "user",
                "is_excluded": False,
                "is_system": False,
                "editable": True,
                "can_toggle": True,
                "can_archive": True,
                "window_title": "Sensitive Window",
                "clipboard": "Sensitive Clipboard",
                "note": "Sensitive Note",
                "folder_rules": [],
                "keyword_rules": [],
            }
        ],
    )
    result = build_test_bridge().get_project_rules()
    rendered = repr(result)
    for forbidden in (
        "traceback", "Traceback", "sqlite", "SELECT", "window_title", "clipboard", "note",
        "Sensitive Window", "Sensitive Clipboard", "Sensitive Note",
    ):
        assert forbidden not in rendered


def test_get_project_rules_exception_collapses_without_sensitive_text(monkeypatch):
    def fail():
        raise RuntimeError(
            "boom SELECT * FROM activity_log traceback window_title clipboard note"
        )

    monkeypatch.setattr(bridge_rules_module.project_api, "list_project_bindings", fail)
    result = build_test_bridge().get_project_rules()
    assert result == {
        "ok": False,
        "error": "加载项目规则失败",
        "projects": [],
        "advanced": {
            "excluded_rules_enabled": False,
            "excluded_project": None,
            "excluded_rules": [],
        },
    }
    lowered = repr(result).lower()
    for forbidden in (
        "traceback", "sqlite", "select", "boom", "window_title", "clipboard", "note", "activity_log",
    ):
        assert forbidden not in lowered


def test_set_project_rule_enabled_keyword_success(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.rule_api,
        "set_project_rule_enabled",
        lambda rule_type, rule_id, enabled: {
            "ok": True,
            "rule_type": rule_type,
            "rule_id": rule_id,
            "enabled": enabled,
        },
    )
    assert build_test_bridge().set_project_rule_enabled("keyword", 11, False) == {
        "ok": True, "rule_type": "keyword", "rule_id": 11, "enabled": False,
    }
    assert build_test_bridge().set_project_rule_enabled("keyword", 11, True) == {
        "ok": True, "rule_type": "keyword", "rule_id": 11, "enabled": True,
    }


def test_set_project_rule_enabled_folder_success(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.rule_api,
        "set_project_rule_enabled",
        lambda rule_type, rule_id, enabled: {
            "ok": True, "rule_type": rule_type, "rule_id": rule_id, "enabled": enabled,
        },
    )
    assert build_test_bridge().set_project_rule_enabled("folder", 10, False) == {
        "ok": True, "rule_type": "folder", "rule_id": 10, "enabled": False,
    }
    assert build_test_bridge().set_project_rule_enabled("folder", 10, True) == {
        "ok": True, "rule_type": "folder", "rule_id": 10, "enabled": True,
    }


def test_set_project_rule_enabled_rejects_invalid_bridge_input():
    bridge = build_test_bridge()
    assert bridge.set_project_rule_enabled("project", 1, True) == {"ok": False, "error": "操作无效"}
    for bad_id in (None, True, False, "1", 0, -1, 1.0):
        assert bridge.set_project_rule_enabled("keyword", bad_id, True) == {"ok": False, "error": "操作无效"}
    for bad_enabled in (None, 0, 1, "true", "false"):
        assert bridge.set_project_rule_enabled("keyword", 1, bad_enabled) == {"ok": False, "error": "操作无效"}


@pytest.mark.parametrize(
    "bad_rule_type",
    [None, "", "project", "folder_rule", "keyword_rule", "Folder", "KEYWORD", "PROJECT", "folders", "keywords", "unknown", 1, 1.0, True, [], {}],
)
def test_set_project_rule_enabled_rejects_invalid_rule_type_variants(bad_rule_type):
    assert build_test_bridge().set_project_rule_enabled(bad_rule_type, 1, True) == {"ok": False, "error": "操作无效"}


@pytest.mark.parametrize("bad_id", ["abc", "1.5", 2.5, 0.5, -999, [], {}])
def test_set_project_rule_enabled_rejects_invalid_id_extra_variants(bad_id):
    assert build_test_bridge().set_project_rule_enabled("folder", bad_id, True) == {"ok": False, "error": "操作无效"}


@pytest.mark.parametrize("bad_enabled", ["1", "0", "True", "False", 1.0, 0.0, [], {}])
def test_set_project_rule_enabled_rejects_invalid_enabled_extra_variants(bad_enabled):
    assert build_test_bridge().set_project_rule_enabled("keyword", 1, bad_enabled) == {"ok": False, "error": "操作无效"}


def test_set_project_rule_enabled_invalid_input_payload_excludes_sensitive_text():
    bridge = build_test_bridge()
    for args in (
        ("project", 1, True), (None, 1, True), ([], 1, True), ({}, 1, True),
        ("keyword", [], True), ("keyword", {}, True), ("keyword", 1, "true"),
        ("keyword", 1, []), ("keyword", 1, {}),
    ):
        result = bridge.set_project_rule_enabled(*args)
        assert result == {"ok": False, "error": "操作无效"}
        lowered = repr(result).lower()
        for forbidden in ("traceback", "sqlite", "select", "window_title", "clipboard", "note", "secret"):
            assert forbidden not in lowered


def test_set_project_rule_enabled_success_payload_does_not_return_full_project_list(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.rule_api,
        "set_project_rule_enabled",
        lambda rule_type, rule_id, enabled: {
            "ok": True, "rule_type": rule_type, "rule_id": rule_id, "enabled": enabled,
            "projects": [{"id": 1, "name": "should not leak"}],
        },
    )
    result = build_test_bridge().set_project_rule_enabled("folder", 10, False)
    assert result == {"ok": True, "rule_type": "folder", "rule_id": 10, "enabled": False}
    assert "projects" not in result
    assert "rules" not in result


def test_set_project_rule_enabled_never_calls_create_edit_delete_or_project_toggle_apis(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.rule_api,
        "set_project_rule_enabled",
        lambda rule_type, rule_id, enabled: {
            "ok": True, "rule_type": rule_type, "rule_id": rule_id, "enabled": enabled,
        },
    )
    forbidden_calls: list[str] = []

    def make_forbidden(name: str):
        def _fail(*args, **kwargs):
            forbidden_calls.append(name)
            raise AssertionError(name + " must not be called by toggle path")
        return _fail

    for name in (
        "create_keyword_rule", "create_or_update_folder_rule", "set_keyword_rule_enabled",
        "set_folder_rule_enabled", "delete_keyword_rule", "delete_folder_rule",
        "preview_folder_rule_conflicts",
    ):
        monkeypatch.setattr(bridge_rules_module.rule_api, name, make_forbidden(name), raising=False)
    monkeypatch.setattr(
        bridge_rules_module.rule_history_api, "backfill_project_rule", make_forbidden("backfill_project_rule")
    )
    forbidden_project_calls: list[str] = []

    def make_project_forbidden(name: str):
        def _fail(*args, **kwargs):
            forbidden_project_calls.append(name)
            raise AssertionError(name + " must not be called by toggle path")
        return _fail

    for name in ("create_project", "update_project", "delete_project", "archive_project", "set_project_enabled"):
        if hasattr(bridge_rules_module.project_api, name):
            monkeypatch.setattr(bridge_rules_module.project_api, name, make_project_forbidden(name))
    result = build_test_bridge().set_project_rule_enabled("folder", 10, False)
    assert result["ok"] is True
    assert forbidden_calls == []
    assert forbidden_project_calls == []


def test_set_project_rule_enabled_not_found_payload_excludes_sensitive_text(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.rule_api,
        "set_project_rule_enabled",
        lambda rule_type, rule_id, enabled: {
            "ok": False, "error": "not_found",
            "traceback": "SELECT * FROM folder_project_rule WHERE id=999",
            "details": "C:\\Secret window_title clipboard note",
        },
    )
    result = build_test_bridge().set_project_rule_enabled("folder", 999, False)
    assert result == {"ok": False, "error": "规则不存在"}
    lowered = repr(result).lower()
    for forbidden in ("traceback", "sqlite", "select", "window_title", "clipboard", "note", "secret", "details"):
        assert forbidden not in lowered


def test_set_project_rule_enabled_invalid_input_payload_excludes_backend_codes(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.rule_api,
        "set_project_rule_enabled",
        lambda rule_type, rule_id, enabled: {
            "ok": False, "error": "invalid_input", "code": "invalid_input",
            "internal_field": "should not leak",
        },
    )
    result = build_test_bridge().set_project_rule_enabled("folder", -1, True)
    assert result == {"ok": False, "error": "操作无效"}
    lowered = repr(result).lower()
    for forbidden in ("internal_field", "should not leak", "code", "invalid_input"):
        assert forbidden not in lowered


def test_set_project_rule_enabled_success_payload_types_are_stable(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.rule_api,
        "set_project_rule_enabled",
        lambda rule_type, rule_id, enabled: {
            "ok": True, "rule_type": rule_type, "rule_id": rule_id, "enabled": enabled,
        },
    )
    result = build_test_bridge().set_project_rule_enabled("keyword", 25, True)
    assert isinstance(result["rule_type"], str)
    assert isinstance(result["rule_id"], int)
    assert isinstance(result["enabled"], bool)
    assert type(result["rule_id"]) is int
    assert type(result["enabled"]) is bool


def test_set_project_rule_enabled_get_project_rules_payload_is_unchanged(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.project_api,
        "list_project_bindings",
        lambda: [{
            "id": 1, "name": "Client", "description": "Billable", "enabled": 1,
            "created_by": "user",
            "folder_rules": [{"id": 10, "folder_path": "D:\\Client", "enabled": 1, "recursive": 1}],
            "keyword_rules": [{"id": 11, "keyword": "Spec", "enabled": 0}],
        }],
    )
    result = build_test_bridge().get_project_rules()
    assert result["ok"] is True
    project = result["projects"][0]
    assert project["id"] == 1
    assert project["name"] == "Client"
    assert project["language"] == "中文"
    assert project["last_used_at"] is None
    json.dumps(result, ensure_ascii=False)


def test_set_project_rule_enabled_not_found(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.rule_api, "set_project_rule_enabled",
        lambda rule_type, rule_id, enabled: {"ok": False, "error": "not_found"},
    )
    assert build_test_bridge().set_project_rule_enabled("keyword", 999, False) == {
        "ok": False, "error": "规则不存在",
    }


def test_set_project_rule_enabled_unknown_api_exception_collapses(monkeypatch):
    def fail(rule_type, rule_id, enabled):
        raise RuntimeError(
            "boom SELECT * FROM activity_log traceback window_title clipboard note C:\\Secret"
        )
    monkeypatch.setattr(bridge_rules_module.rule_api, "set_project_rule_enabled", fail)
    result = build_test_bridge().set_project_rule_enabled("folder", 10, False)
    assert result == {"ok": False, "error": "更新规则状态失败"}
    lowered = repr(result).lower()
    for forbidden in (
        "traceback", "sqlite", "select", "boom", "window_title", "clipboard", "note",
        "activity_log", "secret",
    ):
        assert forbidden not in lowered


def test_set_project_rule_enabled_api_error_codes_are_stable(monkeypatch):
    messages = {
        "invalid_input": "操作无效",
        "operation_failed": "更新规则状态失败",
        "unexpected raw exception": "更新规则状态失败",
    }
    for code, message in messages.items():
        monkeypatch.setattr(
            bridge_rules_module.rule_api, "set_project_rule_enabled",
            lambda rule_type, rule_id, enabled, code=code: {"ok": False, "error": code},
        )
        result = build_test_bridge().set_project_rule_enabled("folder", 10, False)
        assert result == {"ok": False, "error": message}


def test_set_project_rule_enabled_payload_json_serializable(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.rule_api, "set_project_rule_enabled",
        lambda rule_type, rule_id, enabled: {
            "ok": True, "rule_type": rule_type, "rule_id": rule_id, "enabled": enabled,
        },
    )
    result = build_test_bridge().set_project_rule_enabled("keyword", 20, True)
    json.dumps(result, ensure_ascii=False)
    assert "Traceback" not in repr(result)
    assert "SELECT" not in repr(result)


def test_project_rules_bridge_import_boundary():
    bridge_dir = Path(bridge_module.__file__).parent
    bridge_sources = {"bridge.py": (bridge_dir / "bridge.py").read_text(encoding="utf-8")}
    bridge_rules_path = bridge_dir / "bridge_rules.py"
    if bridge_rules_path.is_file():
        bridge_sources["bridge_rules.py"] = bridge_rules_path.read_text(encoding="utf-8")
    forbidden_patterns = (
        r"^\s*from\s+\.\.services(\s|\.)", r"^\s*from\s+\.\.db(\s|\.)",
        r"^\s*from\s+\.\.collector(\s|\.)", r"^\s*from\s+\.\.security(\s|\.)",
        r"^\s*from\s+\.\.runtime(\s|\.)", r"^\s*from\s+\.\.config(\s|\.)",
        r"^\s*from\s+\.\.ui(\s|\.)", r"^\s*from\s+worktrace\.services(\s|\.)",
        r"^\s*from\s+worktrace\.db(\s|\.)", r"^\s*from\s+worktrace\.collector(\s|\.)",
        r"^\s*from\s+worktrace\.security(\s|\.)", r"^\s*from\s+worktrace\.runtime(\s|\.)",
        r"^\s*from\s+worktrace\.config(\s|\.)", r"^\s*from\s+worktrace\.ui(\s|\.)",
        r"^\s*import\s+worktrace\.services(\s|$)", r"^\s*import\s+worktrace\.db(\s|$)",
        r"^\s*import\s+worktrace\.collector(\s|$)", r"^\s*import\s+worktrace\.security(\s|$)",
        r"^\s*import\s+worktrace\.runtime(\s|$)", r"^\s*import\s+worktrace\.config(\s|$)",
        r"^\s*import\s+worktrace\.ui(\s|$)",
    )
    for fname, source in bridge_sources.items():
        for pattern in forbidden_patterns:
            assert not re.search(pattern, source, re.MULTILINE), (
                f"{fname} must not import forbidden backend/UI module: " + pattern
            )


def test_create_project_keyword_rule_success_payload(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.rule_api, "create_project_keyword_rule",
        lambda project_id, keyword: {
            "ok": True,
            "rule": {"kind": "keyword", "id": 123, "project_id": project_id, "keyword": keyword.strip(), "enabled": True},
        },
    )
    result = build_test_bridge().create_project_keyword_rule(1, "Spec")
    assert result == {
        "ok": True,
        "rule": {"kind": "keyword", "id": 123, "project_id": 1, "keyword": "Spec", "enabled": True},
    }
    assert "projects" not in result
    assert "rules" not in result


@pytest.mark.parametrize("bad_id", [None, True, False, "1", "abc", 0, -1, 1.0, 2.5, [], {}])
def test_create_project_keyword_rule_rejects_invalid_project_id(bad_id):
    result = build_test_bridge().create_project_keyword_rule(bad_id, "Spec")
    assert result == {"ok": False, "error": "操作无效"}


@pytest.mark.parametrize("bad_keyword", [None, True, False, 1, 1.0, 2.5, [], {}, ""])
def test_create_project_keyword_rule_rejects_invalid_keyword(bad_keyword):
    result = build_test_bridge().create_project_keyword_rule(1, bad_keyword)
    assert result == {"ok": False, "error": "操作无效"}


@pytest.mark.parametrize("bad_keyword", ["   ", "\t", "\n", "  \t  "])
def test_create_project_keyword_rule_rejects_whitespace_only_keyword(bad_keyword):
    result = build_test_bridge().create_project_keyword_rule(1, bad_keyword)
    assert result == {"ok": False, "error": "操作无效"}


def test_create_project_keyword_rule_invalid_input_payload_excludes_sensitive_text():
    bridge = build_test_bridge()
    for args in (
        (None, "Spec"), (True, "Spec"), (False, "Spec"), ("1", "Spec"), (1.0, "Spec"),
        ([], "Spec"), ({}, "Spec"), (0, "Spec"), (-1, "Spec"), (1, None), (1, True),
        (1, 1), (1, 1.0), (1, []), (1, {}), (1, ""), (1, "   "),
    ):
        result = bridge.create_project_keyword_rule(*args)
        assert result == {"ok": False, "error": "操作无效"}
        lowered = repr(result).lower()
        for forbidden in ("traceback", "sqlite", "select", "window_title", "clipboard", "note", "secret"):
            assert forbidden not in lowered


def test_create_project_keyword_rule_project_not_found_maps_to_chinese(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.rule_api, "create_project_keyword_rule",
        lambda project_id, keyword: {"ok": False, "error": "project_not_found"},
    )
    result = build_test_bridge().create_project_keyword_rule(9999, "Spec")
    assert result == {"ok": False, "error": "项目不存在"}


def test_create_project_keyword_rule_duplicate_rule_maps_to_chinese(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.rule_api, "create_project_keyword_rule",
        lambda project_id, keyword: {"ok": False, "error": "duplicate_rule"},
    )
    result = build_test_bridge().create_project_keyword_rule(1, "Spec")
    assert result == {"ok": False, "error": "关键词规则已存在"}


def test_create_project_keyword_rule_invalid_input_code_maps_to_chinese(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.rule_api, "create_project_keyword_rule",
        lambda project_id, keyword: {"ok": False, "error": "invalid_input"},
    )
    result = build_test_bridge().create_project_keyword_rule(1, "Spec")
    assert result == {"ok": False, "error": "操作无效"}


def test_create_project_keyword_rule_operation_failed_code_maps_to_chinese(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.rule_api, "create_project_keyword_rule",
        lambda project_id, keyword: {"ok": False, "error": "operation_failed"},
    )
    result = build_test_bridge().create_project_keyword_rule(1, "Spec")
    assert result == {"ok": False, "error": "新增关键词规则失败"}


def test_create_project_keyword_rule_unknown_error_code_collapses_to_create_failed(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.rule_api, "create_project_keyword_rule",
        lambda project_id, keyword: {"ok": False, "error": "unexpected raw code"},
    )
    result = build_test_bridge().create_project_keyword_rule(1, "Spec")
    assert result == {"ok": False, "error": "新增关键词规则失败"}


def test_create_project_keyword_rule_unknown_exception_collapses(monkeypatch):
    def fail(project_id, keyword):
        raise RuntimeError(
            "boom SELECT * FROM activity_log traceback window_title clipboard note C:\\Secret"
        )
    monkeypatch.setattr(bridge_rules_module.rule_api, "create_project_keyword_rule", fail)
    result = build_test_bridge().create_project_keyword_rule(1, "Spec")
    assert result == {"ok": False, "error": "新增关键词规则失败"}
    lowered = repr(result).lower()
    for forbidden in (
        "traceback", "sqlite", "select", "boom", "window_title", "clipboard", "note", "activity_log", "secret",
    ):
        assert forbidden not in lowered


def test_create_project_keyword_rule_failure_payload_excludes_backend_codes(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.rule_api, "create_project_keyword_rule",
        lambda project_id, keyword: {
            "ok": False, "error": "duplicate_rule", "code": "duplicate_rule",
            "internal_field": "should not leak", "traceback": "SELECT * FROM project_rule",
            "details": "C:\\Secret window_title clipboard note",
        },
    )
    result = build_test_bridge().create_project_keyword_rule(1, "Spec")
    assert result == {"ok": False, "error": "关键词规则已存在"}
    lowered = repr(result).lower()
    for forbidden in (
        "internal_field", "should not leak", "code", "duplicate_rule", "traceback", "sqlite",
        "select", "window_title", "clipboard", "note", "secret", "details",
    ):
        assert forbidden not in lowered


def test_create_project_keyword_rule_success_payload_types_are_stable(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.rule_api, "create_project_keyword_rule",
        lambda project_id, keyword: {
            "ok": True,
            "rule": {"kind": "keyword", "id": 25, "project_id": project_id, "keyword": keyword, "enabled": 1},
        },
    )
    result = build_test_bridge().create_project_keyword_rule(7, "Spec")
    assert type(result["ok"]) is bool
    rule = result["rule"]
    assert type(rule["kind"]) is str
    assert type(rule["id"]) is int
    assert type(rule["project_id"]) is int
    assert type(rule["keyword"]) is str
    assert type(rule["enabled"]) is bool


def test_create_project_keyword_rule_payload_json_serializable(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.rule_api, "create_project_keyword_rule",
        lambda project_id, keyword: {
            "ok": True,
            "rule": {"kind": "keyword", "id": 20, "project_id": project_id, "keyword": keyword.strip(), "enabled": True},
        },
    )
    result = build_test_bridge().create_project_keyword_rule(1, "Spec")
    json.dumps(result, ensure_ascii=False)
    assert "Traceback" not in repr(result)
    assert "SELECT" not in repr(result)


def test_create_project_keyword_rule_never_calls_other_project_rules_write_apis(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.rule_api, "create_project_keyword_rule",
        lambda project_id, keyword: {
            "ok": True,
            "rule": {"kind": "keyword", "id": 1, "project_id": project_id, "keyword": keyword.strip(), "enabled": True},
        },
    )
    forbidden_calls: list[str] = []

    def make_forbidden(name: str):
        def _fail(*args, **kwargs):
            forbidden_calls.append(name)
            raise AssertionError(name + " must not be called by create-keyword path")
        return _fail

    for name in (
        "set_project_rule_enabled", "create_or_update_folder_rule", "set_keyword_rule_enabled",
        "set_folder_rule_enabled", "delete_keyword_rule", "delete_folder_rule", "preview_folder_rule_conflicts",
    ):
        monkeypatch.setattr(bridge_rules_module.rule_api, name, make_forbidden(name), raising=False)
    monkeypatch.setattr(
        bridge_rules_module.rule_history_api, "backfill_project_rule", make_forbidden("backfill_project_rule")
    )
    forbidden_project_calls: list[str] = []

    def make_project_forbidden(name: str):
        def _fail(*args, **kwargs):
            forbidden_project_calls.append(name)
            raise AssertionError(name + " must not be called by create-keyword path")
        return _fail

    for name in ("create_project", "update_project", "delete_project", "archive_project", "set_project_enabled"):
        if hasattr(bridge_rules_module.project_api, name):
            monkeypatch.setattr(bridge_rules_module.project_api, name, make_project_forbidden(name))
    result = build_test_bridge().create_project_keyword_rule(1, "Spec")
    assert result["ok"] is True
    assert forbidden_calls == []
    assert forbidden_project_calls == []


def test_create_project_keyword_rule_does_not_regress_get_project_rules(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.project_api, "list_project_bindings",
        lambda: [{
            "id": 1, "name": "Client", "description": "Billable", "enabled": 1, "created_by": "user",
            "folder_rules": [{"id": 10, "folder_path": "D:\\Client", "enabled": 1, "recursive": 1}],
            "keyword_rules": [{"id": 11, "keyword": "Spec", "enabled": 0}],
        }],
    )
    result = build_test_bridge().get_project_rules()
    assert result["ok"] is True
    project = result["projects"][0]
    assert project["id"] == 1
    assert project["name"] == "Client"
    assert project["language"] == "中文"
    assert project["last_used_at"] is None
    json.dumps(result, ensure_ascii=False)


def test_create_project_keyword_rule_does_not_regress_set_project_rule_enabled(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.rule_api, "set_project_rule_enabled",
        lambda rule_type, rule_id, enabled: {
            "ok": True, "rule_type": rule_type, "rule_id": rule_id, "enabled": enabled,
        },
    )
    result = build_test_bridge().set_project_rule_enabled("keyword", 11, False)
    assert result == {"ok": True, "rule_type": "keyword", "rule_id": 11, "enabled": False}


def test_create_project_keyword_rule_bridge_passes_trimmed_keyword_to_api(monkeypatch):
    captured: dict[str, object] = {}

    def capture(project_id, keyword):
        captured["project_id"] = project_id
        captured["keyword"] = keyword
        return {
            "ok": True,
            "rule": {"kind": "keyword", "id": 42, "project_id": project_id, "keyword": keyword, "enabled": True},
        }

    monkeypatch.setattr(bridge_rules_module.rule_api, "create_project_keyword_rule", capture)
    result = build_test_bridge().create_project_keyword_rule(1, "  Spec  ")
    assert result["ok"] is True
    assert captured["keyword"] == "Spec"
    assert captured["project_id"] == 1


def test_create_project_keyword_rule_bridge_html_script_keyword_safe(monkeypatch):
    html_keyword = "<script>alert('xss')</script>"
    monkeypatch.setattr(
        bridge_rules_module.rule_api, "create_project_keyword_rule",
        lambda project_id, keyword: {
            "ok": True,
            "rule": {"kind": "keyword", "id": 99, "project_id": project_id, "keyword": keyword, "enabled": True},
        },
    )
    result = build_test_bridge().create_project_keyword_rule(1, html_keyword)
    assert result["ok"] is True
    assert result["rule"]["keyword"] == html_keyword
    json.dumps(result, ensure_ascii=False)


def test_create_project_keyword_rule_bridge_rejects_tuple_and_set_project_id():
    for bad_id in ((), (1,), {1, 2}, frozenset({1})):
        result = build_test_bridge().create_project_keyword_rule(bad_id, "Spec")
        assert result == {"ok": False, "error": "操作无效"}


def test_create_project_keyword_rule_bridge_rejects_tuple_and_set_keyword():
    for bad_keyword in ((), (1,), {1, 2}, frozenset({1})):
        result = build_test_bridge().create_project_keyword_rule(1, bad_keyword)
        assert result == {"ok": False, "error": "操作无效"}


def test_delete_project_keyword_rule_success_payload(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.rule_api, "delete_project_keyword_rule",
        lambda rule_id, apply_to_history: {"ok": True, "rule": {"kind": "keyword", "id": rule_id, "deleted": True}},
    )
    result = build_test_bridge().delete_project_keyword_rule(123, apply_to_history=False)
    assert result == {
        "ok": True,
        "rule": {
            "kind": "keyword",
            "id": 123,
            "deleted": True,
            "history_updated": False,
            "updated_count": 0,
        },
    }
    assert "projects" not in result
    assert "rules" not in result


@pytest.mark.parametrize(
    "bad_id",
    [None, True, False, "1", "abc", 0, -1, 1.0, 2.5, [], {}, (), {1, 2}, (1,), frozenset({1})],
)
def test_delete_project_keyword_rule_rejects_invalid_rule_id(bad_id):
    result = build_test_bridge().delete_project_keyword_rule(bad_id, apply_to_history=False)
    assert result == {"ok": False, "error": "操作无效"}


def test_delete_project_keyword_rule_invalid_input_payload_excludes_sensitive_text():
    bridge = build_test_bridge()
    for bad_id in (None, True, False, "1", 1.0, [], {}, 0, -1, (), {1, 2}, (1,), frozenset({1})):
        result = bridge.delete_project_keyword_rule(bad_id, apply_to_history=False)
        assert result == {"ok": False, "error": "操作无效"}
        lowered = repr(result).lower()
        for forbidden in ("traceback", "sqlite", "select", "window_title", "clipboard", "note", "secret"):
            assert forbidden not in lowered


def test_delete_project_keyword_rule_not_found_maps_to_chinese(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.rule_api, "delete_project_keyword_rule",
        lambda rule_id, apply_to_history: {"ok": False, "error": "not_found"},
    )
    result = build_test_bridge().delete_project_keyword_rule(999, apply_to_history=False)
    assert result == {"ok": False, "error": "关键词规则不存在"}


def test_delete_project_keyword_rule_invalid_input_code_maps_to_chinese(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.rule_api, "delete_project_keyword_rule",
        lambda rule_id, apply_to_history: {"ok": False, "error": "invalid_input"},
    )
    result = build_test_bridge().delete_project_keyword_rule(1, apply_to_history=False)
    assert result == {"ok": False, "error": "操作无效"}


def test_delete_project_keyword_rule_operation_failed_code_maps_to_chinese(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.rule_api, "delete_project_keyword_rule",
        lambda rule_id, apply_to_history: {"ok": False, "error": "operation_failed"},
    )
    result = build_test_bridge().delete_project_keyword_rule(1, apply_to_history=False)
    assert result == {"ok": False, "error": "删除关键词规则失败"}


def test_delete_project_keyword_rule_unknown_error_code_collapses_to_delete_failed(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.rule_api, "delete_project_keyword_rule",
        lambda rule_id, apply_to_history: {"ok": False, "error": "unexpected raw code"},
    )
    result = build_test_bridge().delete_project_keyword_rule(1, apply_to_history=False)
    assert result == {"ok": False, "error": "删除关键词规则失败"}


def test_delete_project_keyword_rule_unknown_exception_collapses(monkeypatch):
    def fail(rule_id, apply_to_history):
        assert type(apply_to_history) is bool
        raise RuntimeError(
            "boom SELECT * FROM activity_log traceback window_title clipboard note C:\\Secret"
        )
    monkeypatch.setattr(bridge_rules_module.rule_api, "delete_project_keyword_rule", fail)
    result = build_test_bridge().delete_project_keyword_rule(1, apply_to_history=False)
    assert result == {"ok": False, "error": "删除关键词规则失败"}
    lowered = repr(result).lower()
    for forbidden in (
        "traceback", "sqlite", "select", "boom", "window_title", "clipboard", "note", "activity_log", "secret",
    ):
        assert forbidden not in lowered


def test_delete_project_keyword_rule_failure_payload_excludes_backend_codes(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.rule_api, "delete_project_keyword_rule",
        lambda rule_id, apply_to_history: {
            "ok": False, "error": "not_found", "code": "not_found",
            "internal_field": "should not leak", "traceback": "SELECT * FROM project_rule",
            "details": "C:\\Secret window_title clipboard note",
        },
    )
    result = build_test_bridge().delete_project_keyword_rule(999, apply_to_history=False)
    assert result == {"ok": False, "error": "关键词规则不存在"}
    lowered = repr(result).lower()
    for forbidden in (
        "internal_field", "should not leak", "code", "not_found", "traceback", "sqlite",
        "select", "window_title", "clipboard", "note", "secret", "details",
    ):
        assert forbidden not in lowered


def test_delete_project_keyword_rule_success_payload_types_are_stable(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.rule_api, "delete_project_keyword_rule",
        lambda rule_id, apply_to_history: {"ok": True, "rule": {"kind": "keyword", "id": rule_id, "deleted": 1}},
    )
    result = build_test_bridge().delete_project_keyword_rule(25, apply_to_history=False)
    assert type(result["ok"]) is bool
    rule = result["rule"]
    assert type(rule["kind"]) is str
    assert type(rule["id"]) is int
    assert type(rule["deleted"]) is bool


def test_delete_project_keyword_rule_payload_json_serializable(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.rule_api, "delete_project_keyword_rule",
        lambda rule_id, apply_to_history: {"ok": True, "rule": {"kind": "keyword", "id": rule_id, "deleted": True}},
    )
    result = build_test_bridge().delete_project_keyword_rule(20, apply_to_history=False)
    json.dumps(result, ensure_ascii=False)
    assert "Traceback" not in repr(result)
    assert "SELECT" not in repr(result)


def test_delete_project_keyword_rule_never_calls_other_project_rules_write_apis(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.rule_api, "delete_project_keyword_rule",
        lambda rule_id, apply_to_history: {"ok": True, "rule": {"kind": "keyword", "id": rule_id, "deleted": True}},
    )
    forbidden_calls: list[str] = []

    def make_forbidden(name: str):
        def _fail(*args, **kwargs):
            forbidden_calls.append(name)
            raise AssertionError(name + " must not be called by delete-keyword path")
        return _fail

    for name in (
        "create_project_keyword_rule", "set_project_rule_enabled", "create_or_update_folder_rule",
        "set_keyword_rule_enabled", "set_folder_rule_enabled", "delete_keyword_rule",
        "delete_folder_rule", "preview_folder_rule_conflicts",
    ):
        monkeypatch.setattr(bridge_rules_module.rule_api, name, make_forbidden(name), raising=False)
    monkeypatch.setattr(
        bridge_rules_module.rule_history_api, "backfill_project_rule", make_forbidden("backfill_project_rule")
    )
    forbidden_project_calls: list[str] = []

    def make_project_forbidden(name: str):
        def _fail(*args, **kwargs):
            forbidden_project_calls.append(name)
            raise AssertionError(name + " must not be called by delete-keyword path")
        return _fail

    for name in ("create_project", "update_project", "delete_project", "archive_project", "set_project_enabled"):
        if hasattr(bridge_rules_module.project_api, name):
            monkeypatch.setattr(bridge_rules_module.project_api, name, make_project_forbidden(name))
    result = build_test_bridge().delete_project_keyword_rule(1, apply_to_history=False)
    assert result["ok"] is True
    assert forbidden_calls == []
    assert forbidden_project_calls == []


def test_delete_project_keyword_rule_does_not_regress_get_project_rules(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.project_api, "list_project_bindings",
        lambda: [{
            "id": 1, "name": "Client", "description": "Billable", "enabled": 1, "created_by": "user",
            "folder_rules": [{"id": 10, "folder_path": "D:\\Client", "enabled": 1, "recursive": 1}],
            "keyword_rules": [{"id": 11, "keyword": "Spec", "enabled": 0}],
        }],
    )
    result = build_test_bridge().get_project_rules()
    assert result["ok"] is True
    project = result["projects"][0]
    assert project["id"] == 1
    assert project["name"] == "Client"
    assert project["language"] == "中文"
    assert project["last_used_at"] is None
    json.dumps(result, ensure_ascii=False)


def test_delete_project_keyword_rule_does_not_regress_set_project_rule_enabled(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.rule_api, "set_project_rule_enabled",
        lambda rule_type, rule_id, enabled: {
            "ok": True, "rule_type": rule_type, "rule_id": rule_id, "enabled": enabled,
        },
    )
    result = build_test_bridge().set_project_rule_enabled("keyword", 11, False)
    assert result == {"ok": True, "rule_type": "keyword", "rule_id": 11, "enabled": False}


def test_delete_project_keyword_rule_does_not_regress_create_project_keyword_rule(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.rule_api, "create_project_keyword_rule",
        lambda project_id, keyword: {
            "ok": True,
            "rule": {"kind": "keyword", "id": 42, "project_id": project_id, "keyword": keyword.strip(), "enabled": True},
        },
    )
    result = build_test_bridge().create_project_keyword_rule(1, "Spec")
    assert result["ok"] is True
    assert result["rule"]["id"] == 42
    assert result["rule"]["keyword"] == "Spec"


def test_delete_project_keyword_rule_success_payload_strips_extra_api_keys(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.rule_api, "delete_project_keyword_rule",
        lambda rule_id, apply_to_history: {
            "ok": True,
            "rule": {
                "kind": "keyword", "id": rule_id, "deleted": True, "project_id": 999,
                "keyword": "should not leak", "enabled": True, "folder_path": r"D:\Secret",
                "internal_field": "should not leak", "traceback": "SELECT * FROM project_rule",
                "details": "C:\\Secret window_title clipboard note",
            },
        },
    )
    result = build_test_bridge().delete_project_keyword_rule(7, apply_to_history=False)
    assert result == {
        "ok": True,
        "rule": {
            "kind": "keyword",
            "id": 7,
            "deleted": True,
            "history_updated": False,
            "updated_count": 0,
        },
    }
    rule = result["rule"]
    assert set(rule.keys()) == {"kind", "id", "deleted", "history_updated", "updated_count"}
    lowered = repr(result).lower()
    for forbidden in (
        "should not leak", "project_id", "folder_path", "internal_field", "traceback", "sqlite",
        "select", "window_title", "clipboard", "note", "secret", "details",
    ):
        assert forbidden not in lowered


def test_delete_project_keyword_rule_folder_rule_id_maps_to_stable_not_found(monkeypatch):
    captured: dict[str, object] = {}

    def fake_delete(rule_id, apply_to_history):
        captured["rule_id"] = rule_id
        captured["apply_to_history"] = apply_to_history
        return {
            "ok": False, "error": "not_found", "table": "folder_project_rule",
            "details": "C:\\Secret folder path window_title clipboard note",
        }

    monkeypatch.setattr(bridge_rules_module.rule_api, "delete_project_keyword_rule", fake_delete)
    result = build_test_bridge().delete_project_keyword_rule(55, apply_to_history=False)
    assert captured["rule_id"] == 55
    assert captured["apply_to_history"] is False
    assert result == {"ok": False, "error": "关键词规则不存在"}
    lowered = repr(result).lower()
    for forbidden in (
        "folder_project_rule", "table", "details", "traceback", "sqlite", "select",
        "window_title", "clipboard", "note", "secret",
    ):
        assert forbidden not in lowered


def test_delete_project_keyword_rule_bridge_input_validation_payloads_json_serializable():
    bridge = build_test_bridge()
    for bad_id in (None, True, False, "1", "abc", 1.0, 2.5, 0, -1, [], {}, (), {1, 2}, (1,), frozenset({1})):
        result = bridge.delete_project_keyword_rule(bad_id, apply_to_history=False)
        assert result == {"ok": False, "error": "操作无效"}
        json.dumps(result, ensure_ascii=False)
        lowered = repr(result).lower()
        for forbidden in ("traceback", "sqlite", "select", "window_title", "clipboard", "note", "secret"):
            assert forbidden not in lowered


def test_create_project_folder_rule_success_payload(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.rule_api, "create_project_folder_rule",
        lambda project_id, folder_path, recursive: {
            "ok": True,
            "rule": {
                "kind": "folder", "id": 456, "project_id": project_id,
                "folder_path": folder_path, "recursive": recursive, "enabled": True,
            },
        },
    )
    result = build_test_bridge().create_project_folder_rule(1, r"D:\Work", True)
    assert result == {
        "ok": True,
        "rule": {
            "kind": "folder", "id": 456, "project_id": 1,
            "folder_path": r"D:\Work", "recursive": True, "enabled": True,
        },
    }
    assert "projects" not in result
    assert "rules" not in result


@pytest.mark.parametrize("bad_id", [None, True, False, "1", "abc", 0, -1, 1.0, 2.5, [], {}, (), {1, 2}, (1,), frozenset({1})])
def test_create_project_folder_rule_rejects_invalid_project_id(bad_id):
    result = build_test_bridge().create_project_folder_rule(bad_id, r"D:\Work", True)
    assert result == {"ok": False, "error": "操作无效"}


@pytest.mark.parametrize("bad_path", [None, True, False, 1, 1.0, 2.5, [], {}, (), (1,), frozenset({1}), "", "   ", "\t", "\n", "  \t  "])
def test_create_project_folder_rule_rejects_invalid_folder_path(bad_path):
    result = build_test_bridge().create_project_folder_rule(1, bad_path, True)
    assert result == {"ok": False, "error": "操作无效"}


@pytest.mark.parametrize("bad_recursive", [None, "true", 1, 0, 1.0, 2.5, [], {}, (), (1,), frozenset({1})])
def test_create_project_folder_rule_rejects_non_bool_recursive(bad_recursive):
    result = build_test_bridge().create_project_folder_rule(1, r"D:\Work", bad_recursive)
    assert result == {"ok": False, "error": "操作无效"}


def test_create_project_folder_rule_invalid_input_payload_excludes_sensitive_text():
    bridge = build_test_bridge()
    for args in (
        (None, r"D:\Work", True), (True, r"D:\Work", True), (False, r"D:\Work", True),
        ("1", r"D:\Work", True), (1.0, r"D:\Work", True), ([], r"D:\Work", True),
        ({}, r"D:\Work", True), (0, r"D:\Work", True), (-1, r"D:\Work", True),
        (1, None, True), (1, True, True), (1, 1, True), (1, 1.0, True), (1, [], True),
        (1, {}, True), (1, "", True), (1, "   ", True), (1, r"D:\Work", None),
        (1, r"D:\Work", "true"), (1, r"D:\Work", 1), (1, r"D:\Work", []),
        (1, r"D:\Work", {}),
    ):
        result = bridge.create_project_folder_rule(*args)
        assert result == {"ok": False, "error": "操作无效"}
        lowered = repr(result).lower()
        for forbidden in ("traceback", "sqlite", "select", "window_title", "clipboard", "note", "secret"):
            assert forbidden not in lowered


def test_create_project_folder_rule_project_not_found_maps_to_chinese(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.rule_api, "create_project_folder_rule",
        lambda project_id, folder_path, recursive: {"ok": False, "error": "project_not_found"},
    )
    result = build_test_bridge().create_project_folder_rule(9999, r"D:\Work", True)
    assert result == {"ok": False, "error": "项目不存在或不可用"}


def test_create_project_folder_rule_operation_failed_maps_to_chinese(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.rule_api, "create_project_folder_rule",
        lambda project_id, folder_path, recursive: {"ok": False, "error": "operation_failed"},
    )
    result = build_test_bridge().create_project_folder_rule(1, r"D:\Work", True)
    assert result == {"ok": False, "error": "新增文件夹规则失败"}


def test_create_project_folder_rule_unknown_error_code_collapses(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.rule_api, "create_project_folder_rule",
        lambda project_id, folder_path, recursive: {"ok": False, "error": "unknown_code"},
    )
    result = build_test_bridge().create_project_folder_rule(1, r"D:\Work", True)
    assert result == {"ok": False, "error": "新增文件夹规则失败"}


def test_create_project_folder_rule_unknown_exception_collapses(monkeypatch):
    def _boom(*args, **kwargs):
        raise RuntimeError("boom: sensitive SQL SELECT * FROM ...")
    monkeypatch.setattr(bridge_rules_module.rule_api, "create_project_folder_rule", _boom)
    result = build_test_bridge().create_project_folder_rule(1, r"D:\Work", True)
    assert result == {"ok": False, "error": "新增文件夹规则失败"}
    lowered = repr(result).lower()
    for forbidden in ("boom", "select", "sensitive", "traceback", "runtimeerror", "window_title", "clipboard", "note"):
        assert forbidden not in lowered


def test_create_project_folder_rule_failure_payload_excludes_backend_codes(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.rule_api, "create_project_folder_rule",
        lambda project_id, folder_path, recursive: {
            "ok": False, "error": "operation_failed", "sql": "SELECT * FROM folder_project_rule",
            "traceback": "RuntimeError: ...", "details": "C:\\Secret window_title clipboard note",
        },
    )
    result = build_test_bridge().create_project_folder_rule(1, r"D:\Work", True)
    assert result == {"ok": False, "error": "新增文件夹规则失败"}
    lowered = repr(result).lower()
    for forbidden in (
        "operation_failed", "sql", "select", "traceback", "details", "window_title", "clipboard", "note", "secret",
    ):
        assert forbidden not in lowered


def test_create_project_folder_rule_success_payload_types_are_stable(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.rule_api, "create_project_folder_rule",
        lambda project_id, folder_path, recursive: {
            "ok": True,
            "rule": {
                "kind": "folder", "id": 789, "project_id": project_id,
                "folder_path": folder_path, "recursive": recursive, "enabled": True,
            },
        },
    )
    result = build_test_bridge().create_project_folder_rule(1, r"D:\Work", True)
    assert isinstance(result["ok"], bool)
    rule = result["rule"]
    assert isinstance(rule["kind"], str)
    assert isinstance(rule["id"], int)
    assert isinstance(rule["project_id"], int)
    assert isinstance(rule["folder_path"], str)
    assert isinstance(rule["recursive"], bool)
    assert isinstance(rule["enabled"], bool)


def test_create_project_folder_rule_payload_json_serializable(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.rule_api, "create_project_folder_rule",
        lambda project_id, folder_path, recursive: {
            "ok": True,
            "rule": {
                "kind": "folder", "id": 1, "project_id": project_id,
                "folder_path": folder_path, "recursive": recursive, "enabled": True,
            },
        },
    )
    result = build_test_bridge().create_project_folder_rule(1, r"D:\Work\Client\路径", True)
    json.dumps(result, ensure_ascii=False)


def test_create_project_folder_rule_bridge_passes_trimmed_path_to_api(monkeypatch):
    captured: dict[str, object] = {}

    def fake_create(project_id, folder_path, recursive):
        captured["project_id"] = project_id
        captured["folder_path"] = folder_path
        captured["recursive"] = recursive
        return {
            "ok": True,
            "rule": {
                "kind": "folder", "id": 1, "project_id": project_id,
                "folder_path": folder_path, "recursive": recursive, "enabled": True,
            },
        }

    monkeypatch.setattr(bridge_rules_module.rule_api, "create_project_folder_rule", fake_create)
    build_test_bridge().create_project_folder_rule(1, "  D:\\Work  ", True)
    assert captured["folder_path"] == r"D:\Work"


def test_create_project_folder_rule_success_payload_strips_extra_api_keys(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.rule_api, "create_project_folder_rule",
        lambda project_id, folder_path, recursive: {
            "ok": True,
            "rule": {
                "kind": "folder", "id": 1, "project_id": project_id,
                "folder_path": folder_path, "recursive": recursive, "enabled": True,
                "normalized_folder_key": "d:\\work", "created_at": "2026-06-28T10:00:00",
                "updated_at": "2026-06-28T10:00:00",
                "internal_note": "C:\\Secret window_title clipboard note",
            },
        },
    )
    result = build_test_bridge().create_project_folder_rule(1, r"D:\Work", True)
    rule = result["rule"]
    assert set(rule.keys()) == {"kind", "id", "project_id", "folder_path", "recursive", "enabled"}
    lowered = repr(result).lower()
    for forbidden in (
        "normalized_folder_key", "created_at", "updated_at", "internal_note",
        "secret", "window_title", "clipboard", "note",
    ):
        assert forbidden not in lowered


def test_create_project_folder_rule_never_calls_other_project_rules_write_apis(monkeypatch):
    called: dict[str, int] = {}

    def _track(name):
        def _impl(*args, **kwargs):
            called[name] = called.get(name, 0) + 1
            return {"ok": True, "rule": {"kind": "folder", "id": 1, "deleted": True}}
        return _impl

    monkeypatch.setattr(bridge_rules_module.rule_api, "create_project_folder_rule", _track("create_folder"))
    monkeypatch.setattr(bridge_rules_module.rule_api, "set_project_rule_enabled", _track("toggle"))
    monkeypatch.setattr(bridge_rules_module.rule_api, "create_project_keyword_rule", _track("create_keyword"))
    monkeypatch.setattr(bridge_rules_module.rule_api, "delete_project_keyword_rule", _track("delete_keyword"))
    monkeypatch.setattr(bridge_rules_module.rule_api, "update_project_folder_rule", _track("update_folder"))
    monkeypatch.setattr(bridge_rules_module.rule_api, "delete_project_folder_rule", _track("delete_folder"))
    build_test_bridge().create_project_folder_rule(1, r"D:\Work", True)
    assert called == {"create_folder": 1}


def test_create_project_folder_rule_does_not_regress_get_project_rules(monkeypatch):
    called = {"get_project_rules": 0}

    def _track(*args, **kwargs):
        called["get_project_rules"] += 1
        return []

    monkeypatch.setattr(bridge_rules_module.project_api, "list_project_bindings", _track)
    monkeypatch.setattr(
        bridge_rules_module.rule_api, "create_project_folder_rule",
        lambda project_id, folder_path, recursive: {
            "ok": True,
            "rule": {"kind": "folder", "id": 1, "project_id": project_id, "folder_path": folder_path, "recursive": recursive, "enabled": True},
        },
    )
    bridge = build_test_bridge()
    bridge.create_project_folder_rule(1, r"D:\Work", True)
    result = bridge.get_project_rules()
    assert called["get_project_rules"] == 1
    assert result["ok"] is True


def test_create_project_folder_rule_does_not_regress_set_project_rule_enabled(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.rule_api, "create_project_folder_rule",
        lambda project_id, folder_path, recursive: {
            "ok": True,
            "rule": {"kind": "folder", "id": 1, "project_id": project_id, "folder_path": folder_path, "recursive": recursive, "enabled": True},
        },
    )
    monkeypatch.setattr(
        bridge_rules_module.rule_api, "set_project_rule_enabled",
        lambda rule_type, rule_id, enabled: {"ok": True, "rule": {"kind": rule_type, "id": rule_id, "enabled": enabled}},
    )
    bridge = build_test_bridge()
    create_result = bridge.create_project_folder_rule(1, r"D:\Work", True)
    toggle_result = bridge.set_project_rule_enabled("folder", create_result["rule"]["id"], False)
    assert create_result["ok"] is True
    assert toggle_result["ok"] is True


def test_create_project_folder_rule_does_not_regress_create_project_keyword_rule(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.rule_api, "create_project_folder_rule",
        lambda project_id, folder_path, recursive: {
            "ok": True,
            "rule": {"kind": "folder", "id": 1, "project_id": project_id, "folder_path": folder_path, "recursive": recursive, "enabled": True},
        },
    )
    monkeypatch.setattr(
        bridge_rules_module.rule_api, "create_project_keyword_rule",
        lambda project_id, keyword: {
            "ok": True,
            "rule": {"kind": "keyword", "id": 2, "project_id": project_id, "keyword": keyword.strip(), "enabled": True},
        },
    )
    bridge = build_test_bridge()
    folder_result = bridge.create_project_folder_rule(1, r"D:\Work", True)
    keyword_result = bridge.create_project_keyword_rule(1, "Spec")
    assert folder_result["ok"] is True
    assert keyword_result["ok"] is True


def test_create_project_folder_rule_does_not_regress_delete_project_keyword_rule(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.rule_api, "create_project_folder_rule",
        lambda project_id, folder_path, recursive: {
            "ok": True,
            "rule": {"kind": "folder", "id": 1, "project_id": project_id, "folder_path": folder_path, "recursive": recursive, "enabled": True},
        },
    )
    monkeypatch.setattr(
        bridge_rules_module.rule_api, "delete_project_keyword_rule",
        lambda rule_id, apply_to_history: {"ok": True, "rule": {"kind": "keyword", "id": rule_id, "deleted": True}},
    )
    bridge = build_test_bridge()
    folder_result = bridge.create_project_folder_rule(1, r"D:\Work", True)
    delete_result = bridge.delete_project_keyword_rule(99, apply_to_history=False)
    assert folder_result["ok"] is True
    assert delete_result["ok"] is True


def test_update_project_folder_rule_success_payload(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.rule_api, "update_project_folder_rule",
        lambda rule_id, folder_path, recursive: {
            "ok": True,
            "rule": {
                "kind": "folder", "id": rule_id, "project_id": 1,
                "folder_path": folder_path, "recursive": recursive, "enabled": True,
            },
        },
    )
    result = build_test_bridge().update_project_folder_rule(10, r"D:\New", False)
    assert result == {
        "ok": True,
        "rule": {"kind": "folder", "id": 10, "project_id": 1, "folder_path": r"D:\New", "recursive": False, "enabled": True},
    }
    assert "projects" not in result


@pytest.mark.parametrize("bad_id", [None, True, False, "1", "abc", 0, -1, 1.0, 2.5, [], {}, (), {1, 2}, (1,), frozenset({1})])
def test_update_project_folder_rule_rejects_invalid_rule_id(bad_id):
    result = build_test_bridge().update_project_folder_rule(bad_id, r"D:\New", True)
    assert result == {"ok": False, "error": "操作无效"}


@pytest.mark.parametrize("bad_path", [None, True, False, 1, 1.0, 2.5, [], {}, (), (1,), frozenset({1}), "", "   ", "\t", "\n", "  \t  "])
def test_update_project_folder_rule_rejects_invalid_folder_path(bad_path):
    result = build_test_bridge().update_project_folder_rule(1, bad_path, True)
    assert result == {"ok": False, "error": "操作无效"}


@pytest.mark.parametrize("bad_recursive", [None, "true", 1, 0, 1.0, 2.5, [], {}, (), (1,), frozenset({1})])
def test_update_project_folder_rule_rejects_non_bool_recursive(bad_recursive):
    result = build_test_bridge().update_project_folder_rule(1, r"D:\New", bad_recursive)
    assert result == {"ok": False, "error": "操作无效"}


def test_update_project_folder_rule_not_found_maps_to_chinese(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.rule_api, "update_project_folder_rule",
        lambda rule_id, folder_path, recursive: {"ok": False, "error": "not_found"},
    )
    result = build_test_bridge().update_project_folder_rule(9999, r"D:\New", True)
    assert result == {"ok": False, "error": "文件夹规则不存在"}


def test_update_project_folder_rule_operation_failed_maps_to_chinese(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.rule_api, "update_project_folder_rule",
        lambda rule_id, folder_path, recursive: {"ok": False, "error": "operation_failed"},
    )
    result = build_test_bridge().update_project_folder_rule(1, r"D:\New", True)
    assert result == {"ok": False, "error": "保存文件夹规则失败"}


def test_update_project_folder_rule_unknown_error_code_collapses(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.rule_api, "update_project_folder_rule",
        lambda rule_id, folder_path, recursive: {"ok": False, "error": "unknown_code"},
    )
    result = build_test_bridge().update_project_folder_rule(1, r"D:\New", True)
    assert result == {"ok": False, "error": "保存文件夹规则失败"}


def test_update_project_folder_rule_unknown_exception_collapses(monkeypatch):
    def _boom(*args, **kwargs):
        raise RuntimeError("boom: sensitive SQL UPDATE ...")
    monkeypatch.setattr(bridge_rules_module.rule_api, "update_project_folder_rule", _boom)
    result = build_test_bridge().update_project_folder_rule(1, r"D:\New", True)
    assert result == {"ok": False, "error": "保存文件夹规则失败"}
    lowered = repr(result).lower()
    for forbidden in ("boom", "update", "sensitive", "traceback", "runtimeerror", "window_title", "clipboard", "note"):
        assert forbidden not in lowered


def test_update_project_folder_rule_failure_payload_excludes_backend_codes(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.rule_api, "update_project_folder_rule",
        lambda rule_id, folder_path, recursive: {
            "ok": False, "error": "operation_failed", "sql": "UPDATE folder_project_rule SET ...",
            "traceback": "RuntimeError: ...", "details": "C:\\Secret window_title clipboard note",
        },
    )
    result = build_test_bridge().update_project_folder_rule(1, r"D:\New", True)
    assert result == {"ok": False, "error": "保存文件夹规则失败"}
    lowered = repr(result).lower()
    for forbidden in (
        "operation_failed", "sql", "update", "traceback", "details", "window_title", "clipboard", "note", "secret",
    ):
        assert forbidden not in lowered


def test_update_project_folder_rule_success_payload_types_are_stable(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.rule_api, "update_project_folder_rule",
        lambda rule_id, folder_path, recursive: {
            "ok": True,
            "rule": {
                "kind": "folder", "id": rule_id, "project_id": 1,
                "folder_path": folder_path, "recursive": recursive, "enabled": True,
            },
        },
    )
    result = build_test_bridge().update_project_folder_rule(1, r"D:\New", True)
    assert isinstance(result["ok"], bool)
    rule = result["rule"]
    assert isinstance(rule["kind"], str)
    assert isinstance(rule["id"], int)
    assert isinstance(rule["project_id"], int)
    assert isinstance(rule["folder_path"], str)
    assert isinstance(rule["recursive"], bool)
    assert isinstance(rule["enabled"], bool)


def test_update_project_folder_rule_payload_json_serializable(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.rule_api, "update_project_folder_rule",
        lambda rule_id, folder_path, recursive: {
            "ok": True,
            "rule": {
                "kind": "folder", "id": rule_id, "project_id": 1,
                "folder_path": folder_path, "recursive": recursive, "enabled": True,
            },
        },
    )
    result = build_test_bridge().update_project_folder_rule(1, r"D:\Work\路径", True)
    json.dumps(result, ensure_ascii=False)


def test_update_project_folder_rule_bridge_passes_trimmed_path_to_api(monkeypatch):
    captured: dict[str, object] = {}

    def fake_update(rule_id, folder_path, recursive):
        captured["folder_path"] = folder_path
        captured["rule_id"] = rule_id
        captured["recursive"] = recursive
        return {
            "ok": True,
            "rule": {
                "kind": "folder", "id": rule_id, "project_id": 1,
                "folder_path": folder_path, "recursive": recursive, "enabled": True,
            },
        }

    monkeypatch.setattr(bridge_rules_module.rule_api, "update_project_folder_rule", fake_update)
    build_test_bridge().update_project_folder_rule(10, "  D:\\New  ", True)
    assert captured["folder_path"] == r"D:\New"
    assert captured["rule_id"] == 10


def test_update_project_folder_rule_success_payload_strips_extra_api_keys(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.rule_api, "update_project_folder_rule",
        lambda rule_id, folder_path, recursive: {
            "ok": True,
            "rule": {
                "kind": "folder", "id": rule_id, "project_id": 1, "folder_path": folder_path,
                "recursive": recursive, "enabled": True, "normalized_folder_key": "d:\\new",
                "created_at": "2026-06-28T10:00:00", "updated_at": "2026-06-28T10:00:00",
                "internal_note": "C:\\Secret window_title clipboard note",
            },
        },
    )
    result = build_test_bridge().update_project_folder_rule(1, r"D:\New", True)
    rule = result["rule"]
    assert set(rule.keys()) == {"kind", "id", "project_id", "folder_path", "recursive", "enabled"}
    lowered = repr(result).lower()
    for forbidden in (
        "normalized_folder_key", "created_at", "updated_at", "internal_note",
        "secret", "window_title", "clipboard", "note",
    ):
        assert forbidden not in lowered


def test_update_project_folder_rule_never_calls_other_project_rules_write_apis(monkeypatch):
    called: dict[str, int] = {}

    def _track(name):
        def _impl(*args, **kwargs):
            called[name] = called.get(name, 0) + 1
            return {"ok": True, "rule": {"kind": "folder", "id": 1, "deleted": True}}
        return _impl

    monkeypatch.setattr(bridge_rules_module.rule_api, "update_project_folder_rule", _track("update_folder"))
    monkeypatch.setattr(bridge_rules_module.rule_api, "set_project_rule_enabled", _track("toggle"))
    monkeypatch.setattr(bridge_rules_module.rule_api, "create_project_keyword_rule", _track("create_keyword"))
    monkeypatch.setattr(bridge_rules_module.rule_api, "delete_project_keyword_rule", _track("delete_keyword"))
    monkeypatch.setattr(bridge_rules_module.rule_api, "create_project_folder_rule", _track("create_folder"))
    monkeypatch.setattr(bridge_rules_module.rule_api, "delete_project_folder_rule", _track("delete_folder"))
    build_test_bridge().update_project_folder_rule(1, r"D:\New", True)
    assert called == {"update_folder": 1}


def test_delete_project_folder_rule_success_payload(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.rule_api, "delete_project_folder_rule",
        lambda rule_id, apply_to_history: {"ok": True, "rule": {"kind": "folder", "id": rule_id, "deleted": True}},
    )
    result = build_test_bridge().delete_project_folder_rule(10, apply_to_history=False)
    assert result == {
        "ok": True,
        "rule": {
            "kind": "folder",
            "id": 10,
            "deleted": True,
            "history_updated": False,
            "updated_count": 0,
        },
    }
    assert "projects" not in result


@pytest.mark.parametrize("bad_id", [None, True, False, "1", "abc", 0, -1, 1.0, 2.5, [], {}, (), {1, 2}, (1,), frozenset({1})])
def test_delete_project_folder_rule_rejects_invalid_rule_id(bad_id):
    result = build_test_bridge().delete_project_folder_rule(bad_id, apply_to_history=False)
    assert result == {"ok": False, "error": "操作无效"}


def test_delete_project_folder_rule_invalid_input_payload_excludes_sensitive_text():
    bridge = build_test_bridge()
    for bad_id in (None, True, False, "1", "abc", 1.0, 2.5, 0, -1, [], {}, (), {1, 2}, (1,), frozenset({1})):
        result = bridge.delete_project_folder_rule(bad_id, apply_to_history=False)
        assert result == {"ok": False, "error": "操作无效"}
        lowered = repr(result).lower()
        for forbidden in ("traceback", "sqlite", "select", "window_title", "clipboard", "note", "secret"):
            assert forbidden not in lowered


def test_delete_project_folder_rule_not_found_maps_to_chinese(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.rule_api, "delete_project_folder_rule",
        lambda rule_id, apply_to_history: {"ok": False, "error": "not_found"},
    )
    result = build_test_bridge().delete_project_folder_rule(9999, apply_to_history=False)
    assert result == {"ok": False, "error": "文件夹规则不存在"}


def test_delete_project_folder_rule_operation_failed_maps_to_chinese(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.rule_api, "delete_project_folder_rule",
        lambda rule_id, apply_to_history: {"ok": False, "error": "operation_failed"},
    )
    result = build_test_bridge().delete_project_folder_rule(1, apply_to_history=False)
    assert result == {"ok": False, "error": "删除文件夹规则失败"}


def test_delete_project_folder_rule_unknown_error_code_collapses(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.rule_api, "delete_project_folder_rule",
        lambda rule_id, apply_to_history: {"ok": False, "error": "unknown_code"},
    )
    result = build_test_bridge().delete_project_folder_rule(1, apply_to_history=False)
    assert result == {"ok": False, "error": "删除文件夹规则失败"}


def test_delete_project_folder_rule_unknown_exception_collapses(monkeypatch):
    def _boom(*args, **kwargs):
        raise RuntimeError("boom: sensitive SQL DELETE FROM ...")
    monkeypatch.setattr(bridge_rules_module.rule_api, "delete_project_folder_rule", _boom)
    result = build_test_bridge().delete_project_folder_rule(1, apply_to_history=False)
    assert result == {"ok": False, "error": "删除文件夹规则失败"}
    lowered = repr(result).lower()
    for forbidden in ("boom", "delete", "sensitive", "traceback", "runtimeerror", "window_title", "clipboard", "note"):
        assert forbidden not in lowered


def test_delete_project_folder_rule_failure_payload_excludes_backend_codes(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.rule_api, "delete_project_folder_rule",
        lambda rule_id, apply_to_history: {
            "ok": False, "error": "operation_failed", "sql": "DELETE FROM folder_project_rule WHERE ...",
            "traceback": "RuntimeError: ...", "details": "C:\\Secret window_title clipboard note",
        },
    )
    result = build_test_bridge().delete_project_folder_rule(1, apply_to_history=False)
    assert result == {"ok": False, "error": "删除文件夹规则失败"}
    lowered = repr(result).lower()
    for forbidden in (
        "operation_failed", "sql", "delete", "traceback", "details", "window_title", "clipboard", "note", "secret",
    ):
        assert forbidden not in lowered


def test_delete_project_folder_rule_success_payload_types_are_stable(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.rule_api, "delete_project_folder_rule",
        lambda rule_id, apply_to_history: {"ok": True, "rule": {"kind": "folder", "id": rule_id, "deleted": True}},
    )
    result = build_test_bridge().delete_project_folder_rule(1, apply_to_history=False)
    assert isinstance(result["ok"], bool)
    rule = result["rule"]
    assert isinstance(rule["kind"], str)
    assert isinstance(rule["id"], int)
    assert isinstance(rule["deleted"], bool)


def test_delete_project_folder_rule_payload_json_serializable(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.rule_api, "delete_project_folder_rule",
        lambda rule_id, apply_to_history: {"ok": True, "rule": {"kind": "folder", "id": rule_id, "deleted": True}},
    )
    result = build_test_bridge().delete_project_folder_rule(1, apply_to_history=False)
    json.dumps(result, ensure_ascii=False)


def test_delete_project_folder_rule_success_payload_strips_extra_api_keys(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.rule_api, "delete_project_folder_rule",
        lambda rule_id, apply_to_history: {
            "ok": True,
            "rule": {
                "kind": "folder", "id": rule_id, "deleted": True, "folder_path": r"C:\Secret",
                "project_id": 99, "normalized_folder_key": "c:\\secret",
                "internal_note": "C:\\Secret window_title clipboard note",
            },
        },
    )
    result = build_test_bridge().delete_project_folder_rule(1, apply_to_history=False)
    rule = result["rule"]
    assert set(rule.keys()) == {"kind", "id", "deleted", "history_updated", "updated_count"}
    lowered = repr(result).lower()
    for forbidden in (
        "folder_path", "project_id", "normalized_folder_key", "internal_note",
        "secret", "window_title", "clipboard", "note",
    ):
        assert forbidden not in lowered


def test_delete_project_folder_rule_never_calls_other_project_rules_write_apis(monkeypatch):
    called: dict[str, int] = {}

    def _track(name):
        def _impl(*args, **kwargs):
            called[name] = called.get(name, 0) + 1
            return {"ok": True, "rule": {"kind": "folder", "id": 1, "deleted": True}}
        return _impl

    monkeypatch.setattr(bridge_rules_module.rule_api, "delete_project_folder_rule", _track("delete_folder"))
    monkeypatch.setattr(bridge_rules_module.rule_api, "set_project_rule_enabled", _track("toggle"))
    monkeypatch.setattr(bridge_rules_module.rule_api, "create_project_keyword_rule", _track("create_keyword"))
    monkeypatch.setattr(bridge_rules_module.rule_api, "delete_project_keyword_rule", _track("delete_keyword"))
    monkeypatch.setattr(bridge_rules_module.rule_api, "create_project_folder_rule", _track("create_folder"))
    monkeypatch.setattr(bridge_rules_module.rule_api, "update_project_folder_rule", _track("update_folder"))
    build_test_bridge().delete_project_folder_rule(1, apply_to_history=False)
    assert called == {"delete_folder": 1}


def test_delete_project_folder_rule_keyword_rule_id_maps_to_stable_not_found(monkeypatch):
    captured: dict[str, object] = {}

    def fake_delete(rule_id, apply_to_history):
        captured["rule_id"] = rule_id
        captured["apply_to_history"] = apply_to_history
        return {
            "ok": False, "error": "not_found", "table": "project_rule",
            "details": "Spec keyword window_title clipboard note",
        }

    monkeypatch.setattr(bridge_rules_module.rule_api, "delete_project_folder_rule", fake_delete)
    result = build_test_bridge().delete_project_folder_rule(77, apply_to_history=False)
    assert captured["rule_id"] == 77
    assert captured["apply_to_history"] is False
    assert result == {"ok": False, "error": "文件夹规则不存在"}
    lowered = repr(result).lower()
    for forbidden in (
        "project_rule", "table", "details", "traceback", "sqlite", "select", "window_title",
        "clipboard", "note", "secret", "spec", "keyword",
    ):
        assert forbidden not in lowered


def test_delete_project_folder_rule_bridge_input_validation_payloads_json_serializable():
    bridge = build_test_bridge()
    for bad_id in (None, True, False, "1", "abc", 1.0, 2.5, 0, -1, [], {}, (), {1, 2}, (1,), frozenset({1})):
        result = bridge.delete_project_folder_rule(bad_id, apply_to_history=False)
        assert result == {"ok": False, "error": "操作无效"}
        json.dumps(result, ensure_ascii=False)
        lowered = repr(result).lower()
        for forbidden in ("traceback", "sqlite", "select", "window_title", "clipboard", "note", "secret"):
            assert forbidden not in lowered


def test_delete_project_folder_rule_does_not_regress_get_project_rules(monkeypatch):
    called = {"get_project_rules": 0}

    def _track(*args, **kwargs):
        called["get_project_rules"] += 1
        return []

    monkeypatch.setattr(bridge_rules_module.project_api, "list_project_bindings", _track)
    monkeypatch.setattr(
        bridge_rules_module.rule_api, "delete_project_folder_rule",
        lambda rule_id, apply_to_history: {"ok": True, "rule": {"kind": "folder", "id": rule_id, "deleted": True}},
    )
    bridge = build_test_bridge()
    bridge.delete_project_folder_rule(1, apply_to_history=False)
    result = bridge.get_project_rules()
    assert called["get_project_rules"] == 1
    assert result["ok"] is True


def test_delete_project_folder_rule_does_not_regress_set_project_rule_enabled(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.rule_api, "delete_project_folder_rule",
        lambda rule_id, apply_to_history: {"ok": True, "rule": {"kind": "folder", "id": rule_id, "deleted": True}},
    )
    monkeypatch.setattr(
        bridge_rules_module.rule_api, "set_project_rule_enabled",
        lambda rule_type, rule_id, enabled: {"ok": True, "rule": {"kind": rule_type, "id": rule_id, "enabled": enabled}},
    )
    bridge = build_test_bridge()
    delete_result = bridge.delete_project_folder_rule(1, apply_to_history=False)
    toggle_result = bridge.set_project_rule_enabled("folder", 10, False)
    assert delete_result["ok"] is True
    assert toggle_result["ok"] is True


def test_delete_project_folder_rule_does_not_regress_create_project_keyword_rule(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.rule_api, "delete_project_folder_rule",
        lambda rule_id, apply_to_history: {"ok": True, "rule": {"kind": "folder", "id": rule_id, "deleted": True}},
    )
    monkeypatch.setattr(
        bridge_rules_module.rule_api, "create_project_keyword_rule",
        lambda project_id, keyword: {
            "ok": True,
            "rule": {"kind": "keyword", "id": 2, "project_id": project_id, "keyword": keyword.strip(), "enabled": True},
        },
    )
    bridge = build_test_bridge()
    delete_result = bridge.delete_project_folder_rule(1, apply_to_history=False)
    keyword_result = bridge.create_project_keyword_rule(1, "Spec")
    assert delete_result["ok"] is True
    assert keyword_result["ok"] is True


def test_delete_project_folder_rule_does_not_regress_delete_project_keyword_rule(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.rule_api, "delete_project_folder_rule",
        lambda rule_id, apply_to_history: {"ok": True, "rule": {"kind": "folder", "id": rule_id, "deleted": True}},
    )
    monkeypatch.setattr(
        bridge_rules_module.rule_api, "delete_project_keyword_rule",
        lambda rule_id, apply_to_history: {"ok": True, "rule": {"kind": "keyword", "id": rule_id, "deleted": True}},
    )
    bridge = build_test_bridge()
    folder_result = bridge.delete_project_folder_rule(1, apply_to_history=False)
    keyword_result = bridge.delete_project_keyword_rule(99, apply_to_history=False)
    assert folder_result["ok"] is True
    assert keyword_result["ok"] is True


@pytest.mark.parametrize("bad_id", [True, False])
def test_create_project_folder_rule_rejects_bool_as_int_project_id_consolidated(bad_id):
    result = build_test_bridge().create_project_folder_rule(bad_id, r"D:\Work", True)
    assert result == {"ok": False, "error": "操作无效"}


@pytest.mark.parametrize("bad_id", [True, False])
def test_update_project_folder_rule_rejects_bool_as_int_rule_id_consolidated(bad_id):
    result = build_test_bridge().update_project_folder_rule(bad_id, r"D:\New", True)
    assert result == {"ok": False, "error": "操作无效"}


@pytest.mark.parametrize("bad_id", [True, False])
def test_delete_project_folder_rule_rejects_bool_as_int_rule_id_consolidated(bad_id):
    result = build_test_bridge().delete_project_folder_rule(bad_id, apply_to_history=False)
    assert result == {"ok": False, "error": "操作无效"}


def test_folder_bridge_methods_invalid_input_return_consistent_message():
    bridge = build_test_bridge()
    create_result = bridge.create_project_folder_rule(True, r"D:\Work", True)
    update_result = bridge.update_project_folder_rule(True, r"D:\New", True)
    delete_result = bridge.delete_project_folder_rule(True, apply_to_history=False)
    assert create_result == update_result == delete_result == {"ok": False, "error": "操作无效"}


def test_folder_bridge_methods_error_message_maps_are_distinct_and_stable():
    assert presenter_module._PROJECT_RULE_FOLDER_CREATE_MESSAGES["operation_failed"] == "新增文件夹规则失败"
    assert presenter_module._PROJECT_RULE_FOLDER_UPDATE_MESSAGES["not_found"] == "文件夹规则不存在"
    assert presenter_module._PROJECT_RULE_FOLDER_UPDATE_MESSAGES["operation_failed"] == "保存文件夹规则失败"
    assert presenter_module._PROJECT_RULE_FOLDER_DELETE_MESSAGES["not_found"] == "文件夹规则不存在"
    assert presenter_module._PROJECT_RULE_FOLDER_DELETE_MESSAGES["operation_failed"] == "删除文件夹规则失败"
    assert "not_found" not in presenter_module._PROJECT_RULE_FOLDER_CREATE_MESSAGES
    assert presenter_module._PROJECT_RULE_FOLDER_CREATE_MESSAGES["project_not_found"] == "项目不存在或不可用"


def test_create_project_folder_rule_never_forwards_bool_project_id_to_api(monkeypatch):
    called: list = []

    def _spy(*args, **kwargs):
        called.append(args)
        return {"ok": True, "rule": {"kind": "folder", "id": 1, "project_id": 1, "folder_path": "x", "recursive": True, "enabled": True}}

    monkeypatch.setattr(bridge_rules_module.rule_api, "create_project_folder_rule", _spy)
    build_test_bridge().create_project_folder_rule(True, r"D:\Work", True)
    assert called == []


def test_update_project_folder_rule_never_forwards_bool_rule_id_to_api(monkeypatch):
    called: list = []

    def _spy(*args, **kwargs):
        called.append(args)
        return {"ok": True, "rule": {"kind": "folder", "id": 1, "project_id": 1, "folder_path": "x", "recursive": True, "enabled": True}}

    monkeypatch.setattr(bridge_rules_module.rule_api, "update_project_folder_rule", _spy)
    build_test_bridge().update_project_folder_rule(True, r"D:\New", True)
    assert called == []


def test_delete_project_folder_rule_never_forwards_bool_rule_id_to_api(monkeypatch):
    called: list = []

    def _spy(*args, **kwargs):
        called.append(args)
        return {"ok": True, "rule": {"kind": "folder", "id": 1, "deleted": True}}

    monkeypatch.setattr(bridge_rules_module.rule_api, "delete_project_folder_rule", _spy)
    build_test_bridge().delete_project_folder_rule(True, apply_to_history=False)
    assert called == []


def test_create_project_folder_rule_never_forwards_non_bool_recursive_to_api(monkeypatch):
    called: list = []

    def _spy(*args, **kwargs):
        called.append(args)
        return {"ok": True, "rule": {"kind": "folder", "id": 1, "project_id": 1, "folder_path": "x", "recursive": True, "enabled": True}}

    monkeypatch.setattr(bridge_rules_module.rule_api, "create_project_folder_rule", _spy)
    for bad_recursive in (1, 0, "true", None, 1.0):
        build_test_bridge().create_project_folder_rule(1, r"D:\Work", bad_recursive)
    assert called == []


def test_update_project_folder_rule_never_forwards_non_bool_recursive_to_api(monkeypatch):
    called: list = []

    def _spy(*args, **kwargs):
        called.append(args)
        return {"ok": True, "rule": {"kind": "folder", "id": 1, "project_id": 1, "folder_path": "x", "recursive": True, "enabled": True}}

    monkeypatch.setattr(bridge_rules_module.rule_api, "update_project_folder_rule", _spy)
    for bad_recursive in (1, 0, "true", None, 1.0):
        build_test_bridge().update_project_folder_rule(1, r"D:\New", bad_recursive)
    assert called == []


def test_folder_bridge_failure_payloads_are_json_serializable(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.rule_api, "create_project_folder_rule",
        lambda project_id, folder_path, recursive: {"ok": False, "error": "operation_failed"},
    )
    monkeypatch.setattr(
        bridge_rules_module.rule_api, "update_project_folder_rule",
        lambda rule_id, folder_path, recursive: {"ok": False, "error": "not_found"},
    )
    monkeypatch.setattr(
        bridge_rules_module.rule_api, "delete_project_folder_rule",
        lambda rule_id, apply_to_history: {"ok": False, "error": "operation_failed"},
    )
    bridge = build_test_bridge()
    json.dumps(bridge.create_project_folder_rule(True, r"D:\Work", True), ensure_ascii=False)
    json.dumps(bridge.create_project_folder_rule(1, r"D:\Work", True), ensure_ascii=False)
    json.dumps(bridge.update_project_folder_rule(True, r"D:\New", True), ensure_ascii=False)
    json.dumps(bridge.update_project_folder_rule(1, r"D:\New", True), ensure_ascii=False)
    json.dumps(bridge.delete_project_folder_rule(True, apply_to_history=False), ensure_ascii=False)
    json.dumps(bridge.delete_project_folder_rule(1, apply_to_history=False), ensure_ascii=False)


def test_folder_bridge_methods_do_not_cross_pollute_keyword_or_toggle(monkeypatch):
    called: dict[str, int] = {}

    def _track(name):
        def _impl(*args, **kwargs):
            called[name] = called.get(name, 0) + 1
            return {"ok": True, "rule": {"kind": "folder", "id": 1, "deleted": True}}
        return _impl

    monkeypatch.setattr(bridge_rules_module.rule_api, "create_project_folder_rule", _track("create_folder"))
    monkeypatch.setattr(bridge_rules_module.rule_api, "update_project_folder_rule", _track("update_folder"))
    monkeypatch.setattr(bridge_rules_module.rule_api, "delete_project_folder_rule", _track("delete_folder"))
    monkeypatch.setattr(bridge_rules_module.rule_api, "create_project_keyword_rule", _track("create_keyword"))
    monkeypatch.setattr(bridge_rules_module.rule_api, "delete_project_keyword_rule", _track("delete_keyword"))
    monkeypatch.setattr(bridge_rules_module.rule_api, "set_project_rule_enabled", _track("toggle"))
    bridge = build_test_bridge()
    bridge.create_project_folder_rule(1, r"D:\Work", True)
    bridge.update_project_folder_rule(1, r"D:\New", False)
    bridge.delete_project_folder_rule(1, apply_to_history=False)
    assert called == {"create_folder": 1, "update_folder": 1, "delete_folder": 1}
    before = dict(called)
    bridge.create_project_keyword_rule(1, "Spec")
    bridge.delete_project_keyword_rule(99, apply_to_history=False)
    bridge.set_project_rule_enabled("folder", 1, False)
    assert called["create_folder"] == before["create_folder"]
    assert called["update_folder"] == before["update_folder"]
    assert called["delete_folder"] == before["delete_folder"]
    assert called["create_keyword"] == 1
    assert called["delete_keyword"] == 1
    assert called["toggle"] == 1


def test_folder_bridge_success_payloads_never_include_api_error_keys(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.rule_api, "create_project_folder_rule",
        lambda project_id, folder_path, recursive: {
            "ok": True,
            "rule": {"kind": "folder", "id": 7, "project_id": project_id, "folder_path": folder_path, "recursive": recursive, "enabled": True},
        },
    )
    monkeypatch.setattr(
        bridge_rules_module.rule_api, "update_project_folder_rule",
        lambda rule_id, folder_path, recursive: {
            "ok": True,
            "rule": {"kind": "folder", "id": rule_id, "project_id": 1, "folder_path": folder_path, "recursive": recursive, "enabled": True},
        },
    )
    monkeypatch.setattr(
        bridge_rules_module.rule_api, "delete_project_folder_rule",
        lambda rule_id, apply_to_history: {"ok": True, "rule": {"kind": "folder", "id": rule_id, "deleted": True}},
    )
    bridge = build_test_bridge()
    create_result = bridge.create_project_folder_rule(1, r"D:\Work", True)
    update_result = bridge.update_project_folder_rule(1, r"D:\New", False)
    delete_result = bridge.delete_project_folder_rule(1, apply_to_history=False)
    assert set(create_result.keys()) == {"ok", "rule"}
    assert set(create_result["rule"].keys()) == {"kind", "id", "project_id", "folder_path", "recursive", "enabled"}
    assert set(update_result.keys()) == {"ok", "rule"}
    assert set(update_result["rule"].keys()) == {"kind", "id", "project_id", "folder_path", "recursive", "enabled"}
    assert set(delete_result.keys()) == {"ok", "rule"}
    assert set(delete_result["rule"].keys()) == {"kind", "id", "deleted", "history_updated", "updated_count"}
    for result in (create_result, update_result, delete_result):
        assert "error" not in result
        assert "projects" not in result
        assert "rules" not in result


def test_update_project_keyword_rule_success_payload(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.rule_api, "update_project_keyword_rule",
        lambda rule_id, keyword: {
            "ok": True,
            "rule": {"kind": "keyword", "id": rule_id, "project_id": 1, "keyword": keyword, "enabled": True},
        },
    )
    result = build_test_bridge().update_project_keyword_rule(123, "NewSpec")
    assert result == {
        "ok": True,
        "rule": {"kind": "keyword", "id": 123, "project_id": 1, "keyword": "NewSpec", "enabled": True},
    }
    assert "projects" not in result


@pytest.mark.parametrize("bad_id", [None, True, False, "1", "abc", 0, -1, 1.0, 2.5, [], {}, (), {1, 2}, (1,), frozenset({1})])
def test_update_project_keyword_rule_rejects_invalid_rule_id(bad_id):
    result = build_test_bridge().update_project_keyword_rule(bad_id, "Spec")
    assert result == {"ok": False, "error": "操作无效"}


@pytest.mark.parametrize("bad_keyword", [None, True, False, 1, 1.0, [], {}, (), {1, 2}, (1,), frozenset({1})])
def test_update_project_keyword_rule_rejects_non_string_keyword(bad_keyword):
    result = build_test_bridge().update_project_keyword_rule(1, bad_keyword)
    assert result == {"ok": False, "error": "操作无效"}


@pytest.mark.parametrize("bad_keyword", ["", "   ", "\t", "\n", "  \t  "])
def test_update_project_keyword_rule_rejects_empty_or_whitespace_keyword(bad_keyword):
    result = build_test_bridge().update_project_keyword_rule(1, bad_keyword)
    assert result == {"ok": False, "error": "操作无效"}


def test_update_project_keyword_rule_bridge_passes_trimmed_keyword_to_api(monkeypatch):
    captured: list = []

    def _spy(rule_id, keyword):
        captured.append((rule_id, keyword))
        return {
            "ok": True,
            "rule": {"kind": "keyword", "id": rule_id, "project_id": 1, "keyword": keyword, "enabled": True},
        }

    monkeypatch.setattr(bridge_rules_module.rule_api, "update_project_keyword_rule", _spy)
    build_test_bridge().update_project_keyword_rule(5, "  NewSpec  ")
    assert captured == [(5, "NewSpec")]


def test_update_project_keyword_rule_invalid_input_maps_to_chinese(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.rule_api, "update_project_keyword_rule",
        lambda rule_id, keyword: {"ok": False, "error": "invalid_input"},
    )
    result = build_test_bridge().update_project_keyword_rule(1, "Spec")
    assert result == {"ok": False, "error": "操作无效"}


def test_update_project_keyword_rule_not_found_maps_to_chinese(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.rule_api, "update_project_keyword_rule",
        lambda rule_id, keyword: {"ok": False, "error": "not_found"},
    )
    result = build_test_bridge().update_project_keyword_rule(999, "Spec")
    assert result == {"ok": False, "error": "关键词规则不存在"}


def test_update_project_keyword_rule_duplicate_rule_maps_to_chinese(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.rule_api, "update_project_keyword_rule",
        lambda rule_id, keyword: {"ok": False, "error": "duplicate_rule"},
    )
    result = build_test_bridge().update_project_keyword_rule(1, "Spec")
    assert result == {"ok": False, "error": "关键词规则已存在"}


def test_update_project_keyword_rule_operation_failed_maps_to_chinese(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.rule_api, "update_project_keyword_rule",
        lambda rule_id, keyword: {"ok": False, "error": "operation_failed"},
    )
    result = build_test_bridge().update_project_keyword_rule(1, "Spec")
    assert result == {"ok": False, "error": "保存关键词规则失败"}


def test_update_project_keyword_rule_unknown_error_code_collapses(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.rule_api, "update_project_keyword_rule",
        lambda rule_id, keyword: {"ok": False, "error": "unexpected raw code"},
    )
    result = build_test_bridge().update_project_keyword_rule(1, "Spec")
    assert result == {"ok": False, "error": "保存关键词规则失败"}


def test_update_project_keyword_rule_unknown_exception_collapses(monkeypatch):
    def fail(rule_id, keyword):
        raise RuntimeError(
            "boom SELECT * FROM activity_log traceback window_title clipboard note C:\\Secret"
        )
    monkeypatch.setattr(bridge_rules_module.rule_api, "update_project_keyword_rule", fail)
    result = build_test_bridge().update_project_keyword_rule(1, "Spec")
    assert result == {"ok": False, "error": "保存关键词规则失败"}
    lowered = repr(result).lower()
    for forbidden in (
        "traceback", "sqlite", "select", "boom", "window_title", "clipboard", "note", "activity_log", "secret",
    ):
        assert forbidden not in lowered


def test_update_project_keyword_rule_failure_payload_excludes_backend_codes(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.rule_api, "update_project_keyword_rule",
        lambda rule_id, keyword: {
            "ok": False, "error": "not_found", "code": "not_found", "internal_field": "should not leak",
            "traceback": "SELECT * FROM project_rule", "details": "C:\\Secret window_title clipboard note",
        },
    )
    result = build_test_bridge().update_project_keyword_rule(999, "Spec")
    assert result == {"ok": False, "error": "关键词规则不存在"}
    lowered = repr(result).lower()
    for forbidden in (
        "internal_field", "should not leak", "code", "not_found", "traceback", "sqlite",
        "select", "window_title", "clipboard", "note", "secret", "details",
    ):
        assert forbidden not in lowered


def test_update_project_keyword_rule_success_payload_types_are_stable(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.rule_api, "update_project_keyword_rule",
        lambda rule_id, keyword: {
            "ok": True,
            "rule": {"kind": "keyword", "id": rule_id, "project_id": 1, "keyword": keyword, "enabled": 1},
        },
    )
    result = build_test_bridge().update_project_keyword_rule(25, "NewSpec")
    assert type(result["ok"]) is bool
    rule = result["rule"]
    assert type(rule["kind"]) is str
    assert type(rule["id"]) is int
    assert type(rule["project_id"]) is int
    assert type(rule["keyword"]) is str
    assert type(rule["enabled"]) is bool


def test_update_project_keyword_rule_payload_json_serializable(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.rule_api, "update_project_keyword_rule",
        lambda rule_id, keyword: {
            "ok": True,
            "rule": {"kind": "keyword", "id": rule_id, "project_id": 1, "keyword": keyword, "enabled": True},
        },
    )
    result = build_test_bridge().update_project_keyword_rule(20, "NewSpec")
    json.dumps(result, ensure_ascii=False)
    assert "Traceback" not in repr(result)
    assert "SELECT" not in repr(result)


def test_update_project_keyword_rule_success_payload_strips_extra_api_keys(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.rule_api, "update_project_keyword_rule",
        lambda rule_id, keyword: {
            "ok": True,
            "rule": {
                "kind": "keyword", "id": rule_id, "project_id": 1, "keyword": keyword, "enabled": True,
                "created_by": "user", "created_at": "2026-06-28T10:00:00",
                "updated_at": "2026-06-28T10:00:00", "rule_type": "keyword", "pattern": keyword,
                "internal_field": "should not leak", "traceback": "SELECT * FROM project_rule",
                "details": "C:\\Secret window_title clipboard note",
            },
        },
    )
    result = build_test_bridge().update_project_keyword_rule(7, "NewSpec")
    rule = result["rule"]
    assert set(rule.keys()) == {"kind", "id", "project_id", "keyword", "enabled"}
    lowered = repr(result).lower()
    for forbidden in (
        "created_by", "created_at", "updated_at", "rule_type", "pattern", "should not leak",
        "internal_field", "traceback", "sqlite", "select", "window_title", "clipboard", "note", "secret", "details",
    ):
        assert forbidden not in lowered


def test_update_project_keyword_rule_never_calls_other_project_rules_write_apis(monkeypatch):
    called: dict[str, int] = {}

    def _track(name):
        def _impl(*args, **kwargs):
            called[name] = called.get(name, 0) + 1
            return {"ok": True, "rule": {"kind": "keyword", "id": 1, "deleted": True}}
        return _impl

    monkeypatch.setattr(bridge_rules_module.rule_api, "update_project_keyword_rule", _track("update_keyword"))
    monkeypatch.setattr(bridge_rules_module.rule_api, "set_project_rule_enabled", _track("toggle"))
    monkeypatch.setattr(bridge_rules_module.rule_api, "create_project_keyword_rule", _track("create_keyword"))
    monkeypatch.setattr(bridge_rules_module.rule_api, "delete_project_keyword_rule", _track("delete_keyword"))
    monkeypatch.setattr(bridge_rules_module.rule_api, "create_project_folder_rule", _track("create_folder"))
    monkeypatch.setattr(bridge_rules_module.rule_api, "update_project_folder_rule", _track("update_folder"))
    monkeypatch.setattr(bridge_rules_module.rule_api, "delete_project_folder_rule", _track("delete_folder"))
    build_test_bridge().update_project_keyword_rule(1, "NewSpec")
    assert called == {"update_keyword": 1}


def test_update_project_keyword_rule_never_forwards_bool_rule_id_to_api(monkeypatch):
    called: list = []

    def _spy(*args, **kwargs):
        called.append(args)
        return {"ok": True, "rule": {"kind": "keyword", "id": 1, "project_id": 1, "keyword": "x", "enabled": True}}

    monkeypatch.setattr(bridge_rules_module.rule_api, "update_project_keyword_rule", _spy)
    build_test_bridge().update_project_keyword_rule(True, "NewSpec")
    assert called == []


def test_other_write_apis_do_not_call_update_project_keyword_rule(monkeypatch):
    called: list = []

    def _spy(*args, **kwargs):
        called.append(args)
        return {"ok": True, "rule": {"kind": "keyword", "id": 1, "keyword": "x", "enabled": True}}

    monkeypatch.setattr(bridge_rules_module.rule_api, "update_project_keyword_rule", _spy)
    monkeypatch.setattr(
        bridge_rules_module.rule_api, "create_project_keyword_rule",
        lambda project_id, keyword: {"ok": True, "rule": {"kind": "keyword", "id": 1, "project_id": project_id, "keyword": keyword, "enabled": True}},
    )
    monkeypatch.setattr(
        bridge_rules_module.rule_api, "delete_project_keyword_rule",
        lambda rule_id, apply_to_history: {"ok": True, "rule": {"kind": "keyword", "id": rule_id, "deleted": True}},
    )
    monkeypatch.setattr(
        bridge_rules_module.rule_api, "set_project_rule_enabled",
        lambda rule_type, rule_id, enabled: {"ok": True, "rule_type": rule_type, "rule_id": rule_id, "enabled": enabled},
    )
    monkeypatch.setattr(
        bridge_rules_module.rule_api, "create_project_folder_rule",
        lambda project_id, folder_path, recursive: {"ok": True, "rule": {"kind": "folder", "id": 1, "project_id": project_id, "folder_path": folder_path, "recursive": recursive, "enabled": True}},
    )
    monkeypatch.setattr(
        bridge_rules_module.rule_api, "update_project_folder_rule",
        lambda rule_id, folder_path, recursive: {"ok": True, "rule": {"kind": "folder", "id": rule_id, "project_id": 1, "folder_path": folder_path, "recursive": recursive, "enabled": True}},
    )
    monkeypatch.setattr(
        bridge_rules_module.rule_api, "delete_project_folder_rule",
        lambda rule_id, apply_to_history: {"ok": True, "rule": {"kind": "folder", "id": rule_id, "deleted": True}},
    )
    bridge = build_test_bridge()
    bridge.create_project_keyword_rule(1, "Spec")
    bridge.delete_project_keyword_rule(1, apply_to_history=False)
    bridge.set_project_rule_enabled("keyword", 1, False)
    bridge.create_project_folder_rule(1, r"D:\Work", True)
    bridge.update_project_folder_rule(1, r"D:\New", False)
    bridge.delete_project_folder_rule(1, apply_to_history=False)
    assert called == []


def test_update_project_keyword_rule_invalid_input_payload_excludes_sensitive_text():
    bridge = build_test_bridge()
    for bad_id in (None, True, False, "1", 1.0, [], {}, 0, -1, (), {1, 2}, (1,), frozenset({1})):
        result = bridge.update_project_keyword_rule(bad_id, "Spec")
        assert result == {"ok": False, "error": "操作无效"}
        lowered = repr(result).lower()
        for forbidden in ("traceback", "sqlite", "select", "window_title", "clipboard", "note", "secret"):
            assert forbidden not in lowered
    for bad_keyword in (None, True, False, 1, 1.0, [], {}, "", "   ", (), {1, 2}, (1,), frozenset({1})):
        result = bridge.update_project_keyword_rule(1, bad_keyword)
        assert result == {"ok": False, "error": "操作无效"}
        lowered = repr(result).lower()
        for forbidden in ("traceback", "sqlite", "select", "window_title", "clipboard", "note", "secret"):
            assert forbidden not in lowered


def test_update_project_keyword_rule_failure_payloads_json_serializable(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.rule_api, "update_project_keyword_rule",
        lambda rule_id, keyword: {"ok": False, "error": "operation_failed"},
    )
    for bad_id in (True, None, 0, -1, "1", 1.0, [], {}):
        result = build_test_bridge().update_project_keyword_rule(bad_id, "Spec")
        json.dumps(result, ensure_ascii=False)
    for bad_keyword in (None, True, 1, "", "   "):
        result = build_test_bridge().update_project_keyword_rule(1, bad_keyword)
        json.dumps(result, ensure_ascii=False)
    for code in ("invalid_input", "not_found", "duplicate_rule", "operation_failed", "unknown"):
        monkeypatch.setattr(
            bridge_rules_module.rule_api, "update_project_keyword_rule",
            lambda rule_id, keyword, c=code: {"ok": False, "error": c},
        )
        result = build_test_bridge().update_project_keyword_rule(1, "Spec")
        json.dumps(result, ensure_ascii=False)
        assert "Traceback" not in repr(result)


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


def test_create_project_for_rules_success_narrow_payload(monkeypatch):
    calls = _patch_project_api(
        monkeypatch, "create_project_for_rules",
        {"ok": True, "project": dict(_PROJECT_LIFECYCLE_SUMMARY)},
    )
    result = build_test_bridge().create_project_for_rules("  Client  ", "  billable  ")
    assert result == {"ok": True, "project": _PROJECT_LIFECYCLE_SUMMARY}
    assert calls == [(("Client", "billable", "中文"), {})]
    json.dumps(result, ensure_ascii=False)


def test_create_project_for_rules_rejects_non_str_name():
    bridge = build_test_bridge()
    for bad_name in (None, True, False, 1, 1.5, [], {}, b"Client"):
        assert bridge.create_project_for_rules(bad_name, "desc") == {"ok": False, "error": "操作无效"}


def test_create_project_for_rules_rejects_non_str_description():
    bridge = build_test_bridge()
    for bad_desc in (None, True, False, 1, 1.5, [], {}, b"desc"):
        assert bridge.create_project_for_rules("Client", bad_desc) == {"ok": False, "error": "操作无效"}


def test_create_project_for_rules_rejects_empty_or_whitespace_name():
    bridge = build_test_bridge()
    for bad_name in ("", "   ", "\t\n"):
        assert bridge.create_project_for_rules(bad_name, "desc") == {"ok": False, "error": "操作无效"}


def test_create_project_for_rules_maps_error_codes_to_chinese(monkeypatch):
    bridge = build_test_bridge()
    for code, expected in (
        ("invalid_input", "操作无效"), ("duplicate_project", "项目名称已存在"),
        ("operation_failed", "新增项目失败"), ("unknown_code", "新增项目失败"),
    ):
        monkeypatch.setattr(
            bridge_rules_module.project_api, "create_project_for_rules",
            lambda name, description, language="中文", c=code: {"ok": False, "error": c},
        )
        assert bridge.create_project_for_rules("Client", "") == {"ok": False, "error": expected}


def test_create_project_for_rules_unknown_exception_collapses(monkeypatch):
    def boom(name, description="", language="中文"):
        raise RuntimeError(
            "boom SELECT * FROM activity_log traceback window_title clipboard note C:\\Secret"
        )
    monkeypatch.setattr(bridge_rules_module.project_api, "create_project_for_rules", boom)
    result = build_test_bridge().create_project_for_rules("Client", "desc")
    assert result == {"ok": False, "error": "新增项目失败"}
    lowered = repr(result).lower()
    for forbidden in ("traceback", "sqlite", "select", "boom", "window_title", "clipboard", "note", "secret"):
        assert forbidden not in lowered


def test_create_project_for_rules_does_not_call_keyword_or_folder_apis(monkeypatch):
    forbidden_calls: list = []

    def make_forbidden(name: str):
        def _fail(*args, **kwargs):
            forbidden_calls.append(name)
            raise AssertionError(name + " must not be called by project create path")
        return _fail

    for name in (
        "create_project_keyword_rule", "delete_project_keyword_rule", "update_project_keyword_rule",
        "create_project_folder_rule", "update_project_folder_rule", "delete_project_folder_rule",
        "set_project_rule_enabled",
    ):
        monkeypatch.setattr(bridge_rules_module.rule_api, name, make_forbidden(name), raising=False)
    monkeypatch.setattr(
        bridge_rules_module.project_api, "create_project_for_rules",
        lambda name, description="", language="中文": {"ok": True, "project": dict(_PROJECT_LIFECYCLE_SUMMARY)},
    )
    build_test_bridge().create_project_for_rules("Client", "desc")
    assert forbidden_calls == []


def test_update_project_for_rules_success_narrow_payload(monkeypatch):
    calls = _patch_project_api(
        monkeypatch, "update_project_for_rules",
        {"ok": True, "project": dict(_PROJECT_LIFECYCLE_SUMMARY)},
    )
    result = build_test_bridge().update_project_for_rules(1, "  Client  ", "  billable  ")
    assert result == {"ok": True, "project": _PROJECT_LIFECYCLE_SUMMARY}
    assert calls == [((1, "Client", "billable", "中文"), {})]
    json.dumps(result, ensure_ascii=False)


def test_update_project_for_rules_rejects_bool_as_int_project_id(monkeypatch):
    forwarded: list = []

    def _spy(*args, **kwargs):
        forwarded.append(args)
        return {"ok": True, "project": dict(_PROJECT_LIFECYCLE_SUMMARY)}

    monkeypatch.setattr(bridge_rules_module.project_api, "update_project_for_rules", _spy)
    bridge = build_test_bridge()
    for bad_id in (True, False):
        assert bridge.update_project_for_rules(bad_id, "Renamed", "new") == {"ok": False, "error": "操作无效"}
    assert forwarded == []


def test_update_project_for_rules_rejects_non_int_or_non_positive_project_id():
    bridge = build_test_bridge()
    for bad_id in (None, "1", 1.0, 1.5, [], {}, b"1", 0, -1):
        assert bridge.update_project_for_rules(bad_id, "Renamed", "new") == {"ok": False, "error": "操作无效"}


def test_update_project_for_rules_rejects_non_str_name():
    bridge = build_test_bridge()
    for bad_name in (None, True, False, 1, 1.5, [], {}):
        assert bridge.update_project_for_rules(1, bad_name, "new") == {"ok": False, "error": "操作无效"}


def test_update_project_for_rules_rejects_non_str_description():
    bridge = build_test_bridge()
    for bad_desc in (None, True, False, 1, 1.5, [], {}):
        assert bridge.update_project_for_rules(1, "Renamed", bad_desc) == {"ok": False, "error": "操作无效"}


def test_update_project_for_rules_rejects_empty_name():
    bridge = build_test_bridge()
    for bad_name in ("", "   ", "\t\n"):
        assert bridge.update_project_for_rules(1, bad_name, "new") == {"ok": False, "error": "操作无效"}


def test_update_project_for_rules_maps_error_codes_to_chinese(monkeypatch):
    bridge = build_test_bridge()
    for code, expected in (
        ("invalid_input", "操作无效"), ("not_found", "项目不存在"),
        ("system_project", "系统项目不能修改"), ("duplicate_project", "项目名称已存在"),
        ("operation_failed", "保存项目失败"), ("unknown_code", "保存项目失败"),
    ):
        monkeypatch.setattr(
            bridge_rules_module.project_api, "update_project_for_rules",
            lambda project_id, name, description, language="中文", c=code: {"ok": False, "error": c},
        )
        assert bridge.update_project_for_rules(1, "Renamed", "new") == {"ok": False, "error": expected}


def test_update_project_for_rules_unknown_exception_collapses(monkeypatch):
    def boom(project_id, name, description="", language="中文"):
        raise RuntimeError(
            "boom SELECT * FROM activity_log traceback window_title clipboard note C:\\Secret"
        )
    monkeypatch.setattr(bridge_rules_module.project_api, "update_project_for_rules", boom)
    result = build_test_bridge().update_project_for_rules(1, "Renamed", "new")
    assert result == {"ok": False, "error": "保存项目失败"}
    lowered = repr(result).lower()
    for forbidden in ("traceback", "sqlite", "select", "boom", "window_title", "clipboard", "note", "secret"):
        assert forbidden not in lowered


def test_update_project_for_rules_does_not_call_keyword_or_folder_apis(monkeypatch):
    forbidden_calls: list = []

    def make_forbidden(name: str):
        def _fail(*args, **kwargs):
            forbidden_calls.append(name)
            raise AssertionError(name + " must not be called by project update path")
        return _fail

    for name in (
        "create_project_keyword_rule", "delete_project_keyword_rule", "update_project_keyword_rule",
        "create_project_folder_rule", "update_project_folder_rule", "delete_project_folder_rule",
        "set_project_rule_enabled",
    ):
        monkeypatch.setattr(bridge_rules_module.rule_api, name, make_forbidden(name), raising=False)
    monkeypatch.setattr(
        bridge_rules_module.project_api, "update_project_for_rules",
        lambda project_id, name, description="", language="中文": {"ok": True, "project": dict(_PROJECT_LIFECYCLE_SUMMARY)},
    )
    build_test_bridge().update_project_for_rules(1, "Renamed", "new")
    assert forbidden_calls == []


def test_set_project_enabled_for_rules_success_narrow_payload(monkeypatch):
    calls = _patch_project_api(
        monkeypatch, "set_project_enabled_for_rules",
        {"ok": True, "project": dict(_PROJECT_LIFECYCLE_SUMMARY)},
    )
    result = build_test_bridge().set_project_enabled_for_rules(1, False)
    assert result == {"ok": True, "project": _PROJECT_LIFECYCLE_SUMMARY}
    assert calls == [((1, False), {})]
    json.dumps(result, ensure_ascii=False)


def test_set_project_enabled_for_rules_rejects_bool_as_int_project_id(monkeypatch):
    forwarded: list = []

    def _spy(*args, **kwargs):
        forwarded.append(args)
        return {"ok": True, "project": dict(_PROJECT_LIFECYCLE_SUMMARY)}

    monkeypatch.setattr(bridge_rules_module.project_api, "set_project_enabled_for_rules", _spy)
    bridge = build_test_bridge()
    for bad_id in (True, False):
        assert bridge.set_project_enabled_for_rules(bad_id, False) == {"ok": False, "error": "操作无效"}
    assert forwarded == []


def test_set_project_enabled_for_rules_rejects_non_int_or_non_positive_project_id():
    bridge = build_test_bridge()
    for bad_id in (None, "1", 1.0, 1.5, [], {}, b"1", 0, -1):
        assert bridge.set_project_enabled_for_rules(bad_id, False) == {"ok": False, "error": "操作无效"}


def test_set_project_enabled_for_rules_rejects_non_bool_enabled():
    bridge = build_test_bridge()
    for bad_enabled in (None, 1, 0, "true", "false", [], {}):
        assert bridge.set_project_enabled_for_rules(1, bad_enabled) == {"ok": False, "error": "操作无效"}


def test_set_project_enabled_for_rules_maps_error_codes_to_chinese(monkeypatch):
    bridge = build_test_bridge()
    for code, expected in (
        ("invalid_input", "操作无效"), ("not_found", "项目不存在"),
        ("system_project", "系统项目不能修改"), ("operation_failed", "更新项目状态失败"),
        ("unknown_code", "更新项目状态失败"),
    ):
        monkeypatch.setattr(
            bridge_rules_module.project_api, "set_project_enabled_for_rules",
            lambda project_id, enabled, c=code: {"ok": False, "error": c},
        )
        assert bridge.set_project_enabled_for_rules(1, False) == {"ok": False, "error": expected}


def test_set_project_enabled_for_rules_unknown_exception_collapses(monkeypatch):
    def boom(project_id, enabled):
        raise RuntimeError(
            "boom SELECT * FROM activity_log traceback window_title clipboard note C:\\Secret"
        )
    monkeypatch.setattr(bridge_rules_module.project_api, "set_project_enabled_for_rules", boom)
    result = build_test_bridge().set_project_enabled_for_rules(1, False)
    assert result == {"ok": False, "error": "更新项目状态失败"}
    lowered = repr(result).lower()
    for forbidden in ("traceback", "sqlite", "select", "boom", "window_title", "clipboard", "note", "secret"):
        assert forbidden not in lowered


def test_set_project_enabled_for_rules_does_not_call_keyword_or_folder_apis(monkeypatch):
    forbidden_calls: list = []

    def make_forbidden(name: str):
        def _fail(*args, **kwargs):
            forbidden_calls.append(name)
            raise AssertionError(name + " must not be called by project toggle path")
        return _fail

    for name in (
        "create_project_keyword_rule", "delete_project_keyword_rule", "update_project_keyword_rule",
        "create_project_folder_rule", "update_project_folder_rule", "delete_project_folder_rule",
        "set_project_rule_enabled",
    ):
        monkeypatch.setattr(bridge_rules_module.rule_api, name, make_forbidden(name), raising=False)
    monkeypatch.setattr(
        bridge_rules_module.project_api, "set_project_enabled_for_rules",
        lambda project_id, enabled: {"ok": True, "project": dict(_PROJECT_LIFECYCLE_SUMMARY)},
    )
    build_test_bridge().set_project_enabled_for_rules(1, False)
    assert forbidden_calls == []


def test_archive_project_for_rules_success_narrow_payload(monkeypatch):
    calls = _patch_project_api(
        monkeypatch, "archive_project_for_rules",
        {"ok": True, "project": dict(_PROJECT_LIFECYCLE_SUMMARY)},
    )
    result = build_test_bridge().archive_project_for_rules(1)
    assert result == {"ok": True, "project": _PROJECT_LIFECYCLE_SUMMARY}
    assert calls == [((1,), {})]
    json.dumps(result, ensure_ascii=False)


def test_archive_project_for_rules_rejects_bool_as_int_project_id(monkeypatch):
    forwarded: list = []

    def _spy(*args, **kwargs):
        forwarded.append(args)
        return {"ok": True, "project": dict(_PROJECT_LIFECYCLE_SUMMARY)}

    monkeypatch.setattr(bridge_rules_module.project_api, "archive_project_for_rules", _spy)
    bridge = build_test_bridge()
    for bad_id in (True, False):
        assert bridge.archive_project_for_rules(bad_id) == {"ok": False, "error": "操作无效"}
    assert forwarded == []


def test_archive_project_for_rules_rejects_non_int_or_non_positive_project_id():
    bridge = build_test_bridge()
    for bad_id in (None, "1", 1.0, 1.5, [], {}, b"1", 0, -1):
        assert bridge.archive_project_for_rules(bad_id) == {"ok": False, "error": "操作无效"}


def test_archive_project_for_rules_maps_error_codes_to_chinese(monkeypatch):
    bridge = build_test_bridge()
    for code, expected in (
        ("invalid_input", "操作无效"), ("not_found", "项目不存在"),
        ("system_project", "系统项目不能修改"), ("operation_failed", "归档项目失败"),
        ("unknown_code", "归档项目失败"),
    ):
        monkeypatch.setattr(
            bridge_rules_module.project_api, "archive_project_for_rules",
            lambda project_id, c=code: {"ok": False, "error": c},
        )
        assert bridge.archive_project_for_rules(1) == {"ok": False, "error": expected}


def test_archive_project_for_rules_unknown_exception_collapses(monkeypatch):
    def boom(project_id):
        raise RuntimeError(
            "boom SELECT * FROM activity_log traceback window_title clipboard note C:\\Secret"
        )
    monkeypatch.setattr(bridge_rules_module.project_api, "archive_project_for_rules", boom)
    result = build_test_bridge().archive_project_for_rules(1)
    assert result == {"ok": False, "error": "归档项目失败"}
    lowered = repr(result).lower()
    for forbidden in ("traceback", "sqlite", "select", "boom", "window_title", "clipboard", "note", "secret"):
        assert forbidden not in lowered


def test_archive_project_for_rules_does_not_call_keyword_or_folder_apis(monkeypatch):
    forbidden_calls: list = []

    def make_forbidden(name: str):
        def _fail(*args, **kwargs):
            forbidden_calls.append(name)
            raise AssertionError(name + " must not be called by project archive path")
        return _fail

    for name in (
        "create_project_keyword_rule", "delete_project_keyword_rule", "update_project_keyword_rule",
        "create_project_folder_rule", "update_project_folder_rule", "delete_project_folder_rule",
        "set_project_rule_enabled",
    ):
        monkeypatch.setattr(bridge_rules_module.rule_api, name, make_forbidden(name), raising=False)
    monkeypatch.setattr(
        bridge_rules_module.project_api, "archive_project_for_rules",
        lambda project_id: {"ok": True, "project": dict(_PROJECT_LIFECYCLE_SUMMARY)},
    )
    build_test_bridge().archive_project_for_rules(1)
    assert forbidden_calls == []


def test_lifecycle_methods_never_call_delete_project(monkeypatch):
    forbidden_calls: list = []

    def _fail(*args, **kwargs):
        forbidden_calls.append("delete_project")
        raise AssertionError("delete_project must not be called by lifecycle path")

    assert not hasattr(bridge_rules_module.project_api, "delete_project")
    monkeypatch.setattr(bridge_rules_module.project_api, "delete_project", _fail, raising=False)
    monkeypatch.setattr(
        bridge_rules_module.project_api, "create_project_for_rules",
        lambda name, description="": {"ok": True, "project": dict(_PROJECT_LIFECYCLE_SUMMARY)},
    )
    monkeypatch.setattr(
        bridge_rules_module.project_api, "update_project_for_rules",
        lambda project_id, name, description="": {"ok": True, "project": dict(_PROJECT_LIFECYCLE_SUMMARY)},
    )
    monkeypatch.setattr(
        bridge_rules_module.project_api, "set_project_enabled_for_rules",
        lambda project_id, enabled: {"ok": True, "project": dict(_PROJECT_LIFECYCLE_SUMMARY)},
    )
    monkeypatch.setattr(
        bridge_rules_module.project_api, "archive_project_for_rules",
        lambda project_id: {"ok": True, "project": dict(_PROJECT_LIFECYCLE_SUMMARY)},
    )
    bridge = build_test_bridge()
    bridge.create_project_for_rules("Client", "desc")
    bridge.update_project_for_rules(1, "Renamed", "new")
    bridge.set_project_enabled_for_rules(1, False)
    bridge.archive_project_for_rules(1)
    assert forbidden_calls == []


def test_get_project_rules_payload_includes_display_safe_lifecycle_flags(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.project_api, "list_project_bindings",
        lambda: [
            {
                "id": 1, "name": "Client", "description": "billable", "enabled": 1,
                "created_by": "user", "is_excluded": False, "is_system": False,
                "editable": True, "can_toggle": True, "can_archive": True,
                "folder_rules": [], "keyword_rules": [],
            },
            {
                "id": 2, "name": "排除规则", "description": "命中后匿名记录", "enabled": 0,
                "created_by": "system", "is_excluded": True, "is_system": True,
                "editable": False, "can_toggle": False, "can_archive": False,
                "folder_rules": [], "keyword_rules": [],
            },
        ],
    )
    result = build_test_bridge().get_project_rules()
    client = result["projects"][0]
    assert client["is_system"] is False
    assert client["editable"] is True
    assert client["can_toggle"] is True
    assert client["can_archive"] is True
    assert len(result["projects"]) == 1
    excluded = result["advanced"]["excluded_project"]
    assert excluded["is_system"] is True
    assert excluded["editable"] is False
    assert excluded["can_toggle"] is False
    assert excluded["can_archive"] is False
    json.dumps(result, ensure_ascii=False)


def test_get_project_rules_read_payload_excludes_sensitive_internal_fields(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.project_api, "list_project_bindings",
        lambda: [
            {
                "id": 1, "name": "Client", "description": "billable", "enabled": 1,
                "created_by": "user", "created_at": "2026-06-28T10:00:00",
                "updated_at": "2026-06-28T10:00:00", "folder_rules": [], "keyword_rules": [],
            },
            {
                "id": 2, "name": "排除规则", "description": "命中后匿名记录", "enabled": 0,
                "created_by": "system", "created_at": "2026-06-28T10:00:00",
                "updated_at": "2026-06-28T10:00:00", "folder_rules": [], "keyword_rules": [],
            },
        ],
    )
    result = build_test_bridge().get_project_rules()
    json.dumps(result, ensure_ascii=False)
    lowered = repr(result).lower()
    for forbidden in ("created_by", "created_at", "updated_at", "traceback", "select ", "insert ", "update "):
        assert forbidden not in lowered, f"Project Rules read payload must not leak {forbidden!r}"
    for project in result["projects"]:
        assert "created_by" not in project
        assert "created_at" not in project
        assert "updated_at" not in project
        for flag in ("is_system", "editable", "can_toggle", "can_archive", "is_excluded"):
            assert flag in project, f"missing display-safe flag {flag!r}"
            assert isinstance(project[flag], bool), f"display-safe flag {flag!r} must be bool"


_SENSITIVE_FORBIDDEN_TOKENS = (
    "traceback", "sqlite", "select ", "insert ", "update ", "window_title",
    "file_path_hint", "path_hint", "clipboard", "note", "secret", "details", "C:\\",
)


def _assert_no_sensitive_tokens(result) -> None:
    lowered = repr(result).lower()
    for forbidden in _SENSITIVE_FORBIDDEN_TOKENS:
        assert forbidden not in lowered, f"bridge payload must not leak {forbidden!r}: {result!r}"


def test_preview_project_rule_impact_success_returns_narrow_impact_payload(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.rule_history_api, "preview_project_rule_impact",
        lambda rule_type, rule_id: {
            "ok": True,
            "impact": {
                "rule": {
                    "kind": "folder", "id": rule_id, "enabled": True, "project_id": 5,
                    "project_name": "Client", "target": r"D:\Client",
                },
                "counts": {
                    "matched_count": 3, "eligible_count": 3, "would_update_count": 2,
                    "already_target_count": 1, "manual_skipped_count": 0,
                    "hidden_skipped_count": 0, "deleted_skipped_count": 0,
                    "in_progress_skipped_count": 0, "non_normal_skipped_count": 0,
                },
                "samples": [{
                    "activity_id": 100, "start_time": "2026-06-28 09:00:00",
                    "end_time": "2026-06-28 10:00:00", "duration_seconds": 3600,
                    "resource_name": "report.docx", "current_project_name": "未归类",
                    "target_project_name": "Client", "match_source": "folder_rule",
                }],
            },
            "projects": [{"id": 1, "name": "should not leak"}],
            "traceback": "SELECT * FROM activity_log",
        },
    )
    result = build_test_bridge().preview_project_rule_impact("folder", 10)
    assert result["ok"] is True
    assert "impact" in result
    assert "projects" not in result
    assert "traceback" not in result
    impact = result["impact"]
    assert impact["rule"]["kind"] == "folder"
    assert impact["rule"]["id"] == 10
    assert impact["counts"]["would_update_count"] == 2
    assert len(impact["samples"]) == 1
    assert impact["samples"][0]["activity_id"] == 100
    _assert_no_sensitive_tokens(result)
    json.dumps(result, ensure_ascii=False)


def test_preview_project_rule_impact_invalid_rule_type_does_not_call_api(monkeypatch):
    calls: list[tuple] = []

    def _fail(*args, **kwargs):
        calls.append(args)
        raise AssertionError("preview API must not be called for invalid rule_type")

    monkeypatch.setattr(bridge_rules_module.rule_history_api, "preview_project_rule_impact", _fail)
    for bad_type in (None, 123, True, False, [], {}, "invalid", "Folder", "KEYWORD", ""):
        result = build_test_bridge().preview_project_rule_impact(bad_type, 10)
        assert result == {"ok": False, "error": "操作无效"}, (
            f"expected invalid_input for rule_type={bad_type!r}, got {result!r}"
        )
    assert calls == []


def test_preview_project_rule_impact_invalid_rule_id_does_not_call_api(monkeypatch):
    calls: list[tuple] = []

    def _fail(*args, **kwargs):
        calls.append(args)
        raise AssertionError("preview API must not be called for invalid rule_id")

    monkeypatch.setattr(bridge_rules_module.rule_history_api, "preview_project_rule_impact", _fail)
    for bad_id in (True, False, 0, -1, -100, "10", 10.0, None, [], {}):
        result = build_test_bridge().preview_project_rule_impact("folder", bad_id)
        assert result == {"ok": False, "error": "操作无效"}, (
            f"expected invalid_input for rule_id={bad_id!r}, got {result!r}"
        )
    assert calls == []


def test_preview_project_rule_impact_not_found_maps_to_chinese_message(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.rule_history_api, "preview_project_rule_impact",
        lambda rule_type, rule_id: {
            "ok": False, "error": "not_found",
            "traceback": "SELECT * FROM folder_project_rule WHERE id=999",
            "details": "C:\\Secret window_title clipboard note",
        },
    )
    result = build_test_bridge().preview_project_rule_impact("folder", 999)
    assert result == {"ok": False, "error": "规则不存在"}
    _assert_no_sensitive_tokens(result)


def test_preview_project_rule_impact_operation_failed_maps_to_chinese_message(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.rule_history_api, "preview_project_rule_impact",
        lambda rule_type, rule_id: {"ok": False, "error": "operation_failed", "internal_field": "should not leak"},
    )
    result = build_test_bridge().preview_project_rule_impact("keyword", 25)
    assert result == {"ok": False, "error": "预览规则影响失败"}
    lowered = repr(result).lower()
    for forbidden in ("operation_failed", "internal_field", "should not leak"):
        assert forbidden not in lowered


def test_preview_project_rule_impact_unknown_error_code_collapses_to_generic_message(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.rule_history_api, "preview_project_rule_impact",
        lambda rule_type, rule_id: {"ok": False, "error": "some_new_internal_code", "internal_field": "should not leak"},
    )
    result = build_test_bridge().preview_project_rule_impact("folder", 10)
    assert result == {"ok": False, "error": "预览规则影响失败"}
    lowered = repr(result).lower()
    for forbidden in ("some_new_internal_code", "internal_field", "should not leak"):
        assert forbidden not in lowered


def test_preview_project_rule_impact_unknown_exception_collapses_to_generic_message(monkeypatch):
    def _raise(*args, **kwargs):
        raise RuntimeError("C:\\Secret window_title clipboard note SELECT * FROM")
    monkeypatch.setattr(bridge_rules_module.rule_history_api, "preview_project_rule_impact", _raise)
    result = build_test_bridge().preview_project_rule_impact("folder", 10)
    assert result == {"ok": False, "error": "预览规则影响失败"}
    _assert_no_sensitive_tokens(result)


def test_backfill_project_rule_success_returns_narrow_result_payload(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.rule_history_api, "backfill_project_rule",
        lambda rule_type, rule_id: {
            "ok": True,
            "result": {
                "rule": {
                    "kind": "keyword", "id": rule_id, "enabled": True, "project_id": 7,
                    "project_name": "Marketing", "target": "campaign",
                },
                "updated_count": 5, "matched_count": 8, "eligible_count": 8,
                "would_update_count": 5, "already_target_count": 3,
                "manual_skipped_count": 0, "hidden_skipped_count": 0,
                "deleted_skipped_count": 0, "in_progress_skipped_count": 0,
                "non_normal_skipped_count": 0, "too_many_matches": False,
            },
            "projects": [{"id": 1, "name": "should not leak"}],
            "traceback": "UPDATE activity_log SET project_id=7",
        },
    )
    result = build_test_bridge().backfill_project_rule("keyword", 25)
    assert result["ok"] is True
    assert "result" in result
    assert "projects" not in result
    assert "traceback" not in result
    backfill = result["result"]
    assert backfill["updated_count"] == 5
    assert backfill["rule"]["kind"] == "keyword"
    _assert_no_sensitive_tokens(result)
    json.dumps(result, ensure_ascii=False)


def test_backfill_project_rule_invalid_rule_type_does_not_call_api(monkeypatch):
    calls: list[tuple] = []

    def _fail(*args, **kwargs):
        calls.append(args)
        raise AssertionError("backfill API must not be called for invalid rule_type")

    monkeypatch.setattr(bridge_rules_module.rule_history_api, "backfill_project_rule", _fail)
    for bad_type in (None, 123, True, False, [], {}, "invalid", "Folder", ""):
        result = build_test_bridge().backfill_project_rule(bad_type, 10)
        assert result == {"ok": False, "error": "操作无效"}, (
            f"expected invalid_input for rule_type={bad_type!r}, got {result!r}"
        )
    assert calls == []


def test_backfill_project_rule_invalid_rule_id_does_not_call_api(monkeypatch):
    calls: list[tuple] = []

    def _fail(*args, **kwargs):
        calls.append(args)
        raise AssertionError("backfill API must not be called for invalid rule_id")

    monkeypatch.setattr(bridge_rules_module.rule_history_api, "backfill_project_rule", _fail)
    for bad_id in (True, False, 0, -1, "10", 10.0, None, [], {}):
        result = build_test_bridge().backfill_project_rule("keyword", bad_id)
        assert result == {"ok": False, "error": "操作无效"}, (
            f"expected invalid_input for rule_id={bad_id!r}, got {result!r}"
        )
    assert calls == []


def test_backfill_project_rule_not_found_maps_to_chinese_message(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.rule_history_api, "backfill_project_rule",
        lambda rule_type, rule_id: {
            "ok": False, "error": "not_found", "traceback": "SELECT * FROM project_rule WHERE id=999",
            "details": "C:\\Secret clipboard note",
        },
    )
    result = build_test_bridge().backfill_project_rule("keyword", 999)
    assert result == {"ok": False, "error": "规则不存在"}
    _assert_no_sensitive_tokens(result)


def test_backfill_project_rule_rule_disabled_maps_to_chinese_message(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.rule_history_api, "backfill_project_rule",
        lambda rule_type, rule_id: {"ok": False, "error": "rule_disabled", "internal_field": "should not leak"},
    )
    result = build_test_bridge().backfill_project_rule("folder", 10)
    assert result == {"ok": False, "error": "规则未启用，无法应用"}
    lowered = repr(result).lower()
    for forbidden in ("rule_disabled", "internal_field", "should not leak"):
        assert forbidden not in lowered


def test_backfill_project_rule_project_not_available_maps_to_chinese_message(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.rule_history_api, "backfill_project_rule",
        lambda rule_type, rule_id: {"ok": False, "error": "project_not_available", "internal_field": "should not leak"},
    )
    result = build_test_bridge().backfill_project_rule("keyword", 25)
    assert result == {"ok": False, "error": "目标项目不可用"}
    lowered = repr(result).lower()
    for forbidden in ("project_not_available", "internal_field", "should not leak"):
        assert forbidden not in lowered


def test_backfill_project_rule_too_many_matches_maps_to_chinese_message(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.rule_history_api, "backfill_project_rule",
        lambda rule_type, rule_id: {"ok": False, "error": "too_many_matches", "internal_field": "should not leak"},
    )
    result = build_test_bridge().backfill_project_rule("folder", 10)
    assert result == {"ok": False, "error": "命中记录过多，请先缩小范围"}
    lowered = repr(result).lower()
    for forbidden in ("too_many_matches", "internal_field", "should not leak"):
        assert forbidden not in lowered


def test_backfill_project_rule_operation_failed_maps_to_chinese_message(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.rule_history_api, "backfill_project_rule",
        lambda rule_type, rule_id: {"ok": False, "error": "operation_failed", "internal_field": "should not leak"},
    )
    result = build_test_bridge().backfill_project_rule("keyword", 25)
    assert result == {"ok": False, "error": "应用规则失败"}
    lowered = repr(result).lower()
    for forbidden in ("operation_failed", "internal_field", "should not leak"):
        assert forbidden not in lowered


def test_backfill_project_rule_unknown_error_code_collapses_to_generic_message(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.rule_history_api, "backfill_project_rule",
        lambda rule_type, rule_id: {"ok": False, "error": "some_new_internal_code", "internal_field": "should not leak"},
    )
    result = build_test_bridge().backfill_project_rule("folder", 10)
    assert result == {"ok": False, "error": "应用规则失败"}
    lowered = repr(result).lower()
    for forbidden in ("some_new_internal_code", "internal_field", "should not leak"):
        assert forbidden not in lowered


def test_backfill_project_rule_unknown_exception_collapses_to_generic_message(monkeypatch):
    def _raise(*args, **kwargs):
        raise RuntimeError("C:\\Secret window_title clipboard note UPDATE activity_log")
    monkeypatch.setattr(bridge_rules_module.rule_history_api, "backfill_project_rule", _raise)
    result = build_test_bridge().backfill_project_rule("folder", 10)
    assert result == {"ok": False, "error": "应用规则失败"}
    _assert_no_sensitive_tokens(result)


def test_preview_and_backfill_do_not_cross_call_other_project_rules_apis(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.rule_history_api, "preview_project_rule_impact",
        lambda rule_type, rule_id: {"ok": True, "impact": {"rule": {}, "counts": {}, "samples": []}},
    )
    monkeypatch.setattr(
        bridge_rules_module.rule_history_api, "backfill_project_rule",
        lambda rule_type, rule_id: {"ok": True, "result": {"updated_count": 0}},
    )
    forbidden_calls: list[str] = []

    def make_forbidden(name: str):
        def _fail(*args, **kwargs):
            forbidden_calls.append(name)
            raise AssertionError(name + " must not be called by single-rule operation paths")
        return _fail

    for name in (
        "set_project_rule_enabled", "create_keyword_rule", "create_or_update_folder_rule",
        "set_keyword_rule_enabled", "set_folder_rule_enabled", "delete_keyword_rule",
        "delete_folder_rule", "preview_folder_rule_conflicts",
    ):
        monkeypatch.setattr(bridge_rules_module.rule_api, name, make_forbidden(name), raising=False)
    for name in ("create_project", "update_project", "delete_project", "archive_project", "set_project_enabled"):
        if hasattr(bridge_rules_module.project_api, name):
            monkeypatch.setattr(bridge_rules_module.project_api, name, make_forbidden(name))
    result = build_test_bridge().preview_project_rule_impact("folder", 10)
    assert result["ok"] is True
    result = build_test_bridge().backfill_project_rule("keyword", 25)
    assert result["ok"] is True
    assert forbidden_calls == []


def test_preview_and_backfill_payloads_are_json_serializable(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.rule_history_api, "preview_project_rule_impact",
        lambda rule_type, rule_id: {
            "ok": True,
            "impact": {
                "rule": {"kind": "folder", "id": rule_id, "enabled": True, "project_id": 1, "project_name": "P", "target": "D:\\X"},
                "counts": {
                    "matched_count": 0, "eligible_count": 0, "would_update_count": 0,
                    "already_target_count": 0, "manual_skipped_count": 0,
                    "hidden_skipped_count": 0, "deleted_skipped_count": 0,
                    "in_progress_skipped_count": 0, "non_normal_skipped_count": 0,
                },
                "samples": [],
            },
        },
    )
    monkeypatch.setattr(
        bridge_rules_module.rule_history_api, "backfill_project_rule",
        lambda rule_type, rule_id: {
            "ok": True,
            "result": {
                "rule": {"kind": "keyword", "id": rule_id, "enabled": True, "project_id": 1, "project_name": "P", "target": "kw"},
                "updated_count": 0, "matched_count": 0, "eligible_count": 0,
                "would_update_count": 0, "already_target_count": 0,
                "manual_skipped_count": 0, "hidden_skipped_count": 0,
                "deleted_skipped_count": 0, "in_progress_skipped_count": 0,
                "non_normal_skipped_count": 0, "too_many_matches": False,
            },
        },
    )
    preview = build_test_bridge().preview_project_rule_impact("folder", 10)
    backfill = build_test_bridge().backfill_project_rule("keyword", 25)
    json.dumps(preview, ensure_ascii=False)
    json.dumps(backfill, ensure_ascii=False)
    assert preview["ok"] is True
    assert backfill["ok"] is True


def test_bridge_rules_5h_message_maps_are_stable_chinese():
    from worktrace.webview_ui.project_rules_presenter import (
        _PROJECT_RULE_BACKFILL_MESSAGES,
        _PROJECT_RULE_IMPACT_PREVIEW_MESSAGES,
    )
    assert _PROJECT_RULE_IMPACT_PREVIEW_MESSAGES["invalid_input"] == "操作无效"
    assert _PROJECT_RULE_IMPACT_PREVIEW_MESSAGES["not_found"] == "规则不存在"
    assert _PROJECT_RULE_IMPACT_PREVIEW_MESSAGES["operation_failed"] == "预览规则影响失败"
    assert _PROJECT_RULE_BACKFILL_MESSAGES["invalid_input"] == "操作无效"
    assert _PROJECT_RULE_BACKFILL_MESSAGES["not_found"] == "规则不存在"
    assert _PROJECT_RULE_BACKFILL_MESSAGES["rule_disabled"] == "规则未启用，无法应用"
    assert _PROJECT_RULE_BACKFILL_MESSAGES["project_not_available"] == "目标项目不可用"
    assert _PROJECT_RULE_BACKFILL_MESSAGES["too_many_matches"] == "命中记录过多，请先缩小范围"
    assert _PROJECT_RULE_BACKFILL_MESSAGES["operation_failed"] == "应用规则失败"


def test_preview_project_rules_batch_impact_success_returns_narrow_payload(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.rule_history_api, "preview_project_rules_batch_impact",
        lambda rules: {
            "ok": True,
            "impact": {
                "rules": [{
                    "kind": "folder", "id": 10, "enabled": True, "project_id": 5,
                    "project_name": "Client", "target": r"D:\Client", "project_available": True,
                    "counts": {"matched_count": 3, "would_update_count": 2},
                }],
                "counts": {"matched_count": 3, "would_update_count": 2},
                "samples": [{
                    "activity_id": 100, "start_time": "2026-06-28 09:00:00",
                    "end_time": "2026-06-28 10:00:00", "duration_seconds": 3600,
                    "resource_name": "report.docx", "current_project_name": "未归类",
                    "target_project_name": "Client", "match_source": "folder_rule",
                }],
            },
            "projects": [{"id": 1, "name": "should not leak"}],
            "traceback": "SELECT * FROM activity_log",
        },
    )
    result = build_test_bridge().preview_project_rules_batch_impact([{"rule_type": "folder", "rule_id": 10}])
    assert result["ok"] is True
    assert "impact" in result
    assert "projects" not in result
    assert "traceback" not in result
    impact = result["impact"]
    assert len(impact["rules"]) == 1
    assert impact["counts"]["would_update_count"] == 2
    assert len(impact["samples"]) == 1
    _assert_no_sensitive_tokens(result)
    json.dumps(result, ensure_ascii=False)


def test_preview_project_rules_batch_impact_invalid_input_does_not_call_api(monkeypatch):
    calls: list[tuple] = []

    def _fail(*args, **kwargs):
        calls.append(args)
        raise AssertionError("batch preview API must not be called for invalid input")

    monkeypatch.setattr(bridge_rules_module.rule_history_api, "preview_project_rules_batch_impact", _fail)
    bad_inputs = [
        "not a list", [], ["not a dict"], [{"rule_type": "unknown", "rule_id": 1}],
        [{"rule_type": "folder", "rule_id": True}], [{"rule_type": "folder", "rule_id": 0}],
        [{"rule_type": "folder", "rule_id": -1}], [{"rule_type": "folder", "rule_id": "1"}],
        [{"rule_type": "folder"}], [{"rule_id": 1}], [None],
    ]
    for bad in bad_inputs:
        result = build_test_bridge().preview_project_rules_batch_impact(bad)
        assert result == {"ok": False, "error": "操作无效"}, (
            f"expected invalid_input for {bad!r}, got {result!r}"
        )
    assert calls == []


def test_preview_project_rules_batch_impact_not_found_maps_to_chinese(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.rule_history_api, "preview_project_rules_batch_impact",
        lambda rules: {
            "ok": False, "error": "not_found", "traceback": "SELECT * FROM folder_project_rule",
            "details": "C:\\Secret window_title clipboard note",
        },
    )
    result = build_test_bridge().preview_project_rules_batch_impact([{"rule_type": "folder", "rule_id": 999}])
    assert result == {"ok": False, "error": "规则不存在"}
    _assert_no_sensitive_tokens(result)


def test_preview_project_rules_batch_impact_too_many_rules_maps_to_chinese(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.rule_history_api, "preview_project_rules_batch_impact",
        lambda rules: {"ok": False, "error": "too_many_rules"},
    )
    result = build_test_bridge().preview_project_rules_batch_impact(
        [{"rule_type": "folder", "rule_id": i} for i in range(1, 22)]
    )
    assert result == {"ok": False, "error": "选择的规则过多"}


def test_preview_project_rules_batch_impact_operation_failed_maps_to_chinese(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.rule_history_api, "preview_project_rules_batch_impact",
        lambda rules: {"ok": False, "error": "operation_failed"},
    )
    result = build_test_bridge().preview_project_rules_batch_impact([{"rule_type": "folder", "rule_id": 1}])
    assert result == {"ok": False, "error": "批量预览失败"}


def test_preview_project_rules_batch_impact_unknown_error_code_collapses(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.rule_history_api, "preview_project_rules_batch_impact",
        lambda rules: {"ok": False, "error": "some_new_unknown_code"},
    )
    result = build_test_bridge().preview_project_rules_batch_impact([{"rule_type": "folder", "rule_id": 1}])
    assert result == {"ok": False, "error": "批量预览失败"}


def test_preview_project_rules_batch_impact_exception_collapses(monkeypatch):
    def _raise(*args, **kwargs):
        raise RuntimeError("C:\\Secret window_title clipboard note SELECT * FROM")
    monkeypatch.setattr(bridge_rules_module.rule_history_api, "preview_project_rules_batch_impact", _raise)
    result = build_test_bridge().preview_project_rules_batch_impact([{"rule_type": "folder", "rule_id": 1}])
    assert result == {"ok": False, "error": "批量预览失败"}
    _assert_no_sensitive_tokens(result)


def test_backfill_project_rules_batch_success_returns_narrow_payload(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.rule_history_api, "backfill_project_rules_batch",
        lambda rules: {
            "ok": True,
            "result": {
                "rules": [{
                    "rule": {"kind": "folder", "id": 10, "enabled": True, "project_id": 5, "project_name": "Client", "target": r"D:\Client"},
                    "counts": {"updated_count": 2, "collision_skipped_count": 0},
                }],
                "counts": {"updated_count": 2, "collision_skipped_count": 0},
                "too_many_matches": False,
            },
            "projects": [{"id": 1, "name": "should not leak"}],
            "traceback": "SELECT * FROM activity_log",
        },
    )
    result = build_test_bridge().backfill_project_rules_batch([{"rule_type": "folder", "rule_id": 10}])
    assert result["ok"] is True
    assert "result" in result
    assert "projects" not in result
    assert "traceback" not in result
    assert result["result"]["counts"]["updated_count"] == 2
    _assert_no_sensitive_tokens(result)
    json.dumps(result, ensure_ascii=False)


def test_backfill_project_rules_batch_invalid_input_does_not_call_api(monkeypatch):
    calls: list[tuple] = []

    def _fail(*args, **kwargs):
        calls.append(args)
        raise AssertionError("batch apply API must not be called for invalid input")

    monkeypatch.setattr(bridge_rules_module.rule_history_api, "backfill_project_rules_batch", _fail)
    for bad in ("not a list", [], [None], [{"rule_type": "folder", "rule_id": True}]):
        result = build_test_bridge().backfill_project_rules_batch(bad)
        assert result == {"ok": False, "error": "操作无效"}
    assert calls == []


def test_backfill_project_rules_batch_not_found_maps_to_chinese(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.rule_history_api, "backfill_project_rules_batch",
        lambda rules: {"ok": False, "error": "not_found"},
    )
    result = build_test_bridge().backfill_project_rules_batch([{"rule_type": "folder", "rule_id": 999}])
    assert result == {"ok": False, "error": "规则不存在"}


def test_backfill_project_rules_batch_too_many_rules_maps_to_chinese(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.rule_history_api, "backfill_project_rules_batch",
        lambda rules: {"ok": False, "error": "too_many_rules"},
    )
    result = build_test_bridge().backfill_project_rules_batch(
        [{"rule_type": "folder", "rule_id": i} for i in range(1, 22)]
    )
    assert result == {"ok": False, "error": "选择的规则过多"}


def test_backfill_project_rules_batch_rule_disabled_maps_to_chinese(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.rule_history_api, "backfill_project_rules_batch",
        lambda rules: {"ok": False, "error": "rule_disabled"},
    )
    result = build_test_bridge().backfill_project_rules_batch([{"rule_type": "folder", "rule_id": 1}])
    assert result == {"ok": False, "error": "存在未启用规则，无法应用"}


def test_backfill_project_rules_batch_project_not_available_maps_to_chinese(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.rule_history_api, "backfill_project_rules_batch",
        lambda rules: {"ok": False, "error": "project_not_available"},
    )
    result = build_test_bridge().backfill_project_rules_batch([{"rule_type": "folder", "rule_id": 1}])
    assert result == {"ok": False, "error": "存在目标项目不可用的规则"}


def test_backfill_project_rules_batch_too_many_matches_maps_to_chinese(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.rule_history_api, "backfill_project_rules_batch",
        lambda rules: {"ok": False, "error": "too_many_matches"},
    )
    result = build_test_bridge().backfill_project_rules_batch([{"rule_type": "folder", "rule_id": 1}])
    assert result == {"ok": False, "error": "命中记录过多，请先缩小范围"}


def test_backfill_project_rules_batch_operation_failed_maps_to_chinese(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.rule_history_api, "backfill_project_rules_batch",
        lambda rules: {"ok": False, "error": "operation_failed"},
    )
    result = build_test_bridge().backfill_project_rules_batch([{"rule_type": "folder", "rule_id": 1}])
    assert result == {"ok": False, "error": "批量应用失败"}


def test_backfill_project_rules_batch_unknown_error_code_collapses(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.rule_history_api, "backfill_project_rules_batch",
        lambda rules: {"ok": False, "error": "some_new_unknown_code"},
    )
    result = build_test_bridge().backfill_project_rules_batch([{"rule_type": "folder", "rule_id": 1}])
    assert result == {"ok": False, "error": "批量应用失败"}


def test_backfill_project_rules_batch_exception_collapses(monkeypatch):
    def _raise(*args, **kwargs):
        raise RuntimeError("C:\\Secret window_title clipboard note SELECT * FROM")
    monkeypatch.setattr(bridge_rules_module.rule_history_api, "backfill_project_rules_batch", _raise)
    result = build_test_bridge().backfill_project_rules_batch([{"rule_type": "folder", "rule_id": 1}])
    assert result == {"ok": False, "error": "批量应用失败"}
    _assert_no_sensitive_tokens(result)


def test_set_project_rules_batch_enabled_success_returns_narrow_payload(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.rule_history_api, "set_project_rules_batch_enabled",
        lambda rules, enabled: {
            "ok": True,
            "result": {
                "rules": [{"kind": "folder", "id": 10, "enabled": True, "project_id": 5, "project_name": "Client", "target": r"D:\Client"}],
                "enabled": True, "count": 1,
            },
            "projects": [{"id": 1, "name": "should not leak"}],
            "traceback": "SELECT * FROM folder_project_rule",
        },
    )
    result = build_test_bridge().set_project_rules_batch_enabled([{"rule_type": "folder", "rule_id": 10}], True)
    assert result["ok"] is True
    assert "result" in result
    assert "projects" not in result
    assert "traceback" not in result
    assert result["result"]["enabled"] is True
    assert result["result"]["count"] == 1
    _assert_no_sensitive_tokens(result)
    json.dumps(result, ensure_ascii=False)


def test_set_project_rules_batch_enabled_invalid_input_does_not_call_api(monkeypatch):
    calls: list[tuple] = []

    def _fail(*args, **kwargs):
        calls.append(args)
        raise AssertionError("batch toggle API must not be called for invalid input")

    monkeypatch.setattr(bridge_rules_module.rule_history_api, "set_project_rules_batch_enabled", _fail)
    for bad in ("not a list", [], [None], [{"rule_type": "folder", "rule_id": True}]):
        result = build_test_bridge().set_project_rules_batch_enabled(bad, True)
        assert result == {"ok": False, "error": "操作无效"}
    valid_rules = [{"rule_type": "folder", "rule_id": 1}]
    for bad_enabled in (1, 0, "true", None, []):
        result = build_test_bridge().set_project_rules_batch_enabled(valid_rules, bad_enabled)
        assert result == {"ok": False, "error": "操作无效"}
    assert calls == []


def test_set_project_rules_batch_enabled_not_found_maps_to_chinese(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.rule_history_api, "set_project_rules_batch_enabled",
        lambda rules, enabled: {"ok": False, "error": "not_found"},
    )
    result = build_test_bridge().set_project_rules_batch_enabled([{"rule_type": "folder", "rule_id": 999}], True)
    assert result == {"ok": False, "error": "规则不存在"}


def test_set_project_rules_batch_enabled_too_many_rules_maps_to_chinese(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.rule_history_api, "set_project_rules_batch_enabled",
        lambda rules, enabled: {"ok": False, "error": "too_many_rules"},
    )
    result = build_test_bridge().set_project_rules_batch_enabled(
        [{"rule_type": "folder", "rule_id": i} for i in range(1, 22)], True
    )
    assert result == {"ok": False, "error": "选择的规则过多"}


def test_set_project_rules_batch_enabled_operation_failed_maps_to_chinese(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.rule_history_api, "set_project_rules_batch_enabled",
        lambda rules, enabled: {"ok": False, "error": "operation_failed"},
    )
    result = build_test_bridge().set_project_rules_batch_enabled([{"rule_type": "folder", "rule_id": 1}], True)
    assert result == {"ok": False, "error": "批量操作失败"}


def test_set_project_rules_batch_enabled_unknown_error_code_collapses(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.rule_history_api, "set_project_rules_batch_enabled",
        lambda rules, enabled: {"ok": False, "error": "some_new_unknown_code"},
    )
    result = build_test_bridge().set_project_rules_batch_enabled([{"rule_type": "folder", "rule_id": 1}], True)
    assert result == {"ok": False, "error": "批量操作失败"}


def test_set_project_rules_batch_enabled_exception_collapses(monkeypatch):
    def _raise(*args, **kwargs):
        raise RuntimeError("C:\\Secret window_title clipboard note SELECT * FROM")
    monkeypatch.setattr(bridge_rules_module.rule_history_api, "set_project_rules_batch_enabled", _raise)
    result = build_test_bridge().set_project_rules_batch_enabled([{"rule_type": "folder", "rule_id": 1}], True)
    assert result == {"ok": False, "error": "批量操作失败"}
    _assert_no_sensitive_tokens(result)


def test_automatic_rules_status_success_returns_narrow_payload(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.rule_history_api, "automatic_rules_status",
        lambda: {
            "ok": True,
            "status": {
                "supported": True, "scope": "enabled_folder_keyword_rules",
                "priority": "folder_before_keyword", "confidence": {"folder_rule": 85, "keyword_rule": 80},
            },
            "projects": [{"id": 1, "name": "should not leak"}],
            "traceback": "SELECT * FROM project",
        },
    )
    result = build_test_bridge().automatic_rules_status()
    assert result["ok"] is True
    assert "status" in result
    assert "projects" not in result
    assert "traceback" not in result
    assert result["status"]["supported"] is True
    _assert_no_sensitive_tokens(result)
    json.dumps(result, ensure_ascii=False)


def test_automatic_rules_status_exception_collapses(monkeypatch):
    def _raise(*args, **kwargs):
        raise RuntimeError("C:\\Secret window_title clipboard note SELECT * FROM")
    monkeypatch.setattr(bridge_rules_module.rule_history_api, "automatic_rules_status", _raise)
    result = build_test_bridge().automatic_rules_status()
    assert result == {"ok": False, "error": "加载自动规则状态失败"}
    _assert_no_sensitive_tokens(result)


def test_batch_bridge_methods_do_not_cross_call_other_apis(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.rule_history_api, "preview_project_rules_batch_impact",
        lambda rules: {"ok": True, "impact": {"rules": [], "counts": {}, "samples": []}},
    )
    monkeypatch.setattr(
        bridge_rules_module.rule_history_api, "backfill_project_rules_batch",
        lambda rules: {"ok": True, "result": {"rules": [], "counts": {"updated_count": 0}}},
    )
    monkeypatch.setattr(
        bridge_rules_module.rule_history_api, "set_project_rules_batch_enabled",
        lambda rules, enabled: {"ok": True, "result": {"rules": [], "enabled": True, "count": 0}},
    )
    monkeypatch.setattr(
        bridge_rules_module.rule_history_api, "automatic_rules_status",
        lambda: {"ok": True, "status": {"supported": True}},
    )
    forbidden_calls: list[str] = []

    def make_forbidden(name: str):
        def _fail(*args, **kwargs):
            forbidden_calls.append(name)
            raise AssertionError(name + " must not be called by 5I batch paths")
        return _fail

    for name in (
        "set_project_rule_enabled", "create_keyword_rule", "create_or_update_folder_rule",
        "set_keyword_rule_enabled", "set_folder_rule_enabled", "delete_keyword_rule",
        "delete_folder_rule", "preview_folder_rule_conflicts",
    ):
        monkeypatch.setattr(bridge_rules_module.rule_api, name, make_forbidden(name), raising=False)
    for name in ("preview_project_rule_impact", "backfill_project_rule"):
        monkeypatch.setattr(bridge_rules_module.rule_history_api, name, make_forbidden(name))
    valid_rules = [{"rule_type": "folder", "rule_id": 1}]
    assert build_test_bridge().preview_project_rules_batch_impact(valid_rules)["ok"] is True
    assert build_test_bridge().backfill_project_rules_batch(valid_rules)["ok"] is True
    assert build_test_bridge().set_project_rules_batch_enabled(valid_rules, True)["ok"] is True
    assert build_test_bridge().automatic_rules_status()["ok"] is True
    assert forbidden_calls == []


def test_batch_bridge_payloads_are_json_serializable(monkeypatch):
    monkeypatch.setattr(
        bridge_rules_module.rule_history_api, "preview_project_rules_batch_impact",
        lambda rules: {"ok": True, "impact": {"rules": [], "counts": {}, "samples": []}},
    )
    monkeypatch.setattr(
        bridge_rules_module.rule_history_api, "backfill_project_rules_batch",
        lambda rules: {"ok": True, "result": {"rules": [], "counts": {"updated_count": 0}}},
    )
    monkeypatch.setattr(
        bridge_rules_module.rule_history_api, "set_project_rules_batch_enabled",
        lambda rules, enabled: {"ok": True, "result": {"rules": [], "enabled": True, "count": 0}},
    )
    monkeypatch.setattr(
        bridge_rules_module.rule_history_api, "automatic_rules_status",
        lambda: {"ok": True, "status": {"supported": True}},
    )
    valid_rules = [{"rule_type": "folder", "rule_id": 1}]
    preview = build_test_bridge().preview_project_rules_batch_impact(valid_rules)
    apply = build_test_bridge().backfill_project_rules_batch(valid_rules)
    toggle = build_test_bridge().set_project_rules_batch_enabled(valid_rules, True)
    status = build_test_bridge().automatic_rules_status()
    json.dumps(preview, ensure_ascii=False)
    json.dumps(apply, ensure_ascii=False)
    json.dumps(toggle, ensure_ascii=False)
    json.dumps(status, ensure_ascii=False)
    assert preview["ok"] is True
    assert apply["ok"] is True
    assert toggle["ok"] is True
    assert status["ok"] is True


def test_bridge_rules_5i_batch_message_maps_are_stable_chinese():
    from worktrace.webview_ui.project_rules_presenter import (
        _PROJECT_RULE_BATCH_APPLY_MESSAGES,
        _PROJECT_RULE_BATCH_PREVIEW_MESSAGES,
        _PROJECT_RULE_BATCH_TOGGLE_MESSAGES,
    )
    assert _PROJECT_RULE_BATCH_PREVIEW_MESSAGES["invalid_input"] == "操作无效"
    assert _PROJECT_RULE_BATCH_PREVIEW_MESSAGES["not_found"] == "规则不存在"
    assert _PROJECT_RULE_BATCH_PREVIEW_MESSAGES["too_many_rules"] == "选择的规则过多"
    assert _PROJECT_RULE_BATCH_PREVIEW_MESSAGES["operation_failed"] == "批量预览失败"
    assert _PROJECT_RULE_BATCH_APPLY_MESSAGES["invalid_input"] == "操作无效"
    assert _PROJECT_RULE_BATCH_APPLY_MESSAGES["not_found"] == "规则不存在"
    assert _PROJECT_RULE_BATCH_APPLY_MESSAGES["too_many_rules"] == "选择的规则过多"
    assert _PROJECT_RULE_BATCH_APPLY_MESSAGES["rule_disabled"] == "存在未启用规则，无法应用"
    assert _PROJECT_RULE_BATCH_APPLY_MESSAGES["project_not_available"] == "存在目标项目不可用的规则"
    assert _PROJECT_RULE_BATCH_APPLY_MESSAGES["too_many_matches"] == "命中记录过多，请先缩小范围"
    assert _PROJECT_RULE_BATCH_APPLY_MESSAGES["operation_failed"] == "批量应用失败"
    assert _PROJECT_RULE_BATCH_TOGGLE_MESSAGES["invalid_input"] == "操作无效"
    assert _PROJECT_RULE_BATCH_TOGGLE_MESSAGES["not_found"] == "规则不存在"
    assert _PROJECT_RULE_BATCH_TOGGLE_MESSAGES["too_many_rules"] == "选择的规则过多"
    assert _PROJECT_RULE_BATCH_TOGGLE_MESSAGES["operation_failed"] == "批量操作失败"


def test_create_excluded_keyword_rule_success_returns_narrow_payload(monkeypatch):
    captured = {}

    def _fake(keyword):
        captured["keyword"] = keyword
        return {
            "ok": True,
            "rule": {
                "kind": "keyword", "id": 777, "project_id": 99,
                "keyword": keyword, "enabled": True, "internal_field": "should not leak",
            },
        }

    monkeypatch.setattr(bridge_rules_module.rule_api, "create_excluded_keyword_rule_for_webview", _fake)
    result = build_test_bridge().create_excluded_keyword_rule("  排除词  ")
    assert captured["keyword"] == "排除词"
    assert result == {
        "ok": True,
        "rule": {"kind": "keyword", "id": 777, "project_id": 99, "keyword": "排除词", "enabled": True},
    }
    assert "projects" not in result
    assert "rules" not in result
    assert "internal_field" not in result["rule"]
    json.dumps(result, ensure_ascii=False)
    _assert_no_sensitive_tokens(result)


@pytest.mark.parametrize(
    "bad_keyword",
    [None, True, False, 1, 1.0, 2.5, [], {}, b"kw", "", "   ", "\t", "\n", "  \t  "],
)
def test_create_excluded_keyword_rule_rejects_invalid_keyword_does_not_call_api(monkeypatch, bad_keyword):
    called = {"count": 0}

    def _spy(keyword):
        called["count"] += 1
        return {"ok": True, "rule": {}}

    monkeypatch.setattr(bridge_rules_module.rule_api, "create_excluded_keyword_rule_for_webview", _spy)
    result = build_test_bridge().create_excluded_keyword_rule(bad_keyword)
    assert result == {"ok": False, "error": "操作无效"}
    assert called["count"] == 0


def test_create_excluded_keyword_rule_maps_error_codes_to_chinese(monkeypatch):
    cases = [
        ("invalid_input", "操作无效"), ("duplicate_rule", "关键词规则已存在"),
        ("operation_failed", "新增排除关键词规则失败"),
        ("some_new_unknown_code", "新增排除关键词规则失败"),
    ]
    for code, expected in cases:
        monkeypatch.setattr(
            bridge_rules_module.rule_api, "create_excluded_keyword_rule_for_webview",
            lambda keyword, _code=code: {"ok": False, "error": _code, "internal_field": "should not leak"},
        )
        result = build_test_bridge().create_excluded_keyword_rule("kw")
        assert result == {"ok": False, "error": expected}, code
        _assert_no_sensitive_tokens(result)


def test_create_excluded_keyword_rule_exception_collapses(monkeypatch):
    def _raise(*args, **kwargs):
        raise RuntimeError("C:\\Secret window_title clipboard note SELECT * FROM")
    monkeypatch.setattr(bridge_rules_module.rule_api, "create_excluded_keyword_rule_for_webview", _raise)
    result = build_test_bridge().create_excluded_keyword_rule("kw")
    assert result == {"ok": False, "error": "新增排除关键词规则失败"}
    _assert_no_sensitive_tokens(result)


def test_create_excluded_folder_rule_success_returns_narrow_payload(monkeypatch):
    captured = {}

    def _fake(folder_path, recursive):
        captured["folder_path"] = folder_path
        captured["recursive"] = recursive
        return {
            "ok": True,
            "rule": {
                "kind": "folder", "id": 888, "project_id": 99,
                "folder_path": folder_path, "recursive": recursive, "enabled": True,
                "internal_field": "should not leak",
            },
        }

    monkeypatch.setattr(bridge_rules_module.rule_api, "create_excluded_folder_rule_for_webview", _fake)
    result = build_test_bridge().create_excluded_folder_rule("  D:\\Work\\Excluded  ", False)
    assert captured["folder_path"] == r"D:\Work\Excluded"
    assert captured["recursive"] is False
    assert result == {
        "ok": True,
        "rule": {
            "kind": "folder", "id": 888, "project_id": 99,
            "folder_path": r"D:\Work\Excluded", "recursive": False, "enabled": True,
        },
    }
    assert "internal_field" not in result["rule"]
    json.dumps(result, ensure_ascii=False)
    _assert_no_sensitive_tokens(result)


@pytest.mark.parametrize(
    "bad_path,bad_recursive",
    [
        (None, True), (True, True), (False, True), (1, True), (1.5, True), ([], True),
        ({}, True), (b"D:\\X", True), ("", True), ("   ", True), ("\t\n", True),
        ("D:\\Work", None), ("D:\\Work", 1), ("D:\\Work", "yes"),
        ("D:\\Work", []), ("D:\\Work", {}),
    ],
)
def test_create_excluded_folder_rule_rejects_invalid_input_does_not_call_api(monkeypatch, bad_path, bad_recursive):
    called = {"count": 0}

    def _spy(folder_path, recursive):
        called["count"] += 1
        return {"ok": True, "rule": {}}

    monkeypatch.setattr(bridge_rules_module.rule_api, "create_excluded_folder_rule_for_webview", _spy)
    result = build_test_bridge().create_excluded_folder_rule(bad_path, bad_recursive)
    assert result == {"ok": False, "error": "操作无效"}
    assert called["count"] == 0


def test_excluded_rule_bridge_methods_signature_has_no_project_id():
    import inspect
    bridge_type = type(build_test_bridge())
    kw_sig = inspect.signature(bridge_type.create_excluded_keyword_rule)
    assert list(kw_sig.parameters.keys()) == ["self", "keyword"]
    folder_sig = inspect.signature(bridge_type.create_excluded_folder_rule)
    assert list(folder_sig.parameters.keys()) == ["self", "folder_path", "recursive"]
