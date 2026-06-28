from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

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


def test_set_project_rule_enabled_keyword_success(monkeypatch):
    monkeypatch.setattr(
        bridge_module.rule_api,
        "set_project_rule_enabled",
        lambda rule_type, rule_id, enabled: {
            "ok": True,
            "rule_type": rule_type,
            "rule_id": rule_id,
            "enabled": enabled,
        },
    )

    assert WebViewBridge().set_project_rule_enabled("keyword", 11, False) == {
        "ok": True,
        "rule_type": "keyword",
        "rule_id": 11,
        "enabled": False,
    }
    assert WebViewBridge().set_project_rule_enabled("keyword", 11, True) == {
        "ok": True,
        "rule_type": "keyword",
        "rule_id": 11,
        "enabled": True,
    }


def test_set_project_rule_enabled_folder_success(monkeypatch):
    monkeypatch.setattr(
        bridge_module.rule_api,
        "set_project_rule_enabled",
        lambda rule_type, rule_id, enabled: {
            "ok": True,
            "rule_type": rule_type,
            "rule_id": rule_id,
            "enabled": enabled,
        },
    )

    assert WebViewBridge().set_project_rule_enabled("folder", 10, False) == {
        "ok": True,
        "rule_type": "folder",
        "rule_id": 10,
        "enabled": False,
    }
    assert WebViewBridge().set_project_rule_enabled("folder", 10, True) == {
        "ok": True,
        "rule_type": "folder",
        "rule_id": 10,
        "enabled": True,
    }


def test_set_project_rule_enabled_rejects_invalid_bridge_input():
    bridge = WebViewBridge()

    assert bridge.set_project_rule_enabled("project", 1, True) == {
        "ok": False,
        "error": "操作无效",
    }
    for bad_id in (None, True, False, "1", 0, -1, 1.0):
        assert bridge.set_project_rule_enabled("keyword", bad_id, True) == {
            "ok": False,
            "error": "操作无效",
        }
    for bad_enabled in (None, 0, 1, "true", "false"):
        assert bridge.set_project_rule_enabled("keyword", 1, bad_enabled) == {
            "ok": False,
            "error": "操作无效",
        }


@pytest.mark.parametrize(
    "bad_rule_type",
    [
        None,
        "",
        "project",
        "folder_rule",
        "keyword_rule",
        "Folder",
        "KEYWORD",
        "PROJECT",
        "folders",
        "keywords",
        "unknown",
        1,
        1.0,
        True,
        [],
        {},
    ],
)
def test_set_project_rule_enabled_rejects_invalid_rule_type_variants(bad_rule_type):
    # Phase 5B.1 regression lock: non-string types (including unhashable
    # list / dict) collapse to ``操作无效`` at the bridge layer without
    # leaking a TypeError or being misreported as ``更新规则状态失败``.
    assert WebViewBridge().set_project_rule_enabled(bad_rule_type, 1, True) == {
        "ok": False,
        "error": "操作无效",
    }


@pytest.mark.parametrize("bad_id", ["abc", "1.5", 2.5, 0.5, -999, [], {}])
def test_set_project_rule_enabled_rejects_invalid_id_extra_variants(bad_id):
    # Phase 5B.1 regression lock: numeric strings, arbitrary floats, deep
    # negatives, and container types all collapse to ``操作无效``.
    assert WebViewBridge().set_project_rule_enabled("folder", bad_id, True) == {
        "ok": False,
        "error": "操作无效",
    }


@pytest.mark.parametrize("bad_enabled", ["1", "0", "True", "False", 1.0, 0.0, [], {}])
def test_set_project_rule_enabled_rejects_invalid_enabled_extra_variants(bad_enabled):
    # Phase 5B.1 regression lock: ``enabled`` must be a real ``bool`` at the
    # bridge layer. Numeric strings, mixed-case bool strings, floats, and
    # container types all collapse to ``操作无效``.
    assert WebViewBridge().set_project_rule_enabled("keyword", 1, bad_enabled) == {
        "ok": False,
        "error": "操作无效",
    }


def test_set_project_rule_enabled_invalid_input_payload_excludes_sensitive_text():
    # Phase 5B.1 regression lock: failure payloads for invalid input never
    # carry traceback / SQL / path / note / clipboard / window_title text
    # even when the bridge has access to rich exception context.
    bridge = WebViewBridge()
    for args in (
        ("project", 1, True),
        (None, 1, True),
        ([], 1, True),
        ({}, 1, True),
        ("keyword", [], True),
        ("keyword", {}, True),
        ("keyword", 1, "true"),
        ("keyword", 1, []),
        ("keyword", 1, {}),
    ):
        result = bridge.set_project_rule_enabled(*args)
        assert result == {"ok": False, "error": "操作无效"}
        lowered = repr(result).lower()
        for forbidden in (
            "traceback",
            "sqlite",
            "select",
            "window_title",
            "clipboard",
            "note",
            "secret",
        ):
            assert forbidden not in lowered


def test_set_project_rule_enabled_success_payload_does_not_return_full_project_list(monkeypatch):
    # Phase 5B.1 regression lock: the toggle success payload is intentionally
    # narrow (``rule_type`` / ``rule_id`` / ``enabled`` only). It must never
    # echo the full refreshed Project Rules list back to JS — the frontend
    # re-fetches via ``get_project_rules`` after success.
    monkeypatch.setattr(
        bridge_module.rule_api,
        "set_project_rule_enabled",
        lambda rule_type, rule_id, enabled: {
            "ok": True,
            "rule_type": rule_type,
            "rule_id": rule_id,
            "enabled": enabled,
            # Defensive: even if the API tried to echo a project list, the
            # bridge must not surface it on the toggle write path.
            "projects": [{"id": 1, "name": "should not leak"}],
        },
    )

    result = WebViewBridge().set_project_rule_enabled("folder", 10, False)

    assert result == {
        "ok": True,
        "rule_type": "folder",
        "rule_id": 10,
        "enabled": False,
    }
    assert "projects" not in result
    assert "rules" not in result


def test_set_project_rule_enabled_never_calls_create_edit_delete_or_project_toggle_apis(monkeypatch):
    # Phase 5B.1 regression lock: the toggle path must only ever call
    # ``rule_api.set_project_rule_enabled``. It must not invoke any of the
    # other Project Rules write APIs (project enable/disable, project /
    # rule create / edit / delete, conflict preview, backfill).
    monkeypatch.setattr(
        bridge_module.rule_api,
        "set_project_rule_enabled",
        lambda rule_type, rule_id, enabled: {
            "ok": True,
            "rule_type": rule_type,
            "rule_id": rule_id,
            "enabled": enabled,
        },
    )

    forbidden_calls: list[str] = []

    def make_forbidden(name: str):
        def _fail(*args, **kwargs):
            forbidden_calls.append(name)
            raise AssertionError(name + " must not be called by toggle path")
        return _fail

    for name in (
        "create_keyword_rule",
        "create_or_update_folder_rule",
        "set_keyword_rule_enabled",
        "set_folder_rule_enabled",
        "delete_keyword_rule",
        "delete_folder_rule",
        "preview_folder_rule_conflicts",
        "backfill_folder_rule",
    ):
        monkeypatch.setattr(bridge_module.rule_api, name, make_forbidden(name))

    forbidden_project_calls: list[str] = []

    def make_project_forbidden(name: str):
        def _fail(*args, **kwargs):
            forbidden_project_calls.append(name)
            raise AssertionError(name + " must not be called by toggle path")
        return _fail

    for name in (
        "create_project",
        "update_project",
        "delete_project",
        "archive_project",
        "set_project_enabled",
    ):
        if hasattr(bridge_module.project_api, name):
            monkeypatch.setattr(bridge_module.project_api, name, make_project_forbidden(name))

    result = WebViewBridge().set_project_rule_enabled("folder", 10, False)
    assert result["ok"] is True
    assert forbidden_calls == []
    assert forbidden_project_calls == []


def test_set_project_rule_enabled_not_found_payload_excludes_sensitive_text(monkeypatch):
    # Phase 5B.1 regression lock: the ``not_found`` failure payload never
    # surfaces SQL / traceback / path / note / clipboard / window_title even
    # when the underlying service raises a verbose exception.
    monkeypatch.setattr(
        bridge_module.rule_api,
        "set_project_rule_enabled",
        lambda rule_type, rule_id, enabled: {
            "ok": False,
            "error": "not_found",
            "traceback": "SELECT * FROM folder_project_rule WHERE id=999",
            "details": "C:\\Secret window_title clipboard note",
        },
    )

    result = WebViewBridge().set_project_rule_enabled("folder", 999, False)

    assert result == {"ok": False, "error": "规则不存在"}
    lowered = repr(result).lower()
    for forbidden in (
        "traceback",
        "sqlite",
        "select",
        "window_title",
        "clipboard",
        "note",
        "secret",
        "details",
    ):
        assert forbidden not in lowered


def test_set_project_rule_enabled_invalid_input_payload_excludes_backend_codes(monkeypatch):
    # Phase 5B.1 regression lock: the ``invalid_input`` failure payload
    # surfaces only the stable Chinese message, not the underlying code or
    # any backend-internal fields the API might have attached.
    monkeypatch.setattr(
        bridge_module.rule_api,
        "set_project_rule_enabled",
        lambda rule_type, rule_id, enabled: {
            "ok": False,
            "error": "invalid_input",
            "code": "invalid_input",
            "internal_field": "should not leak",
        },
    )

    result = WebViewBridge().set_project_rule_enabled("folder", -1, True)

    assert result == {"ok": False, "error": "操作无效"}
    lowered = repr(result).lower()
    for forbidden in ("internal_field", "should not leak", "code", "invalid_input"):
        assert forbidden not in lowered


def test_set_project_rule_enabled_success_payload_types_are_stable(monkeypatch):
    # Phase 5B.1 regression lock: success payload field types must remain
    # ``str`` / ``int`` / ``bool`` so JS consumers can rely on the contract
    # even when the backend returns loose numeric / string variants.
    monkeypatch.setattr(
        bridge_module.rule_api,
        "set_project_rule_enabled",
        lambda rule_type, rule_id, enabled: {
            "ok": True,
            "rule_type": rule_type,
            "rule_id": rule_id,
            "enabled": enabled,
        },
    )

    result = WebViewBridge().set_project_rule_enabled("keyword", 25, True)

    assert isinstance(result["rule_type"], str)
    assert isinstance(result["rule_id"], int)
    assert isinstance(result["enabled"], bool)
    assert type(result["rule_id"]) is int
    assert type(result["enabled"]) is bool


def test_set_project_rule_enabled_get_project_rules_payload_is_unchanged(monkeypatch):
    # Phase 5B.1 regression lock: ``get_project_rules`` remains the read path
    # and is not affected by the toggle hardening. Its payload shape and
    # display-safe projection stay stable.
    monkeypatch.setattr(
        bridge_module.project_api,
        "list_project_bindings",
        lambda: [
            {
                "id": 1,
                "name": "Client",
                "description": "Billable",
                "enabled": 1,
                "created_by": "user",
                "folder_rules": [
                    {"id": 10, "folder_path": "D:\\Client", "enabled": 1, "recursive": 1},
                ],
                "keyword_rules": [
                    {"id": 11, "keyword": "Spec", "enabled": 0},
                ],
            },
        ],
    )

    result = WebViewBridge().get_project_rules()

    assert result["ok"] is True
    project = result["projects"][0]
    assert project["id"] == 1
    assert project["name"] == "Client"
    assert project["rule_count"] == 2
    assert project["folder_rule_count"] == 1
    assert project["keyword_rule_count"] == 1
    json.dumps(result, ensure_ascii=False)


def test_set_project_rule_enabled_not_found(monkeypatch):
    monkeypatch.setattr(
        bridge_module.rule_api,
        "set_project_rule_enabled",
        lambda rule_type, rule_id, enabled: {"ok": False, "error": "not_found"},
    )

    assert WebViewBridge().set_project_rule_enabled("keyword", 999, False) == {
        "ok": False,
        "error": "规则不存在",
    }


def test_set_project_rule_enabled_unknown_api_exception_collapses(monkeypatch):
    def fail(rule_type, rule_id, enabled):
        raise RuntimeError(
            "boom SELECT * FROM activity_log traceback window_title clipboard note C:\\Secret"
        )

    monkeypatch.setattr(bridge_module.rule_api, "set_project_rule_enabled", fail)

    result = WebViewBridge().set_project_rule_enabled("folder", 10, False)

    assert result == {"ok": False, "error": "更新规则状态失败"}
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
        "secret",
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
            bridge_module.rule_api,
            "set_project_rule_enabled",
            lambda rule_type, rule_id, enabled, code=code: {"ok": False, "error": code},
        )
        result = WebViewBridge().set_project_rule_enabled("folder", 10, False)
        assert result == {"ok": False, "error": message}


def test_set_project_rule_enabled_payload_json_serializable(monkeypatch):
    monkeypatch.setattr(
        bridge_module.rule_api,
        "set_project_rule_enabled",
        lambda rule_type, rule_id, enabled: {
            "ok": True,
            "rule_type": rule_type,
            "rule_id": rule_id,
            "enabled": enabled,
        },
    )

    result = WebViewBridge().set_project_rule_enabled("keyword", 20, True)

    json.dumps(result, ensure_ascii=False)
    assert "Traceback" not in repr(result)
    assert "SELECT" not in repr(result)


def test_project_rules_bridge_import_boundary():
    source = Path(bridge_module.__file__).read_text(encoding="utf-8")
    forbidden_patterns = (
        r"^\s*from\s+\.\.services(\s|\.)",
        r"^\s*from\s+\.\.db(\s|\.)",
        r"^\s*from\s+\.\.collector(\s|\.)",
        r"^\s*from\s+\.\.security(\s|\.)",
        r"^\s*from\s+\.\.runtime(\s|\.)",
        r"^\s*from\s+\.\.config(\s|\.)",
        r"^\s*from\s+\.\.ui(\s|\.)",
        r"^\s*from\s+worktrace\.services(\s|\.)",
        r"^\s*from\s+worktrace\.db(\s|\.)",
        r"^\s*from\s+worktrace\.collector(\s|\.)",
        r"^\s*from\s+worktrace\.security(\s|\.)",
        r"^\s*from\s+worktrace\.runtime(\s|\.)",
        r"^\s*from\s+worktrace\.config(\s|\.)",
        r"^\s*from\s+worktrace\.ui(\s|\.)",
        r"^\s*import\s+worktrace\.services(\s|$)",
        r"^\s*import\s+worktrace\.db(\s|$)",
        r"^\s*import\s+worktrace\.collector(\s|$)",
        r"^\s*import\s+worktrace\.security(\s|$)",
        r"^\s*import\s+worktrace\.runtime(\s|$)",
        r"^\s*import\s+worktrace\.config(\s|$)",
        r"^\s*import\s+worktrace\.ui(\s|$)",
    )
    for pattern in forbidden_patterns:
        assert not re.search(pattern, source, re.MULTILINE), (
            "bridge.py must not import forbidden backend/UI module: " + pattern
        )


# --- Phase 5C: Project Rules keyword rule creation foundation ------------


def test_create_project_keyword_rule_success_payload(monkeypatch):
    # Phase 5C regression lock: the success payload is the narrow created-rule
    # summary only (``kind`` / ``id`` / ``project_id`` / ``keyword`` /
    # ``enabled``). It must NOT echo the full refreshed Project Rules list
    # back to JS — the frontend re-fetches via ``get_project_rules`` after
    # success.
    monkeypatch.setattr(
        bridge_module.rule_api,
        "create_project_keyword_rule",
        lambda project_id, keyword: {
            "ok": True,
            "rule": {
                "kind": "keyword",
                "id": 123,
                "project_id": project_id,
                "keyword": keyword.strip(),
                "enabled": True,
            },
        },
    )

    result = WebViewBridge().create_project_keyword_rule(1, "Spec")

    assert result == {
        "ok": True,
        "rule": {
            "kind": "keyword",
            "id": 123,
            "project_id": 1,
            "keyword": "Spec",
            "enabled": True,
        },
    }
    # The narrow payload must not surface a full project list. The frontend
    # refreshes via a separate ``get_project_rules`` call.
    assert "projects" not in result
    assert "rules" not in result


@pytest.mark.parametrize("bad_id", [None, True, False, "1", "abc", 0, -1, 1.0, 2.5, [], {}])
def test_create_project_keyword_rule_rejects_invalid_project_id(bad_id):
    # Phase 5C regression lock: ``project_id`` must be a real positive int.
    # bool / float / numeric string / None / list / dict / zero / negative
    # all collapse to ``操作无效`` at the bridge layer before any API call.
    result = WebViewBridge().create_project_keyword_rule(bad_id, "Spec")
    assert result == {"ok": False, "error": "操作无效"}


@pytest.mark.parametrize(
    "bad_keyword", [None, True, False, 1, 1.0, 2.5, [], {}, ""]
)
def test_create_project_keyword_rule_rejects_invalid_keyword(bad_keyword):
    # Phase 5C regression lock: ``keyword`` must be a real non-empty str.
    result = WebViewBridge().create_project_keyword_rule(1, bad_keyword)
    assert result == {"ok": False, "error": "操作无效"}


@pytest.mark.parametrize("bad_keyword", ["   ", "\t", "\n", "  \t  "])
def test_create_project_keyword_rule_rejects_whitespace_only_keyword(bad_keyword):
    # Phase 5C regression lock: whitespace-only keyword collapses to
    # ``操作无效`` at the bridge layer.
    result = WebViewBridge().create_project_keyword_rule(1, bad_keyword)
    assert result == {"ok": False, "error": "操作无效"}


def test_create_project_keyword_rule_invalid_input_payload_excludes_sensitive_text():
    # Phase 5C regression lock: invalid-input failure payloads never carry
    # traceback / SQL / path / note / clipboard / window_title text even
    # when the bridge has access to rich exception context.
    bridge = WebViewBridge()
    for args in (
        (None, "Spec"),
        (True, "Spec"),
        (False, "Spec"),
        ("1", "Spec"),
        (1.0, "Spec"),
        ([], "Spec"),
        ({}, "Spec"),
        (0, "Spec"),
        (-1, "Spec"),
        (1, None),
        (1, True),
        (1, 1),
        (1, 1.0),
        (1, []),
        (1, {}),
        (1, ""),
        (1, "   "),
    ):
        result = bridge.create_project_keyword_rule(*args)
        assert result == {"ok": False, "error": "操作无效"}
        lowered = repr(result).lower()
        for forbidden in (
            "traceback",
            "sqlite",
            "select",
            "window_title",
            "clipboard",
            "note",
            "secret",
        ):
            assert forbidden not in lowered


def test_create_project_keyword_rule_project_not_found_maps_to_chinese(monkeypatch):
    monkeypatch.setattr(
        bridge_module.rule_api,
        "create_project_keyword_rule",
        lambda project_id, keyword: {"ok": False, "error": "project_not_found"},
    )

    result = WebViewBridge().create_project_keyword_rule(9999, "Spec")

    assert result == {"ok": False, "error": "项目不存在"}


def test_create_project_keyword_rule_duplicate_rule_maps_to_chinese(monkeypatch):
    monkeypatch.setattr(
        bridge_module.rule_api,
        "create_project_keyword_rule",
        lambda project_id, keyword: {"ok": False, "error": "duplicate_rule"},
    )

    result = WebViewBridge().create_project_keyword_rule(1, "Spec")

    assert result == {"ok": False, "error": "关键词规则已存在"}


def test_create_project_keyword_rule_invalid_input_code_maps_to_chinese(monkeypatch):
    monkeypatch.setattr(
        bridge_module.rule_api,
        "create_project_keyword_rule",
        lambda project_id, keyword: {"ok": False, "error": "invalid_input"},
    )

    result = WebViewBridge().create_project_keyword_rule(1, "Spec")

    assert result == {"ok": False, "error": "操作无效"}


def test_create_project_keyword_rule_operation_failed_code_maps_to_chinese(monkeypatch):
    monkeypatch.setattr(
        bridge_module.rule_api,
        "create_project_keyword_rule",
        lambda project_id, keyword: {"ok": False, "error": "operation_failed"},
    )

    result = WebViewBridge().create_project_keyword_rule(1, "Spec")

    assert result == {"ok": False, "error": "新增关键词规则失败"}


def test_create_project_keyword_rule_unknown_error_code_collapses_to_create_failed(monkeypatch):
    # Phase 5C regression lock: unknown API error codes collapse to the
    # generic create-failed message so internal details are never surfaced.
    monkeypatch.setattr(
        bridge_module.rule_api,
        "create_project_keyword_rule",
        lambda project_id, keyword: {"ok": False, "error": "unexpected raw code"},
    )

    result = WebViewBridge().create_project_keyword_rule(1, "Spec")

    assert result == {"ok": False, "error": "新增关键词规则失败"}


def test_create_project_keyword_rule_unknown_exception_collapses(monkeypatch):
    def fail(project_id, keyword):
        raise RuntimeError(
            "boom SELECT * FROM activity_log traceback window_title clipboard note C:\\Secret"
        )

    monkeypatch.setattr(bridge_module.rule_api, "create_project_keyword_rule", fail)

    result = WebViewBridge().create_project_keyword_rule(1, "Spec")

    assert result == {"ok": False, "error": "新增关键词规则失败"}
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
        "secret",
    ):
        assert forbidden not in lowered


def test_create_project_keyword_rule_failure_payload_excludes_backend_codes(monkeypatch):
    # Phase 5C regression lock: the failure payload surfaces only the stable
    # Chinese message, not the underlying code or any backend-internal fields
    # the API might have attached.
    monkeypatch.setattr(
        bridge_module.rule_api,
        "create_project_keyword_rule",
        lambda project_id, keyword: {
            "ok": False,
            "error": "duplicate_rule",
            "code": "duplicate_rule",
            "internal_field": "should not leak",
            "traceback": "SELECT * FROM project_rule",
            "details": "C:\\Secret window_title clipboard note",
        },
    )

    result = WebViewBridge().create_project_keyword_rule(1, "Spec")

    assert result == {"ok": False, "error": "关键词规则已存在"}
    lowered = repr(result).lower()
    for forbidden in (
        "internal_field",
        "should not leak",
        "code",
        "duplicate_rule",
        "traceback",
        "sqlite",
        "select",
        "window_title",
        "clipboard",
        "note",
        "secret",
        "details",
    ):
        assert forbidden not in lowered


def test_create_project_keyword_rule_success_payload_types_are_stable(monkeypatch):
    # Phase 5C regression lock: success payload field types must remain
    # ``str`` / ``int`` / ``bool`` so JS consumers can rely on the contract
    # even when the backend returns loose numeric / string variants.
    monkeypatch.setattr(
        bridge_module.rule_api,
        "create_project_keyword_rule",
        lambda project_id, keyword: {
            "ok": True,
            "rule": {
                "kind": "keyword",
                "id": 25,
                "project_id": project_id,
                "keyword": keyword,
                "enabled": 1,  # backend may return int instead of bool
            },
        },
    )

    result = WebViewBridge().create_project_keyword_rule(7, "Spec")

    assert type(result["ok"]) is bool
    rule = result["rule"]
    assert type(rule["kind"]) is str
    assert type(rule["id"]) is int
    assert type(rule["project_id"]) is int
    assert type(rule["keyword"]) is str
    assert type(rule["enabled"]) is bool


def test_create_project_keyword_rule_payload_json_serializable(monkeypatch):
    monkeypatch.setattr(
        bridge_module.rule_api,
        "create_project_keyword_rule",
        lambda project_id, keyword: {
            "ok": True,
            "rule": {
                "kind": "keyword",
                "id": 20,
                "project_id": project_id,
                "keyword": keyword.strip(),
                "enabled": True,
            },
        },
    )

    result = WebViewBridge().create_project_keyword_rule(1, "Spec")

    json.dumps(result, ensure_ascii=False)
    assert "Traceback" not in repr(result)
    assert "SELECT" not in repr(result)


def test_create_project_keyword_rule_never_calls_other_project_rules_write_apis(monkeypatch):
    # Phase 5C regression lock: the create-keyword path must only ever call
    # ``rule_api.create_project_keyword_rule``. It must not invoke any other
    # Project Rules write APIs (project toggle / create / edit / delete,
    # folder create / edit / delete, rule edit / delete, conflict preview,
    # backfill).
    monkeypatch.setattr(
        bridge_module.rule_api,
        "create_project_keyword_rule",
        lambda project_id, keyword: {
            "ok": True,
            "rule": {
                "kind": "keyword",
                "id": 1,
                "project_id": project_id,
                "keyword": keyword.strip(),
                "enabled": True,
            },
        },
    )

    forbidden_calls: list[str] = []

    def make_forbidden(name: str):
        def _fail(*args, **kwargs):
            forbidden_calls.append(name)
            raise AssertionError(name + " must not be called by create-keyword path")
        return _fail

    for name in (
        "set_project_rule_enabled",
        "create_or_update_folder_rule",
        "set_keyword_rule_enabled",
        "set_folder_rule_enabled",
        "delete_keyword_rule",
        "delete_folder_rule",
        "preview_folder_rule_conflicts",
        "backfill_folder_rule",
    ):
        monkeypatch.setattr(bridge_module.rule_api, name, make_forbidden(name))

    forbidden_project_calls: list[str] = []

    def make_project_forbidden(name: str):
        def _fail(*args, **kwargs):
            forbidden_project_calls.append(name)
            raise AssertionError(name + " must not be called by create-keyword path")
        return _fail

    for name in (
        "create_project",
        "update_project",
        "delete_project",
        "archive_project",
        "set_project_enabled",
    ):
        if hasattr(bridge_module.project_api, name):
            monkeypatch.setattr(bridge_module.project_api, name, make_project_forbidden(name))

    result = WebViewBridge().create_project_keyword_rule(1, "Spec")
    assert result["ok"] is True
    assert forbidden_calls == []
    assert forbidden_project_calls == []


def test_create_project_keyword_rule_does_not_regress_get_project_rules(monkeypatch):
    # Phase 5C regression lock: ``get_project_rules`` remains the read path
    # and is not affected by the keyword-create addition.
    monkeypatch.setattr(
        bridge_module.project_api,
        "list_project_bindings",
        lambda: [
            {
                "id": 1,
                "name": "Client",
                "description": "Billable",
                "enabled": 1,
                "created_by": "user",
                "folder_rules": [
                    {"id": 10, "folder_path": "D:\\Client", "enabled": 1, "recursive": 1},
                ],
                "keyword_rules": [
                    {"id": 11, "keyword": "Spec", "enabled": 0},
                ],
            },
        ],
    )

    result = WebViewBridge().get_project_rules()

    assert result["ok"] is True
    project = result["projects"][0]
    assert project["id"] == 1
    assert project["name"] == "Client"
    assert project["rule_count"] == 2
    json.dumps(result, ensure_ascii=False)


def test_create_project_keyword_rule_does_not_regress_set_project_rule_enabled(monkeypatch):
    # Phase 5C regression lock: the existing Phase 5B toggle path remains
    # intact after the Phase 5C create-keyword addition.
    monkeypatch.setattr(
        bridge_module.rule_api,
        "set_project_rule_enabled",
        lambda rule_type, rule_id, enabled: {
            "ok": True,
            "rule_type": rule_type,
            "rule_id": rule_id,
            "enabled": enabled,
        },
    )

    result = WebViewBridge().set_project_rule_enabled("keyword", 11, False)

    assert result == {
        "ok": True,
        "rule_type": "keyword",
        "rule_id": 11,
        "enabled": False,
    }


# --- Phase 5C.1: keyword creation hardening regression locks -------------


def test_create_project_keyword_rule_bridge_passes_trimmed_keyword_to_api(monkeypatch):
    # Phase 5C.1 regression lock: the bridge must pass the trimmed keyword to
    # the API, not the raw keyword with leading/trailing whitespace. This is
    # a defense-in-depth hardening so the bridge never forwards whitespace
    # even if a future API change drops the trim.
    captured: dict[str, object] = {}

    def capture(project_id, keyword):
        captured["project_id"] = project_id
        captured["keyword"] = keyword
        return {
            "ok": True,
            "rule": {
                "kind": "keyword",
                "id": 42,
                "project_id": project_id,
                "keyword": keyword,
                "enabled": True,
            },
        }

    monkeypatch.setattr(bridge_module.rule_api, "create_project_keyword_rule", capture)

    result = WebViewBridge().create_project_keyword_rule(1, "  Spec  ")

    assert result["ok"] is True
    # The API must receive the trimmed keyword, not "  Spec  ".
    assert captured["keyword"] == "Spec"
    assert captured["project_id"] == 1


def test_create_project_keyword_rule_bridge_html_script_keyword_safe(monkeypatch):
    # Phase 5C.1 regression lock: HTML / script-like content in the keyword
    # must pass through the bridge as ordinary plain text without leaking an
    # exception. The bridge success payload carries the plain-text keyword;
    # frontend rendering is responsible for escaping (locked by the
    # static-contract escape-helper test).
    html_keyword = "<script>alert('xss')</script>"

    monkeypatch.setattr(
        bridge_module.rule_api,
        "create_project_keyword_rule",
        lambda project_id, keyword: {
            "ok": True,
            "rule": {
                "kind": "keyword",
                "id": 99,
                "project_id": project_id,
                "keyword": keyword,
                "enabled": True,
            },
        },
    )

    result = WebViewBridge().create_project_keyword_rule(1, html_keyword)

    assert result["ok"] is True
    assert result["rule"]["keyword"] == html_keyword
    json.dumps(result, ensure_ascii=False)


def test_create_project_keyword_rule_bridge_rejects_tuple_and_set_project_id():
    # Phase 5C.1 regression lock: tuple / set / frozenset project_id values
    # all collapse to ``操作无效`` at the bridge layer.
    for bad_id in ((), (1,), {1, 2}, frozenset({1})):
        result = WebViewBridge().create_project_keyword_rule(bad_id, "Spec")
        assert result == {"ok": False, "error": "操作无效"}


def test_create_project_keyword_rule_bridge_rejects_tuple_and_set_keyword():
    # Phase 5C.1 regression lock: tuple / set / frozenset keyword values all
    # collapse to ``操作无效`` at the bridge layer.
    for bad_keyword in ((), (1,), {1, 2}, frozenset({1})):
        result = WebViewBridge().create_project_keyword_rule(1, bad_keyword)
        assert result == {"ok": False, "error": "操作无效"}


# --- Phase 5D: Project Rules keyword rule deletion foundation ------------


def test_delete_project_keyword_rule_success_payload(monkeypatch):
    # Phase 5D regression lock: the success payload is the narrow
    # deleted-rule summary only (``kind`` / ``id`` / ``deleted``). It must
    # NOT echo the full refreshed Project Rules list back to JS — the
    # frontend re-fetches via ``get_project_rules`` after success.
    monkeypatch.setattr(
        bridge_module.rule_api,
        "delete_project_keyword_rule",
        lambda rule_id: {
            "ok": True,
            "rule": {
                "kind": "keyword",
                "id": rule_id,
                "deleted": True,
            },
        },
    )

    result = WebViewBridge().delete_project_keyword_rule(123)

    assert result == {
        "ok": True,
        "rule": {
            "kind": "keyword",
            "id": 123,
            "deleted": True,
        },
    }
    # The narrow payload must not surface a full project list.
    assert "projects" not in result
    assert "rules" not in result


@pytest.mark.parametrize(
    "bad_id",
    [None, True, False, "1", "abc", 0, -1, 1.0, 2.5, [], {}, (), {1, 2}, (1,), frozenset({1})],
)
def test_delete_project_keyword_rule_rejects_invalid_rule_id(bad_id):
    # Phase 5D regression lock: ``rule_id`` must be a real positive int.
    # bool / float / numeric string / None / list / dict / tuple / set /
    # frozenset / zero / negative all collapse to ``操作无效`` at the bridge
    # layer before any API call.
    result = WebViewBridge().delete_project_keyword_rule(bad_id)
    assert result == {"ok": False, "error": "操作无效"}


def test_delete_project_keyword_rule_invalid_input_payload_excludes_sensitive_text():
    # Phase 5D regression lock: invalid-input failure payloads never carry
    # traceback / SQL / path / note / clipboard / window_title text even
    # when the bridge has access to rich exception context.
    bridge = WebViewBridge()
    for bad_id in (None, True, False, "1", 1.0, [], {}, 0, -1, (), {1, 2}, (1,), frozenset({1})):
        result = bridge.delete_project_keyword_rule(bad_id)
        assert result == {"ok": False, "error": "操作无效"}
        lowered = repr(result).lower()
        for forbidden in (
            "traceback",
            "sqlite",
            "select",
            "window_title",
            "clipboard",
            "note",
            "secret",
        ):
            assert forbidden not in lowered


def test_delete_project_keyword_rule_not_found_maps_to_chinese(monkeypatch):
    monkeypatch.setattr(
        bridge_module.rule_api,
        "delete_project_keyword_rule",
        lambda rule_id: {"ok": False, "error": "not_found"},
    )

    result = WebViewBridge().delete_project_keyword_rule(999)

    assert result == {"ok": False, "error": "关键词规则不存在"}


def test_delete_project_keyword_rule_invalid_input_code_maps_to_chinese(monkeypatch):
    monkeypatch.setattr(
        bridge_module.rule_api,
        "delete_project_keyword_rule",
        lambda rule_id: {"ok": False, "error": "invalid_input"},
    )

    result = WebViewBridge().delete_project_keyword_rule(1)

    assert result == {"ok": False, "error": "操作无效"}


def test_delete_project_keyword_rule_operation_failed_code_maps_to_chinese(monkeypatch):
    monkeypatch.setattr(
        bridge_module.rule_api,
        "delete_project_keyword_rule",
        lambda rule_id: {"ok": False, "error": "operation_failed"},
    )

    result = WebViewBridge().delete_project_keyword_rule(1)

    assert result == {"ok": False, "error": "删除关键词规则失败"}


def test_delete_project_keyword_rule_unknown_error_code_collapses_to_delete_failed(monkeypatch):
    # Phase 5D regression lock: unknown API error codes collapse to the
    # generic delete-failed message so internal details are never surfaced.
    monkeypatch.setattr(
        bridge_module.rule_api,
        "delete_project_keyword_rule",
        lambda rule_id: {"ok": False, "error": "unexpected raw code"},
    )

    result = WebViewBridge().delete_project_keyword_rule(1)

    assert result == {"ok": False, "error": "删除关键词规则失败"}


def test_delete_project_keyword_rule_unknown_exception_collapses(monkeypatch):
    def fail(rule_id):
        raise RuntimeError(
            "boom SELECT * FROM activity_log traceback window_title clipboard note C:\\Secret"
        )

    monkeypatch.setattr(bridge_module.rule_api, "delete_project_keyword_rule", fail)

    result = WebViewBridge().delete_project_keyword_rule(1)

    assert result == {"ok": False, "error": "删除关键词规则失败"}
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
        "secret",
    ):
        assert forbidden not in lowered


def test_delete_project_keyword_rule_failure_payload_excludes_backend_codes(monkeypatch):
    # Phase 5D regression lock: the failure payload surfaces only the stable
    # Chinese message, not the underlying code or any backend-internal fields
    # the API might have attached.
    monkeypatch.setattr(
        bridge_module.rule_api,
        "delete_project_keyword_rule",
        lambda rule_id: {
            "ok": False,
            "error": "not_found",
            "code": "not_found",
            "internal_field": "should not leak",
            "traceback": "SELECT * FROM project_rule",
            "details": "C:\\Secret window_title clipboard note",
        },
    )

    result = WebViewBridge().delete_project_keyword_rule(999)

    assert result == {"ok": False, "error": "关键词规则不存在"}
    lowered = repr(result).lower()
    for forbidden in (
        "internal_field",
        "should not leak",
        "code",
        "not_found",
        "traceback",
        "sqlite",
        "select",
        "window_title",
        "clipboard",
        "note",
        "secret",
        "details",
    ):
        assert forbidden not in lowered


def test_delete_project_keyword_rule_success_payload_types_are_stable(monkeypatch):
    # Phase 5D regression lock: success payload field types must remain
    # ``str`` / ``int`` / ``bool`` so JS consumers can rely on the contract
    # even when the backend returns loose numeric / string variants.
    monkeypatch.setattr(
        bridge_module.rule_api,
        "delete_project_keyword_rule",
        lambda rule_id: {
            "ok": True,
            "rule": {
                "kind": "keyword",
                "id": rule_id,
                "deleted": 1,  # backend may return int instead of bool
            },
        },
    )

    result = WebViewBridge().delete_project_keyword_rule(25)

    assert type(result["ok"]) is bool
    rule = result["rule"]
    assert type(rule["kind"]) is str
    assert type(rule["id"]) is int
    assert type(rule["deleted"]) is bool


def test_delete_project_keyword_rule_payload_json_serializable(monkeypatch):
    monkeypatch.setattr(
        bridge_module.rule_api,
        "delete_project_keyword_rule",
        lambda rule_id: {
            "ok": True,
            "rule": {
                "kind": "keyword",
                "id": rule_id,
                "deleted": True,
            },
        },
    )

    result = WebViewBridge().delete_project_keyword_rule(20)

    json.dumps(result, ensure_ascii=False)
    assert "Traceback" not in repr(result)
    assert "SELECT" not in repr(result)


def test_delete_project_keyword_rule_never_calls_other_project_rules_write_apis(monkeypatch):
    # Phase 5D regression lock: the delete-keyword path must only ever call
    # ``rule_api.delete_project_keyword_rule``. It must not invoke any other
    # Project Rules write APIs (project toggle / create / edit / delete,
    # folder create / edit / delete, rule create / edit / toggle, conflict
    # preview, backfill).
    monkeypatch.setattr(
        bridge_module.rule_api,
        "delete_project_keyword_rule",
        lambda rule_id: {
            "ok": True,
            "rule": {
                "kind": "keyword",
                "id": rule_id,
                "deleted": True,
            },
        },
    )

    forbidden_calls: list[str] = []

    def make_forbidden(name: str):
        def _fail(*args, **kwargs):
            forbidden_calls.append(name)
            raise AssertionError(name + " must not be called by delete-keyword path")
        return _fail

    for name in (
        "create_project_keyword_rule",
        "set_project_rule_enabled",
        "create_or_update_folder_rule",
        "set_keyword_rule_enabled",
        "set_folder_rule_enabled",
        "delete_keyword_rule",
        "delete_folder_rule",
        "preview_folder_rule_conflicts",
        "backfill_folder_rule",
    ):
        monkeypatch.setattr(bridge_module.rule_api, name, make_forbidden(name))

    forbidden_project_calls: list[str] = []

    def make_project_forbidden(name: str):
        def _fail(*args, **kwargs):
            forbidden_project_calls.append(name)
            raise AssertionError(name + " must not be called by delete-keyword path")
        return _fail

    for name in (
        "create_project",
        "update_project",
        "delete_project",
        "archive_project",
        "set_project_enabled",
    ):
        if hasattr(bridge_module.project_api, name):
            monkeypatch.setattr(bridge_module.project_api, name, make_project_forbidden(name))

    result = WebViewBridge().delete_project_keyword_rule(1)
    assert result["ok"] is True
    assert forbidden_calls == []
    assert forbidden_project_calls == []


def test_delete_project_keyword_rule_does_not_regress_get_project_rules(monkeypatch):
    # Phase 5D regression lock: ``get_project_rules`` remains the read path
    # and is not affected by the keyword-delete addition.
    monkeypatch.setattr(
        bridge_module.project_api,
        "list_project_bindings",
        lambda: [
            {
                "id": 1,
                "name": "Client",
                "description": "Billable",
                "enabled": 1,
                "created_by": "user",
                "folder_rules": [
                    {"id": 10, "folder_path": "D:\\Client", "enabled": 1, "recursive": 1},
                ],
                "keyword_rules": [
                    {"id": 11, "keyword": "Spec", "enabled": 0},
                ],
            },
        ],
    )

    result = WebViewBridge().get_project_rules()

    assert result["ok"] is True
    project = result["projects"][0]
    assert project["id"] == 1
    assert project["name"] == "Client"
    assert project["rule_count"] == 2
    json.dumps(result, ensure_ascii=False)


def test_delete_project_keyword_rule_does_not_regress_set_project_rule_enabled(monkeypatch):
    # Phase 5D regression lock: the existing Phase 5B toggle path remains
    # intact after the Phase 5D delete-keyword addition.
    monkeypatch.setattr(
        bridge_module.rule_api,
        "set_project_rule_enabled",
        lambda rule_type, rule_id, enabled: {
            "ok": True,
            "rule_type": rule_type,
            "rule_id": rule_id,
            "enabled": enabled,
        },
    )

    result = WebViewBridge().set_project_rule_enabled("keyword", 11, False)

    assert result == {
        "ok": True,
        "rule_type": "keyword",
        "rule_id": 11,
        "enabled": False,
    }


def test_delete_project_keyword_rule_does_not_regress_create_project_keyword_rule(monkeypatch):
    # Phase 5D regression lock: the existing Phase 5C create path remains
    # intact after the Phase 5D delete-keyword addition.
    monkeypatch.setattr(
        bridge_module.rule_api,
        "create_project_keyword_rule",
        lambda project_id, keyword: {
            "ok": True,
            "rule": {
                "kind": "keyword",
                "id": 42,
                "project_id": project_id,
                "keyword": keyword.strip(),
                "enabled": True,
            },
        },
    )

    result = WebViewBridge().create_project_keyword_rule(1, "Spec")

    assert result["ok"] is True
    assert result["rule"]["id"] == 42
    assert result["rule"]["keyword"] == "Spec"


# --- Phase 5D.1: keyword deletion hardening regression locks ------------


def test_delete_project_keyword_rule_success_payload_strips_extra_api_keys(monkeypatch):
    # Phase 5D.1 regression lock: the bridge success payload must surface
    # only the narrow ``kind`` / ``id`` / ``deleted`` keys. Even if the API
    # returned extra keys (project_id, keyword, enabled, internal fields,
    # sensitive tokens), the bridge must not forward them to JS. The
    # frontend re-fetches the full Project Rules list via
    # ``get_project_rules`` after success.
    monkeypatch.setattr(
        bridge_module.rule_api,
        "delete_project_keyword_rule",
        lambda rule_id: {
            "ok": True,
            "rule": {
                "kind": "keyword",
                "id": rule_id,
                "deleted": True,
                # Defensive: the bridge must drop these even if the API
                # tried to surface them on the delete write path.
                "project_id": 999,
                "keyword": "should not leak",
                "enabled": True,
                "folder_path": r"D:\Secret",
                "internal_field": "should not leak",
                "traceback": "SELECT * FROM project_rule",
                "details": "C:\\Secret window_title clipboard note",
            },
        },
    )

    result = WebViewBridge().delete_project_keyword_rule(7)

    assert result == {
        "ok": True,
        "rule": {
            "kind": "keyword",
            "id": 7,
            "deleted": True,
        },
    }
    rule = result["rule"]
    assert set(rule.keys()) == {"kind", "id", "deleted"}
    lowered = repr(result).lower()
    # ``kind == "keyword"`` is legitimate; the leak to guard against is the
    # rule's keyword *text* and any extra API key / sensitive token.
    for forbidden in (
        "should not leak",
        "project_id",
        "folder_path",
        "internal_field",
        "traceback",
        "sqlite",
        "select",
        "window_title",
        "clipboard",
        "note",
        "secret",
        "details",
    ):
        assert forbidden not in lowered


def test_delete_project_keyword_rule_folder_rule_id_maps_to_stable_not_found(monkeypatch):
    # Phase 5D.1 regression lock: a folder rule id reaches the bridge as a
    # normal positive int (the bridge does not know which table it belongs
    # to). The API returns ``not_found`` for folder rule ids, and the
    # bridge must map that to the stable ``关键词规则不存在`` message
    # without revealing that the id was a folder rule or surfacing any
    # folder-table detail.
    captured: dict[str, object] = {}

    def fake_delete(rule_id):
        captured["rule_id"] = rule_id
        return {
            "ok": False,
            "error": "not_found",
            # Defensive: the bridge must drop any folder-table leak the
            # API might attach.
            "table": "folder_project_rule",
            "details": "C:\\Secret folder path window_title clipboard note",
        }

    monkeypatch.setattr(bridge_module.rule_api, "delete_project_keyword_rule", fake_delete)

    result = WebViewBridge().delete_project_keyword_rule(55)

    assert captured["rule_id"] == 55
    assert result == {"ok": False, "error": "关键词规则不存在"}
    lowered = repr(result).lower()
    for forbidden in (
        "folder_project_rule",
        "table",
        "details",
        "traceback",
        "sqlite",
        "select",
        "window_title",
        "clipboard",
        "note",
        "secret",
    ):
        assert forbidden not in lowered


def test_delete_project_keyword_rule_bridge_input_validation_payloads_json_serializable():
    # Phase 5D.1 regression lock: every invalid-input failure payload
    # produced at the bridge layer (before any API call) must be JSON
    # serializable and free of sensitive text.
    bridge = WebViewBridge()
    for bad_id in (None, True, False, "1", "abc", 1.0, 2.5, 0, -1, [], {}, (), {1, 2}, (1,), frozenset({1})):
        result = bridge.delete_project_keyword_rule(bad_id)
        assert result == {"ok": False, "error": "操作无效"}
        json.dumps(result, ensure_ascii=False)
        lowered = repr(result).lower()
        for forbidden in ("traceback", "sqlite", "select", "window_title", "clipboard", "note", "secret"):
            assert forbidden not in lowered


# --- Phase 5E: folder rule create bridge tests ---------------------------


def test_create_project_folder_rule_success_payload(monkeypatch):
    # Phase 5E regression lock: the success payload is the narrow created-rule
    # summary only (``kind`` / ``id`` / ``project_id`` / ``folder_path`` /
    # ``recursive`` / ``enabled``). It must NOT echo the full refreshed
    # Project Rules list back to JS — the frontend re-fetches via
    # ``get_project_rules`` after success.
    monkeypatch.setattr(
        bridge_module.rule_api,
        "create_project_folder_rule",
        lambda project_id, folder_path, recursive: {
            "ok": True,
            "rule": {
                "kind": "folder",
                "id": 456,
                "project_id": project_id,
                "folder_path": folder_path,
                "recursive": recursive,
                "enabled": True,
            },
        },
    )

    result = WebViewBridge().create_project_folder_rule(1, r"D:\Work", True)

    assert result == {
        "ok": True,
        "rule": {
            "kind": "folder",
            "id": 456,
            "project_id": 1,
            "folder_path": r"D:\Work",
            "recursive": True,
            "enabled": True,
        },
    }
    assert "projects" not in result
    assert "rules" not in result


@pytest.mark.parametrize("bad_id", [None, True, False, "1", "abc", 0, -1, 1.0, 2.5, [], {}, (), {1, 2}, (1,), frozenset({1})])
def test_create_project_folder_rule_rejects_invalid_project_id(bad_id):
    result = WebViewBridge().create_project_folder_rule(bad_id, r"D:\Work", True)
    assert result == {"ok": False, "error": "操作无效"}


@pytest.mark.parametrize("bad_path", [None, True, False, 1, 1.0, 2.5, [], {}, (), (1,), frozenset({1}), "", "   ", "\t", "\n", "  \t  "])
def test_create_project_folder_rule_rejects_invalid_folder_path(bad_path):
    result = WebViewBridge().create_project_folder_rule(1, bad_path, True)
    assert result == {"ok": False, "error": "操作无效"}


@pytest.mark.parametrize("bad_recursive", [None, "true", 1, 0, 1.0, 2.5, [], {}, (), (1,), frozenset({1})])
def test_create_project_folder_rule_rejects_non_bool_recursive(bad_recursive):
    result = WebViewBridge().create_project_folder_rule(1, r"D:\Work", bad_recursive)
    assert result == {"ok": False, "error": "操作无效"}


def test_create_project_folder_rule_invalid_input_payload_excludes_sensitive_text():
    bridge = WebViewBridge()
    for args in (
        (None, r"D:\Work", True),
        (True, r"D:\Work", True),
        (False, r"D:\Work", True),
        ("1", r"D:\Work", True),
        (1.0, r"D:\Work", True),
        ([], r"D:\Work", True),
        ({}, r"D:\Work", True),
        (0, r"D:\Work", True),
        (-1, r"D:\Work", True),
        (1, None, True),
        (1, True, True),
        (1, 1, True),
        (1, 1.0, True),
        (1, [], True),
        (1, {}, True),
        (1, "", True),
        (1, "   ", True),
        (1, r"D:\Work", None),
        (1, r"D:\Work", "true"),
        (1, r"D:\Work", 1),
        (1, r"D:\Work", []),
        (1, r"D:\Work", {}),
    ):
        result = bridge.create_project_folder_rule(*args)
        assert result == {"ok": False, "error": "操作无效"}
        lowered = repr(result).lower()
        for forbidden in ("traceback", "sqlite", "select", "window_title", "clipboard", "note", "secret"):
            assert forbidden not in lowered


def test_create_project_folder_rule_project_not_found_maps_to_chinese(monkeypatch):
    monkeypatch.setattr(
        bridge_module.rule_api,
        "create_project_folder_rule",
        lambda project_id, folder_path, recursive: {"ok": False, "error": "project_not_found"},
    )

    result = WebViewBridge().create_project_folder_rule(9999, r"D:\Work", True)

    assert result == {"ok": False, "error": "项目不存在或不可用"}


def test_create_project_folder_rule_operation_failed_maps_to_chinese(monkeypatch):
    monkeypatch.setattr(
        bridge_module.rule_api,
        "create_project_folder_rule",
        lambda project_id, folder_path, recursive: {"ok": False, "error": "operation_failed"},
    )

    result = WebViewBridge().create_project_folder_rule(1, r"D:\Work", True)

    assert result == {"ok": False, "error": "新增文件夹规则失败"}


def test_create_project_folder_rule_unknown_error_code_collapses(monkeypatch):
    monkeypatch.setattr(
        bridge_module.rule_api,
        "create_project_folder_rule",
        lambda project_id, folder_path, recursive: {"ok": False, "error": "unknown_code"},
    )

    result = WebViewBridge().create_project_folder_rule(1, r"D:\Work", True)

    assert result == {"ok": False, "error": "新增文件夹规则失败"}


def test_create_project_folder_rule_unknown_exception_collapses(monkeypatch):
    def _boom(*args, **kwargs):
        raise RuntimeError("boom: sensitive SQL SELECT * FROM ...")

    monkeypatch.setattr(bridge_module.rule_api, "create_project_folder_rule", _boom)

    result = WebViewBridge().create_project_folder_rule(1, r"D:\Work", True)

    assert result == {"ok": False, "error": "新增文件夹规则失败"}
    lowered = repr(result).lower()
    for forbidden in ("boom", "select", "sensitive", "traceback", "runtimeerror", "window_title", "clipboard", "note"):
        assert forbidden not in lowered


def test_create_project_folder_rule_failure_payload_excludes_backend_codes(monkeypatch):
    monkeypatch.setattr(
        bridge_module.rule_api,
        "create_project_folder_rule",
        lambda project_id, folder_path, recursive: {
            "ok": False,
            "error": "operation_failed",
            "sql": "SELECT * FROM folder_project_rule",
            "traceback": "RuntimeError: ...",
            "details": "C:\\Secret window_title clipboard note",
        },
    )

    result = WebViewBridge().create_project_folder_rule(1, r"D:\Work", True)

    assert result == {"ok": False, "error": "新增文件夹规则失败"}
    lowered = repr(result).lower()
    for forbidden in ("operation_failed", "sql", "select", "traceback", "details", "window_title", "clipboard", "note", "secret"):
        assert forbidden not in lowered


def test_create_project_folder_rule_success_payload_types_are_stable(monkeypatch):
    monkeypatch.setattr(
        bridge_module.rule_api,
        "create_project_folder_rule",
        lambda project_id, folder_path, recursive: {
            "ok": True,
            "rule": {
                "kind": "folder",
                "id": 789,
                "project_id": project_id,
                "folder_path": folder_path,
                "recursive": recursive,
                "enabled": True,
            },
        },
    )

    result = WebViewBridge().create_project_folder_rule(1, r"D:\Work", True)

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
        bridge_module.rule_api,
        "create_project_folder_rule",
        lambda project_id, folder_path, recursive: {
            "ok": True,
            "rule": {
                "kind": "folder",
                "id": 1,
                "project_id": project_id,
                "folder_path": folder_path,
                "recursive": recursive,
                "enabled": True,
            },
        },
    )

    result = WebViewBridge().create_project_folder_rule(1, r"D:\Work\Client\路径", True)
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
                "kind": "folder",
                "id": 1,
                "project_id": project_id,
                "folder_path": folder_path,
                "recursive": recursive,
                "enabled": True,
            },
        }

    monkeypatch.setattr(bridge_module.rule_api, "create_project_folder_rule", fake_create)

    WebViewBridge().create_project_folder_rule(1, "  D:\\Work  ", True)

    assert captured["folder_path"] == r"D:\Work"


def test_create_project_folder_rule_success_payload_strips_extra_api_keys(monkeypatch):
    monkeypatch.setattr(
        bridge_module.rule_api,
        "create_project_folder_rule",
        lambda project_id, folder_path, recursive: {
            "ok": True,
            "rule": {
                "kind": "folder",
                "id": 1,
                "project_id": project_id,
                "folder_path": folder_path,
                "recursive": recursive,
                "enabled": True,
                "normalized_folder_key": "d:\\work",
                "created_at": "2026-06-28T10:00:00",
                "updated_at": "2026-06-28T10:00:00",
                "internal_note": "C:\\Secret window_title clipboard note",
            },
        },
    )

    result = WebViewBridge().create_project_folder_rule(1, r"D:\Work", True)

    rule = result["rule"]
    assert set(rule.keys()) == {"kind", "id", "project_id", "folder_path", "recursive", "enabled"}
    lowered = repr(result).lower()
    for forbidden in ("normalized_folder_key", "created_at", "updated_at", "internal_note", "secret", "window_title", "clipboard", "note"):
        assert forbidden not in lowered


def test_create_project_folder_rule_never_calls_other_project_rules_write_apis(monkeypatch):
    # Phase 5E regression lock: the folder create bridge must only call
    # ``rule_api.create_project_folder_rule``. It must not call any other
    # write API (toggle / keyword create / keyword delete / folder update /
    # folder delete / preview / backfill / project write).
    called: dict[str, int] = {}

    def _track(name):
        def _impl(*args, **kwargs):
            called[name] = called.get(name, 0) + 1
            return {"ok": True, "rule": {"kind": "folder", "id": 1, "deleted": True}}

        return _impl

    monkeypatch.setattr(bridge_module.rule_api, "create_project_folder_rule", _track("create_folder"))
    monkeypatch.setattr(bridge_module.rule_api, "set_project_rule_enabled", _track("toggle"))
    monkeypatch.setattr(bridge_module.rule_api, "create_project_keyword_rule", _track("create_keyword"))
    monkeypatch.setattr(bridge_module.rule_api, "delete_project_keyword_rule", _track("delete_keyword"))
    monkeypatch.setattr(bridge_module.rule_api, "update_project_folder_rule", _track("update_folder"))
    monkeypatch.setattr(bridge_module.rule_api, "delete_project_folder_rule", _track("delete_folder"))

    WebViewBridge().create_project_folder_rule(1, r"D:\Work", True)

    assert called == {"create_folder": 1}


def test_create_project_folder_rule_does_not_regress_get_project_rules(monkeypatch):
    called = {"get_project_rules": 0}

    def _track(*args, **kwargs):
        called["get_project_rules"] += 1
        return []

    monkeypatch.setattr(bridge_module.project_api, "list_project_bindings", _track)
    monkeypatch.setattr(
        bridge_module.rule_api,
        "create_project_folder_rule",
        lambda project_id, folder_path, recursive: {
            "ok": True,
            "rule": {"kind": "folder", "id": 1, "project_id": project_id, "folder_path": folder_path, "recursive": recursive, "enabled": True},
        },
    )

    bridge = WebViewBridge()
    bridge.create_project_folder_rule(1, r"D:\Work", True)
    result = bridge.get_project_rules()

    assert called["get_project_rules"] == 1
    assert result["ok"] is True


def test_create_project_folder_rule_does_not_regress_set_project_rule_enabled(monkeypatch):
    monkeypatch.setattr(
        bridge_module.rule_api,
        "create_project_folder_rule",
        lambda project_id, folder_path, recursive: {
            "ok": True,
            "rule": {"kind": "folder", "id": 1, "project_id": project_id, "folder_path": folder_path, "recursive": recursive, "enabled": True},
        },
    )
    monkeypatch.setattr(
        bridge_module.rule_api,
        "set_project_rule_enabled",
        lambda rule_type, rule_id, enabled: {"ok": True, "rule": {"kind": rule_type, "id": rule_id, "enabled": enabled}},
    )

    bridge = WebViewBridge()
    create_result = bridge.create_project_folder_rule(1, r"D:\Work", True)
    toggle_result = bridge.set_project_rule_enabled("folder", create_result["rule"]["id"], False)

    assert create_result["ok"] is True
    assert toggle_result["ok"] is True


def test_create_project_folder_rule_does_not_regress_create_project_keyword_rule(monkeypatch):
    monkeypatch.setattr(
        bridge_module.rule_api,
        "create_project_folder_rule",
        lambda project_id, folder_path, recursive: {
            "ok": True,
            "rule": {"kind": "folder", "id": 1, "project_id": project_id, "folder_path": folder_path, "recursive": recursive, "enabled": True},
        },
    )
    monkeypatch.setattr(
        bridge_module.rule_api,
        "create_project_keyword_rule",
        lambda project_id, keyword: {
            "ok": True,
            "rule": {"kind": "keyword", "id": 2, "project_id": project_id, "keyword": keyword.strip(), "enabled": True},
        },
    )

    bridge = WebViewBridge()
    folder_result = bridge.create_project_folder_rule(1, r"D:\Work", True)
    keyword_result = bridge.create_project_keyword_rule(1, "Spec")

    assert folder_result["ok"] is True
    assert keyword_result["ok"] is True


def test_create_project_folder_rule_does_not_regress_delete_project_keyword_rule(monkeypatch):
    monkeypatch.setattr(
        bridge_module.rule_api,
        "create_project_folder_rule",
        lambda project_id, folder_path, recursive: {
            "ok": True,
            "rule": {"kind": "folder", "id": 1, "project_id": project_id, "folder_path": folder_path, "recursive": recursive, "enabled": True},
        },
    )
    monkeypatch.setattr(
        bridge_module.rule_api,
        "delete_project_keyword_rule",
        lambda rule_id: {"ok": True, "rule": {"kind": "keyword", "id": rule_id, "deleted": True}},
    )

    bridge = WebViewBridge()
    folder_result = bridge.create_project_folder_rule(1, r"D:\Work", True)
    delete_result = bridge.delete_project_keyword_rule(99)

    assert folder_result["ok"] is True
    assert delete_result["ok"] is True


# --- Phase 5E: folder rule update bridge tests ---------------------------


def test_update_project_folder_rule_success_payload(monkeypatch):
    monkeypatch.setattr(
        bridge_module.rule_api,
        "update_project_folder_rule",
        lambda rule_id, folder_path, recursive: {
            "ok": True,
            "rule": {
                "kind": "folder",
                "id": rule_id,
                "project_id": 1,
                "folder_path": folder_path,
                "recursive": recursive,
                "enabled": True,
            },
        },
    )

    result = WebViewBridge().update_project_folder_rule(10, r"D:\New", False)

    assert result == {
        "ok": True,
        "rule": {
            "kind": "folder",
            "id": 10,
            "project_id": 1,
            "folder_path": r"D:\New",
            "recursive": False,
            "enabled": True,
        },
    }
    assert "projects" not in result


@pytest.mark.parametrize("bad_id", [None, True, False, "1", "abc", 0, -1, 1.0, 2.5, [], {}, (), {1, 2}, (1,), frozenset({1})])
def test_update_project_folder_rule_rejects_invalid_rule_id(bad_id):
    result = WebViewBridge().update_project_folder_rule(bad_id, r"D:\New", True)
    assert result == {"ok": False, "error": "操作无效"}


@pytest.mark.parametrize("bad_path", [None, True, False, 1, 1.0, 2.5, [], {}, (), (1,), frozenset({1}), "", "   ", "\t", "\n", "  \t  "])
def test_update_project_folder_rule_rejects_invalid_folder_path(bad_path):
    result = WebViewBridge().update_project_folder_rule(1, bad_path, True)
    assert result == {"ok": False, "error": "操作无效"}


@pytest.mark.parametrize("bad_recursive", [None, "true", 1, 0, 1.0, 2.5, [], {}, (), (1,), frozenset({1})])
def test_update_project_folder_rule_rejects_non_bool_recursive(bad_recursive):
    result = WebViewBridge().update_project_folder_rule(1, r"D:\New", bad_recursive)
    assert result == {"ok": False, "error": "操作无效"}


def test_update_project_folder_rule_not_found_maps_to_chinese(monkeypatch):
    monkeypatch.setattr(
        bridge_module.rule_api,
        "update_project_folder_rule",
        lambda rule_id, folder_path, recursive: {"ok": False, "error": "not_found"},
    )

    result = WebViewBridge().update_project_folder_rule(9999, r"D:\New", True)

    assert result == {"ok": False, "error": "文件夹规则不存在"}


def test_update_project_folder_rule_operation_failed_maps_to_chinese(monkeypatch):
    monkeypatch.setattr(
        bridge_module.rule_api,
        "update_project_folder_rule",
        lambda rule_id, folder_path, recursive: {"ok": False, "error": "operation_failed"},
    )

    result = WebViewBridge().update_project_folder_rule(1, r"D:\New", True)

    assert result == {"ok": False, "error": "保存文件夹规则失败"}


def test_update_project_folder_rule_unknown_error_code_collapses(monkeypatch):
    monkeypatch.setattr(
        bridge_module.rule_api,
        "update_project_folder_rule",
        lambda rule_id, folder_path, recursive: {"ok": False, "error": "unknown_code"},
    )

    result = WebViewBridge().update_project_folder_rule(1, r"D:\New", True)

    assert result == {"ok": False, "error": "保存文件夹规则失败"}


def test_update_project_folder_rule_unknown_exception_collapses(monkeypatch):
    def _boom(*args, **kwargs):
        raise RuntimeError("boom: sensitive SQL UPDATE ...")

    monkeypatch.setattr(bridge_module.rule_api, "update_project_folder_rule", _boom)

    result = WebViewBridge().update_project_folder_rule(1, r"D:\New", True)

    assert result == {"ok": False, "error": "保存文件夹规则失败"}
    lowered = repr(result).lower()
    for forbidden in ("boom", "update", "sensitive", "traceback", "runtimeerror", "window_title", "clipboard", "note"):
        assert forbidden not in lowered


def test_update_project_folder_rule_failure_payload_excludes_backend_codes(monkeypatch):
    monkeypatch.setattr(
        bridge_module.rule_api,
        "update_project_folder_rule",
        lambda rule_id, folder_path, recursive: {
            "ok": False,
            "error": "operation_failed",
            "sql": "UPDATE folder_project_rule SET ...",
            "traceback": "RuntimeError: ...",
            "details": "C:\\Secret window_title clipboard note",
        },
    )

    result = WebViewBridge().update_project_folder_rule(1, r"D:\New", True)

    assert result == {"ok": False, "error": "保存文件夹规则失败"}
    lowered = repr(result).lower()
    for forbidden in ("operation_failed", "sql", "update", "traceback", "details", "window_title", "clipboard", "note", "secret"):
        assert forbidden not in lowered


def test_update_project_folder_rule_success_payload_types_are_stable(monkeypatch):
    monkeypatch.setattr(
        bridge_module.rule_api,
        "update_project_folder_rule",
        lambda rule_id, folder_path, recursive: {
            "ok": True,
            "rule": {
                "kind": "folder",
                "id": rule_id,
                "project_id": 1,
                "folder_path": folder_path,
                "recursive": recursive,
                "enabled": True,
            },
        },
    )

    result = WebViewBridge().update_project_folder_rule(1, r"D:\New", True)

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
        bridge_module.rule_api,
        "update_project_folder_rule",
        lambda rule_id, folder_path, recursive: {
            "ok": True,
            "rule": {
                "kind": "folder",
                "id": rule_id,
                "project_id": 1,
                "folder_path": folder_path,
                "recursive": recursive,
                "enabled": True,
            },
        },
    )

    result = WebViewBridge().update_project_folder_rule(1, r"D:\Work\路径", True)
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
                "kind": "folder",
                "id": rule_id,
                "project_id": 1,
                "folder_path": folder_path,
                "recursive": recursive,
                "enabled": True,
            },
        }

    monkeypatch.setattr(bridge_module.rule_api, "update_project_folder_rule", fake_update)

    WebViewBridge().update_project_folder_rule(10, "  D:\\New  ", True)

    assert captured["folder_path"] == r"D:\New"
    assert captured["rule_id"] == 10


def test_update_project_folder_rule_success_payload_strips_extra_api_keys(monkeypatch):
    monkeypatch.setattr(
        bridge_module.rule_api,
        "update_project_folder_rule",
        lambda rule_id, folder_path, recursive: {
            "ok": True,
            "rule": {
                "kind": "folder",
                "id": rule_id,
                "project_id": 1,
                "folder_path": folder_path,
                "recursive": recursive,
                "enabled": True,
                "normalized_folder_key": "d:\\new",
                "created_at": "2026-06-28T10:00:00",
                "updated_at": "2026-06-28T10:00:00",
                "internal_note": "C:\\Secret window_title clipboard note",
            },
        },
    )

    result = WebViewBridge().update_project_folder_rule(1, r"D:\New", True)

    rule = result["rule"]
    assert set(rule.keys()) == {"kind", "id", "project_id", "folder_path", "recursive", "enabled"}
    lowered = repr(result).lower()
    for forbidden in ("normalized_folder_key", "created_at", "updated_at", "internal_note", "secret", "window_title", "clipboard", "note"):
        assert forbidden not in lowered


def test_update_project_folder_rule_never_calls_other_project_rules_write_apis(monkeypatch):
    called: dict[str, int] = {}

    def _track(name):
        def _impl(*args, **kwargs):
            called[name] = called.get(name, 0) + 1
            return {"ok": True, "rule": {"kind": "folder", "id": 1, "deleted": True}}

        return _impl

    monkeypatch.setattr(bridge_module.rule_api, "update_project_folder_rule", _track("update_folder"))
    monkeypatch.setattr(bridge_module.rule_api, "set_project_rule_enabled", _track("toggle"))
    monkeypatch.setattr(bridge_module.rule_api, "create_project_keyword_rule", _track("create_keyword"))
    monkeypatch.setattr(bridge_module.rule_api, "delete_project_keyword_rule", _track("delete_keyword"))
    monkeypatch.setattr(bridge_module.rule_api, "create_project_folder_rule", _track("create_folder"))
    monkeypatch.setattr(bridge_module.rule_api, "delete_project_folder_rule", _track("delete_folder"))

    WebViewBridge().update_project_folder_rule(1, r"D:\New", True)

    assert called == {"update_folder": 1}


# --- Phase 5E: folder rule delete bridge tests ---------------------------


def test_delete_project_folder_rule_success_payload(monkeypatch):
    monkeypatch.setattr(
        bridge_module.rule_api,
        "delete_project_folder_rule",
        lambda rule_id: {
            "ok": True,
            "rule": {"kind": "folder", "id": rule_id, "deleted": True},
        },
    )

    result = WebViewBridge().delete_project_folder_rule(10)

    assert result == {
        "ok": True,
        "rule": {"kind": "folder", "id": 10, "deleted": True},
    }
    assert "projects" not in result


@pytest.mark.parametrize("bad_id", [None, True, False, "1", "abc", 0, -1, 1.0, 2.5, [], {}, (), {1, 2}, (1,), frozenset({1})])
def test_delete_project_folder_rule_rejects_invalid_rule_id(bad_id):
    result = WebViewBridge().delete_project_folder_rule(bad_id)
    assert result == {"ok": False, "error": "操作无效"}


def test_delete_project_folder_rule_invalid_input_payload_excludes_sensitive_text():
    bridge = WebViewBridge()
    for bad_id in (None, True, False, "1", "abc", 1.0, 2.5, 0, -1, [], {}, (), {1, 2}, (1,), frozenset({1})):
        result = bridge.delete_project_folder_rule(bad_id)
        assert result == {"ok": False, "error": "操作无效"}
        lowered = repr(result).lower()
        for forbidden in ("traceback", "sqlite", "select", "window_title", "clipboard", "note", "secret"):
            assert forbidden not in lowered


def test_delete_project_folder_rule_not_found_maps_to_chinese(monkeypatch):
    monkeypatch.setattr(
        bridge_module.rule_api,
        "delete_project_folder_rule",
        lambda rule_id: {"ok": False, "error": "not_found"},
    )

    result = WebViewBridge().delete_project_folder_rule(9999)

    assert result == {"ok": False, "error": "文件夹规则不存在"}


def test_delete_project_folder_rule_operation_failed_maps_to_chinese(monkeypatch):
    monkeypatch.setattr(
        bridge_module.rule_api,
        "delete_project_folder_rule",
        lambda rule_id: {"ok": False, "error": "operation_failed"},
    )

    result = WebViewBridge().delete_project_folder_rule(1)

    assert result == {"ok": False, "error": "删除文件夹规则失败"}


def test_delete_project_folder_rule_unknown_error_code_collapses(monkeypatch):
    monkeypatch.setattr(
        bridge_module.rule_api,
        "delete_project_folder_rule",
        lambda rule_id: {"ok": False, "error": "unknown_code"},
    )

    result = WebViewBridge().delete_project_folder_rule(1)

    assert result == {"ok": False, "error": "删除文件夹规则失败"}


def test_delete_project_folder_rule_unknown_exception_collapses(monkeypatch):
    def _boom(*args, **kwargs):
        raise RuntimeError("boom: sensitive SQL DELETE FROM ...")

    monkeypatch.setattr(bridge_module.rule_api, "delete_project_folder_rule", _boom)

    result = WebViewBridge().delete_project_folder_rule(1)

    assert result == {"ok": False, "error": "删除文件夹规则失败"}
    lowered = repr(result).lower()
    for forbidden in ("boom", "delete", "sensitive", "traceback", "runtimeerror", "window_title", "clipboard", "note"):
        assert forbidden not in lowered


def test_delete_project_folder_rule_failure_payload_excludes_backend_codes(monkeypatch):
    monkeypatch.setattr(
        bridge_module.rule_api,
        "delete_project_folder_rule",
        lambda rule_id: {
            "ok": False,
            "error": "operation_failed",
            "sql": "DELETE FROM folder_project_rule WHERE ...",
            "traceback": "RuntimeError: ...",
            "details": "C:\\Secret window_title clipboard note",
        },
    )

    result = WebViewBridge().delete_project_folder_rule(1)

    assert result == {"ok": False, "error": "删除文件夹规则失败"}
    lowered = repr(result).lower()
    for forbidden in ("operation_failed", "sql", "delete", "traceback", "details", "window_title", "clipboard", "note", "secret"):
        assert forbidden not in lowered


def test_delete_project_folder_rule_success_payload_types_are_stable(monkeypatch):
    monkeypatch.setattr(
        bridge_module.rule_api,
        "delete_project_folder_rule",
        lambda rule_id: {
            "ok": True,
            "rule": {"kind": "folder", "id": rule_id, "deleted": True},
        },
    )

    result = WebViewBridge().delete_project_folder_rule(1)

    assert isinstance(result["ok"], bool)
    rule = result["rule"]
    assert isinstance(rule["kind"], str)
    assert isinstance(rule["id"], int)
    assert isinstance(rule["deleted"], bool)


def test_delete_project_folder_rule_payload_json_serializable(monkeypatch):
    monkeypatch.setattr(
        bridge_module.rule_api,
        "delete_project_folder_rule",
        lambda rule_id: {
            "ok": True,
            "rule": {"kind": "folder", "id": rule_id, "deleted": True},
        },
    )

    result = WebViewBridge().delete_project_folder_rule(1)
    json.dumps(result, ensure_ascii=False)


def test_delete_project_folder_rule_success_payload_strips_extra_api_keys(monkeypatch):
    monkeypatch.setattr(
        bridge_module.rule_api,
        "delete_project_folder_rule",
        lambda rule_id: {
            "ok": True,
            "rule": {
                "kind": "folder",
                "id": rule_id,
                "deleted": True,
                "folder_path": r"C:\Secret",
                "project_id": 99,
                "normalized_folder_key": "c:\\secret",
                "internal_note": "C:\\Secret window_title clipboard note",
            },
        },
    )

    result = WebViewBridge().delete_project_folder_rule(1)

    rule = result["rule"]
    assert set(rule.keys()) == {"kind", "id", "deleted"}
    lowered = repr(result).lower()
    for forbidden in ("folder_path", "project_id", "normalized_folder_key", "internal_note", "secret", "window_title", "clipboard", "note"):
        assert forbidden not in lowered


def test_delete_project_folder_rule_never_calls_other_project_rules_write_apis(monkeypatch):
    called: dict[str, int] = {}

    def _track(name):
        def _impl(*args, **kwargs):
            called[name] = called.get(name, 0) + 1
            return {"ok": True, "rule": {"kind": "folder", "id": 1, "deleted": True}}

        return _impl

    monkeypatch.setattr(bridge_module.rule_api, "delete_project_folder_rule", _track("delete_folder"))
    monkeypatch.setattr(bridge_module.rule_api, "set_project_rule_enabled", _track("toggle"))
    monkeypatch.setattr(bridge_module.rule_api, "create_project_keyword_rule", _track("create_keyword"))
    monkeypatch.setattr(bridge_module.rule_api, "delete_project_keyword_rule", _track("delete_keyword"))
    monkeypatch.setattr(bridge_module.rule_api, "create_project_folder_rule", _track("create_folder"))
    monkeypatch.setattr(bridge_module.rule_api, "update_project_folder_rule", _track("update_folder"))

    WebViewBridge().delete_project_folder_rule(1)

    assert called == {"delete_folder": 1}


def test_delete_project_folder_rule_keyword_rule_id_maps_to_stable_not_found(monkeypatch):
    # A keyword rule id reaches the bridge as a normal positive int. The API
    # returns ``not_found`` for keyword rule ids, and the bridge must map
    # that to the stable ``文件夹规则不存在`` message without revealing that
    # the id was a keyword rule or surfacing any keyword-table detail.
    captured: dict[str, object] = {}

    def fake_delete(rule_id):
        captured["rule_id"] = rule_id
        return {
            "ok": False,
            "error": "not_found",
            "table": "project_rule",
            "details": "Spec keyword window_title clipboard note",
        }

    monkeypatch.setattr(bridge_module.rule_api, "delete_project_folder_rule", fake_delete)

    result = WebViewBridge().delete_project_folder_rule(77)

    assert captured["rule_id"] == 77
    assert result == {"ok": False, "error": "文件夹规则不存在"}
    lowered = repr(result).lower()
    for forbidden in ("project_rule", "table", "details", "traceback", "sqlite", "select", "window_title", "clipboard", "note", "secret", "spec", "keyword"):
        assert forbidden not in lowered


def test_delete_project_folder_rule_bridge_input_validation_payloads_json_serializable():
    bridge = WebViewBridge()
    for bad_id in (None, True, False, "1", "abc", 1.0, 2.5, 0, -1, [], {}, (), {1, 2}, (1,), frozenset({1})):
        result = bridge.delete_project_folder_rule(bad_id)
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

    monkeypatch.setattr(bridge_module.project_api, "list_project_bindings", _track)
    monkeypatch.setattr(
        bridge_module.rule_api,
        "delete_project_folder_rule",
        lambda rule_id: {"ok": True, "rule": {"kind": "folder", "id": rule_id, "deleted": True}},
    )

    bridge = WebViewBridge()
    bridge.delete_project_folder_rule(1)
    result = bridge.get_project_rules()

    assert called["get_project_rules"] == 1
    assert result["ok"] is True


def test_delete_project_folder_rule_does_not_regress_set_project_rule_enabled(monkeypatch):
    monkeypatch.setattr(
        bridge_module.rule_api,
        "delete_project_folder_rule",
        lambda rule_id: {"ok": True, "rule": {"kind": "folder", "id": rule_id, "deleted": True}},
    )
    monkeypatch.setattr(
        bridge_module.rule_api,
        "set_project_rule_enabled",
        lambda rule_type, rule_id, enabled: {"ok": True, "rule": {"kind": rule_type, "id": rule_id, "enabled": enabled}},
    )

    bridge = WebViewBridge()
    delete_result = bridge.delete_project_folder_rule(1)
    toggle_result = bridge.set_project_rule_enabled("folder", 10, False)

    assert delete_result["ok"] is True
    assert toggle_result["ok"] is True


def test_delete_project_folder_rule_does_not_regress_create_project_keyword_rule(monkeypatch):
    monkeypatch.setattr(
        bridge_module.rule_api,
        "delete_project_folder_rule",
        lambda rule_id: {"ok": True, "rule": {"kind": "folder", "id": rule_id, "deleted": True}},
    )
    monkeypatch.setattr(
        bridge_module.rule_api,
        "create_project_keyword_rule",
        lambda project_id, keyword: {
            "ok": True,
            "rule": {"kind": "keyword", "id": 2, "project_id": project_id, "keyword": keyword.strip(), "enabled": True},
        },
    )

    bridge = WebViewBridge()
    delete_result = bridge.delete_project_folder_rule(1)
    keyword_result = bridge.create_project_keyword_rule(1, "Spec")

    assert delete_result["ok"] is True
    assert keyword_result["ok"] is True


def test_delete_project_folder_rule_does_not_regress_delete_project_keyword_rule(monkeypatch):
    monkeypatch.setattr(
        bridge_module.rule_api,
        "delete_project_folder_rule",
        lambda rule_id: {"ok": True, "rule": {"kind": "folder", "id": rule_id, "deleted": True}},
    )
    monkeypatch.setattr(
        bridge_module.rule_api,
        "delete_project_keyword_rule",
        lambda rule_id: {"ok": True, "rule": {"kind": "keyword", "id": rule_id, "deleted": True}},
    )

    bridge = WebViewBridge()
    folder_result = bridge.delete_project_folder_rule(1)
    keyword_result = bridge.delete_project_keyword_rule(99)

    assert folder_result["ok"] is True
    assert keyword_result["ok"] is True


# --- Phase 5E.1: folder rule CRUD bridge hardening regression locks -------
#
# These locks consolidate the bool-as-int rejection, the error-message-map
# consistency, the API-call boundary (the bridge never forwards bool /
# non-int / non-bool values to the API), the failure-path JSON
# serializability, and the cross-method state isolation that guarantees
# the three folder bridge methods do not pollute each other or the
# keyword / toggle bridge methods.


@pytest.mark.parametrize("bad_id", [True, False])
def test_create_project_folder_rule_rejects_bool_as_int_project_id_consolidated(bad_id):
    # Phase 5E.1 regression lock: ``bool`` is a subclass of ``int``, so
    # ``True``/``False`` must be rejected before reaching the API. The bridge
    # uses ``type(...) is not int`` which excludes ``bool``.
    result = WebViewBridge().create_project_folder_rule(bad_id, r"D:\Work", True)
    assert result == {"ok": False, "error": "操作无效"}


@pytest.mark.parametrize("bad_id", [True, False])
def test_update_project_folder_rule_rejects_bool_as_int_rule_id_consolidated(bad_id):
    result = WebViewBridge().update_project_folder_rule(bad_id, r"D:\New", True)
    assert result == {"ok": False, "error": "操作无效"}


@pytest.mark.parametrize("bad_id", [True, False])
def test_delete_project_folder_rule_rejects_bool_as_int_rule_id_consolidated(bad_id):
    result = WebViewBridge().delete_project_folder_rule(bad_id)
    assert result == {"ok": False, "error": "操作无效"}


def test_folder_bridge_methods_invalid_input_return_consistent_message():
    # Phase 5E.1 regression lock: all three folder bridge methods must
    # return the same stable ``操作无效`` message for invalid input so the
    # user never sees a method-specific validation string.
    bridge = WebViewBridge()
    create_result = bridge.create_project_folder_rule(True, r"D:\Work", True)
    update_result = bridge.update_project_folder_rule(True, r"D:\New", True)
    delete_result = bridge.delete_project_folder_rule(True)
    assert create_result == update_result == delete_result == {"ok": False, "error": "操作无效"}


def test_folder_bridge_methods_error_message_maps_are_distinct_and_stable():
    # Phase 5E.1 regression lock: the three folder bridge methods must map
    # ``not_found`` and ``operation_failed`` to distinct, stable Chinese
    # messages so a folder-update failure is never reported with a
    # folder-delete message and vice versa.
    assert bridge_module._PROJECT_RULE_FOLDER_CREATE_MESSAGES["operation_failed"] == "新增文件夹规则失败"
    assert bridge_module._PROJECT_RULE_FOLDER_UPDATE_MESSAGES["not_found"] == "文件夹规则不存在"
    assert bridge_module._PROJECT_RULE_FOLDER_UPDATE_MESSAGES["operation_failed"] == "保存文件夹规则失败"
    assert bridge_module._PROJECT_RULE_FOLDER_DELETE_MESSAGES["not_found"] == "文件夹规则不存在"
    assert bridge_module._PROJECT_RULE_FOLDER_DELETE_MESSAGES["operation_failed"] == "删除文件夹规则失败"
    # The create map must NOT have a ``not_found`` entry (create uses
    # ``project_not_found`` instead).
    assert "not_found" not in bridge_module._PROJECT_RULE_FOLDER_CREATE_MESSAGES
    assert bridge_module._PROJECT_RULE_FOLDER_CREATE_MESSAGES["project_not_found"] == "项目不存在或不可用"


def test_create_project_folder_rule_never_forwards_bool_project_id_to_api(monkeypatch):
    # Phase 5E.1 regression lock: the bridge must validate before calling
    # the API, so a bool ``project_id`` never reaches ``rule_api``.
    called: list = []

    def _spy(*args, **kwargs):
        called.append(args)
        return {"ok": True, "rule": {"kind": "folder", "id": 1, "project_id": 1, "folder_path": "x", "recursive": True, "enabled": True}}

    monkeypatch.setattr(bridge_module.rule_api, "create_project_folder_rule", _spy)
    WebViewBridge().create_project_folder_rule(True, r"D:\Work", True)
    assert called == []


def test_update_project_folder_rule_never_forwards_bool_rule_id_to_api(monkeypatch):
    called: list = []

    def _spy(*args, **kwargs):
        called.append(args)
        return {"ok": True, "rule": {"kind": "folder", "id": 1, "project_id": 1, "folder_path": "x", "recursive": True, "enabled": True}}

    monkeypatch.setattr(bridge_module.rule_api, "update_project_folder_rule", _spy)
    WebViewBridge().update_project_folder_rule(True, r"D:\New", True)
    assert called == []


def test_delete_project_folder_rule_never_forwards_bool_rule_id_to_api(monkeypatch):
    called: list = []

    def _spy(*args, **kwargs):
        called.append(args)
        return {"ok": True, "rule": {"kind": "folder", "id": 1, "deleted": True}}

    monkeypatch.setattr(bridge_module.rule_api, "delete_project_folder_rule", _spy)
    WebViewBridge().delete_project_folder_rule(True)
    assert called == []


def test_create_project_folder_rule_never_forwards_non_bool_recursive_to_api(monkeypatch):
    # Phase 5E.1 regression lock: the bridge must reject non-bool
    # ``recursive`` (including int 1/0) before calling the API.
    called: list = []

    def _spy(*args, **kwargs):
        called.append(args)
        return {"ok": True, "rule": {"kind": "folder", "id": 1, "project_id": 1, "folder_path": "x", "recursive": True, "enabled": True}}

    monkeypatch.setattr(bridge_module.rule_api, "create_project_folder_rule", _spy)
    for bad_recursive in (1, 0, "true", None, 1.0):
        WebViewBridge().create_project_folder_rule(1, r"D:\Work", bad_recursive)
    assert called == []


def test_update_project_folder_rule_never_forwards_non_bool_recursive_to_api(monkeypatch):
    called: list = []

    def _spy(*args, **kwargs):
        called.append(args)
        return {"ok": True, "rule": {"kind": "folder", "id": 1, "project_id": 1, "folder_path": "x", "recursive": True, "enabled": True}}

    monkeypatch.setattr(bridge_module.rule_api, "update_project_folder_rule", _spy)
    for bad_recursive in (1, 0, "true", None, 1.0):
        WebViewBridge().update_project_folder_rule(1, r"D:\New", bad_recursive)
    assert called == []


def test_folder_bridge_failure_payloads_are_json_serializable(monkeypatch):
    # Phase 5E.1 regression lock: failure payloads must be JSON serializable
    # so pywebview can deliver them to JS. Covers both invalid-input and
    # API-error-code paths for all three folder methods.
    monkeypatch.setattr(
        bridge_module.rule_api,
        "create_project_folder_rule",
        lambda project_id, folder_path, recursive: {"ok": False, "error": "operation_failed"},
    )
    monkeypatch.setattr(
        bridge_module.rule_api,
        "update_project_folder_rule",
        lambda rule_id, folder_path, recursive: {"ok": False, "error": "not_found"},
    )
    monkeypatch.setattr(
        bridge_module.rule_api,
        "delete_project_folder_rule",
        lambda rule_id: {"ok": False, "error": "operation_failed"},
    )
    bridge = WebViewBridge()
    json.dumps(bridge.create_project_folder_rule(True, r"D:\Work", True), ensure_ascii=False)
    json.dumps(bridge.create_project_folder_rule(1, r"D:\Work", True), ensure_ascii=False)
    json.dumps(bridge.update_project_folder_rule(True, r"D:\New", True), ensure_ascii=False)
    json.dumps(bridge.update_project_folder_rule(1, r"D:\New", True), ensure_ascii=False)
    json.dumps(bridge.delete_project_folder_rule(True), ensure_ascii=False)
    json.dumps(bridge.delete_project_folder_rule(1), ensure_ascii=False)


def test_folder_bridge_methods_do_not_cross_pollute_keyword_or_toggle(monkeypatch):
    # Phase 5E.1 regression lock: calling the three folder bridge methods
    # must never trigger any keyword or toggle API call, and vice versa.
    called: dict[str, int] = {}

    def _track(name):
        def _impl(*args, **kwargs):
            called[name] = called.get(name, 0) + 1
            return {"ok": True, "rule": {"kind": "folder", "id": 1, "deleted": True}}

        return _impl

    monkeypatch.setattr(bridge_module.rule_api, "create_project_folder_rule", _track("create_folder"))
    monkeypatch.setattr(bridge_module.rule_api, "update_project_folder_rule", _track("update_folder"))
    monkeypatch.setattr(bridge_module.rule_api, "delete_project_folder_rule", _track("delete_folder"))
    monkeypatch.setattr(bridge_module.rule_api, "create_project_keyword_rule", _track("create_keyword"))
    monkeypatch.setattr(bridge_module.rule_api, "delete_project_keyword_rule", _track("delete_keyword"))
    monkeypatch.setattr(bridge_module.rule_api, "set_project_rule_enabled", _track("toggle"))

    bridge = WebViewBridge()
    bridge.create_project_folder_rule(1, r"D:\Work", True)
    bridge.update_project_folder_rule(1, r"D:\New", False)
    bridge.delete_project_folder_rule(1)

    assert called == {"create_folder": 1, "update_folder": 1, "delete_folder": 1}
    # Now call keyword / toggle methods and confirm they don't trigger folder APIs.
    before = dict(called)
    bridge.create_project_keyword_rule(1, "Spec")
    bridge.delete_project_keyword_rule(99)
    bridge.set_project_rule_enabled("folder", 1, False)
    assert called["create_folder"] == before["create_folder"]
    assert called["update_folder"] == before["update_folder"]
    assert called["delete_folder"] == before["delete_folder"]
    assert called["create_keyword"] == 1
    assert called["delete_keyword"] == 1
    assert called["toggle"] == 1


def test_folder_bridge_success_payloads_never_include_api_error_keys(monkeypatch):
    # Phase 5E.1 regression lock: success payloads must never carry the
    # ``error`` key or any API-internal key. This complements the existing
    # strip-extra-keys tests by asserting the full key set in one place.
    monkeypatch.setattr(
        bridge_module.rule_api,
        "create_project_folder_rule",
        lambda project_id, folder_path, recursive: {
            "ok": True,
            "rule": {"kind": "folder", "id": 7, "project_id": project_id, "folder_path": folder_path, "recursive": recursive, "enabled": True},
        },
    )
    monkeypatch.setattr(
        bridge_module.rule_api,
        "update_project_folder_rule",
        lambda rule_id, folder_path, recursive: {
            "ok": True,
            "rule": {"kind": "folder", "id": rule_id, "project_id": 1, "folder_path": folder_path, "recursive": recursive, "enabled": True},
        },
    )
    monkeypatch.setattr(
        bridge_module.rule_api,
        "delete_project_folder_rule",
        lambda rule_id: {"ok": True, "rule": {"kind": "folder", "id": rule_id, "deleted": True}},
    )
    bridge = WebViewBridge()
    create_result = bridge.create_project_folder_rule(1, r"D:\Work", True)
    update_result = bridge.update_project_folder_rule(1, r"D:\New", False)
    delete_result = bridge.delete_project_folder_rule(1)

    assert set(create_result.keys()) == {"ok", "rule"}
    assert set(create_result["rule"].keys()) == {"kind", "id", "project_id", "folder_path", "recursive", "enabled"}
    assert set(update_result.keys()) == {"ok", "rule"}
    assert set(update_result["rule"].keys()) == {"kind", "id", "project_id", "folder_path", "recursive", "enabled"}
    assert set(delete_result.keys()) == {"ok", "rule"}
    assert set(delete_result["rule"].keys()) == {"kind", "id", "deleted"}
    for result in (create_result, update_result, delete_result):
        assert "error" not in result
        assert "projects" not in result
        assert "rules" not in result


# --- Phase 5F: keyword rule edit bridge tests ----------------------------


def test_update_project_keyword_rule_success_payload(monkeypatch):
    monkeypatch.setattr(
        bridge_module.rule_api,
        "update_project_keyword_rule",
        lambda rule_id, keyword: {
            "ok": True,
            "rule": {
                "kind": "keyword",
                "id": rule_id,
                "project_id": 1,
                "keyword": keyword,
                "enabled": True,
            },
        },
    )

    result = WebViewBridge().update_project_keyword_rule(123, "NewSpec")

    assert result == {
        "ok": True,
        "rule": {
            "kind": "keyword",
            "id": 123,
            "project_id": 1,
            "keyword": "NewSpec",
            "enabled": True,
        },
    }
    assert "projects" not in result


@pytest.mark.parametrize(
    "bad_id",
    [None, True, False, "1", "abc", 0, -1, 1.0, 2.5, [], {}, (), {1, 2}, (1,), frozenset({1})],
)
def test_update_project_keyword_rule_rejects_invalid_rule_id(bad_id):
    result = WebViewBridge().update_project_keyword_rule(bad_id, "Spec")
    assert result == {"ok": False, "error": "操作无效"}


@pytest.mark.parametrize(
    "bad_keyword",
    [None, True, False, 1, 1.0, [], {}, (), {1, 2}, (1,), frozenset({1})],
)
def test_update_project_keyword_rule_rejects_non_string_keyword(bad_keyword):
    result = WebViewBridge().update_project_keyword_rule(1, bad_keyword)
    assert result == {"ok": False, "error": "操作无效"}


@pytest.mark.parametrize("bad_keyword", ["", "   ", "\t", "\n", "  \t  "])
def test_update_project_keyword_rule_rejects_empty_or_whitespace_keyword(bad_keyword):
    result = WebViewBridge().update_project_keyword_rule(1, bad_keyword)
    assert result == {"ok": False, "error": "操作无效"}


def test_update_project_keyword_rule_bridge_passes_trimmed_keyword_to_api(monkeypatch):
    captured: list = []

    def _spy(rule_id, keyword):
        captured.append((rule_id, keyword))
        return {
            "ok": True,
            "rule": {
                "kind": "keyword",
                "id": rule_id,
                "project_id": 1,
                "keyword": keyword,
                "enabled": True,
            },
        }

    monkeypatch.setattr(bridge_module.rule_api, "update_project_keyword_rule", _spy)

    WebViewBridge().update_project_keyword_rule(5, "  NewSpec  ")

    assert captured == [(5, "NewSpec")]


def test_update_project_keyword_rule_invalid_input_maps_to_chinese(monkeypatch):
    monkeypatch.setattr(
        bridge_module.rule_api,
        "update_project_keyword_rule",
        lambda rule_id, keyword: {"ok": False, "error": "invalid_input"},
    )

    result = WebViewBridge().update_project_keyword_rule(1, "Spec")

    assert result == {"ok": False, "error": "操作无效"}


def test_update_project_keyword_rule_not_found_maps_to_chinese(monkeypatch):
    monkeypatch.setattr(
        bridge_module.rule_api,
        "update_project_keyword_rule",
        lambda rule_id, keyword: {"ok": False, "error": "not_found"},
    )

    result = WebViewBridge().update_project_keyword_rule(999, "Spec")

    assert result == {"ok": False, "error": "关键词规则不存在"}


def test_update_project_keyword_rule_duplicate_rule_maps_to_chinese(monkeypatch):
    monkeypatch.setattr(
        bridge_module.rule_api,
        "update_project_keyword_rule",
        lambda rule_id, keyword: {"ok": False, "error": "duplicate_rule"},
    )

    result = WebViewBridge().update_project_keyword_rule(1, "Spec")

    assert result == {"ok": False, "error": "关键词规则已存在"}


def test_update_project_keyword_rule_operation_failed_maps_to_chinese(monkeypatch):
    monkeypatch.setattr(
        bridge_module.rule_api,
        "update_project_keyword_rule",
        lambda rule_id, keyword: {"ok": False, "error": "operation_failed"},
    )

    result = WebViewBridge().update_project_keyword_rule(1, "Spec")

    assert result == {"ok": False, "error": "保存关键词规则失败"}


def test_update_project_keyword_rule_unknown_error_code_collapses(monkeypatch):
    monkeypatch.setattr(
        bridge_module.rule_api,
        "update_project_keyword_rule",
        lambda rule_id, keyword: {"ok": False, "error": "unexpected raw code"},
    )

    result = WebViewBridge().update_project_keyword_rule(1, "Spec")

    assert result == {"ok": False, "error": "保存关键词规则失败"}


def test_update_project_keyword_rule_unknown_exception_collapses(monkeypatch):
    def fail(rule_id, keyword):
        raise RuntimeError(
            "boom SELECT * FROM activity_log traceback window_title clipboard note C:\\Secret"
        )

    monkeypatch.setattr(bridge_module.rule_api, "update_project_keyword_rule", fail)

    result = WebViewBridge().update_project_keyword_rule(1, "Spec")

    assert result == {"ok": False, "error": "保存关键词规则失败"}
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
        "secret",
    ):
        assert forbidden not in lowered


def test_update_project_keyword_rule_failure_payload_excludes_backend_codes(monkeypatch):
    monkeypatch.setattr(
        bridge_module.rule_api,
        "update_project_keyword_rule",
        lambda rule_id, keyword: {
            "ok": False,
            "error": "not_found",
            "code": "not_found",
            "internal_field": "should not leak",
            "traceback": "SELECT * FROM project_rule",
            "details": "C:\\Secret window_title clipboard note",
        },
    )

    result = WebViewBridge().update_project_keyword_rule(999, "Spec")

    assert result == {"ok": False, "error": "关键词规则不存在"}
    lowered = repr(result).lower()
    for forbidden in (
        "internal_field",
        "should not leak",
        "code",
        "not_found",
        "traceback",
        "sqlite",
        "select",
        "window_title",
        "clipboard",
        "note",
        "secret",
        "details",
    ):
        assert forbidden not in lowered


def test_update_project_keyword_rule_success_payload_types_are_stable(monkeypatch):
    monkeypatch.setattr(
        bridge_module.rule_api,
        "update_project_keyword_rule",
        lambda rule_id, keyword: {
            "ok": True,
            "rule": {
                "kind": "keyword",
                "id": rule_id,
                "project_id": 1,
                "keyword": keyword,
                "enabled": 1,
            },
        },
    )

    result = WebViewBridge().update_project_keyword_rule(25, "NewSpec")

    assert type(result["ok"]) is bool
    rule = result["rule"]
    assert type(rule["kind"]) is str
    assert type(rule["id"]) is int
    assert type(rule["project_id"]) is int
    assert type(rule["keyword"]) is str
    assert type(rule["enabled"]) is bool


def test_update_project_keyword_rule_payload_json_serializable(monkeypatch):
    monkeypatch.setattr(
        bridge_module.rule_api,
        "update_project_keyword_rule",
        lambda rule_id, keyword: {
            "ok": True,
            "rule": {
                "kind": "keyword",
                "id": rule_id,
                "project_id": 1,
                "keyword": keyword,
                "enabled": True,
            },
        },
    )

    result = WebViewBridge().update_project_keyword_rule(20, "NewSpec")

    json.dumps(result, ensure_ascii=False)
    assert "Traceback" not in repr(result)
    assert "SELECT" not in repr(result)


def test_update_project_keyword_rule_success_payload_strips_extra_api_keys(monkeypatch):
    monkeypatch.setattr(
        bridge_module.rule_api,
        "update_project_keyword_rule",
        lambda rule_id, keyword: {
            "ok": True,
            "rule": {
                "kind": "keyword",
                "id": rule_id,
                "project_id": 1,
                "keyword": keyword,
                "enabled": True,
                "created_by": "user",
                "created_at": "2026-06-28T10:00:00",
                "updated_at": "2026-06-28T10:00:00",
                "rule_type": "keyword",
                "pattern": keyword,
                "internal_field": "should not leak",
                "traceback": "SELECT * FROM project_rule",
                "details": "C:\\Secret window_title clipboard note",
            },
        },
    )

    result = WebViewBridge().update_project_keyword_rule(7, "NewSpec")

    rule = result["rule"]
    assert set(rule.keys()) == {"kind", "id", "project_id", "keyword", "enabled"}
    lowered = repr(result).lower()
    for forbidden in (
        "created_by",
        "created_at",
        "updated_at",
        "rule_type",
        "pattern",
        "should not leak",
        "internal_field",
        "traceback",
        "sqlite",
        "select",
        "window_title",
        "clipboard",
        "note",
        "secret",
        "details",
    ):
        assert forbidden not in lowered


def test_update_project_keyword_rule_never_calls_other_project_rules_write_apis(monkeypatch):
    called: dict[str, int] = {}

    def _track(name):
        def _impl(*args, **kwargs):
            called[name] = called.get(name, 0) + 1
            return {"ok": True, "rule": {"kind": "keyword", "id": 1, "deleted": True}}

        return _impl

    monkeypatch.setattr(bridge_module.rule_api, "update_project_keyword_rule", _track("update_keyword"))
    monkeypatch.setattr(bridge_module.rule_api, "set_project_rule_enabled", _track("toggle"))
    monkeypatch.setattr(bridge_module.rule_api, "create_project_keyword_rule", _track("create_keyword"))
    monkeypatch.setattr(bridge_module.rule_api, "delete_project_keyword_rule", _track("delete_keyword"))
    monkeypatch.setattr(bridge_module.rule_api, "create_project_folder_rule", _track("create_folder"))
    monkeypatch.setattr(bridge_module.rule_api, "update_project_folder_rule", _track("update_folder"))
    monkeypatch.setattr(bridge_module.rule_api, "delete_project_folder_rule", _track("delete_folder"))

    WebViewBridge().update_project_keyword_rule(1, "NewSpec")

    assert called == {"update_keyword": 1}


def test_update_project_keyword_rule_never_forwards_bool_rule_id_to_api(monkeypatch):
    called: list = []

    def _spy(*args, **kwargs):
        called.append(args)
        return {"ok": True, "rule": {"kind": "keyword", "id": 1, "project_id": 1, "keyword": "x", "enabled": True}}

    monkeypatch.setattr(bridge_module.rule_api, "update_project_keyword_rule", _spy)
    WebViewBridge().update_project_keyword_rule(True, "NewSpec")
    assert called == []


def test_other_write_apis_do_not_call_update_project_keyword_rule(monkeypatch):
    # Phase 5F regression lock: create/delete/toggle/folder APIs must not
    # invoke the new update-keyword path.
    called: list = []

    def _spy(*args, **kwargs):
        called.append(args)
        return {"ok": True, "rule": {"kind": "keyword", "id": 1, "keyword": "x", "enabled": True}}

    monkeypatch.setattr(bridge_module.rule_api, "update_project_keyword_rule", _spy)
    monkeypatch.setattr(
        bridge_module.rule_api,
        "create_project_keyword_rule",
        lambda project_id, keyword: {"ok": True, "rule": {"kind": "keyword", "id": 1, "project_id": project_id, "keyword": keyword, "enabled": True}},
    )
    monkeypatch.setattr(
        bridge_module.rule_api,
        "delete_project_keyword_rule",
        lambda rule_id: {"ok": True, "rule": {"kind": "keyword", "id": rule_id, "deleted": True}},
    )
    monkeypatch.setattr(
        bridge_module.rule_api,
        "set_project_rule_enabled",
        lambda rule_type, rule_id, enabled: {"ok": True, "rule_type": rule_type, "rule_id": rule_id, "enabled": enabled},
    )
    monkeypatch.setattr(
        bridge_module.rule_api,
        "create_project_folder_rule",
        lambda project_id, folder_path, recursive: {"ok": True, "rule": {"kind": "folder", "id": 1, "project_id": project_id, "folder_path": folder_path, "recursive": recursive, "enabled": True}},
    )
    monkeypatch.setattr(
        bridge_module.rule_api,
        "update_project_folder_rule",
        lambda rule_id, folder_path, recursive: {"ok": True, "rule": {"kind": "folder", "id": rule_id, "project_id": 1, "folder_path": folder_path, "recursive": recursive, "enabled": True}},
    )
    monkeypatch.setattr(
        bridge_module.rule_api,
        "delete_project_folder_rule",
        lambda rule_id: {"ok": True, "rule": {"kind": "folder", "id": rule_id, "deleted": True}},
    )

    bridge = WebViewBridge()
    bridge.create_project_keyword_rule(1, "Spec")
    bridge.delete_project_keyword_rule(1)
    bridge.set_project_rule_enabled("keyword", 1, False)
    bridge.create_project_folder_rule(1, r"D:\Work", True)
    bridge.update_project_folder_rule(1, r"D:\New", False)
    bridge.delete_project_folder_rule(1)

    assert called == []


def test_update_project_keyword_rule_invalid_input_payload_excludes_sensitive_text():
    bridge = WebViewBridge()
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
        bridge_module.rule_api,
        "update_project_keyword_rule",
        lambda rule_id, keyword: {"ok": False, "error": "operation_failed"},
    )

    # Invalid input failures.
    for bad_id in (True, None, 0, -1, "1", 1.0, [], {}):
        result = WebViewBridge().update_project_keyword_rule(bad_id, "Spec")
        json.dumps(result, ensure_ascii=False)
    for bad_keyword in (None, True, 1, "", "   "):
        result = WebViewBridge().update_project_keyword_rule(1, bad_keyword)
        json.dumps(result, ensure_ascii=False)

    # API error code failures.
    for code in ("invalid_input", "not_found", "duplicate_rule", "operation_failed", "unknown"):
        monkeypatch.setattr(
            bridge_module.rule_api,
            "update_project_keyword_rule",
            lambda rule_id, keyword, c=code: {"ok": False, "error": c},
        )
        result = WebViewBridge().update_project_keyword_rule(1, "Spec")
        json.dumps(result, ensure_ascii=False)
        assert "Traceback" not in repr(result)
