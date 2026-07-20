from __future__ import annotations

from tests.project_rules_bridge_cases_common import (
    Path,
    _PROJECT_LIFECYCLE_SUMMARY,
    _assert_no_sensitive_tokens,
    _forbidden_rule_api_replacement,
    _patch_project_api,
    bridge_module,
    bridge_rules_module,
    build_test_bridge,
    json,
    presenter_module,
    pytest,
    re,
)

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
