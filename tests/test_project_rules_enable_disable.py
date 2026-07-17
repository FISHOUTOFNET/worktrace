from __future__ import annotations

import pytest

from worktrace.api import rule_api
from worktrace.constants import EXCLUDED_PROJECT
from worktrace.db import get_connection, now_str
from tests.support import activity_factory as activity_service
from worktrace.services import (
    folder_rule_service,
    project_inference_service,
    project_service,
    rule_service,
)

pytestmark = [pytest.mark.db, pytest.mark.integration, pytest.mark.contract]


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
                "SELECT COUNT(*) AS c FROM report_session_operation"
            ).fetchone()["c"],
        }


def _enabled(table: str, rule_id: int) -> int:
    with get_connection() as conn:
        return int(
            conn.execute(f"SELECT enabled FROM {table} WHERE id = ?", (rule_id,)).fetchone()[
                "enabled"
            ]
        )


def test_keyword_rule_disable_enable_updates_existing_row(temp_db):
    project = project_service.create_project("Client")
    rule_id = rule_service.create_rule("Spec", project)

    disabled = rule_api.set_project_rule_enabled("keyword", rule_id, False)

    assert disabled == {
        "ok": True,
        "rule_type": "keyword",
        "rule_id": rule_id,
        "enabled": False,
    }
    assert _enabled("project_rule", rule_id) == 0
    enabled = rule_api.set_project_rule_enabled("keyword", rule_id, True)
    assert enabled == {
        "ok": True,
        "rule_type": "keyword",
        "rule_id": rule_id,
        "enabled": True,
    }
    assert _enabled("project_rule", rule_id) == 1


def test_folder_rule_disable_enable_updates_existing_row(temp_db):
    project = project_service.create_project("Client")
    rule_id = folder_rule_service.create_or_update_folder_rule("D:\\Client", project)

    disabled = rule_api.set_project_rule_enabled("folder", rule_id, False)

    assert disabled == {
        "ok": True,
        "rule_type": "folder",
        "rule_id": rule_id,
        "enabled": False,
    }
    assert _enabled("folder_project_rule", rule_id) == 0
    enabled = rule_api.set_project_rule_enabled("folder", rule_id, True)
    assert enabled == {
        "ok": True,
        "rule_type": "folder",
        "rule_id": rule_id,
        "enabled": True,
    }
    assert _enabled("folder_project_rule", rule_id) == 1


def test_missing_rules_return_stable_not_found(temp_db):
    assert rule_api.set_project_rule_enabled("keyword", 999, False) == {
        "ok": False,
        "error": "not_found",
    }
    assert rule_api.set_project_rule_enabled("folder", 999, False) == {
        "ok": False,
        "error": "not_found",
    }


def test_invalid_rule_type_returns_stable_invalid_input(temp_db):
    assert rule_api.set_project_rule_enabled("project", 1, True) == {
        "ok": False,
        "error": "invalid_input",
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
def test_invalid_rule_type_variants_return_stable_invalid_input(temp_db, bad_rule_type):
    # Regression lock: only ``"folder"`` and ``"keyword"`` are
    # accepted. Anything else (None, empty, case variants, plurals, unknown
    # strings, non-string types) collapses to ``invalid_input`` without
    # crossing the service layer.
    assert rule_api.set_project_rule_enabled(bad_rule_type, 1, True) == {
        "ok": False,
        "error": "invalid_input",
    }


@pytest.mark.parametrize("bad_id", [None, True, False, "1", 0, -1, 1.0])
def test_invalid_rule_id_returns_stable_invalid_input(temp_db, bad_id):
    assert rule_api.set_project_rule_enabled("keyword", bad_id, True) == {
        "ok": False,
        "error": "invalid_input",
    }


@pytest.mark.parametrize("bad_id", ["abc", "1.5", 2.5, 0.5, -999, [], {}, "true"])
def test_invalid_rule_id_extra_variants_return_stable_invalid_input(temp_db, bad_id):
    # Regression lock: numeric strings, arbitrary floats, deep
    # negatives, and container types all collapse to ``invalid_input``.
    assert rule_api.set_project_rule_enabled("folder", bad_id, True) == {
        "ok": False,
        "error": "invalid_input",
    }


@pytest.mark.parametrize("bad_enabled", [None, 0, 1, "true", "false"])
def test_invalid_enabled_returns_stable_invalid_input(temp_db, bad_enabled):
    assert rule_api.set_project_rule_enabled("keyword", 1, bad_enabled) == {
        "ok": False,
        "error": "invalid_input",
    }


@pytest.mark.parametrize("bad_enabled", ["1", "0", "True", "False", 1.0, 0.0, [], {}])
def test_invalid_enabled_extra_variants_return_stable_invalid_input(temp_db, bad_enabled):
    # Regression lock: ``enabled`` must be a real ``bool``. Numeric
    # strings, mixed-case bool strings, floats, and container types all
    # collapse to ``invalid_input``.
    assert rule_api.set_project_rule_enabled("keyword", 1, bad_enabled) == {
        "ok": False,
        "error": "invalid_input",
    }


def test_toggle_does_not_create_or_delete_projects_rules_or_activity_rows(temp_db):
    project = project_service.create_project("Client")
    folder_rule = folder_rule_service.create_or_update_folder_rule("D:\\Client", project)
    keyword_rule = rule_service.create_rule("Spec", project)
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
                    report_date, operation_type, source_instance_key, source_expected_revision, sequence,
                    payload_json, created_at
                )
                VALUES (?, 'edit_session', ?, ?, 1, ?, ?)
            """,
            (
                "2026-06-18",
                "base:" + "d" * 40,
                "revision-d",
                    '{"payload_version":4,"note":{"mode":"set","value":"keep"}}',
                    now_str(),
            ),
        )
        conn.execute(
            "INSERT INTO report_session_operation_member(operation_id, role, activity_id, report_date, slice_start_time) VALUES (?, 'source', ?, ?, ?)",
            (int(cur.lastrowid), activity_id, "2026-06-18", "2026-06-18 09:00:00"),
        )
        conn.execute(
            """INSERT INTO report_mutation_request(
                request_id, input_signature, outcome_type, operation_id, result_json, created_at, committed_at
            ) VALUES (?, ?, 'operation_committed', ?, '{}', ?, ?)""",
            ("test-enable-disable-d", "seed-d", int(cur.lastrowid), now_str(), now_str()),
        )
    before = _counts()

    assert rule_api.set_project_rule_enabled("folder", folder_rule, False)["ok"] is True
    assert rule_api.set_project_rule_enabled("keyword", keyword_rule, False)["ok"] is True

    assert _counts() == before


def test_folder_toggle_does_not_trigger_backfill(temp_db, monkeypatch):
    project = project_service.create_project("Client")
    rule_id = folder_rule_service.create_or_update_folder_rule("D:\\Client", project)

    def fail_backfill(*args, **kwargs):
        raise AssertionError("backfill must not run")

    from worktrace.services import rule_impact_service

    monkeypatch.setattr(rule_impact_service, "backfill_rule_impact", fail_backfill)

    assert rule_api.set_project_rule_enabled("folder", rule_id, False)["ok"] is True


def test_toggles_invalidate_relevant_caches(temp_db, monkeypatch):
    project = project_service.create_project("Client")
    keyword_rule = rule_service.create_rule("Spec", project)
    folder_rule = folder_rule_service.create_or_update_folder_rule("D:\\Client", project)
    project_inference_service.invalidate_keyword_rule_cache()
    folder_rule_service.invalidate_folder_rule_cache()
    assert project_inference_service._enabled_keyword_rules()
    assert folder_rule_service.find_matching_folder_rule("D:\\Client\\Spec.docx")

    keyword_calls = {"count": 0}
    folder_calls = {"count": 0}

    def keyword_invalidate():
        keyword_calls["count"] += 1
        project_inference_service.invalidate_keyword_rule_cache()

    def folder_invalidate():
        folder_calls["count"] += 1
        folder_rule_service._FOLDER_RULE_CACHE.clear()

    monkeypatch.setattr(rule_service, "invalidate_keyword_rule_cache", keyword_invalidate)
    monkeypatch.setattr(folder_rule_service, "invalidate_folder_rule_cache", folder_invalidate)

    assert rule_api.set_project_rule_enabled("keyword", keyword_rule, False)["ok"] is True
    assert rule_api.set_project_rule_enabled("folder", folder_rule, False)["ok"] is True
    assert keyword_calls["count"] == 1
    assert folder_calls["count"] == 1


def test_excluded_project_existing_rules_can_be_toggled(temp_db):
    excluded_project = project_service.get_or_create_excluded_project()
    keyword_rule = rule_service.create_rule("Secret", excluded_project)
    folder_rule = folder_rule_service.create_or_update_folder_rule("D:\\Secret", excluded_project)

    bindings = project_service.list_project_bindings()
    excluded = next(project for project in bindings if project["name"] == EXCLUDED_PROJECT)
    assert excluded["enabled"] == 0

    assert rule_api.set_project_rule_enabled("keyword", keyword_rule, False)["ok"] is True
    assert rule_api.set_project_rule_enabled("folder", folder_rule, False)["ok"] is True
    assert _enabled("project_rule", keyword_rule) == 0
    assert _enabled("folder_project_rule", folder_rule) == 0




def test_keyword_service_exception_is_folded_to_operation_failed(temp_db, monkeypatch):
    # Regression lock: when the keyword service raises any
    # exception, the API collapses it to ``operation_failed`` and never
    # surfaces the raw exception text or SQL in the payload.
    project = project_service.create_project("Client")
    rule_id = rule_service.create_rule("Spec", project)

    def boom(rule_id, enabled):
        raise RuntimeError(
            "boom SELECT * FROM activity_log traceback window_title clipboard note C:\\Secret"
        )

    monkeypatch.setattr(rule_service, "set_rule_enabled", boom)
    result = rule_api.set_project_rule_enabled("keyword", rule_id, False)
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


def test_folder_service_exception_is_folded_to_operation_failed(temp_db, monkeypatch):
    # Regression lock: same collapse behavior for the folder rule
    # service write path.
    project = project_service.create_project("Client")
    rule_id = folder_rule_service.create_or_update_folder_rule("D:\\Client", project)

    def boom(rule_id, enabled):
        raise RuntimeError(
            "boom SELECT * FROM activity_log traceback window_title clipboard note C:\\Secret"
        )

    monkeypatch.setattr(folder_rule_service, "set_folder_rule_enabled", boom)
    result = rule_api.set_project_rule_enabled("folder", rule_id, False)
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


def test_existence_check_runs_before_service_write(temp_db, monkeypatch):
    # Regression lock: when the rule does not exist, the API
    # returns ``not_found`` and never invokes the service write path. This
    # guarantees a SQLite UPDATE no-op on a missing rule is never treated as
    # success.
    keyword_calls = {"count": 0}
    folder_calls = {"count": 0}

    def fail_keyword(*args, **kwargs):
        keyword_calls["count"] += 1
        raise AssertionError("keyword service write must not run for missing rule")

    def fail_folder(*args, **kwargs):
        folder_calls["count"] += 1
        raise AssertionError("folder service write must not run for missing rule")

    monkeypatch.setattr(rule_service, "set_rule_enabled", fail_keyword)
    monkeypatch.setattr(folder_rule_service, "set_folder_rule_enabled", fail_folder)

    assert rule_api.set_project_rule_enabled("keyword", 999, False) == {
        "ok": False,
        "error": "not_found",
    }
    assert rule_api.set_project_rule_enabled("folder", 999, False) == {
        "ok": False,
        "error": "not_found",
    }
    assert keyword_calls["count"] == 0
    assert folder_calls["count"] == 0


def test_toggle_does_not_call_conflict_preview(temp_db, monkeypatch):
    # Regression lock: enabling/disabling a folder rule must not
    # invoke ``preview_folder_rule_conflicts``.
    project = project_service.create_project("Client")
    rule_id = folder_rule_service.create_or_update_folder_rule("D:\\Client", project)

    def fail_preview(*args, **kwargs):
        raise AssertionError("conflict preview must not run during toggle")

    monkeypatch.setattr(folder_rule_service, "preview_folder_rule_conflicts", fail_preview)
    assert rule_api.set_project_rule_enabled("folder", rule_id, False)["ok"] is True
    assert rule_api.set_project_rule_enabled("folder", rule_id, True)["ok"] is True


def test_toggle_idempotent_when_rule_already_at_target_state(temp_db):
    # Regression lock: re-toggling a rule to its current
    # ``enabled`` value still returns success. The existence check protects
    # against a missing-rule no-op; a same-value update on an existing rule
    # is a legitimate idempotent write.
    project = project_service.create_project("Client")
    keyword_rule = rule_service.create_rule("Spec", project)
    folder_rule = folder_rule_service.create_or_update_folder_rule("D:\\Client", project)

    assert rule_api.set_project_rule_enabled("keyword", keyword_rule, True)["ok"] is True
    assert _enabled("project_rule", keyword_rule) == 1
    assert rule_api.set_project_rule_enabled("folder", folder_rule, True)["ok"] is True
    assert _enabled("folder_project_rule", folder_rule) == 1

    assert rule_api.set_project_rule_enabled("keyword", keyword_rule, False)["ok"] is True
    assert _enabled("project_rule", keyword_rule) == 0
    assert rule_api.set_project_rule_enabled("folder", folder_rule, False)["ok"] is True
    assert _enabled("folder_project_rule", folder_rule) == 0
    # Idempotent: disable an already-disabled rule.
    assert rule_api.set_project_rule_enabled("keyword", keyword_rule, False)["ok"] is True
    assert _enabled("project_rule", keyword_rule) == 0
    assert rule_api.set_project_rule_enabled("folder", folder_rule, False)["ok"] is True
    assert _enabled("folder_project_rule", folder_rule) == 0


def test_keyword_toggle_clears_exclude_rules_cache(temp_db, monkeypatch):
    # Regression lock: the keyword service write path must keep
    # invalidating the privacy/exclude cache so the excluded-project /
    # exclude-rule matching result stays consistent after a toggle.
    from worktrace.services import privacy_service

    project = project_service.create_project("Client")
    rule_id = rule_service.create_rule("Spec", project)

    calls = {"count": 0}
    original = privacy_service.clear_exclude_rules_cache

    def spy():
        calls["count"] += 1
        original()

    monkeypatch.setattr(privacy_service, "clear_exclude_rules_cache", spy)
    assert rule_api.set_project_rule_enabled("keyword", rule_id, False)["ok"] is True
    assert calls["count"] >= 1


def test_folder_toggle_clears_exclude_rules_cache(temp_db, monkeypatch):
    # Regression lock: same as the keyword path, the folder
    # service write path keeps invalidating the privacy/exclude cache.
    from worktrace.services import privacy_service

    project = project_service.create_project("Client")
    rule_id = folder_rule_service.create_or_update_folder_rule("D:\\Client", project)

    calls = {"count": 0}
    original = privacy_service.clear_exclude_rules_cache

    def spy():
        calls["count"] += 1
        original()

    monkeypatch.setattr(privacy_service, "clear_exclude_rules_cache", spy)
    assert rule_api.set_project_rule_enabled("folder", rule_id, False)["ok"] is True
    assert calls["count"] >= 1


def test_toggle_does_not_change_history_activity_assignment_or_session_note_rows(temp_db):
    # Regression lock: re-affirm with explicit pre/post counts
    # that the toggle write path leaves activity history, project assignment,
    # and session notes untouched even when a folder/keyword rule is toggled
    # multiple times.
    project = project_service.create_project("Client")
    keyword_rule = rule_service.create_rule("Spec", project)
    folder_rule = folder_rule_service.create_or_update_folder_rule("D:\\Client", project)
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
                    report_date, operation_type, source_instance_key, source_expected_revision, sequence,
                    payload_json, created_at
                )
                VALUES (?, 'edit_session', ?, ?, 1, ?, ?)
            """,
            (
                "2026-06-18",
                "base:" + "e" * 40,
                "revision-e",
                    '{"payload_version":4,"note":{"mode":"set","value":"keep"}}',
                    now_str(),
            ),
        )
        conn.execute(
            "INSERT INTO report_session_operation_member(operation_id, role, activity_id, report_date, slice_start_time) VALUES (?, 'source', ?, ?, ?)",
            (int(cur.lastrowid), activity_id, "2026-06-18", "2026-06-18 09:00:00"),
        )
        conn.execute(
            """INSERT INTO report_mutation_request(
                request_id, input_signature, outcome_type, operation_id, result_json, created_at, committed_at
            ) VALUES (?, ?, 'operation_committed', ?, '{}', ?, ?)""",
            ("test-enable-disable-e", "seed-e", int(cur.lastrowid), now_str(), now_str()),
        )
    before = _counts()

    for _ in range(3):
        assert rule_api.set_project_rule_enabled("keyword", keyword_rule, False)["ok"] is True
        assert rule_api.set_project_rule_enabled("keyword", keyword_rule, True)["ok"] is True
        assert rule_api.set_project_rule_enabled("folder", folder_rule, False)["ok"] is True
        assert rule_api.set_project_rule_enabled("folder", folder_rule, True)["ok"] is True

    assert _counts() == before


def test_toggle_payload_is_json_serializable_and_stable(temp_db):
    # Regression lock: the API success payload must remain a plain
    # JSON-serializable dict with the exact stable shape the bridge expects.
    import json

    project = project_service.create_project("Client")
    keyword_rule = rule_service.create_rule("Spec", project)
    folder_rule = folder_rule_service.create_or_update_folder_rule("D:\\Client", project)

    keyword_result = rule_api.set_project_rule_enabled("keyword", keyword_rule, False)
    folder_result = rule_api.set_project_rule_enabled("folder", folder_rule, True)

    json.dumps(keyword_result, ensure_ascii=False)
    json.dumps(folder_result, ensure_ascii=False)
    assert keyword_result == {
        "ok": True,
        "rule_type": "keyword",
        "rule_id": keyword_rule,
        "enabled": False,
    }
    assert folder_result == {
        "ok": True,
        "rule_type": "folder",
        "rule_id": folder_rule,
        "enabled": True,
    }
    assert isinstance(keyword_result["rule_id"], int)
    assert isinstance(folder_result["rule_id"], int)
    assert isinstance(keyword_result["enabled"], bool)
    assert isinstance(folder_result["enabled"], bool)
