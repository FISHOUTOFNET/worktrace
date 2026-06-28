"""Phase 5E API / service regression locks for folder rule CRUD.

These tests lock the narrow ``rule_api.create_project_folder_rule``,
``rule_api.update_project_folder_rule``, and
``rule_api.delete_project_folder_rule`` facades introduced in Phase 5E.
They cover valid creation, input validation, project-eligibility rejection,
create-or-update semantics, update / delete isolation between folder and
keyword rules, exception collapse, no-side-effect guarantees (no keyword
rule / project / activity / assignment / session-note rows touched, no
conflict preview / backfill invoked), JSON serializability, and the
existing ``set_project_rule_enabled`` / ``create_project_keyword_rule`` /
``delete_project_keyword_rule`` regression locks.
"""

from __future__ import annotations

import json

import pytest

from worktrace.api import rule_api
from worktrace.db import get_connection
from worktrace.services import (
    folder_rule_service,
    project_service,
    rule_service,
)


def _counts() -> dict[str, int]:
    with get_connection() as conn:
        return {
            "project": conn.execute("SELECT COUNT(*) AS c FROM project").fetchone()["c"],
            "folder": conn.execute("SELECT COUNT(*) AS c FROM folder_project_rule").fetchone()["c"],
            "keyword": conn.execute("SELECT COUNT(*) AS c FROM project_rule").fetchone()["c"],
            "activity": conn.execute("SELECT COUNT(*) AS c FROM activity_log").fetchone()["c"],
            "assignment": conn.execute(
                "SELECT COUNT(*) AS c FROM activity_project_assignment"
            ).fetchone()["c"],
            "session_note": conn.execute(
                "SELECT COUNT(*) AS c FROM project_session_note"
            ).fetchone()["c"],
        }


def _folder_rule_row(rule_id: int) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id, project_id, folder_path, normalized_folder_key, "
            "recursive, enabled FROM folder_project_rule WHERE id = ?",
            (rule_id,),
        ).fetchone()
    return dict(row) if row else None


def _keyword_rule_row(rule_id: int) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id, project_id, pattern, enabled FROM project_rule WHERE id = ?",
            (rule_id,),
        ).fetchone()
    return dict(row) if row else None


# --- Valid creation ------------------------------------------------------


def test_create_folder_rule_for_normal_project(temp_db):
    project = project_service.create_project("Client")

    result = rule_api.create_project_folder_rule(project, r"D:\Work\Client", True)

    assert result["ok"] is True
    rule = result["rule"]
    assert rule["kind"] == "folder"
    assert isinstance(rule["id"], int)
    assert rule["id"] > 0
    assert rule["project_id"] == project
    assert rule["folder_path"] == r"D:\Work\Client"
    assert rule["recursive"] is True
    assert rule["enabled"] is True

    row = _folder_rule_row(rule["id"])
    assert row["project_id"] == project
    assert row["folder_path"] == r"D:\Work\Client"
    assert row["recursive"] == 1
    assert row["enabled"] == 1


def test_create_folder_rule_non_recursive(temp_db):
    project = project_service.create_project("Client")

    result = rule_api.create_project_folder_rule(project, r"D:\Work\Client", False)

    assert result["ok"] is True
    assert result["rule"]["recursive"] is False
    row = _folder_rule_row(result["rule"]["id"])
    assert row["recursive"] == 0


def test_create_folder_rule_trims_path_before_create(temp_db):
    project = project_service.create_project("Client")

    result = rule_api.create_project_folder_rule(project, "  D:\\Work\\Client  ", True)

    assert result["ok"] is True
    assert result["rule"]["folder_path"] == r"D:\Work\Client"
    row = _folder_rule_row(result["rule"]["id"])
    assert row["folder_path"] == r"D:\Work\Client"


def test_create_folder_rule_for_excluded_project_rejected(temp_db):
    excluded_id = project_service.get_or_create_excluded_project()

    result = rule_api.create_project_folder_rule(excluded_id, r"D:\Secret", True)

    assert result == {"ok": False, "error": "project_not_found"}
    assert _folder_rule_row_by_path(r"D:\Secret") is None


def test_create_folder_rule_for_archived_project_rejected(temp_db):
    project = project_service.create_project("Archived")
    project_service.archive_project(project)

    result = rule_api.create_project_folder_rule(project, r"D:\Archived", True)

    assert result == {"ok": False, "error": "project_not_found"}


def test_create_folder_rule_for_disabled_project_rejected(temp_db):
    project = project_service.create_project("Disabled")
    project_service.set_project_enabled(project, False)

    result = rule_api.create_project_folder_rule(project, r"D:\Disabled", True)

    assert result == {"ok": False, "error": "project_not_found"}


def _folder_rule_row_by_path(folder_path: str) -> dict | None:
    from worktrace.path_utils import normalize_folder_key

    key = normalize_folder_key(folder_path)
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id, project_id, folder_path, recursive, enabled "
            "FROM folder_project_rule WHERE normalized_folder_key = ?",
            (key,),
        ).fetchone()
    return dict(row) if row else None


def test_create_folder_rule_create_or_update_semantics(temp_db):
    # The underlying service uses INSERT ... ON CONFLICT(normalized_folder_key)
    # DO UPDATE, so creating a folder rule with the same normalized key as an
    # existing one updates the existing row in place (folder_path / project_id
    # / recursive / enabled are overwritten, enabled is reset to 1). The API
    # wraps this as a stable "create/update single folder rule" contract.
    project_a = project_service.create_project("ClientA")
    project_b = project_service.create_project("ClientB")
    first = rule_api.create_project_folder_rule(project_a, r"D:\Work", True)
    assert first["ok"] is True
    first_id = first["rule"]["id"]

    # Same normalized key (same path after normalization) -> updates existing row.
    second = rule_api.create_project_folder_rule(project_b, r"D:\Work", False)

    assert second["ok"] is True
    assert second["rule"]["id"] == first_id
    assert second["rule"]["project_id"] == project_b
    assert second["rule"]["recursive"] is False
    assert second["rule"]["enabled"] is True

    row = _folder_rule_row(first_id)
    assert row["project_id"] == project_b
    assert row["recursive"] == 0
    assert row["enabled"] == 1


# --- project_id input validation ----------------------------------------


@pytest.mark.parametrize("bad_id", [True, False])
def test_create_folder_rule_rejects_bool_as_int_project_id(temp_db, bad_id):
    result = rule_api.create_project_folder_rule(bad_id, r"D:\Work", True)
    assert result == {"ok": False, "error": "invalid_input"}


@pytest.mark.parametrize("bad_id", ["1", "abc", "true"])
def test_create_folder_rule_rejects_numeric_string_project_id(temp_db, bad_id):
    result = rule_api.create_project_folder_rule(bad_id, r"D:\Work", True)
    assert result == {"ok": False, "error": "invalid_input"}


@pytest.mark.parametrize("bad_id", [1.0, 2.5, -1.5])
def test_create_folder_rule_rejects_float_project_id(temp_db, bad_id):
    result = rule_api.create_project_folder_rule(bad_id, r"D:\Work", True)
    assert result == {"ok": False, "error": "invalid_input"}


@pytest.mark.parametrize("bad_id", [0, -1, -999])
def test_create_folder_rule_rejects_zero_and_negative_project_id(temp_db, bad_id):
    result = rule_api.create_project_folder_rule(bad_id, r"D:\Work", True)
    assert result == {"ok": False, "error": "invalid_input"}


@pytest.mark.parametrize("bad_id", [None, [], {}, (), {1, 2}, (1,), frozenset({1})])
def test_create_folder_rule_rejects_other_invalid_project_id_types(temp_db, bad_id):
    result = rule_api.create_project_folder_rule(bad_id, r"D:\Work", True)
    assert result == {"ok": False, "error": "invalid_input"}


# --- folder_path input validation --------------------------------------


def test_create_folder_rule_rejects_none_folder_path(temp_db):
    project = project_service.create_project("Client")
    result = rule_api.create_project_folder_rule(project, None, True)
    assert result == {"ok": False, "error": "invalid_input"}


@pytest.mark.parametrize("bad_path", [True, False, 1, 1.0, 2.5, [], {}, (), {1, 2}, (1,), frozenset({1})])
def test_create_folder_rule_rejects_non_string_folder_path(temp_db, bad_path):
    project = project_service.create_project("Client")
    result = rule_api.create_project_folder_rule(project, bad_path, True)
    assert result == {"ok": False, "error": "invalid_input"}


def test_create_folder_rule_rejects_empty_folder_path(temp_db):
    project = project_service.create_project("Client")
    result = rule_api.create_project_folder_rule(project, "", True)
    assert result == {"ok": False, "error": "invalid_input"}


@pytest.mark.parametrize("bad_path", ["   ", "\t", "\n", "  \t  "])
def test_create_folder_rule_rejects_whitespace_only_folder_path(temp_db, bad_path):
    project = project_service.create_project("Client")
    result = rule_api.create_project_folder_rule(project, bad_path, True)
    assert result == {"ok": False, "error": "invalid_input"}


# --- recursive input validation ----------------------------------------


@pytest.mark.parametrize("bad_recursive", [None, "true", 1, 0, 1.0, [], {}, (), {1, 2}, (1,), frozenset({1})])
def test_create_folder_rule_rejects_non_bool_recursive(temp_db, bad_recursive):
    project = project_service.create_project("Client")
    result = rule_api.create_project_folder_rule(project, r"D:\Work", bad_recursive)
    assert result == {"ok": False, "error": "invalid_input"}


# --- project_not_found ---------------------------------------------------


def test_create_folder_rule_unknown_project_returns_stable_project_not_found(temp_db):
    result = rule_api.create_project_folder_rule(9999, r"D:\Work", True)
    assert result == {"ok": False, "error": "project_not_found"}


# --- Exception collapse --------------------------------------------------


def test_create_folder_rule_service_exception_collapses_to_operation_failed(temp_db, monkeypatch):
    project = project_service.create_project("Client")

    def _boom(*args, **kwargs):
        raise RuntimeError("boom: sensitive SQL SELECT * FROM ...")

    monkeypatch.setattr(folder_rule_service, "create_or_update_folder_rule", _boom)

    result = rule_api.create_project_folder_rule(project, r"D:\Work", True)

    assert result == {"ok": False, "error": "operation_failed"}
    lowered = repr(result).lower()
    for forbidden in ("boom", "select", "sensitive", "traceback", "runtimeerror"):
        assert forbidden not in lowered


# --- No side effects ----------------------------------------------------


def test_create_folder_rule_no_side_effects_on_other_tables(temp_db):
    project = project_service.create_project("Client")
    before = _counts()

    rule_api.create_project_folder_rule(project, r"D:\Work\Client", True)

    after = _counts()
    assert after["project"] == before["project"]
    assert after["folder"] == before["folder"] + 1
    assert after["keyword"] == before["keyword"]
    assert after["activity"] == before["activity"]
    assert after["assignment"] == before["assignment"]
    assert after["session_note"] == before["session_note"]


def test_create_folder_rule_does_not_create_keyword_rule(temp_db):
    project = project_service.create_project("Client")

    rule_api.create_project_folder_rule(project, r"D:\Work\Client", True)

    with get_connection() as conn:
        count = conn.execute(
            "SELECT COUNT(*) AS c FROM project_rule WHERE project_id = ?",
            (project,),
        ).fetchone()["c"]
    assert count == 0


# --- JSON serializable ---------------------------------------------------


def test_create_folder_rule_payload_json_serializable(temp_db):
    project = project_service.create_project("Client")

    result = rule_api.create_project_folder_rule(project, r"D:\Work\Client", True)

    json.dumps(result, ensure_ascii=False)


# --- Update folder rule --------------------------------------------------


def test_update_folder_rule_success(temp_db):
    project = project_service.create_project("Client")
    created = rule_api.create_project_folder_rule(project, r"D:\Old", True)
    rule_id = created["rule"]["id"]

    result = rule_api.update_project_folder_rule(rule_id, r"D:\New", False)

    assert result["ok"] is True
    rule = result["rule"]
    assert rule["kind"] == "folder"
    assert rule["id"] == rule_id
    assert rule["folder_path"] == r"D:\New"
    assert rule["recursive"] is False

    row = _folder_rule_row(rule_id)
    assert row["folder_path"] == r"D:\New"
    assert row["recursive"] == 0


def test_update_folder_rule_preserves_project_id(temp_db):
    project = project_service.create_project("Client")
    created = rule_api.create_project_folder_rule(project, r"D:\Old", True)
    rule_id = created["rule"]["id"]

    result = rule_api.update_project_folder_rule(rule_id, r"D:\New", False)

    assert result["ok"] is True
    assert result["rule"]["project_id"] == project
    row = _folder_rule_row(rule_id)
    assert row["project_id"] == project


def test_update_folder_rule_trims_path(temp_db):
    project = project_service.create_project("Client")
    created = rule_api.create_project_folder_rule(project, r"D:\Old", True)
    rule_id = created["rule"]["id"]

    result = rule_api.update_project_folder_rule(rule_id, "  D:\\New  ", True)

    assert result["ok"] is True
    assert result["rule"]["folder_path"] == r"D:\New"


@pytest.mark.parametrize("bad_id", [True, False, "1", "abc", 0, -1, 1.0, 2.5, None, [], {}, (), (1,), frozenset({1})])
def test_update_folder_rule_rejects_invalid_rule_id(temp_db, bad_id):
    result = rule_api.update_project_folder_rule(bad_id, r"D:\New", True)
    assert result == {"ok": False, "error": "invalid_input"}


@pytest.mark.parametrize("bad_path", [None, True, False, 1, 1.0, [], {}, "", "   ", "\t", "\n", "  \t  "])
def test_update_folder_rule_rejects_invalid_folder_path(temp_db, bad_path):
    project = project_service.create_project("Client")
    created = rule_api.create_project_folder_rule(project, r"D:\Old", True)
    rule_id = created["rule"]["id"]

    result = rule_api.update_project_folder_rule(rule_id, bad_path, True)

    assert result == {"ok": False, "error": "invalid_input"}


@pytest.mark.parametrize("bad_recursive", [None, "true", 1, 0, 1.0, [], {}, (), (1,), frozenset({1})])
def test_update_folder_rule_rejects_non_bool_recursive(temp_db, bad_recursive):
    project = project_service.create_project("Client")
    created = rule_api.create_project_folder_rule(project, r"D:\Old", True)
    rule_id = created["rule"]["id"]

    result = rule_api.update_project_folder_rule(rule_id, r"D:\New", bad_recursive)

    assert result == {"ok": False, "error": "invalid_input"}


def test_update_folder_rule_missing_rule_id_returns_not_found(temp_db):
    result = rule_api.update_project_folder_rule(9999, r"D:\New", True)
    assert result == {"ok": False, "error": "not_found"}


def test_update_folder_rule_keyword_rule_id_returns_not_found(temp_db):
    # A keyword rule id passed to the folder update path must return
    # ``not_found`` rather than modifying the keyword rule.
    project = project_service.create_project("Client")
    keyword_id = rule_service.create_rule("Spec", project)

    result = rule_api.update_project_folder_rule(keyword_id, r"D:\New", True)

    assert result == {"ok": False, "error": "not_found"}
    # The keyword rule must be untouched.
    row = _keyword_rule_row(keyword_id)
    assert row is not None
    assert row["pattern"] == "Spec"
    assert row["project_id"] == project


def test_update_folder_rule_no_side_effects_on_other_tables(temp_db):
    project = project_service.create_project("Client")
    created = rule_api.create_project_folder_rule(project, r"D:\Old", True)
    rule_id = created["rule"]["id"]
    before = _counts()

    rule_api.update_project_folder_rule(rule_id, r"D:\New", False)

    after = _counts()
    assert after["project"] == before["project"]
    assert after["folder"] == before["folder"]
    assert after["keyword"] == before["keyword"]
    assert after["activity"] == before["activity"]
    assert after["assignment"] == before["assignment"]
    assert after["session_note"] == before["session_note"]


def test_update_folder_rule_does_not_modify_keyword_rule(temp_db):
    project = project_service.create_project("Client")
    keyword_id = rule_service.create_rule("Spec", project)
    created = rule_api.create_project_folder_rule(project, r"D:\Old", True)
    rule_id = created["rule"]["id"]

    rule_api.update_project_folder_rule(rule_id, r"D:\New", False)

    row = _keyword_rule_row(keyword_id)
    assert row["pattern"] == "Spec"


def test_update_folder_rule_payload_json_serializable(temp_db):
    project = project_service.create_project("Client")
    created = rule_api.create_project_folder_rule(project, r"D:\Old", True)
    rule_id = created["rule"]["id"]

    result = rule_api.update_project_folder_rule(rule_id, r"D:\New", False)

    json.dumps(result, ensure_ascii=False)


def test_update_folder_rule_service_exception_collapses_to_operation_failed(temp_db, monkeypatch):
    project = project_service.create_project("Client")
    created = rule_api.create_project_folder_rule(project, r"D:\Old", True)
    rule_id = created["rule"]["id"]

    def _boom(*args, **kwargs):
        raise RuntimeError("boom: sensitive SQL SELECT * FROM ...")

    monkeypatch.setattr(folder_rule_service, "update_folder_rule", _boom)

    result = rule_api.update_project_folder_rule(rule_id, r"D:\New", False)

    assert result == {"ok": False, "error": "operation_failed"}
    lowered = repr(result).lower()
    for forbidden in ("boom", "select", "sensitive", "traceback", "runtimeerror"):
        assert forbidden not in lowered


# --- Delete folder rule --------------------------------------------------


def test_delete_folder_rule_success(temp_db):
    project = project_service.create_project("Client")
    created = rule_api.create_project_folder_rule(project, r"D:\Work", True)
    rule_id = created["rule"]["id"]

    result = rule_api.delete_project_folder_rule(rule_id)

    assert result["ok"] is True
    rule = result["rule"]
    assert rule["kind"] == "folder"
    assert rule["id"] == rule_id
    assert rule["deleted"] is True

    assert _folder_rule_row(rule_id) is None


def test_delete_folder_rule_second_time_returns_not_found(temp_db):
    project = project_service.create_project("Client")
    created = rule_api.create_project_folder_rule(project, r"D:\Work", True)
    rule_id = created["rule"]["id"]

    first = rule_api.delete_project_folder_rule(rule_id)
    assert first["ok"] is True

    second = rule_api.delete_project_folder_rule(rule_id)
    assert second == {"ok": False, "error": "not_found"}


def test_delete_folder_rule_missing_id_returns_not_found(temp_db):
    result = rule_api.delete_project_folder_rule(9999)
    assert result == {"ok": False, "error": "not_found"}


def test_delete_folder_rule_keyword_rule_id_returns_not_found(temp_db):
    # A keyword rule id passed to the folder delete path must return
    # ``not_found`` rather than deleting the keyword rule.
    project = project_service.create_project("Client")
    keyword_id = rule_service.create_rule("Spec", project)

    result = rule_api.delete_project_folder_rule(keyword_id)

    assert result == {"ok": False, "error": "not_found"}
    # The keyword rule must still exist.
    assert _keyword_rule_row(keyword_id) is not None


@pytest.mark.parametrize("bad_id", [True, False, "1", "abc", 0, -1, 1.0, 2.5, None, [], {}, (), (1,), frozenset({1})])
def test_delete_folder_rule_rejects_invalid_rule_id(temp_db, bad_id):
    result = rule_api.delete_project_folder_rule(bad_id)
    assert result == {"ok": False, "error": "invalid_input"}


def test_delete_folder_rule_no_side_effects_on_other_tables(temp_db):
    project = project_service.create_project("Client")
    created = rule_api.create_project_folder_rule(project, r"D:\Work", True)
    rule_id = created["rule"]["id"]
    before = _counts()

    rule_api.delete_project_folder_rule(rule_id)

    after = _counts()
    assert after["project"] == before["project"]
    assert after["folder"] == before["folder"] - 1
    assert after["keyword"] == before["keyword"]
    assert after["activity"] == before["activity"]
    assert after["assignment"] == before["assignment"]
    assert after["session_note"] == before["session_note"]


def test_delete_folder_rule_does_not_delete_keyword_rule(temp_db):
    project = project_service.create_project("Client")
    keyword_id = rule_service.create_rule("Spec", project)
    created = rule_api.create_project_folder_rule(project, r"D:\Work", True)
    rule_id = created["rule"]["id"]

    rule_api.delete_project_folder_rule(rule_id)

    assert _keyword_rule_row(keyword_id) is not None


def test_delete_folder_rule_payload_json_serializable(temp_db):
    project = project_service.create_project("Client")
    created = rule_api.create_project_folder_rule(project, r"D:\Work", True)
    rule_id = created["rule"]["id"]

    result = rule_api.delete_project_folder_rule(rule_id)

    json.dumps(result, ensure_ascii=False)


def test_delete_folder_rule_service_exception_collapses_to_operation_failed(temp_db, monkeypatch):
    project = project_service.create_project("Client")
    created = rule_api.create_project_folder_rule(project, r"D:\Work", True)
    rule_id = created["rule"]["id"]

    def _boom(*args, **kwargs):
        raise RuntimeError("boom: sensitive SQL DELETE FROM ...")

    monkeypatch.setattr(folder_rule_service, "delete_folder_rule", _boom)

    result = rule_api.delete_project_folder_rule(rule_id)

    assert result == {"ok": False, "error": "operation_failed"}
    lowered = repr(result).lower()
    for forbidden in ("boom", "delete", "sensitive", "traceback", "runtimeerror"):
        assert forbidden not in lowered


# --- No cross-contamination with keyword / toggle paths ----------------


def test_folder_crud_does_not_trigger_keyword_create(temp_db, monkeypatch):
    project = project_service.create_project("Client")
    called = {"create_rule": 0}

    original_create_rule = rule_service.create_rule

    def _spy_create_rule(*args, **kwargs):
        called["create_rule"] += 1
        return original_create_rule(*args, **kwargs)

    monkeypatch.setattr(rule_service, "create_rule", _spy_create_rule)

    rule_api.create_project_folder_rule(project, r"D:\Work", True)
    assert called["create_rule"] == 0

    created = rule_api.create_project_folder_rule(project, r"D:\Other", True)
    rule_api.update_project_folder_rule(created["rule"]["id"], r"D:\New", False)
    assert called["create_rule"] == 0

    rule_api.delete_project_folder_rule(created["rule"]["id"])
    assert called["create_rule"] == 0


def test_folder_crud_does_not_trigger_keyword_delete(temp_db, monkeypatch):
    project = project_service.create_project("Client")
    keyword_id = rule_service.create_rule("Spec", project)
    called = {"delete_rule": 0}

    def _spy_delete_rule(*args, **kwargs):
        called["delete_rule"] += 1

    monkeypatch.setattr(rule_service, "delete_rule", _spy_delete_rule)

    created = rule_api.create_project_folder_rule(project, r"D:\Work", True)
    rule_api.update_project_folder_rule(created["rule"]["id"], r"D:\New", False)
    rule_api.delete_project_folder_rule(created["rule"]["id"])

    assert called["delete_rule"] == 0
    # The keyword rule is still there.
    assert _keyword_rule_row(keyword_id) is not None


def test_folder_crud_does_not_trigger_conflict_preview(temp_db, monkeypatch):
    project = project_service.create_project("Client")
    called = {"preview": 0}

    def _spy_preview(*args, **kwargs):
        called["preview"] += 1
        return {}

    monkeypatch.setattr(folder_rule_service, "preview_folder_rule_conflicts", _spy_preview)

    created = rule_api.create_project_folder_rule(project, r"D:\Work", True)
    rule_api.update_project_folder_rule(created["rule"]["id"], r"D:\New", False)
    rule_api.delete_project_folder_rule(created["rule"]["id"])

    assert called["preview"] == 0


def test_folder_crud_does_not_trigger_backfill(temp_db, monkeypatch):
    project = project_service.create_project("Client")
    called = {"backfill": 0}

    def _spy_backfill(*args, **kwargs):
        called["backfill"] += 1
        return {}

    monkeypatch.setattr(folder_rule_service, "backfill_folder_rule", _spy_backfill)

    created = rule_api.create_project_folder_rule(project, r"D:\Work", True)
    rule_api.update_project_folder_rule(created["rule"]["id"], r"D:\New", False)
    rule_api.delete_project_folder_rule(created["rule"]["id"])

    assert called["backfill"] == 0


def test_folder_crud_does_not_modify_project_rows(temp_db):
    project = project_service.create_project("Client")
    project_service.create_project("Other")

    def _snapshot():
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT id, name, enabled, is_archived FROM project ORDER BY id"
            ).fetchall()
        return [(row["id"], row["name"], row["enabled"], row["is_archived"]) for row in rows]

    before = _snapshot()

    created = rule_api.create_project_folder_rule(project, r"D:\Work", True)
    rule_api.update_project_folder_rule(created["rule"]["id"], r"D:\New", False)
    rule_api.delete_project_folder_rule(created["rule"]["id"])

    after = _snapshot()

    assert before == after


# --- Existing regression locks ------------------------------------------


def test_existing_set_project_rule_enabled_still_works(temp_db):
    project = project_service.create_project("Client")
    created = rule_api.create_project_folder_rule(project, r"D:\Work", True)
    rule_id = created["rule"]["id"]

    result = rule_api.set_project_rule_enabled("folder", rule_id, False)

    assert result["ok"] is True
    row = _folder_rule_row(rule_id)
    assert row["enabled"] == 0


def test_existing_create_project_keyword_rule_still_works(temp_db):
    project = project_service.create_project("Client")

    result = rule_api.create_project_keyword_rule(project, "Spec")

    assert result["ok"] is True
    assert result["rule"]["kind"] == "keyword"
    assert result["rule"]["keyword"] == "Spec"


def test_existing_delete_project_keyword_rule_still_works(temp_db):
    project = project_service.create_project("Client")
    keyword_id = rule_service.create_rule("Spec", project)

    result = rule_api.delete_project_keyword_rule(keyword_id)

    assert result["ok"] is True
    assert _keyword_rule_row(keyword_id) is None
