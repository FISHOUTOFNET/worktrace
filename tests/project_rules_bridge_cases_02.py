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
