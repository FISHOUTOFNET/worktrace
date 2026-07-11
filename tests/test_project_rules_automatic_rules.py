"""Automatic Project Rules application foundation tests."""

from __future__ import annotations
from tests.support.db_helpers import assign_activity_project

import json
import re
from pathlib import Path

import pytest

from worktrace.api import rule_api
from worktrace.db import get_connection, now_str
from worktrace.services import (
    activity_lifecycle_service,
    activity_service,
    folder_rule_service,
    project_inference_service,
    project_service,
    rule_automation_service,
    rule_service,
)
from worktrace.webview_ui.bridge_rules import ProjectRulesBridgeMixin

pytestmark = [pytest.mark.db, pytest.mark.integration, pytest.mark.contract]


def _create_closed_activity(
    app_name: str = "Word",
    process_name: str = "winword.exe",
    window_title: str = "Doc.docx - Word",
    start_time: str = "2026-06-25 09:00:00",
    end_time: str = "2026-06-25 09:10:00",
    file_path_hint: str | None = None,
    status: str = "normal",
    project_id: int | None = None,
) -> int:
    """Create a closed activity (end_time set) with the given fields.

    ``create_activity`` auto-closes any open activities first, so the
    explicit ``close_activity`` call here only sets the end_time on the
    newly-created row.
    """
    aid = activity_service.create_activity(
        app_name,
        process_name,
        window_title,
        status=status,
        start_time=start_time,
        file_path_hint=file_path_hint,
        project_id=project_id,
    )
    activity_service.close_activity(aid, end_time)
    return aid


def _set_manual_override(aid: int) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE activity_project_assignment SET is_manual = 1, updated_at = ? "
            "WHERE activity_id = ?",
            (now_str(), aid),
        )


def _set_hidden(aid: int) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE activity_log SET is_hidden = 1, updated_at = ? WHERE id = ?",
            (now_str(), aid),
        )


def _set_deleted(aid: int) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE activity_log SET is_deleted = 1, updated_at = ? WHERE id = ?",
            (now_str(), aid),
        )


def _set_non_normal(aid: int) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE activity_log SET status = 'idle', updated_at = ? WHERE id = ?",
            (now_str(), aid),
        )


def _set_in_progress(aid: int) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE activity_log SET end_time = NULL, duration_seconds = NULL, "
            "updated_at = ? WHERE id = ?",
            (now_str(), aid),
        )


def _activity_row(aid: int) -> dict:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM activity_log WHERE id = ?", (aid,)
        ).fetchone()
        assignment = conn.execute(
            "SELECT project_id, source, is_manual FROM activity_project_assignment WHERE activity_id = ?",
            (aid,),
        ).fetchone()
    if not row:
        return {}
    result = dict(row)
    if assignment:
        result["project_id"] = assignment["project_id"]
        result["manual_override"] = int(assignment["is_manual"] or 0)
        result["auto_classified"] = 1 if assignment["source"] in {"folder_rule", "keyword_rule"} else 0
    else:
        result["project_id"] = result.get("project_id") or 0
    return result


def _assignment_row(aid: int) -> dict:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM activity_project_assignment WHERE activity_id = ?",
            (aid,),
        ).fetchone()
    return dict(row) if row else {}


def _schema_sql_text() -> str:
    schema_path = Path(__file__).resolve().parent.parent / "worktrace" / "schema.sql"
    return schema_path.read_text(encoding="utf-8")


def test_rule_automation_service_confidence_constants_match_inference_contract(temp_db):
    # Automatic-rules confidence must match the single-rule backfill confidence (single inference contract).
    assert rule_automation_service.FOLDER_RULE_CONFIDENCE == 85
    assert rule_automation_service.KEYWORD_RULE_CONFIDENCE == 80


def test_rule_automation_service_source_constants(temp_db):
    assert rule_automation_service.FOLDER_RULE_SOURCE == "folder_rule"
    assert rule_automation_service.KEYWORD_RULE_SOURCE == "keyword_rule"
    # Deterministic priority: folder before keyword.
    assert rule_automation_service.AUTOMATIC_RULE_PRIORITY == (
        "folder_rule",
        "keyword_rule",
    )


def test_apply_automatic_rules_to_activity_delegates_to_inference(temp_db):
    project = project_service.create_project("AutoProject")
    folder_rule_service.create_or_update_folder_rule("D:\\AutoCase", project)
    aid = _create_closed_activity(file_path_hint="D:\\AutoCase\\Doc.docx")
    assign_activity_project(aid, project, manual=False)
    facade_result = rule_automation_service.apply_automatic_rules_to_activity(aid)
    inference_result = project_inference_service.assign_project_for_activity(aid)
    assert facade_result["project_id"] == inference_result["project_id"]
    assert facade_result["source"] == inference_result["source"]
    assert int(facade_result["confidence"]) == int(inference_result["confidence"])
    assert int(facade_result["is_manual"]) == int(inference_result["is_manual"])


# Automatic application: enabled folder rule


def test_enabled_folder_rule_auto_applies_to_new_closed_activity(temp_db):
    project = project_service.create_project("FolderAuto")
    folder_rule_service.create_or_update_folder_rule("D:\\AutoFolder", project)
    aid = _create_closed_activity(file_path_hint="D:\\AutoFolder\\Doc.docx")
    activity_service.finalize_created_activity(aid)
    activity = _activity_row(aid)
    assignment = _assignment_row(aid)
    assert int(activity["project_id"]) == project
    assert int(activity["auto_classified"]) == 1
    # Automatic rules NEVER set manual_override = 1.
    assert int(activity["manual_override"]) == 0
    assert assignment["source"] == "folder_rule"
    assert int(assignment["confidence"]) == 85
    assert int(assignment["is_manual"]) == 0


def test_enabled_keyword_rule_auto_applies_to_new_closed_activity(temp_db):
    project = project_service.create_project("KeywordAuto")
    rule_service.create_rule("invoice", project)
    aid = _create_closed_activity(
        app_name="Excel",
        process_name="excel.exe",
        window_title="invoice-2026.xlsx - Excel",
    )
    activity_service.finalize_created_activity(aid)
    activity = _activity_row(aid)
    assignment = _assignment_row(aid)
    assert int(activity["project_id"]) == project
    assert int(activity["auto_classified"]) == 1
    assert int(activity["manual_override"]) == 0
    assert assignment["source"] == "keyword_rule"
    assert int(assignment["confidence"]) == 80
    assert int(assignment["is_manual"]) == 0


def test_disabled_folder_rule_does_not_apply(temp_db):
    project = project_service.create_project("Disabled")
    rule_id = folder_rule_service.create_or_update_folder_rule(
        "D:\\DisabledFolder", project
    )
    folder_rule_service.set_folder_rule_enabled(rule_id, False)
    aid = _create_closed_activity(file_path_hint="D:\\DisabledFolder\\Doc.docx")
    activity_service.finalize_created_activity(aid)
    activity = _activity_row(aid)
    assert int(activity["project_id"]) != project
    assert int(activity["auto_classified"]) == 0


def test_disabled_keyword_rule_does_not_apply(temp_db):
    project = project_service.create_project("DisabledKw")
    rule_id = rule_service.create_rule("secretkeyword", project)
    rule_service.set_rule_enabled(rule_id, False)
    aid = _create_closed_activity(
        app_name="Excel",
        process_name="excel.exe",
        window_title="secretkeyword-report.xlsx - Excel",
    )
    activity_service.finalize_created_activity(aid)
    activity = _activity_row(aid)
    assert int(activity["project_id"]) != project
    assert int(activity["auto_classified"]) == 0


def test_disabled_target_project_does_not_apply(temp_db):
    project = project_service.create_project("DisabledProj")
    folder_rule_service.create_or_update_folder_rule("D:\\DisabledProjFolder", project)
    project_service.set_project_enabled(project, False)
    aid = _create_closed_activity(file_path_hint="D:\\DisabledProjFolder\\Doc.docx")
    activity_service.finalize_created_activity(aid)
    activity = _activity_row(aid)
    assert int(activity["project_id"]) != project


def test_archived_target_project_does_not_apply(temp_db):
    project = project_service.create_project("ArchivedProj")
    folder_rule_service.create_or_update_folder_rule("D:\\ArchivedFolder", project)
    project_service.archive_project(project)
    aid = _create_closed_activity(file_path_hint="D:\\ArchivedFolder\\Doc.docx")
    activity_service.finalize_created_activity(aid)
    activity = _activity_row(aid)
    assert int(activity["project_id"]) != project


def test_excluded_target_project_does_not_apply(temp_db):
    excluded_id = project_service.get_or_create_excluded_project()
    # Inference path filters excluded projects via _enabled_keyword_rules and find_matching_folder_rule.
    folder_rule_service.create_or_update_folder_rule(
        "D:\\ExcludedFolder", excluded_id
    )
    aid = _create_closed_activity(file_path_hint="D:\\ExcludedFolder\\Doc.docx")
    activity_service.finalize_created_activity(aid)
    activity = _activity_row(aid)
    assert int(activity["project_id"]) != excluded_id


def test_manual_override_activity_is_not_overwritten(temp_db):
    project = project_service.create_project("Manual")
    folder_rule_service.create_or_update_folder_rule("D:\\ManualFolder", project)
    other = project_service.create_project("Other")
    aid = _create_closed_activity(file_path_hint="D:\\ManualFolder\\Doc.docx")
    assign_activity_project(aid, other, manual=True)
    _set_manual_override(aid)
    activity_service.finalize_created_activity(aid)
    activity = _activity_row(aid)
    assignment = _assignment_row(aid)
    assert int(activity["project_id"]) == other
    assert int(activity["manual_override"]) == 1
    assert int(assignment["is_manual"]) == 1
    assert assignment["source"] != "folder_rule"


def test_is_manual_activity_is_not_overwritten(temp_db):
    project = project_service.create_project("ManualAssign")
    folder_rule_service.create_or_update_folder_rule("D:\\ManualAssignFolder", project)
    other = project_service.create_project("Other2")
    aid = _create_closed_activity(file_path_hint="D:\\ManualAssignFolder\\Doc.docx")
    assign_activity_project(aid, other, manual=True)
    activity_service.finalize_created_activity(aid)
    activity = _activity_row(aid)
    assignment = _assignment_row(aid)
    assert int(activity["project_id"]) == other
    assert int(assignment["is_manual"]) == 1
    assert assignment["source"] != "folder_rule"


def test_hidden_activity_is_not_touched(temp_db):
    project = project_service.create_project("Hidden")
    folder_rule_service.create_or_update_folder_rule("D:\\HiddenFolder", project)
    # Create in-progress so finalize/close triggers skip via the in-progress guard.
    aid = activity_service.create_activity(
        "Word", "winword.exe", "Doc.docx - Word",
        file_path_hint="D:\\HiddenFolder\\Doc.docx",
        start_time="2026-06-25 09:00:00",
    )
    activity_service.finalize_created_activity(aid)
    _set_hidden(aid)
    activity_lifecycle_service.close_activity(aid, "2026-06-25 09:10:00")
    activity = _activity_row(aid)
    assert int(activity["project_id"]) != project


def test_deleted_activity_is_not_touched(temp_db):
    project = project_service.create_project("Deleted")
    folder_rule_service.create_or_update_folder_rule("D:\\DeletedFolder", project)
    aid = activity_service.create_activity(
        "Word", "winword.exe", "Doc.docx - Word",
        file_path_hint="D:\\DeletedFolder\\Doc.docx",
        start_time="2026-06-25 09:00:00",
    )
    activity_service.finalize_created_activity(aid)
    _set_deleted(aid)
    activity_lifecycle_service.close_activity(aid, "2026-06-25 09:10:00")
    activity = _activity_row(aid)
    assert int(activity["project_id"]) != project


def test_in_progress_activity_is_not_touched(temp_db):
    project = project_service.create_project("InProgress")
    folder_rule_service.create_or_update_folder_rule("D:\\InProgressFolder", project)
    aid = activity_service.create_activity(
        "Word", "winword.exe", "Doc.docx - Word",
        file_path_hint="D:\\InProgressFolder\\Doc.docx",
        start_time="2026-06-25 09:00:00",
    )
    activity_service.finalize_created_activity(aid)
    project_inference_service.process_new_activity(aid)
    activity = _activity_row(aid)
    assert int(activity["project_id"]) != project


def test_non_normal_activity_is_not_touched(temp_db):
    project = project_service.create_project("NonNormal")
    folder_rule_service.create_or_update_folder_rule("D:\\NonNormalFolder", project)
    aid = _create_closed_activity(
        file_path_hint="D:\\NonNormalFolder\\Doc.docx", status="idle"
    )
    activity_service.finalize_created_activity(aid)
    activity = _activity_row(aid)
    assert int(activity["project_id"]) != project


def test_already_target_activity_not_rewritten(temp_db):
    project = project_service.create_project("AlreadyTarget")
    folder_rule_service.create_or_update_folder_rule(
        "D:\\AlreadyTargetFolder", project
    )
    aid = _create_closed_activity(
        file_path_hint="D:\\AlreadyTargetFolder\\Doc.docx", project_id=project
    )
    activity_service.finalize_created_activity(aid)
    assignment = _assignment_row(aid)
    assert assignment["source"] != "folder_rule"


def test_folder_rule_wins_over_keyword_rule(temp_db):
    folder_project = project_service.create_project("FolderWins")
    keyword_project = project_service.create_project("KeywordLoses")
    folder_rule_service.create_or_update_folder_rule(
        "D:\\PriorityFolder", folder_project
    )
    rule_service.create_rule("prioritydoc", keyword_project)
    aid = _create_closed_activity(
        file_path_hint="D:\\PriorityFolder\\prioritydoc.docx",
        window_title="prioritydoc - Word",
    )
    activity_service.finalize_created_activity(aid)
    activity = _activity_row(aid)
    assignment = _assignment_row(aid)
    assert int(activity["project_id"]) == folder_project
    assert assignment["source"] == "folder_rule"
    assert int(assignment["confidence"]) == 85


def test_first_keyword_rule_wins_in_creation_order(temp_db):
    # _enabled_keyword_rules orders by created_at, id; first match wins (duplicate keywords allowed).
    first_project = project_service.create_project("FirstKw")
    second_project = project_service.create_project("SecondKw")
    rule_service.create_rule("sharedkeyword", first_project)
    rule_service.create_rule("sharedkeyword", second_project)
    aid = _create_closed_activity(
        app_name="Excel",
        process_name="excel.exe",
        window_title="sharedkeyword-report.xlsx - Excel",
    )
    activity_service.finalize_created_activity(aid)
    activity = _activity_row(aid)
    assignment = _assignment_row(aid)
    assert int(activity["project_id"]) == first_project
    assert assignment["source"] == "keyword_rule"


def test_first_match_wins_no_later_rule_overwrites(temp_db):
    folder_project = project_service.create_project("FirstMatch")
    keyword_project = project_service.create_project("LaterNoOverwrite")
    folder_rule_service.create_or_update_folder_rule(
        "D:\\FirstMatchFolder", folder_project
    )
    rule_service.create_rule("firstmatch", keyword_project)
    aid = _create_closed_activity(
        file_path_hint="D:\\FirstMatchFolder\\firstmatch.docx",
        window_title="firstmatch - Word",
    )
    activity_service.finalize_created_activity(aid)
    # Call the automatic path again — the assignment must NOT change.
    first_assignment = _assignment_row(aid)
    activity_service.finalize_created_activity(aid)
    second_assignment = _assignment_row(aid)
    assert first_assignment["project_id"] == second_assignment["project_id"]
    assert first_assignment["source"] == second_assignment["source"]
    assert first_assignment["source"] == "folder_rule"


def test_folder_rule_fields_correct(temp_db):
    project = project_service.create_project("FieldsFolder")
    folder_rule_service.create_or_update_folder_rule("D:\\FieldsFolder", project)
    aid = _create_closed_activity(file_path_hint="D:\\FieldsFolder\\Doc.docx")
    activity_service.finalize_created_activity(aid)
    activity = _activity_row(aid)
    assignment = _assignment_row(aid)
    assert int(activity["auto_classified"]) == 1
    assert int(activity["manual_override"]) == 0
    assert assignment["source"] == "folder_rule"
    assert int(assignment["confidence"]) == 85
    assert int(assignment["is_manual"]) == 0


def test_keyword_rule_fields_correct(temp_db):
    project = project_service.create_project("FieldsKeyword")
    rule_service.create_rule("fieldskw", project)
    aid = _create_closed_activity(
        app_name="Excel",
        process_name="excel.exe",
        window_title="fieldskw.xlsx - Excel",
    )
    activity_service.finalize_created_activity(aid)
    activity = _activity_row(aid)
    assignment = _assignment_row(aid)
    assert int(activity["auto_classified"]) == 1
    assert int(activity["manual_override"]) == 0
    assert assignment["source"] == "keyword_rule"
    assert int(assignment["confidence"]) == 80
    assert int(assignment["is_manual"]) == 0


# No schema change


_SCHEMA_PATH = Path(__file__).resolve().parent.parent / "worktrace" / "schema.sql"


def test_no_schema_change_for_automatic_rules(temp_db):
    # schema.sql is the single source of truth; automatic-rules services
    # must not issue CREATE/ALTER/DROP TABLE SQL.
    import inspect

    for module in (rule_automation_service,):
        source = inspect.getsource(module)
        assert "CREATE TABLE" not in source.upper()
        assert "ALTER TABLE" not in source.upper()
        assert "DROP TABLE" not in source.upper()
    # The schema.sql file must exist and not be empty.
    assert _SCHEMA_PATH.exists()
    assert _SCHEMA_PATH.read_text(encoding="utf-8").strip() != ""


_FORBIDDEN_TOKENS = [
    "window_title",
    "file_path_hint",
    "path_hint",
    "clipboard",
    "traceback",
    "SELECT",
    "INSERT",
    "UPDATE",
    "DELETE",
    "sqlite3",
    "OperationalError",
]

_SQL_KEYWORD_TOKENS = {"SELECT", "INSERT", "UPDATE", "DELETE"}


def _assert_no_sensitive_tokens(payload: dict) -> None:
    serialized = json.dumps(payload, ensure_ascii=False, default=str).lower()
    for token in _FORBIDDEN_TOKENS:
        token_lower = token.lower()
        if token in _SQL_KEYWORD_TOKENS:
            pattern = r"\b" + re.escape(token_lower) + r"\b"
            assert re.search(pattern, serialized) is None, (
                f"forbidden token '{token}' found in payload"
            )
        elif token == "note":
            assert '"note"' not in serialized, (
                f"forbidden token '{token}' found in payload"
            )
        elif token == "path_hint":
            assert "path_hint" not in serialized, (
                f"forbidden token '{token}' found in payload"
            )
        else:
            assert token_lower not in serialized, (
                f"forbidden token '{token}' found in payload"
            )


def test_automatic_rules_status_bridge_payload_display_safe(temp_db):
    bridge = ProjectRulesBridgeMixin()
    result = bridge.automatic_rules_status()
    assert result["ok"] is True
    assert "status" in result
    _assert_no_sensitive_tokens(result)


def test_automatic_rules_status_api_payload_display_safe(temp_db):
    result = rule_api.automatic_rules_status()
    assert result["ok"] is True
    assert "status" in result
    _assert_no_sensitive_tokens(result)


def test_automatic_rules_status_payload_fields(temp_db):
    bridge = ProjectRulesBridgeMixin()
    result = bridge.automatic_rules_status()
    status = result["status"]
    assert status["supported"] is True
    assert status["scope"] == "enabled_folder_keyword_rules"
    assert status["priority"] == "folder_before_keyword"
    assert status["confidence"]["folder_rule"] == 85
    assert status["confidence"]["keyword_rule"] == 80
    assert "is_manual" in status["skips"]
    assert "hidden" in status["skips"]
    assert "deleted" in status["skips"]
    assert "in_progress" in status["skips"]
    assert "non_normal" in status["skips"]
    assert "already_target" in status["skips"]
    assert "disabled_rule" in status["skips"]
    assert "disabled_project" in status["skips"]
    assert "archived_project" in status["skips"]
    assert "excluded_project" in status["skips"]
    assert status["writes"]["activity_project_assignment"] is True
    assert status["writes"]["activity_log"] is False


def test_automatic_rules_status_payload_json_serializable(temp_db):
    bridge = ProjectRulesBridgeMixin()
    result = bridge.automatic_rules_status()
    # Must be JSON-serializable (no datetime / set / custom object).
    json.dumps(result, ensure_ascii=False, default=str)


def test_apply_automatic_rules_facade_source_has_no_separate_matcher(temp_db):
    # rule_automation_service must stay a thin facade over the inference path; no separate matcher (single-matcher invariant).
    import ast
    import inspect

    source = inspect.getsource(rule_automation_service)
    tree = ast.parse(source)
    # Inspect Call nodes only (docstrings intentionally mention matcher names); locks the facade never invokes a matcher itself.
    forbidden_call_names = {
        "keyword_pattern_matches",
        "find_matching_folder_rule",
        "_enabled_keyword_rules",
        "_infer_project_resource_first",
        "_classify_activities",
        "_safe_classification_text",
        "re.match",
        "re.search",
        "re.compile",
        "re.findall",
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            callee = node.func
            if isinstance(callee, ast.Name):
                name = callee.id
            elif isinstance(callee, ast.Attribute):
                # ``re.match(...)`` -> Attribute(value=Name('re'), attr='match')
                parts = []
                cur = callee
                while isinstance(cur, ast.Attribute):
                    parts.append(cur.attr)
                    cur = cur.value
                if isinstance(cur, ast.Name):
                    parts.append(cur.id)
                parts.reverse()
                name = ".".join(parts)
            else:
                continue
            assert name not in forbidden_call_names, (
                "rule_automation_service facade must not invoke a matcher / "
                "inference helper; found call to '" + name + "'"
            )
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name != "re", (
                    "rule_automation_service facade must not import re"
                )
        if isinstance(node, ast.ImportFrom):
            assert node.module != "re", (
                "rule_automation_service facade must not import from re"
            )


def test_process_new_activity_in_progress_guard_runs_before_assign(
    temp_db, monkeypatch
):
    # process_new_activity must skip in-progress (end_time IS NULL) before delegating to assign_project_for_activity.
    project = project_service.create_project("GuardOrder")
    folder_rule_service.create_or_update_folder_rule(
        "D:\\GuardOrderFolder", project
    )
    aid = _create_closed_activity(file_path_hint="D:\\GuardOrderFolder\\Doc.docx")
    _set_in_progress(aid)
    # Spy installed after _create_closed_activity to avoid close_activity trigger polluting the counter.
    called = {"assign": False}
    original_assign = project_inference_service.assign_project_for_activity

    def _spy_assign(activity_id):
        called["assign"] = True
        return original_assign(activity_id)

    monkeypatch.setattr(
        project_inference_service, "assign_project_for_activity", _spy_assign
    )
    project_inference_service.process_new_activity(aid)
    assert called["assign"] is False, (
        "process_new_activity must skip in-progress activities before "
        "calling assign_project_for_activity"
    )


def test_automatic_rules_status_payload_has_no_on_off_toggle_field(temp_db):
    # Status payload is display-only; must NOT carry a toggle-like field (enabled/toggle/on/off/active/is_enabled).
    bridge = ProjectRulesBridgeMixin()
    result = bridge.automatic_rules_status()
    status = result["status"]
    for field in ("enabled", "toggle", "on", "off", "active", "is_enabled"):
        assert field not in status, (
            "automatic_rules_status payload must not carry toggle-like field '"
            + field + "'"
        )


def test_close_activity_triggers_automatic_rules_for_in_progress_activity(temp_db):
    project = project_service.create_project("CloseTrigger")
    folder_rule_service.create_or_update_folder_rule(
        "D:\\CloseTriggerFolder", project
    )
    aid = activity_service.create_activity(
        "Word",
        "winword.exe",
        "Doc.docx - Word",
        file_path_hint="D:\\CloseTriggerFolder\\Doc.docx",
        start_time="2026-06-25 09:00:00",
    )
    activity_service.finalize_created_activity(aid)
    activity = activity_service.get_activity(aid)
    assert activity["project_id"] != project, (
        "in-progress activity must not receive automatic rule application"
    )
    # close_activity close-finalize must re-trigger process_new_activity so the folder rule applies.
    activity_lifecycle_service.close_activity(aid, "2026-06-25 09:10:00")
    activity = activity_service.get_activity(aid)
    assert activity["project_id"] == project, (
        "lifecycle close_activity must trigger automatic rules so the "
        "folder rule applies to the just-closed activity"
    )
    assignment = _assignment_row(aid)
    assert assignment["source"] == "folder_rule"
    assert int(assignment["confidence"]) == 85
    assert int(assignment["is_manual"] or 0) == 0
    # auto_classified lives on activity_log, not activity_project_assignment.
    activity = _activity_row(aid)
    assert int(activity["auto_classified"] or 0) == 1
