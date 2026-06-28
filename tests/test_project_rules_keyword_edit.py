"""Phase 5F API / service regression locks for keyword rule edit.

These tests lock the narrow ``rule_api.update_project_keyword_rule`` facade
introduced in Phase 5F. They cover valid update of an existing keyword
rule's keyword text, input validation (bool-as-int, numeric string,
float, zero / negative, list / dict / tuple / set / frozenset,
non-string keyword, whitespace-only keyword), ``not_found`` for unknown
ids and folder-rule ids, ``duplicate_rule`` for same-project duplicates
(while allowing same-keyword-across-projects and update-to-own-keyword),
exception collapse to ``operation_failed``, cache invalidation
preservation, no-side-effect guarantees (no folder rule / project /
enabled / created_by / created_at touched), JSON serializability, and
existing keyword create / delete / rule enable-disable regression locks.
"""

from __future__ import annotations

import json

import pytest

from worktrace.api import rule_api
from worktrace.db import get_connection
from worktrace.services import (
    folder_rule_service,
    privacy_service,
    project_inference_service,
    project_service,
    rule_service,
)


def _counts() -> dict[str, int]:
    with get_connection() as conn:
        return {
            "project": conn.execute("SELECT COUNT(*) AS c FROM project").fetchone()["c"],
            "folder": conn.execute("SELECT COUNT(*) AS c FROM folder_project_rule").fetchone()["c"],
            "keyword": conn.execute("SELECT COUNT(*) AS c FROM project_rule").fetchone()["c"],
        }


def _keyword_rule_row(rule_id: int) -> dict:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id, project_id, rule_type, pattern, enabled, created_by, created_at, updated_at "
            "FROM project_rule WHERE id = ?",
            (rule_id,),
        ).fetchone()
    return dict(row) if row else {}


# --- Valid update --------------------------------------------------------


def test_update_keyword_rule_succeeds(temp_db):
    project = project_service.create_project("Client")
    rule_id = rule_service.create_rule("Spec", project)

    result = rule_api.update_project_keyword_rule(rule_id, "Spec-Updated")

    assert result["ok"] is True
    rule = result["rule"]
    assert rule["kind"] == "keyword"
    assert type(rule["id"]) is int
    assert rule["id"] == rule_id
    assert rule["project_id"] == project
    assert rule["keyword"] == "Spec-Updated"
    assert rule["enabled"] is True
    # The DB row must reflect the new keyword.
    row = _keyword_rule_row(rule_id)
    assert row["pattern"] == "Spec-Updated"


def test_update_keyword_rule_trims_keyword(temp_db):
    project = project_service.create_project("Client")
    rule_id = rule_service.create_rule("Spec", project)

    result = rule_api.update_project_keyword_rule(rule_id, "  Spec-Updated  ")

    assert result["ok"] is True
    assert result["rule"]["keyword"] == "Spec-Updated"
    row = _keyword_rule_row(rule_id)
    assert row["pattern"] == "Spec-Updated"


def test_update_keyword_rule_preserves_rule_id_project_id_enabled(temp_db):
    project = project_service.create_project("Client")
    rule_id = rule_service.create_rule("Spec", project)
    rule_service.set_rule_enabled(rule_id, False)

    result = rule_api.update_project_keyword_rule(rule_id, "NewSpec")

    assert result["ok"] is True
    rule = result["rule"]
    assert rule["id"] == rule_id
    assert rule["project_id"] == project
    assert rule["enabled"] is False
    row = _keyword_rule_row(rule_id)
    assert row["project_id"] == project
    assert row["enabled"] == 0


def test_update_keyword_rule_preserves_created_by_and_created_at(temp_db):
    project = project_service.create_project("Client")
    rule_id = rule_service.create_rule("Spec", project)
    before = _keyword_rule_row(rule_id)
    assert before["created_by"] == "user"
    original_created_at = before["created_at"]

    result = rule_api.update_project_keyword_rule(rule_id, "NewSpec")

    assert result["ok"] is True
    after = _keyword_rule_row(rule_id)
    assert after["created_by"] == "user"
    assert after["created_at"] == original_created_at


# --- rule_id input validation -------------------------------------------


@pytest.mark.parametrize("bad_id", [True, False])
def test_update_keyword_rule_rejects_bool_as_int_rule_id(temp_db, bad_id):
    result = rule_api.update_project_keyword_rule(bad_id, "Spec")
    assert result == {"ok": False, "error": "invalid_input"}


@pytest.mark.parametrize("bad_id", ["1", "abc", "true"])
def test_update_keyword_rule_rejects_numeric_string_rule_id(temp_db, bad_id):
    result = rule_api.update_project_keyword_rule(bad_id, "Spec")
    assert result == {"ok": False, "error": "invalid_input"}


@pytest.mark.parametrize("bad_id", [1.0, 2.5, -1.5])
def test_update_keyword_rule_rejects_float_rule_id(temp_db, bad_id):
    result = rule_api.update_project_keyword_rule(bad_id, "Spec")
    assert result == {"ok": False, "error": "invalid_input"}


@pytest.mark.parametrize("bad_id", [0, -1, -999])
def test_update_keyword_rule_rejects_zero_and_negative_rule_id(temp_db, bad_id):
    result = rule_api.update_project_keyword_rule(bad_id, "Spec")
    assert result == {"ok": False, "error": "invalid_input"}


@pytest.mark.parametrize(
    "bad_id", [None, [], {}, (), {1, 2}, (1,), frozenset({1})]
)
def test_update_keyword_rule_rejects_other_invalid_rule_id_types(temp_db, bad_id):
    result = rule_api.update_project_keyword_rule(bad_id, "Spec")
    assert result == {"ok": False, "error": "invalid_input"}


# --- keyword input validation -------------------------------------------


@pytest.mark.parametrize(
    "bad_keyword", [None, True, False, 1, 1.0, [], {}, (), {1, 2}, frozenset({1})]
)
def test_update_keyword_rule_rejects_non_string_keyword(temp_db, bad_keyword):
    project = project_service.create_project("Client")
    rule_id = rule_service.create_rule("Spec", project)

    result = rule_api.update_project_keyword_rule(rule_id, bad_keyword)
    assert result == {"ok": False, "error": "invalid_input"}


@pytest.mark.parametrize("bad_keyword", ["", "   ", "\t", "\n", "  \t  "])
def test_update_keyword_rule_rejects_whitespace_only_keyword(temp_db, bad_keyword):
    project = project_service.create_project("Client")
    rule_id = rule_service.create_rule("Spec", project)

    result = rule_api.update_project_keyword_rule(rule_id, bad_keyword)
    assert result == {"ok": False, "error": "invalid_input"}


# --- not_found -----------------------------------------------------------


def test_unknown_keyword_rule_id_returns_not_found(temp_db):
    result = rule_api.update_project_keyword_rule(9999, "Spec")
    assert result == {"ok": False, "error": "not_found"}


def test_folder_rule_id_returns_not_found_and_does_not_modify_folder_rule(temp_db):
    project = project_service.create_project("Client")
    folder_rule_id = folder_rule_service.create_or_update_folder_rule(
        r"D:\Client", project
    )

    result = rule_api.update_project_keyword_rule(folder_rule_id, "Spec")

    assert result == {"ok": False, "error": "not_found"}
    # The folder rule must still exist and be unmodified.
    folder_rules = folder_rule_service.list_folder_rules()
    matching = [r for r in folder_rules if int(r.get("id") or 0) == folder_rule_id]
    assert len(matching) == 1


# --- duplicate_rule ------------------------------------------------------


def test_duplicate_keyword_in_same_project_returns_duplicate_rule(temp_db):
    project = project_service.create_project("Client")
    rule_service.create_rule("Existing", project)
    rule_id = rule_service.create_rule("Original", project)

    result = rule_api.update_project_keyword_rule(rule_id, "Existing")

    assert result == {"ok": False, "error": "duplicate_rule"}
    # The rule being updated must not have changed.
    row = _keyword_rule_row(rule_id)
    assert row["pattern"] == "Original"


def test_same_keyword_in_different_project_allowed(temp_db):
    project_a = project_service.create_project("ClientA")
    project_b = project_service.create_project("ClientB")
    rule_service.create_rule("Shared", project_a)
    rule_id_b = rule_service.create_rule("Original", project_b)

    result = rule_api.update_project_keyword_rule(rule_id_b, "Shared")

    assert result["ok"] is True
    assert result["rule"]["keyword"] == "Shared"


def test_updating_to_own_current_keyword_succeeds(temp_db):
    project = project_service.create_project("Client")
    rule_id = rule_service.create_rule("Spec", project)

    result = rule_api.update_project_keyword_rule(rule_id, "Spec")

    assert result["ok"] is True
    assert result["rule"]["keyword"] == "Spec"


# --- Exception collapse --------------------------------------------------


def test_service_exception_collapses_to_operation_failed(temp_db, monkeypatch):
    project = project_service.create_project("Client")
    rule_id = rule_service.create_rule("Spec", project)

    def boom(rule_id_arg, keyword_arg):
        raise RuntimeError(
            "boom SELECT * FROM activity_log traceback window_title clipboard note C:\\Secret"
        )

    monkeypatch.setattr(rule_service, "update_rule", boom)
    result = rule_api.update_project_keyword_rule(rule_id, "NewSpec")
    assert result == {"ok": False, "error": "operation_failed"}
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
        "c:\\secret",
    ):
        assert forbidden not in lowered


# --- Cache invalidation --------------------------------------------------


def test_update_keyword_rule_invalidates_keyword_rule_cache(temp_db, monkeypatch):
    project = project_service.create_project("Client")
    rule_id = rule_service.create_rule("Spec", project)
    project_inference_service.invalidate_keyword_rule_cache()

    calls = {"count": 0}
    original = project_inference_service.invalidate_keyword_rule_cache

    def spy():
        calls["count"] += 1
        original()

    monkeypatch.setattr(rule_service, "invalidate_keyword_rule_cache", spy)
    monkeypatch.setattr(
        "worktrace.services.rule_service.invalidate_keyword_rule_cache", spy
    )

    result = rule_api.update_project_keyword_rule(rule_id, "NewSpec")

    assert result["ok"] is True
    assert calls["count"] >= 1


def test_update_keyword_rule_clears_exclude_rules_cache(temp_db, monkeypatch):
    project = project_service.create_project("Client")
    rule_id = rule_service.create_rule("Spec", project)

    calls = {"count": 0}
    original = privacy_service.clear_exclude_rules_cache

    def spy():
        calls["count"] += 1
        original()

    monkeypatch.setattr(privacy_service, "clear_exclude_rules_cache", spy)

    result = rule_api.update_project_keyword_rule(rule_id, "NewSpec")

    assert result["ok"] is True
    assert calls["count"] >= 1


def test_invalid_input_does_not_trigger_cache_hooks(temp_db, monkeypatch):
    invalidate_calls = {"count": 0}
    clear_calls = {"count": 0}

    def spy_invalidate():
        invalidate_calls["count"] += 1

    def spy_clear():
        clear_calls["count"] += 1

    monkeypatch.setattr(rule_service, "invalidate_keyword_rule_cache", spy_invalidate)
    monkeypatch.setattr(
        "worktrace.services.rule_service.invalidate_keyword_rule_cache", spy_invalidate
    )
    monkeypatch.setattr(privacy_service, "clear_exclude_rules_cache", spy_clear)

    # Various invalid_input cases.
    for bad_id, bad_keyword in [
        (True, "Spec"),
        (None, "Spec"),
        (0, "Spec"),
        (-1, "Spec"),
        (1, None),
        (1, 123),
        (1, "   "),
    ]:
        result = rule_api.update_project_keyword_rule(bad_id, bad_keyword)
        assert result == {"ok": False, "error": "invalid_input"}

    assert invalidate_calls["count"] == 0
    assert clear_calls["count"] == 0


def test_not_found_does_not_trigger_cache_hooks(temp_db, monkeypatch):
    invalidate_calls = {"count": 0}
    clear_calls = {"count": 0}

    def spy_invalidate():
        invalidate_calls["count"] += 1

    def spy_clear():
        clear_calls["count"] += 1

    monkeypatch.setattr(rule_service, "invalidate_keyword_rule_cache", spy_invalidate)
    monkeypatch.setattr(
        "worktrace.services.rule_service.invalidate_keyword_rule_cache", spy_invalidate
    )
    monkeypatch.setattr(privacy_service, "clear_exclude_rules_cache", spy_clear)

    result = rule_api.update_project_keyword_rule(9999, "Spec")

    assert result == {"ok": False, "error": "not_found"}
    assert invalidate_calls["count"] == 0
    assert clear_calls["count"] == 0


def test_duplicate_rule_does_not_trigger_cache_hooks(temp_db, monkeypatch):
    project = project_service.create_project("Client")
    rule_service.create_rule("Existing", project)
    rule_id = rule_service.create_rule("Original", project)

    invalidate_calls = {"count": 0}
    clear_calls = {"count": 0}

    def spy_invalidate():
        invalidate_calls["count"] += 1

    def spy_clear():
        clear_calls["count"] += 1

    monkeypatch.setattr(rule_service, "invalidate_keyword_rule_cache", spy_invalidate)
    monkeypatch.setattr(
        "worktrace.services.rule_service.invalidate_keyword_rule_cache", spy_invalidate
    )
    monkeypatch.setattr(privacy_service, "clear_exclude_rules_cache", spy_clear)

    result = rule_api.update_project_keyword_rule(rule_id, "Existing")

    assert result == {"ok": False, "error": "duplicate_rule"}
    assert invalidate_calls["count"] == 0
    assert clear_calls["count"] == 0


# --- Payload contract ----------------------------------------------------


def test_update_keyword_rule_success_payload_is_json_serializable(temp_db):
    project = project_service.create_project("Client")
    rule_id = rule_service.create_rule("Spec", project)

    result = rule_api.update_project_keyword_rule(rule_id, "NewSpec")

    json.dumps(result, ensure_ascii=False)
    assert "Traceback" not in repr(result)
    assert "SELECT" not in repr(result)


def test_update_keyword_rule_success_payload_types_are_stable(temp_db):
    project = project_service.create_project("Client")
    rule_id = rule_service.create_rule("Spec", project)

    result = rule_api.update_project_keyword_rule(rule_id, "NewSpec")

    assert type(result["ok"]) is bool
    rule = result["rule"]
    assert type(rule["kind"]) is str
    assert type(rule["id"]) is int
    assert type(rule["project_id"]) is int
    assert type(rule["keyword"]) is str
    assert type(rule["enabled"]) is bool


def test_update_keyword_rule_failure_payloads_are_json_serializable(temp_db):
    project = project_service.create_project("Client")
    rule_id = rule_service.create_rule("Spec", project)

    failures = [
        rule_api.update_project_keyword_rule(True, "Spec"),
        rule_api.update_project_keyword_rule(rule_id, None),
        rule_api.update_project_keyword_rule(9999, "Spec"),
        rule_api.update_project_keyword_rule(rule_id, "   "),
    ]
    # Create a duplicate scenario.
    rule_service.create_rule("Existing", project)
    failures.append(rule_api.update_project_keyword_rule(rule_id, "Existing"))

    for result in failures:
        assert result["ok"] is False
        json.dumps(result, ensure_ascii=False)
        assert "Traceback" not in repr(result)
        assert "SELECT" not in repr(result)


def test_update_keyword_rule_success_payload_excludes_sensitive_metadata(temp_db):
    project = project_service.create_project("Client")
    rule_id = rule_service.create_rule("Spec", project)

    result = rule_api.update_project_keyword_rule(rule_id, "NewSpec")

    rendered = repr(result)
    for forbidden in (
        "traceback",
        "Traceback",
        "sqlite",
        "SELECT",
        "window_title",
        "clipboard",
        "note",
        "created_by",
        "created_at",
        "updated_at",
        "rule_type",
        "pattern",
    ):
        assert forbidden not in rendered


# --- No side effects -----------------------------------------------------


def test_update_keyword_rule_does_not_modify_folder_rules(temp_db):
    project = project_service.create_project("Client")
    folder_rule_id = folder_rule_service.create_or_update_folder_rule(
        r"D:\Client", project
    )
    keyword_rule_id = rule_service.create_rule("Spec", project)
    before = _counts()

    result = rule_api.update_project_keyword_rule(keyword_rule_id, "NewSpec")

    assert result["ok"] is True
    after = _counts()
    assert after["folder"] == before["folder"]
    # The folder rule must still exist.
    folder_rules = folder_rule_service.list_folder_rules()
    assert any(int(r.get("id") or 0) == folder_rule_id for r in folder_rules)


def test_update_keyword_rule_does_not_modify_project_table(temp_db):
    project = project_service.create_project("Client")
    rule_id = rule_service.create_rule("Spec", project)
    before = _counts()

    result = rule_api.update_project_keyword_rule(rule_id, "NewSpec")

    assert result["ok"] is True
    after = _counts()
    assert after["project"] == before["project"]


def test_update_keyword_rule_does_not_modify_enabled_state(temp_db):
    project = project_service.create_project("Client")
    rule_id = rule_service.create_rule("Spec", project)
    rule_service.set_rule_enabled(rule_id, False)

    result = rule_api.update_project_keyword_rule(rule_id, "NewSpec")

    assert result["ok"] is True
    assert result["rule"]["enabled"] is False
    row = _keyword_rule_row(rule_id)
    assert row["enabled"] == 0


def test_update_keyword_rule_does_not_modify_created_by(temp_db):
    project = project_service.create_project("Client")
    rule_id = rule_service.create_rule("Spec", project)

    result = rule_api.update_project_keyword_rule(rule_id, "NewSpec")

    assert result["ok"] is True
    row = _keyword_rule_row(rule_id)
    assert row["created_by"] == "user"


# --- Existing regression locks -------------------------------------------


def test_existing_create_keyword_rule_still_works(temp_db):
    project = project_service.create_project("Client")

    result = rule_api.create_project_keyword_rule(project, "Spec")

    assert result["ok"] is True
    assert result["rule"]["keyword"] == "Spec"


def test_existing_delete_keyword_rule_still_works(temp_db):
    project = project_service.create_project("Client")
    rule_id = rule_service.create_rule("Spec", project)

    result = rule_api.delete_project_keyword_rule(rule_id)

    assert result["ok"] is True


def test_existing_set_project_rule_enabled_still_works(temp_db):
    project = project_service.create_project("Client")
    rule_id = rule_service.create_rule("Spec", project)

    disabled = rule_api.set_project_rule_enabled("keyword", rule_id, False)
    assert disabled == {
        "ok": True,
        "rule_type": "keyword",
        "rule_id": rule_id,
        "enabled": False,
    }
    enabled = rule_api.set_project_rule_enabled("keyword", rule_id, True)
    assert enabled == {
        "ok": True,
        "rule_type": "keyword",
        "rule_id": rule_id,
        "enabled": True,
    }
