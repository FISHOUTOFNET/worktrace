"""API / service regression locks for keyword rule creation.

These tests lock the narrow ``rule_api.create_project_keyword_rule`` facade.
They cover valid creation, input validation,
duplicate rejection, project-eligibility rejection, exception collapse,
no-side-effect guarantees (no folder rule / project / activity / assignment
/ session-note rows touched, no conflict preview / backfill invoked), cache
invalidation preservation, JSON serializability, and the existing
``set_project_rule_enabled`` regression lock.
"""

from __future__ import annotations

import json

import pytest

pytestmark = [pytest.mark.contract, pytest.mark.integration, pytest.mark.db, pytest.mark.security_privacy]

from worktrace.api import rule_api
from worktrace.constants import EXCLUDED_PROJECT
from worktrace.db import get_connection, now_str
from worktrace.services import (
    activity_service,
    folder_rule_service,
    project_inference_service,
    project_service,
    rule_service,
)
from tests.support.assertions import assert_api_error_envelope, assert_privacy_redacted
from tests.support.db_helpers import table_count
from tests.support.project_factory import create_project


def _counts() -> dict[str, int]:
    return {
        "project": table_count("project"),
        "folder": table_count("folder_project_rule"),
        "keyword": table_count("project_rule"),
        "activity": table_count("activity_log"),
        "assignment": table_count("activity_project_assignment"),
        "session_note": table_count("report_session_operation"),
    }


def _keyword_rule_row(rule_id: int) -> dict:
    with get_connection() as conn:
        return dict(
            conn.execute(
                "SELECT id, project_id, pattern, enabled, created_by FROM project_rule WHERE id = ?",
                (rule_id,),
            ).fetchone()
        )




def test_create_keyword_rule_for_normal_project(temp_db):
    project = create_project("Client")

    result = rule_api.create_project_keyword_rule(project, "Spec")

    assert result["ok"] is True
    rule = result["rule"]
    assert rule["kind"] == "keyword"
    assert isinstance(rule["id"], int)
    assert rule["id"] > 0
    assert rule["project_id"] == project
    assert rule["keyword"] == "Spec"
    assert rule["enabled"] is True

    row = _keyword_rule_row(rule["id"])
    assert row["project_id"] == project
    assert row["pattern"] == "Spec"
    assert row["enabled"] == 1
    assert row["created_by"] == "user"


def test_create_keyword_rule_for_excluded_project_rejected_as_project_not_found(temp_db):
    # Regression lock: 排除规则 project (enabled=0) must be rejected as
    # project_not_found, not bypassing service eligibility (spec: 不要绕过 service).
    excluded_id = project_service.get_or_create_excluded_project()

    result = rule_api.create_project_keyword_rule(excluded_id, "Secret")

    assert_api_error_envelope(result, "project_not_found")
    with get_connection() as conn:
        count = conn.execute(
            "SELECT COUNT(*) AS c FROM project_rule WHERE project_id = ?",
            (excluded_id,),
        ).fetchone()["c"]
    assert count == 0


def test_create_keyword_rule_for_archived_project_rejected(temp_db):
    project = project_service.create_project("Archived")
    project_service.archive_project(project)

    result = rule_api.create_project_keyword_rule(project, "Spec")

    assert result == {"ok": False, "error": "project_not_found"}


def test_create_keyword_rule_for_disabled_project_rejected(temp_db):
    project = project_service.create_project("Disabled")
    project_service.set_project_enabled(project, False)

    result = rule_api.create_project_keyword_rule(project, "Spec")

    assert result == {"ok": False, "error": "project_not_found"}




@pytest.mark.parametrize("bad_id", [True, False])
def test_create_keyword_rule_rejects_bool_as_int_project_id(temp_db, bad_id):
    # ``type(True) is bool`` (not int), so bool is rejected before reaching
    # the service layer.
    result = rule_api.create_project_keyword_rule(bad_id, "Spec")
    assert result == {"ok": False, "error": "invalid_input"}


@pytest.mark.parametrize("bad_id", ["1", "abc", "true"])
def test_create_keyword_rule_rejects_numeric_string_project_id(temp_db, bad_id):
    result = rule_api.create_project_keyword_rule(bad_id, "Spec")
    assert result == {"ok": False, "error": "invalid_input"}


@pytest.mark.parametrize("bad_id", [1.0, 2.5, -1.5])
def test_create_keyword_rule_rejects_float_project_id(temp_db, bad_id):
    result = rule_api.create_project_keyword_rule(bad_id, "Spec")
    assert result == {"ok": False, "error": "invalid_input"}


@pytest.mark.parametrize("bad_id", [0, -1, -999])
def test_create_keyword_rule_rejects_zero_and_negative_project_id(temp_db, bad_id):
    result = rule_api.create_project_keyword_rule(bad_id, "Spec")
    assert result == {"ok": False, "error": "invalid_input"}


@pytest.mark.parametrize("bad_id", [None, [], {}, (), {1, 2}, (1,), frozenset({1})])
def test_create_keyword_rule_rejects_other_invalid_project_id_types(temp_db, bad_id):
    # Regression lock: container types (list / dict / tuple / set /
    # frozenset) all collapse to ``invalid_input`` via the ``type(...) is not
    # int`` guard before reaching the service layer.
    result = rule_api.create_project_keyword_rule(bad_id, "Spec")
    assert result == {"ok": False, "error": "invalid_input"}




def test_create_keyword_rule_rejects_none_keyword(temp_db):
    project = project_service.create_project("Client")
    result = rule_api.create_project_keyword_rule(project, None)
    assert result == {"ok": False, "error": "invalid_input"}


@pytest.mark.parametrize("bad_keyword", [True, False])
def test_create_keyword_rule_rejects_bool_keyword(temp_db, bad_keyword):
    project = project_service.create_project("Client")
    result = rule_api.create_project_keyword_rule(project, bad_keyword)
    assert result == {"ok": False, "error": "invalid_input"}


@pytest.mark.parametrize("bad_keyword", [1, 1.0, 2.5, [], {}, (), {1, 2}, (1,), frozenset({1})])
def test_create_keyword_rule_rejects_non_string_keyword(temp_db, bad_keyword):
    # Regression lock: container types (list / dict / tuple / set /
    # frozenset) all collapse to ``invalid_input`` via the ``type(...) is not
    # str`` guard.
    project = project_service.create_project("Client")
    result = rule_api.create_project_keyword_rule(project, bad_keyword)
    assert result == {"ok": False, "error": "invalid_input"}


def test_create_keyword_rule_rejects_empty_keyword(temp_db):
    project = project_service.create_project("Client")
    result = rule_api.create_project_keyword_rule(project, "")
    assert result == {"ok": False, "error": "invalid_input"}


@pytest.mark.parametrize("bad_keyword", ["   ", "\t", "\n", "  \t  "])
def test_create_keyword_rule_rejects_whitespace_only_keyword(temp_db, bad_keyword):
    project = project_service.create_project("Client")
    result = rule_api.create_project_keyword_rule(project, bad_keyword)
    assert result == {"ok": False, "error": "invalid_input"}


def test_create_keyword_rule_trims_keyword_before_create(temp_db):
    project = project_service.create_project("Client")

    result = rule_api.create_project_keyword_rule(project, "  Spec  ")

    assert result["ok"] is True
    assert result["rule"]["keyword"] == "Spec"
    row = _keyword_rule_row(result["rule"]["id"])
    assert row["pattern"] == "Spec"


def test_create_keyword_rule_html_script_keyword_saved_as_plain_text(temp_db):
    # Regression lock: HTML/script keyword must not leak an exception; the
    # API saves it as plain text and frontend rendering escapes it. The
    # success payload must be JSON-serializable.
    project = project_service.create_project("Client")
    html_keyword = "<script>alert('xss')</script>"

    result = rule_api.create_project_keyword_rule(project, html_keyword)

    assert result["ok"] is True
    assert result["rule"]["keyword"] == html_keyword
    row = _keyword_rule_row(result["rule"]["id"])
    assert row["pattern"] == html_keyword
    # The payload must be JSON-serializable without raising.
    json.dumps(result, ensure_ascii=False)


def test_create_keyword_rule_html_script_keyword_duplicate_detection(temp_db):
    # Regression lock: the duplicate check must treat the
    # HTML/script keyword as ordinary plain text — a second identical
    # keyword must be rejected as ``duplicate_rule``.
    project = project_service.create_project("Client")
    html_keyword = "<img src=x onerror=alert(1)>"
    first = rule_api.create_project_keyword_rule(project, html_keyword)
    assert first["ok"] is True

    second = rule_api.create_project_keyword_rule(project, html_keyword)
    assert second == {"ok": False, "error": "duplicate_rule"}




def test_unknown_project_returns_stable_project_not_found(temp_db):
    result = rule_api.create_project_keyword_rule(9999, "Spec")
    assert result == {"ok": False, "error": "project_not_found"}


def test_duplicate_keyword_rule_returns_stable_duplicate_rule(temp_db):
    project = project_service.create_project("Client")
    first = rule_api.create_project_keyword_rule(project, "Spec")
    assert first["ok"] is True

    second = rule_api.create_project_keyword_rule(project, "Spec")

    assert second == {"ok": False, "error": "duplicate_rule"}
    # The duplicate rejection must not create a second row.
    with get_connection() as conn:
        count = conn.execute(
            "SELECT COUNT(*) AS c FROM project_rule WHERE project_id = ? AND pattern = ?",
            (project, "Spec"),
        ).fetchone()["c"]
    assert count == 1


def test_same_keyword_different_project_is_allowed(temp_db):
    # The duplicate check is scoped to (project_id, keyword). The same
    # keyword bound to a different project is a legitimate distinct rule.
    project_a = project_service.create_project("ClientA")
    project_b = project_service.create_project("ClientB")

    result_a = rule_api.create_project_keyword_rule(project_a, "Spec")
    result_b = rule_api.create_project_keyword_rule(project_b, "Spec")

    assert result_a["ok"] is True
    assert result_b["ok"] is True
    assert result_a["rule"]["id"] != result_b["rule"]["id"]


def test_duplicate_keyword_check_is_case_sensitive_and_trim_aware(temp_db):
    project = project_service.create_project("Client")
    assert rule_api.create_project_keyword_rule(project, "Spec")["ok"] is True
    # Different case is a different keyword (existing service semantics).
    assert rule_api.create_project_keyword_rule(project, "spec")["ok"] is True
    # Trimmed version of "  Spec  " equals "Spec" -> duplicate.
    assert rule_api.create_project_keyword_rule(project, "  Spec  ") == {
        "ok": False,
        "error": "duplicate_rule",
    }




def test_service_exception_collapses_to_operation_failed(temp_db, monkeypatch):
    # Regression lock: any unexpected service exception must
    # collapse to ``operation_failed`` and never surface raw exception text
    # or SQL in the payload.
    project = project_service.create_project("Client")

    def boom(keyword, project_id):
        raise RuntimeError(
            "boom SELECT * FROM activity_log traceback window_title clipboard note C:\\Secret"
        )

    monkeypatch.setattr(rule_service, "create_rule", boom)
    result = rule_api.create_project_keyword_rule(project, "Spec")
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


def test_list_rule_target_projects_exception_collapses_to_operation_failed(temp_db, monkeypatch):
    project = project_service.create_project("Client")

    def boom():
        raise RuntimeError("boom SELECT * FROM project traceback C:\\Secret")

    monkeypatch.setattr(
        "worktrace.api.project_api.list_rule_target_projects", boom
    )
    result = rule_api.create_project_keyword_rule(project, "Spec")
    assert result == {"ok": False, "error": "operation_failed"}


def test_list_rules_exception_collapses_to_operation_failed(temp_db, monkeypatch):
    project = project_service.create_project("Client")

    def boom(include_system=False):
        raise RuntimeError("boom SELECT * FROM project_rule traceback C:\\Secret")

    monkeypatch.setattr(rule_service, "list_rules", boom)
    result = rule_api.create_project_keyword_rule(project, "Spec")
    assert result == {"ok": False, "error": "operation_failed"}




def test_create_keyword_rule_does_not_add_folder_rule_rows(temp_db):
    project = project_service.create_project("Client")
    before = _counts()

    result = rule_api.create_project_keyword_rule(project, "Spec")

    assert result["ok"] is True
    after = _counts()
    assert after["folder"] == before["folder"]
    assert after["keyword"] == before["keyword"] + 1


def test_create_keyword_rule_does_not_add_or_delete_project_rows(temp_db):
    project = project_service.create_project("Client")
    before = _counts()

    result = rule_api.create_project_keyword_rule(project, "Spec")

    assert result["ok"] is True
    after = _counts()
    assert after["project"] == before["project"]


def test_create_keyword_rule_does_not_change_activity_log_rows(temp_db):
    project = project_service.create_project("Client")
    activity_id = activity_service.create_activity(
        "Word",
        "winword.exe",
        "Spec.docx",
        start_time="2026-06-18 09:00:00",
        project_id=project,
    )
    before = _counts()

    result = rule_api.create_project_keyword_rule(project, "Spec")

    assert result["ok"] is True
    after = _counts()
    assert after["activity"] == before["activity"]
    # Rule creation does not mutate the raw activity row. Project state lives
    # in the assignment projection instead.
    with get_connection() as conn:
        assignment = conn.execute(
            "SELECT project_id FROM activity_project_assignment WHERE activity_id = ?",
            (activity_id,),
        ).fetchone()
    assert assignment["project_id"] == project


def test_create_keyword_rule_does_not_change_activity_project_assignment_rows(temp_db):
    project = project_service.create_project("Client")
    activity_service.create_activity(
        "Word",
        "winword.exe",
        "Spec.docx",
        start_time="2026-06-18 09:00:00",
        project_id=project,
    )
    before = _counts()

    result = rule_api.create_project_keyword_rule(project, "Spec")

    assert result["ok"] is True
    after = _counts()
    assert after["assignment"] == before["assignment"]


def test_create_keyword_rule_does_not_change_report_session_operation_rows(temp_db):
    project = project_service.create_project("Client")
    activity_id = activity_service.create_activity(
        "Word",
        "winword.exe",
        "Spec.docx",
        start_time="2026-06-18 09:00:00",
        project_id=project,
    )
    with get_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO report_session_operation(
                report_date, operation_type, base_instance_key, base_expected_revision, replay_order,
                match_state, payload_json, created_at, updated_at
            )
            VALUES (?, 'edit_session', ?, ?, 1, 'active', ?, ?, ?)
            """,
            ("2026-06-18", "base:" + "b" * 40, "revision-b", '{"payload_version":3,"note":{"mode":"set","value":"keep"}}', now_str(), now_str()),
        )
        conn.execute(
            """INSERT INTO report_mutation_request(
                request_id, input_signature, outcome_type, operation_id, result_json, created_at, committed_at
            ) VALUES (?, ?, 'operation_committed', ?, '{}', ?, ?)""",
            ("test-keyword-create-b", "seed-b", int(cur.lastrowid), now_str(), now_str()),
        )
    before = _counts()

    result = rule_api.create_project_keyword_rule(project, "Spec")

    assert result["ok"] is True
    after = _counts()
    assert after["session_note"] == before["session_note"]


def test_create_keyword_rule_does_not_call_conflict_preview(temp_db, monkeypatch):
    project = project_service.create_project("Client")

    def fail_preview(*args, **kwargs):
        raise AssertionError("conflict preview must not run during keyword create")

    monkeypatch.setattr(folder_rule_service, "preview_folder_rule_conflicts", fail_preview)
    result = rule_api.create_project_keyword_rule(project, "Spec")
    assert result["ok"] is True


def test_create_keyword_rule_does_not_call_backfill(temp_db, monkeypatch):
    project = project_service.create_project("Client")

    def fail_backfill(*args, **kwargs):
        raise AssertionError("backfill must not run during keyword create")

    from worktrace.services import rule_impact_service

    monkeypatch.setattr(rule_impact_service, "backfill_rule_impact", fail_backfill)
    result = rule_api.create_project_keyword_rule(project, "Spec")
    assert result["ok"] is True


def test_create_keyword_rule_does_not_call_folder_rule_create(temp_db, monkeypatch):
    project = project_service.create_project("Client")

    def fail_folder_create(*args, **kwargs):
        raise AssertionError("folder rule create must not run during keyword create")

    monkeypatch.setattr(folder_rule_service, "create_or_update_folder_rule", fail_folder_create)
    result = rule_api.create_project_keyword_rule(project, "Spec")
    assert result["ok"] is True




def test_create_keyword_rule_invalidates_keyword_rule_cache(temp_db, monkeypatch):
    # Regression lock: ``rule_service.create_rule`` calls
    # ``invalidate_keyword_rule_cache`` so newly created keyword rules take
    # effect immediately for project inference. The API facade must not
    # bypass that cache invalidation.
    project = project_service.create_project("Client")
    project_inference_service.invalidate_keyword_rule_cache()

    calls = {"count": 0}
    original = project_inference_service.invalidate_keyword_rule_cache

    def spy():
        calls["count"] += 1
        original()

    monkeypatch.setattr(rule_service, "invalidate_keyword_rule_cache", spy)
    # Also patch the re-exported name inside project_inference_service so the
    # ``from .project_inference_service import invalidate_keyword_rule_cache``
    # reference inside ``rule_service.create_rule`` resolves to the spy.
    monkeypatch.setattr(
        "worktrace.services.rule_service.invalidate_keyword_rule_cache", spy
    )

    result = rule_api.create_project_keyword_rule(project, "Spec")

    assert result["ok"] is True
    assert calls["count"] >= 1


def test_create_keyword_rule_clears_exclude_rules_cache(temp_db, monkeypatch):
    # Regression lock: ``rule_service.create_rule`` also calls
    # ``privacy_service.clear_exclude_rules_cache`` so the privacy/exclude
    # matching result stays consistent after a new keyword rule is created.
    from worktrace.services import privacy_service

    project = project_service.create_project("Client")

    calls = {"count": 0}
    original = privacy_service.clear_exclude_rules_cache

    def spy():
        calls["count"] += 1
        original()

    monkeypatch.setattr(privacy_service, "clear_exclude_rules_cache", spy)

    result = rule_api.create_project_keyword_rule(project, "Spec")

    assert result["ok"] is True
    assert calls["count"] >= 1




def test_create_keyword_rule_payload_is_json_serializable(temp_db):
    project = project_service.create_project("Client")

    result = rule_api.create_project_keyword_rule(project, "Spec")

    json.dumps(result, ensure_ascii=False)
    assert "Traceback" not in repr(result)
    assert "SELECT" not in repr(result)


def test_create_keyword_rule_success_payload_types_are_stable(temp_db):
    project = project_service.create_project("Client")

    result = rule_api.create_project_keyword_rule(project, "Spec")

    assert type(result["ok"]) is bool
    rule = result["rule"]
    assert type(rule["kind"]) is str
    assert type(rule["id"]) is int
    assert type(rule["project_id"]) is int
    assert type(rule["keyword"]) is str
    assert type(rule["enabled"]) is bool


def test_create_keyword_rule_failure_payloads_are_json_serializable(temp_db):
    project = project_service.create_project("Client")

    failures = [
        rule_api.create_project_keyword_rule(True, "Spec"),
        rule_api.create_project_keyword_rule(project, None),
        rule_api.create_project_keyword_rule(9999, "Spec"),
        rule_api.create_project_keyword_rule(project, "   "),
    ]
    # First create one valid rule, then attempt a duplicate.
    assert rule_api.create_project_keyword_rule(project, "Spec")["ok"] is True
    failures.append(rule_api.create_project_keyword_rule(project, "Spec"))

    for result in failures:
        assert result["ok"] is False
        json.dumps(result, ensure_ascii=False)
        assert "Traceback" not in repr(result)
        assert "SELECT" not in repr(result)




def test_existing_set_project_rule_enabled_still_works(temp_db):
    # Regression lock: the new ``create_project_keyword_rule`` facade
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


def test_create_keyword_rule_does_not_toggle_existing_rules(temp_db):
    # Regression lock: creating a new keyword rule must not change
    # the enabled state of any existing rule.
    project = project_service.create_project("Client")
    existing_rule = rule_service.create_rule("Existing", project)
    # Disable the existing rule so we can detect any accidental enable.
    rule_api.set_project_rule_enabled("keyword", existing_rule, False)

    with get_connection() as conn:
        before = conn.execute(
            "SELECT enabled FROM project_rule WHERE id = ?",
            (existing_rule,),
        ).fetchone()["enabled"]
    assert before == 0

    result = rule_api.create_project_keyword_rule(project, "NewKeyword")

    assert result["ok"] is True
    with get_connection() as conn:
        after = conn.execute(
            "SELECT enabled FROM project_rule WHERE id = ?",
            (existing_rule,),
        ).fetchone()["enabled"]
    assert after == 0




def test_create_excluded_keyword_rule_for_webview_success(temp_db):
    # Regression lock: the dedicated facade creates a keyword rule
    # on the special ``排除规则`` project, trims the keyword, and returns the
    # narrow created-rule summary. It does NOT accept a project_id from the
    # caller — the project is resolved internally.
    result = rule_api.create_excluded_keyword_rule_for_webview("  排除词  ")

    assert result["ok"] is True
    rule = result["rule"]
    assert rule["kind"] == "keyword"
    assert isinstance(rule["id"], int)
    assert rule["id"] > 0
    excluded_id = project_service.get_or_create_excluded_project()
    assert rule["project_id"] == excluded_id
    assert rule["keyword"] == "排除词"
    assert rule["enabled"] is True

    row = _keyword_rule_row(rule["id"])
    assert row["project_id"] == excluded_id
    assert row["pattern"] == "排除词"
    assert row["enabled"] == 1
    # The excluded project is a system project: enabled=0, created_by=system.
    with get_connection() as conn:
        proj = conn.execute(
            "SELECT name, enabled, created_by FROM project WHERE id = ?",
            (excluded_id,),
        ).fetchone()
    assert proj["name"] == EXCLUDED_PROJECT
    assert proj["enabled"] == 0
    assert proj["created_by"] == "system"
    json.dumps(result, ensure_ascii=False)


@pytest.mark.parametrize(
    "bad_keyword", [None, True, False, 1, 1.5, [], {}, b"kw", "", "   ", "\t\n"]
)
def test_create_excluded_keyword_rule_for_webview_rejects_invalid_input(
    temp_db, bad_keyword
):
    # Regression lock: non-str / whitespace-only keyword collapses
    # to ``invalid_input`` and creates no rule row.
    before = _counts()
    result = rule_api.create_excluded_keyword_rule_for_webview(bad_keyword)
    after = _counts()

    assert result == {"ok": False, "error": "invalid_input"}
    assert after["keyword"] == before["keyword"]


def test_create_excluded_keyword_rule_for_webview_rejects_duplicate(temp_db):
    # Regression lock: an exact duplicate (same excluded project +
    # same trimmed keyword) is rejected as ``duplicate_rule`` and creates no
    # second row.
    first = rule_api.create_excluded_keyword_rule_for_webview("敏感词")
    assert first["ok"] is True

    second = rule_api.create_excluded_keyword_rule_for_webview("  敏感词  ")

    assert second == {"ok": False, "error": "duplicate_rule"}
    with get_connection() as conn:
        count = conn.execute(
            "SELECT COUNT(*) AS c FROM project_rule WHERE pattern = ?",
            ("敏感词",),
        ).fetchone()["c"]
    assert count == 1


def test_create_excluded_keyword_rule_for_webview_exception_collapses(
    temp_db, monkeypatch
):
    # Regression lock: an unexpected service failure collapses to
    # ``operation_failed`` without surfacing the exception text, traceback,
    # SQL, or sensitive metadata.
    def _raise(*args, **kwargs):
        raise RuntimeError(
            "boom SELECT * FROM activity_log traceback window_title "
            "clipboard note C:\\Secret"
        )

    monkeypatch.setattr(rule_service, "create_rule", _raise)

    result = rule_api.create_excluded_keyword_rule_for_webview("kw")

    assert_api_error_envelope(result, "operation_failed")
    assert_privacy_redacted(
        result,
        [
            "traceback",
            "sqlite",
            "select ",
            "window_title",
            "clipboard",
            "note",
            "secret",
            "c:\\",
        ],
    )
    json.dumps(result, ensure_ascii=False)
