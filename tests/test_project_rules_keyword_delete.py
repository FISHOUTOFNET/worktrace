"""API / service regression locks for keyword rule deletion.

These tests lock the narrow ``rule_api.delete_project_keyword_rule`` facade.
They cover valid deletion of enabled / disabled
keyword rules, keyword rules under normal and special ``排除规则``
projects, input validation (bool-as-int, numeric string, float,
zero / negative, list / dict / tuple / set / frozenset), ``not_found``
for unknown ids and folder-rule ids, exception collapse to
``operation_failed``, no-side-effect guarantees (no folder rule / project /
activity / assignment / session-note rows touched, no conflict preview /
backfill / folder delete invoked), cache invalidation preservation, JSON
serializability, and existing keyword create / rule enable-disable
regression locks.
"""

from __future__ import annotations

import json

import pytest

from worktrace.api import rule_api
from worktrace.db import get_connection, now_str
from worktrace.services import (
    activity_service,
    folder_rule_service,
    project_inference_service,
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


def _keyword_rule_exists(rule_id: int) -> bool:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM project_rule WHERE id = ?",
            (rule_id,),
        ).fetchone()
    return row["c"] == 1


# --- Valid deletion ------------------------------------------------------


def test_delete_keyword_rule_for_normal_project(temp_db):
    project = project_service.create_project("Client")
    rule_id = rule_service.create_rule("Spec", project)

    result = rule_api.delete_project_keyword_rule(rule_id)

    assert result["ok"] is True
    rule = result["rule"]
    assert rule["kind"] == "keyword"
    assert type(rule["id"]) is int
    assert rule["id"] == rule_id
    assert rule["deleted"] is True
    assert _keyword_rule_exists(rule_id) is False


def test_delete_disabled_keyword_rule(temp_db):
    project = project_service.create_project("Client")
    rule_id = rule_service.create_rule("Spec", project)
    rule_service.set_rule_enabled(rule_id, False)

    result = rule_api.delete_project_keyword_rule(rule_id)

    assert result["ok"] is True
    assert result["rule"]["id"] == rule_id
    assert _keyword_rule_exists(rule_id) is False


def test_delete_keyword_rule_under_normal_project_decreases_count_by_one(temp_db):
    project = project_service.create_project("Client")
    rule_service.create_rule("SpecA", project)
    rule_service.create_rule("SpecB", project)
    rule_service.create_rule("SpecC", project)
    before = _counts()

    # Delete one of the three keyword rules.
    with get_connection() as conn:
        target_id = conn.execute(
            "SELECT id FROM project_rule WHERE pattern = ?",
            ("SpecB",),
        ).fetchone()["id"]

    result = rule_api.delete_project_keyword_rule(target_id)

    assert result["ok"] is True
    after = _counts()
    assert after["keyword"] == before["keyword"] - 1
    # The other two keyword rules survive.
    with get_connection() as conn:
        remaining = conn.execute(
            "SELECT pattern FROM project_rule WHERE project_id = ? ORDER BY pattern",
            (project,),
        ).fetchall()
    assert [row["pattern"] for row in remaining] == ["SpecA", "SpecC"]


def test_delete_keyword_rule_under_excluded_project(temp_db):
    # The special ``排除规则`` project is created with ``enabled = 0`` but
    # keyword rules attached to it are still legitimate keyword rules in
    # the ``project_rule`` table. The delete facade only checks
    # that the id is a real keyword rule — it does not gate on project
    # eligibility (unlike create). This mirrors the spec: "删除
    # existing keyword rule" must work regardless of project state.
    excluded_id = project_service.get_or_create_excluded_project()
    rule_id = rule_service.create_rule("Secret", excluded_id)

    result = rule_api.delete_project_keyword_rule(rule_id)

    assert result["ok"] is True
    assert _keyword_rule_exists(rule_id) is False


# --- rule_id input validation -------------------------------------------


@pytest.mark.parametrize("bad_id", [True, False])
def test_delete_keyword_rule_rejects_bool_as_int_rule_id(temp_db, bad_id):
    # ``type(True) is bool`` (not int), so bool is rejected before reaching
    # the service layer.
    result = rule_api.delete_project_keyword_rule(bad_id)
    assert result == {"ok": False, "error": "invalid_input"}


@pytest.mark.parametrize("bad_id", ["1", "abc", "true"])
def test_delete_keyword_rule_rejects_numeric_string_rule_id(temp_db, bad_id):
    result = rule_api.delete_project_keyword_rule(bad_id)
    assert result == {"ok": False, "error": "invalid_input"}


@pytest.mark.parametrize("bad_id", [1.0, 2.5, -1.5])
def test_delete_keyword_rule_rejects_float_rule_id(temp_db, bad_id):
    result = rule_api.delete_project_keyword_rule(bad_id)
    assert result == {"ok": False, "error": "invalid_input"}


@pytest.mark.parametrize("bad_id", [0, -1, -999])
def test_delete_keyword_rule_rejects_zero_and_negative_rule_id(temp_db, bad_id):
    result = rule_api.delete_project_keyword_rule(bad_id)
    assert result == {"ok": False, "error": "invalid_input"}


@pytest.mark.parametrize(
    "bad_id", [None, [], {}, (), {1, 2}, (1,), frozenset({1})]
)
def test_delete_keyword_rule_rejects_other_invalid_rule_id_types(temp_db, bad_id):
    # Regression lock: container types (list / dict / tuple / set /
    # frozenset) all collapse to ``invalid_input`` via the ``type(...) is not
    # int`` guard before reaching the service layer.
    result = rule_api.delete_project_keyword_rule(bad_id)
    assert result == {"ok": False, "error": "invalid_input"}


# --- not_found -----------------------------------------------------------


def test_unknown_keyword_rule_returns_stable_not_found(temp_db):
    # An id that does not exist in the project_rule table at all.
    result = rule_api.delete_project_keyword_rule(9999)
    assert result == {"ok": False, "error": "not_found"}


def test_folder_rule_id_returns_not_found_and_does_not_delete_folder_rule(temp_db):
    # Regression lock: a folder rule id must never be deleted
    # through the keyword delete path. The facade uses ``_rule_exists(
    # "keyword", rule_id)`` which only returns True for ids in
    # ``project_rule`` (keyword table), so a folder rule id resolves to
    # ``not_found`` instead of deleting the folder rule.
    project = project_service.create_project("Client")
    folder_rule_id = folder_rule_service.create_or_update_folder_rule(
        r"D:\Client", project
    )

    result = rule_api.delete_project_keyword_rule(folder_rule_id)

    assert result == {"ok": False, "error": "not_found"}
    # The folder rule row must still exist.
    folder_rules = folder_rule_service.list_folder_rules()
    assert any(int(r.get("id") or 0) == folder_rule_id for r in folder_rules)


def test_keyword_rule_id_does_not_delete_folder_rule(temp_db):
    # Regression lock: deleting a keyword rule must not delete any
    # folder rule, even folder rules bound to the same project.
    project = project_service.create_project("Client")
    folder_rule_id = folder_rule_service.create_or_update_folder_rule(
        r"D:\Client", project
    )
    keyword_rule_id = rule_service.create_rule("Spec", project)

    result = rule_api.delete_project_keyword_rule(keyword_rule_id)

    assert result["ok"] is True
    # The folder rule row must still exist.
    folder_rules = folder_rule_service.list_folder_rules()
    assert any(int(r.get("id") or 0) == folder_rule_id for r in folder_rules)


# --- Exception collapse --------------------------------------------------


def test_service_exception_collapses_to_operation_failed(temp_db, monkeypatch):
    # Regression lock: any unexpected service exception must
    # collapse to ``operation_failed`` and never surface raw exception text
    # or SQL in the payload.
    project = project_service.create_project("Client")
    rule_id = rule_service.create_rule("Spec", project)

    def boom(rule_id_arg):
        raise RuntimeError(
            "boom SELECT * FROM activity_log traceback window_title clipboard note C:\\Secret"
        )

    monkeypatch.setattr(rule_service, "delete_rule", boom)
    result = rule_api.delete_project_keyword_rule(rule_id)
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
        "secret",
    ):
        assert forbidden not in lowered


# --- No side effects -----------------------------------------------------


def test_delete_keyword_rule_does_not_add_or_delete_folder_rule_rows(temp_db):
    project = project_service.create_project("Client")
    folder_rule_service.create_or_update_folder_rule(r"D:\Client", project)
    rule_id = rule_service.create_rule("Spec", project)
    before = _counts()

    result = rule_api.delete_project_keyword_rule(rule_id)

    assert result["ok"] is True
    after = _counts()
    assert after["folder"] == before["folder"]
    assert after["keyword"] == before["keyword"] - 1


def test_delete_keyword_rule_does_not_add_or_delete_project_rows(temp_db):
    project = project_service.create_project("Client")
    rule_id = rule_service.create_rule("Spec", project)
    before = _counts()

    result = rule_api.delete_project_keyword_rule(rule_id)

    assert result["ok"] is True
    after = _counts()
    assert after["project"] == before["project"]


def test_delete_keyword_rule_does_not_change_activity_log_rows(temp_db):
    project = project_service.create_project("Client")
    rule_id = rule_service.create_rule("Spec", project)
    activity_id = activity_service.create_activity(
        "Word",
        "winword.exe",
        "Spec.docx",
        start_time="2026-06-18 09:00:00",
        project_id=project,
    )
    activity_service.finalize_created_activity(activity_id)
    before = _counts()

    result = rule_api.delete_project_keyword_rule(rule_id)

    assert result["ok"] is True
    after = _counts()
    assert after["activity"] == before["activity"]
    # The existing activity row is not reclassified by rule deletion. The
    # activity's project_id stays as the originally assigned project.
    with get_connection() as conn:
        row = conn.execute(
            "SELECT project_id FROM activity_log WHERE id = ?",
            (activity_id,),
        ).fetchone()
    assert row["project_id"] == project


def test_delete_keyword_rule_does_not_change_activity_project_assignment_rows(temp_db):
    project = project_service.create_project("Client")
    rule_id = rule_service.create_rule("Spec", project)
    activity_service.create_activity(
        "Word",
        "winword.exe",
        "Spec.docx",
        start_time="2026-06-18 09:00:00",
        project_id=project,
    )
    activity_service.finalize_created_activity(
        activity_service.create_activity(
            "Word",
            "winword.exe",
            "Spec2.docx",
            start_time="2026-06-18 10:00:00",
            project_id=project,
        )
    )
    before = _counts()

    result = rule_api.delete_project_keyword_rule(rule_id)

    assert result["ok"] is True
    after = _counts()
    assert after["assignment"] == before["assignment"]


def test_delete_keyword_rule_does_not_change_project_session_note_rows(temp_db):
    project = project_service.create_project("Client")
    rule_id = rule_service.create_rule("Spec", project)
    activity_id = activity_service.create_activity(
        "Word",
        "winword.exe",
        "Spec.docx",
        start_time="2026-06-18 09:00:00",
        project_id=project,
    )
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO project_session_note(report_date, first_activity_id, note, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("2026-06-18", activity_id, "keep", now_str(), now_str()),
        )
    before = _counts()

    result = rule_api.delete_project_keyword_rule(rule_id)

    assert result["ok"] is True
    after = _counts()
    assert after["session_note"] == before["session_note"]


def test_delete_keyword_rule_does_not_call_conflict_preview(temp_db, monkeypatch):
    project = project_service.create_project("Client")
    rule_id = rule_service.create_rule("Spec", project)

    def fail_preview(*args, **kwargs):
        raise AssertionError("conflict preview must not run during keyword delete")

    monkeypatch.setattr(folder_rule_service, "preview_folder_rule_conflicts", fail_preview)
    result = rule_api.delete_project_keyword_rule(rule_id)
    assert result["ok"] is True


def test_delete_keyword_rule_does_not_call_backfill(temp_db, monkeypatch):
    project = project_service.create_project("Client")
    rule_id = rule_service.create_rule("Spec", project)

    def fail_backfill(*args, **kwargs):
        raise AssertionError("backfill must not run during keyword delete")

    from worktrace.services import rule_impact_service

    monkeypatch.setattr(rule_impact_service, "backfill_rule_impact", fail_backfill)
    result = rule_api.delete_project_keyword_rule(rule_id)
    assert result["ok"] is True


def test_delete_keyword_rule_does_not_call_folder_delete(temp_db, monkeypatch):
    project = project_service.create_project("Client")
    folder_rule_service.create_or_update_folder_rule(r"D:\Client", project)
    rule_id = rule_service.create_rule("Spec", project)

    def fail_folder_delete(*args, **kwargs):
        raise AssertionError("folder delete must not run during keyword delete")

    monkeypatch.setattr(folder_rule_service, "delete_folder_rule", fail_folder_delete)
    result = rule_api.delete_project_keyword_rule(rule_id)
    assert result["ok"] is True


# --- Cache invalidation --------------------------------------------------


def test_delete_keyword_rule_invalidates_keyword_rule_cache(temp_db, monkeypatch):
    # Regression lock: ``rule_service.delete_rule`` calls
    # ``invalidate_keyword_rule_cache`` so deleted keyword rules stop
    # matching immediately for project inference. The API facade must not
    # bypass that cache invalidation.
    project = project_service.create_project("Client")
    rule_id = rule_service.create_rule("Spec", project)
    project_inference_service.invalidate_keyword_rule_cache()

    calls = {"count": 0}
    original = project_inference_service.invalidate_keyword_rule_cache

    def spy():
        calls["count"] += 1
        original()

    monkeypatch.setattr(rule_service, "invalidate_keyword_rule_cache", spy)
    # Also patch the re-exported name inside project_inference_service so the
    # ``from .project_inference_service import invalidate_keyword_rule_cache``
    # reference inside ``rule_service.delete_rule`` resolves to the spy.
    monkeypatch.setattr(
        "worktrace.services.rule_service.invalidate_keyword_rule_cache", spy
    )

    result = rule_api.delete_project_keyword_rule(rule_id)

    assert result["ok"] is True
    assert calls["count"] >= 1


def test_delete_keyword_rule_clears_exclude_rules_cache(temp_db, monkeypatch):
    # Regression lock: ``rule_service.delete_rule`` also calls
    # ``privacy_service.clear_exclude_rules_cache`` so the privacy/exclude
    # matching result stays consistent after a keyword rule is deleted.
    project = project_service.create_project("Client")
    rule_id = rule_service.create_rule("Spec", project)

    calls = {"count": 0}
    original = privacy_service.clear_exclude_rules_cache

    def spy():
        calls["count"] += 1
        original()

    monkeypatch.setattr(privacy_service, "clear_exclude_rules_cache", spy)

    result = rule_api.delete_project_keyword_rule(rule_id)

    assert result["ok"] is True
    assert calls["count"] >= 1


# --- Payload contract ----------------------------------------------------


def test_delete_keyword_rule_payload_is_json_serializable(temp_db):
    project = project_service.create_project("Client")
    rule_id = rule_service.create_rule("Spec", project)

    result = rule_api.delete_project_keyword_rule(rule_id)

    json.dumps(result, ensure_ascii=False)
    assert "Traceback" not in repr(result)
    assert "SELECT" not in repr(result)


def test_delete_keyword_rule_success_payload_types_are_stable(temp_db):
    project = project_service.create_project("Client")
    rule_id = rule_service.create_rule("Spec", project)

    result = rule_api.delete_project_keyword_rule(rule_id)

    assert type(result["ok"]) is bool
    rule = result["rule"]
    assert type(rule["kind"]) is str
    assert type(rule["id"]) is int
    assert type(rule["deleted"]) is bool


def test_delete_keyword_rule_failure_payloads_are_json_serializable(temp_db):
    project = project_service.create_project("Client")

    failures = [
        rule_api.delete_project_keyword_rule(True),
        rule_api.delete_project_keyword_rule("1"),
        rule_api.delete_project_keyword_rule(1.0),
        rule_api.delete_project_keyword_rule(0),
        rule_api.delete_project_keyword_rule(-1),
        rule_api.delete_project_keyword_rule(None),
        rule_api.delete_project_keyword_rule([]),
        rule_api.delete_project_keyword_rule({}),
        rule_api.delete_project_keyword_rule(9999),
    ]
    # A folder rule id also returns a failure payload. Use a folder rule id
    # that is guaranteed not to collide with any keyword rule id by creating
    # the folder rule first (before any keyword rule exists in the DB), so
    # the folder rule id cannot match a keyword rule id in the
    # ``project_rule`` table.
    folder_rule_id = folder_rule_service.create_or_update_folder_rule(
        r"D:\Client", project
    )
    # Verify no keyword rule with this id exists before asserting failure.
    assert _keyword_rule_exists(folder_rule_id) is False
    failures.append(rule_api.delete_project_keyword_rule(folder_rule_id))

    for result in failures:
        assert result["ok"] is False
        json.dumps(result, ensure_ascii=False)
        assert "Traceback" not in repr(result)
        assert "SELECT" not in repr(result)


# --- Existing keyword create / rule enable-disable regression lock -------


def test_existing_create_project_keyword_rule_still_works(temp_db):
    # Regression lock: the new ``delete_project_keyword_rule`` facade
    # must not regress the existing create path.
    project = project_service.create_project("Client")

    result = rule_api.create_project_keyword_rule(project, "Spec")

    assert result["ok"] is True
    assert result["rule"]["kind"] == "keyword"
    assert result["rule"]["project_id"] == project
    assert result["rule"]["keyword"] == "Spec"


def test_existing_set_project_rule_enabled_still_works(temp_db):
    # Regression lock: the new ``delete_project_keyword_rule`` facade
    # must not regress the existing toggle path.
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


def test_delete_then_recreate_same_keyword_works(temp_db):
    # Regression lock: after deleting a keyword rule, the same
    # keyword can be re-created on the same project (no soft-delete residue
    # / unique-constraint violation). This verifies the existing service
    # uses a hard DELETE, not a soft-delete.
    project = project_service.create_project("Client")
    rule_id = rule_service.create_rule("Spec", project)

    delete_result = rule_api.delete_project_keyword_rule(rule_id)
    assert delete_result["ok"] is True

    recreate_result = rule_api.create_project_keyword_rule(project, "Spec")
    assert recreate_result["ok"] is True
    assert recreate_result["rule"]["id"] != rule_id
    assert recreate_result["rule"]["keyword"] == "Spec"


# --- keyword deletion hardening regression locks ------------


def test_delete_keyword_rule_second_delete_is_not_treated_as_success(temp_db):
    # Regression lock: a no-op delete must never be reported as
    # success. After a successful first delete, the row is gone, so a second
    # delete on the same id must resolve to ``not_found`` (not ``ok: True``).
    # This locks the existence pre-check + hard DELETE contract so a future
    # change cannot turn a stale-id delete into a silent success.
    project = project_service.create_project("Client")
    rule_id = rule_service.create_rule("Spec", project)

    first = rule_api.delete_project_keyword_rule(rule_id)
    assert first["ok"] is True
    assert _keyword_rule_exists(rule_id) is False

    second = rule_api.delete_project_keyword_rule(rule_id)
    assert second == {"ok": False, "error": "not_found"}
    assert second["ok"] is False


def test_delete_keyword_rule_does_not_call_keyword_create_or_toggle_service_paths(
    temp_db, monkeypatch
):
    # Regression lock: the keyword delete path must only call
    # ``rule_service.delete_rule``. It must not invoke the keyword create
    # service path (``create_rule``) or the keyword toggle service path
    # (``set_rule_enabled``), which would mutate the rule set instead of
    # deleting one row. The existing locks cover folder delete / conflict
    # preview / backfill; this closes the keyword-side create/toggle gap.
    project = project_service.create_project("Client")
    rule_id = rule_service.create_rule("Spec", project)

    def fail_create(*args, **kwargs):
        raise AssertionError("keyword create must not run during keyword delete")

    def fail_toggle(*args, **kwargs):
        raise AssertionError("keyword toggle must not run during keyword delete")

    monkeypatch.setattr(rule_service, "create_rule", fail_create)
    monkeypatch.setattr(rule_service, "set_rule_enabled", fail_toggle)

    result = rule_api.delete_project_keyword_rule(rule_id)

    assert result["ok"] is True
    assert _keyword_rule_exists(rule_id) is False


def test_delete_keyword_rule_folder_rule_id_returns_stable_not_found_code(temp_db):
    # Regression lock: a folder rule id must collapse to the
    # stable ``not_found`` code through the keyword delete path, and the
    # returned code must be exactly ``not_found`` (not a folder-specific
    # code that would leak which table the id belonged to). The folder rule
    # row must survive untouched.
    project = project_service.create_project("Client")
    folder_rule_id = folder_rule_service.create_or_update_folder_rule(
        r"D:\Client", project
    )

    result = rule_api.delete_project_keyword_rule(folder_rule_id)

    assert result == {"ok": False, "error": "not_found"}
    # The folder rule row must still exist.
    folder_rules = folder_rule_service.list_folder_rules()
    assert any(int(r.get("id") or 0) == folder_rule_id for r in folder_rules)
