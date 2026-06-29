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
    folder_index_service,
    folder_rule_service,
    privacy_service,
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


# --- Phase 5E.1: normalized key collision / update-by-id boundary ---------
#
# Regression-only locks for the folder rule CRUD hardening. These tests lock
# the create-or-update normalized-key semantics, the update-by-id boundary
# (including the IntegrityError collapse when the new normalized key already
# belongs to a different rule), the enabled-preservation guarantee, the
# rule_id preservation guarantee when the normalized key changes, the
# cache-invalidation / privacy-exclude-cache / folder-index-rebuild hooks,
# and the sensitive-field absence in the returned payload.


def test_update_folder_rule_to_existing_normalized_key_returns_operation_failed(temp_db):
    # Phase 5E.1 regression lock: updating a folder rule's path so that its
    # normalized key collides with another existing folder rule must collapse
    # to ``operation_failed`` (the service raises ``IntegrityError`` on the
    # UNIQUE constraint). The update path must NOT merge or delete the other
    # rule, and the other rule must remain untouched.
    project = project_service.create_project("Client")
    other = rule_api.create_project_folder_rule(project, r"D:\Other", True)
    other_id = other["rule"]["id"]
    target = rule_api.create_project_folder_rule(project, r"D:\Target", True)
    target_id = target["rule"]["id"]

    result = rule_api.update_project_folder_rule(target_id, r"D:\Other", True)

    assert result == {"ok": False, "error": "operation_failed"}
    # The other rule must remain untouched.
    other_row = _folder_rule_row(other_id)
    assert other_row is not None
    assert other_row["folder_path"] == r"D:\Other"
    # The target rule must also remain untouched (no partial update).
    target_row = _folder_rule_row(target_id)
    assert target_row is not None
    assert target_row["folder_path"] == r"D:\Target"


def test_update_folder_rule_preserves_rule_id_when_normalized_key_changes(temp_db):
    # Phase 5E.1 regression lock: the update-by-id path must preserve the
    # row id even when the new folder_path produces a different
    # normalized_folder_key. This is what distinguishes update from
    # create-or-update (which would reuse the existing row for the same
    # normalized key).
    project = project_service.create_project("Client")
    created = rule_api.create_project_folder_rule(project, r"D:\Old", True)
    rule_id = created["rule"]["id"]

    result = rule_api.update_project_folder_rule(rule_id, r"D:\BrandNew", False)

    assert result["ok"] is True
    assert result["rule"]["id"] == rule_id
    row = _folder_rule_row(rule_id)
    assert row is not None
    assert row["folder_path"] == r"D:\BrandNew"
    # The old normalized key must no longer resolve to any row.
    assert _folder_rule_row_by_path(r"D:\Old") is None


def test_update_folder_rule_preserves_enabled_state_when_disabled(temp_db):
    # Phase 5E.1 regression lock: the update path must preserve the existing
    # ``enabled`` state. The existing test only verifies ``project_id``
    # preservation; this lock explicitly disables the rule first, then
    # updates the path, and confirms ``enabled`` stays ``0``.
    project = project_service.create_project("Client")
    created = rule_api.create_project_folder_rule(project, r"D:\Old", True)
    rule_id = created["rule"]["id"]
    rule_api.set_project_rule_enabled("folder", rule_id, False)
    assert _folder_rule_row(rule_id)["enabled"] == 0

    result = rule_api.update_project_folder_rule(rule_id, r"D:\New", False)

    assert result["ok"] is True
    assert result["rule"]["enabled"] is False
    row = _folder_rule_row(rule_id)
    assert row["enabled"] == 0


def test_create_folder_rule_recursive_update_on_same_normalized_key(temp_db):
    # Phase 5E.1 regression lock: creating a folder rule with the same
    # normalized key as an existing one but a different ``recursive`` value
    # must update the existing row's ``recursive`` field in place (this is
    # the create-or-update semantics). The existing test covers project_id
    # and recursive change together; this lock isolates the recursive-only
    # change on the same project.
    project = project_service.create_project("Client")
    first = rule_api.create_project_folder_rule(project, r"D:\Work", True)
    first_id = first["rule"]["id"]

    second = rule_api.create_project_folder_rule(project, r"D:\Work", False)

    assert second["ok"] is True
    assert second["rule"]["id"] == first_id
    assert second["rule"]["recursive"] is False
    row = _folder_rule_row(first_id)
    assert row["recursive"] == 0


def test_create_folder_rule_payload_excludes_sensitive_fields(temp_db):
    # Phase 5E.1 regression lock: the create success payload must not expose
    # internal DB columns (``normalized_folder_key``, ``created_at``,
    # ``updated_at``) or any sensitive metadata. The bridge further narrows
    # the payload, but the API layer must already be clean.
    project = project_service.create_project("Client")

    result = rule_api.create_project_folder_rule(project, r"D:\Work\Client", True)

    assert result["ok"] is True
    rule = result["rule"]
    assert set(rule.keys()) == {"kind", "id", "project_id", "folder_path", "recursive", "enabled"}
    lowered = repr(result).lower()
    for forbidden in (
        "normalized_folder_key",
        "created_at",
        "updated_at",
        "window_title",
        "clipboard",
        "note",
        "traceback",
        "select",
        "secret",
    ):
        assert forbidden not in lowered


def test_update_folder_rule_payload_excludes_sensitive_fields(temp_db):
    # Phase 5E.1 regression lock: the update success payload must not expose
    # internal DB columns or sensitive metadata.
    project = project_service.create_project("Client")
    created = rule_api.create_project_folder_rule(project, r"D:\Old", True)
    rule_id = created["rule"]["id"]

    result = rule_api.update_project_folder_rule(rule_id, r"D:\New", False)

    assert result["ok"] is True
    rule = result["rule"]
    assert set(rule.keys()) == {"kind", "id", "project_id", "folder_path", "recursive", "enabled"}
    lowered = repr(result).lower()
    for forbidden in (
        "normalized_folder_key",
        "created_at",
        "updated_at",
        "window_title",
        "clipboard",
        "note",
        "traceback",
        "update",
        "secret",
    ):
        assert forbidden not in lowered


def test_delete_folder_rule_payload_excludes_sensitive_fields(temp_db):
    # Phase 5E.1 regression lock: the delete success payload must not expose
    # internal DB columns or sensitive metadata. Note: ``deleted`` is the
    # legitimate success flag and is allowed; the forbidden ``delete`` SQL
    # keyword is checked via the key-set assertion (no ``delete`` key) rather
    # than via substring (which would also match ``deleted``).
    project = project_service.create_project("Client")
    created = rule_api.create_project_folder_rule(project, r"D:\Work", True)
    rule_id = created["rule"]["id"]

    result = rule_api.delete_project_folder_rule(rule_id)

    assert result["ok"] is True
    rule = result["rule"]
    assert set(rule.keys()) == {"kind", "id", "deleted"}
    lowered = repr(result).lower()
    for forbidden in (
        "normalized_folder_key",
        "created_at",
        "updated_at",
        "folder_path",
        "project_id",
        "window_title",
        "clipboard",
        "note",
        "traceback",
        "secret",
    ):
        assert forbidden not in lowered


# --- Phase 5E.1: cache invalidation / privacy exclude / index rebuild ----


def test_create_folder_rule_invokes_cache_invalidation_hooks(temp_db, monkeypatch):
    # Phase 5E.1 regression lock: the create path must call
    # ``invalidate_folder_rule_cache``, ``clear_exclude_rules_cache``, and
    # ``request_rebuild_for_rule`` so the folder rule cache, the privacy
    # exclude cache, and the folder index all reflect the new rule.
    project = project_service.create_project("Client")
    calls: dict[str, list] = {
        "invalidate_folder_rule_cache": [],
        "clear_exclude_rules_cache": [],
        "request_rebuild_for_rule": [],
    }

    def _spy_invalidate():
        calls["invalidate_folder_rule_cache"].append(True)

    def _spy_clear_exclude():
        calls["clear_exclude_rules_cache"].append(True)

    def _spy_rebuild(rule_id):
        calls["request_rebuild_for_rule"].append(int(rule_id))

    monkeypatch.setattr(folder_rule_service, "invalidate_folder_rule_cache", _spy_invalidate)
    monkeypatch.setattr(privacy_service, "clear_exclude_rules_cache", _spy_clear_exclude)
    monkeypatch.setattr(folder_index_service, "request_rebuild_for_rule", _spy_rebuild)

    result = rule_api.create_project_folder_rule(project, r"D:\Work", True)
    rule_id = result["rule"]["id"]

    assert calls["invalidate_folder_rule_cache"] == [True]
    assert calls["clear_exclude_rules_cache"] == [True]
    assert calls["request_rebuild_for_rule"] == [rule_id]


def test_update_folder_rule_invokes_cache_invalidation_hooks(temp_db, monkeypatch):
    # Phase 5E.1 regression lock: the update path must call
    # ``invalidate_folder_rule_cache``, ``clear_exclude_rules_cache``, and
    # ``request_rebuild_for_rule`` so the folder rule cache, the privacy
    # exclude cache, and the folder index all reflect the updated rule.
    project = project_service.create_project("Client")
    created = rule_api.create_project_folder_rule(project, r"D:\Old", True)
    rule_id = created["rule"]["id"]
    calls: dict[str, list] = {
        "invalidate_folder_rule_cache": [],
        "clear_exclude_rules_cache": [],
        "request_rebuild_for_rule": [],
    }

    def _spy_invalidate():
        calls["invalidate_folder_rule_cache"].append(True)

    def _spy_clear_exclude():
        calls["clear_exclude_rules_cache"].append(True)

    def _spy_rebuild(rule_id):
        calls["request_rebuild_for_rule"].append(int(rule_id))

    monkeypatch.setattr(folder_rule_service, "invalidate_folder_rule_cache", _spy_invalidate)
    monkeypatch.setattr(privacy_service, "clear_exclude_rules_cache", _spy_clear_exclude)
    monkeypatch.setattr(folder_index_service, "request_rebuild_for_rule", _spy_rebuild)

    rule_api.update_project_folder_rule(rule_id, r"D:\New", False)

    assert calls["invalidate_folder_rule_cache"] == [True]
    assert calls["clear_exclude_rules_cache"] == [True]
    assert calls["request_rebuild_for_rule"] == [rule_id]


def test_delete_folder_rule_invokes_cache_invalidation_and_index_delete_hooks(temp_db, monkeypatch):
    # Phase 5E.1 regression lock: the delete path must call
    # ``invalidate_folder_rule_cache``, ``clear_exclude_rules_cache``, and
    # ``delete_index_for_rule`` (NOT ``request_rebuild_for_rule``) so the
    # folder rule cache, the privacy exclude cache, and the folder index
    # all reflect the deleted rule.
    project = project_service.create_project("Client")
    created = rule_api.create_project_folder_rule(project, r"D:\Work", True)
    rule_id = created["rule"]["id"]
    calls: dict[str, list] = {
        "invalidate_folder_rule_cache": [],
        "clear_exclude_rules_cache": [],
        "delete_index_for_rule": [],
        "request_rebuild_for_rule": [],
    }

    def _spy_invalidate():
        calls["invalidate_folder_rule_cache"].append(True)

    def _spy_clear_exclude():
        calls["clear_exclude_rules_cache"].append(True)

    def _spy_delete_index(rule_id):
        calls["delete_index_for_rule"].append(int(rule_id))

    def _spy_rebuild(rule_id):
        calls["request_rebuild_for_rule"].append(int(rule_id))

    monkeypatch.setattr(folder_rule_service, "invalidate_folder_rule_cache", _spy_invalidate)
    monkeypatch.setattr(privacy_service, "clear_exclude_rules_cache", _spy_clear_exclude)
    monkeypatch.setattr(folder_index_service, "delete_index_for_rule", _spy_delete_index)
    monkeypatch.setattr(folder_index_service, "request_rebuild_for_rule", _spy_rebuild)

    rule_api.delete_project_folder_rule(rule_id)

    assert calls["invalidate_folder_rule_cache"] == [True]
    assert calls["clear_exclude_rules_cache"] == [True]
    assert calls["delete_index_for_rule"] == [rule_id]
    # The delete path must NOT call request_rebuild_for_rule.
    assert calls["request_rebuild_for_rule"] == []


def test_folder_crud_cache_hooks_not_invoked_on_invalid_input(temp_db, monkeypatch):
    # Phase 5E.1 regression lock: when the API rejects input before reaching
    # the service, none of the cache invalidation hooks may fire. This locks
    # the boundary so a validation rejection never produces a stale cache
    # flush that could mask a real bug.
    project = project_service.create_project("Client")
    calls: dict[str, int] = {
        "invalidate_folder_rule_cache": 0,
        "clear_exclude_rules_cache": 0,
        "request_rebuild_for_rule": 0,
        "delete_index_for_rule": 0,
    }

    def _incr(name):
        def _impl(*args, **kwargs):
            calls[name] += 1
        return _impl

    monkeypatch.setattr(folder_rule_service, "invalidate_folder_rule_cache", _incr("invalidate_folder_rule_cache"))
    monkeypatch.setattr(privacy_service, "clear_exclude_rules_cache", _incr("clear_exclude_rules_cache"))
    monkeypatch.setattr(folder_index_service, "request_rebuild_for_rule", _incr("request_rebuild_for_rule"))
    monkeypatch.setattr(folder_index_service, "delete_index_for_rule", _incr("delete_index_for_rule"))

    # Invalid create (bad project_id, bad path, bad recursive).
    rule_api.create_project_folder_rule(True, r"D:\Work", True)
    rule_api.create_project_folder_rule(project, "", True)
    rule_api.create_project_folder_rule(project, r"D:\Work", "true")
    # Invalid update (bad rule_id, bad path, bad recursive).
    rule_api.update_project_folder_rule(True, r"D:\New", True)
    rule_api.update_project_folder_rule(9999, "", True)
    rule_api.update_project_folder_rule(9999, r"D:\New", "true")
    # Invalid delete (bad rule_id).
    rule_api.delete_project_folder_rule(True)
    rule_api.delete_project_folder_rule(0)
    # project_not_found and not_found rejections.
    rule_api.create_project_folder_rule(9999, r"D:\Work", True)
    rule_api.update_project_folder_rule(9999, r"D:\New", True)
    rule_api.delete_project_folder_rule(9999)

    assert calls == {
        "invalidate_folder_rule_cache": 0,
        "clear_exclude_rules_cache": 0,
        "request_rebuild_for_rule": 0,
        "delete_index_for_rule": 0,
    }


# --- Phase 6G: excluded-folder rule creation facade --------------------


def test_create_excluded_folder_rule_for_webview_success(temp_db):
    # Phase 6G regression lock: the dedicated facade creates a folder rule on
    # the special ``排除规则`` project, trims the path, passes ``recursive``
    # through as a real bool, and returns the narrow created-rule summary. It
    # does NOT accept a project_id from the caller.
    result = rule_api.create_excluded_folder_rule_for_webview(
        "  D:\\Work\\Secret  ", False
    )

    assert result["ok"] is True
    rule = result["rule"]
    assert rule["kind"] == "folder"
    assert isinstance(rule["id"], int)
    assert rule["id"] > 0
    excluded_id = project_service.get_or_create_excluded_project()
    assert rule["project_id"] == excluded_id
    assert rule["folder_path"] == r"D:\Work\Secret"
    assert rule["recursive"] is False
    assert rule["enabled"] is True

    row = _folder_rule_row(rule["id"])
    assert row["project_id"] == excluded_id
    assert row["folder_path"] == r"D:\Work\Secret"
    assert row["recursive"] == 0
    assert row["enabled"] == 1
    # The excluded project is a system project: enabled=0, created_by=system.
    with get_connection() as conn:
        proj = conn.execute(
            "SELECT name, enabled, created_by FROM project WHERE id = ?",
            (excluded_id,),
        ).fetchone()
    assert proj["enabled"] == 0
    assert proj["created_by"] == "system"
    json.dumps(result, ensure_ascii=False)


@pytest.mark.parametrize(
    "bad_path,bad_recursive",
    [
        (None, True),
        (True, True),
        (1, True),
        (1.5, True),
        ([], True),
        ({}, True),
        (b"D:\\X", True),
        ("", True),
        ("   ", True),
        ("\t\n", True),
        ("D:\\Work", None),
        ("D:\\Work", 1),
        ("D:\\Work", "yes"),
        ("D:\\Work", []),
        ("D:\\Work", {}),
    ],
)
def test_create_excluded_folder_rule_for_webview_rejects_invalid_input(
    temp_db, bad_path, bad_recursive
):
    # Phase 6G regression lock: non-str / whitespace-only folder_path or
    # non-bool recursive collapses to ``invalid_input`` and creates no row.
    before = _counts()
    result = rule_api.create_excluded_folder_rule_for_webview(bad_path, bad_recursive)
    after = _counts()

    assert result == {"ok": False, "error": "invalid_input"}
    assert after["folder"] == before["folder"]


def test_create_excluded_folder_rule_for_webview_exception_collapses(
    temp_db, monkeypatch
):
    # Phase 6G regression lock: an unexpected service failure collapses to
    # ``operation_failed`` without surfacing the exception text, traceback,
    # SQL, or sensitive metadata.
    def _raise(*args, **kwargs):
        raise RuntimeError(
            "boom SELECT * FROM folder_project_rule traceback window_title "
            "clipboard note C:\\Secret"
        )

    monkeypatch.setattr(folder_rule_service, "create_or_update_folder_rule", _raise)

    result = rule_api.create_excluded_folder_rule_for_webview(r"D:\Work", True)

    assert result == {"ok": False, "error": "operation_failed"}
    lowered = repr(result).lower()
    for forbidden in (
        "traceback",
        "sqlite",
        "select ",
        "window_title",
        "clipboard",
        "note",
        "secret",
        "c:\\",
    ):
        assert forbidden not in lowered, forbidden
    json.dumps(result, ensure_ascii=False)
