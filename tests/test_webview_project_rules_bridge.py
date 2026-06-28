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
