"""selected-rule batch operations service / API tests."""

from __future__ import annotations
from tests.support.db_helpers import assign_activity_project

import json
import re
from pathlib import Path

import pytest

from worktrace.api import rule_api
from worktrace.db import get_connection, now_str
from worktrace.services import (
    activity_service,
    folder_rule_service,
    project_service,
    rule_batch_service,
    rule_service,
)

pytestmark = [pytest.mark.db, pytest.mark.integration, pytest.mark.contract]

# Helpers


def _create_closed_activity(
    app_name: str = "Word",
    process_name: str = "winword.exe",
    window_title: str = "Doc.docx - Word",
    start_time: str = "2026-06-18 09:00:00",
    end_time: str = "2026-06-18 09:10:00",
    file_path_hint: str | None = None,
    status: str = "normal",
    project_id: int | None = None,
) -> int:
    aid = activity_service.create_activity(
        app_name,
        process_name,
        window_title,
        status=status,
        start_time=start_time,
        file_path_hint=file_path_hint,
        project_id=project_id,
    )
    # Set end_time directly via SQL instead of calling ``close_activity``.
    from datetime import datetime

    from worktrace.db import get_connection, now_str

    fmt = "%Y-%m-%d %H:%M:%S"
    duration = int((datetime.strptime(end_time, fmt) - datetime.strptime(start_time, fmt)).total_seconds())
    with get_connection() as conn:
        conn.execute(
            "UPDATE activity_log SET end_time = ?, duration_seconds = ?, updated_at = ? WHERE id = ?",
            (end_time, max(0, duration), now_str(), aid),
        )
    return aid


def _set_manual_override(aid: int) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE activity_log SET manual_override = 1, updated_at = ? WHERE id = ?",
            (now_str(), aid),
        )
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
    return dict(row) if row else {}


def _assignment_row(aid: int) -> dict:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM activity_project_assignment WHERE activity_id = ?",
            (aid,),
        ).fetchone()
    return dict(row) if row else {}


def _folder_rule_entry(rule_id: int) -> dict:
    return {"rule_type": "folder", "rule_id": rule_id}


def _keyword_rule_entry(rule_id: int) -> dict:
    return {"rule_type": "keyword", "rule_id": rule_id}


_FORBIDDEN_TOKENS = [
    "window_title",
    "file_path_hint",
    "path_hint",
    "clipboard",
    "traceback",
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
        else:
            assert token_lower not in serialized, (
                f"forbidden token '{token}' found in payload"
            )


def _assert_json_serializable(payload: dict) -> None:
    json.dumps(payload, ensure_ascii=False, default=str)


# Input validation


def test_batch_preview_rejects_non_list(temp_db):
    result = rule_api.preview_project_rules_batch_impact("not a list")
    assert result["ok"] is False
    assert result["error"] == "invalid_input"


def test_batch_preview_rejects_empty_list(temp_db):
    result = rule_api.preview_project_rules_batch_impact([])
    assert result["ok"] is False
    assert result["error"] == "invalid_input"


def test_batch_preview_rejects_non_dict_item(temp_db):
    result = rule_api.preview_project_rules_batch_impact(["not a dict"])
    assert result["ok"] is False
    assert result["error"] == "invalid_input"


def test_batch_preview_rejects_unknown_rule_type(temp_db):
    result = rule_api.preview_project_rules_batch_impact(
        [{"rule_type": "unknown", "rule_id": 1}]
    )
    assert result["ok"] is False
    assert result["error"] == "invalid_input"


def test_batch_preview_rejects_bool_rule_id(temp_db):
    result = rule_api.preview_project_rules_batch_impact(
        [{"rule_type": "folder", "rule_id": True}]
    )
    assert result["ok"] is False
    assert result["error"] == "invalid_input"


def test_batch_preview_rejects_zero_rule_id(temp_db):
    result = rule_api.preview_project_rules_batch_impact(
        [{"rule_type": "folder", "rule_id": 0}]
    )
    assert result["ok"] is False
    assert result["error"] == "invalid_input"


def test_batch_preview_rejects_negative_rule_id(temp_db):
    result = rule_api.preview_project_rules_batch_impact(
        [{"rule_type": "folder", "rule_id": -1}]
    )
    assert result["ok"] is False
    assert result["error"] == "invalid_input"


def test_batch_preview_rejects_string_rule_id(temp_db):
    result = rule_api.preview_project_rules_batch_impact(
        [{"rule_type": "folder", "rule_id": "1"}]
    )
    assert result["ok"] is False
    assert result["error"] == "invalid_input"


def test_batch_too_many_rules(temp_db):
    project = project_service.create_project("TooMany")
    rule_ids = []
    for i in range(rule_batch_service.MAX_BATCH_PROJECT_RULES + 1):
        rid = folder_rule_service.create_or_update_folder_rule(
            f"D:\\TooMany\\Folder{i}", project
        )
        rule_ids.append(_folder_rule_entry(rid))
    result = rule_api.preview_project_rules_batch_impact(rule_ids)
    assert result["ok"] is False
    assert result["error"] == "too_many_rules"


# Cross-path resolution: folder id on keyword path / vice versa


def test_folder_id_on_keyword_path_returns_not_found(temp_db):
    project = project_service.create_project("CrossPath")
    folder_rid = folder_rule_service.create_or_update_folder_rule(
        "D:\\CrossFolder", project
    )
    result = rule_api.preview_project_rules_batch_impact(
        [_keyword_rule_entry(folder_rid)]
    )
    assert result["ok"] is False
    assert result["error"] == "not_found"


def test_keyword_id_on_folder_path_returns_not_found(temp_db):
    project = project_service.create_project("CrossPath2")
    keyword_rid = rule_service.create_rule("crosskw", project)
    result = rule_api.preview_project_rules_batch_impact(
        [_folder_rule_entry(keyword_rid)]
    )
    assert result["ok"] is False
    assert result["error"] == "not_found"


def test_nonexistent_rule_id_returns_not_found(temp_db):
    result = rule_api.preview_project_rules_batch_impact(
        [{"rule_type": "folder", "rule_id": 999999}]
    )
    assert result["ok"] is False
    assert result["error"] == "not_found"


# Batch preview success


def test_batch_preview_success(temp_db):
    project_a = project_service.create_project("BatchPreviewA")
    project_b = project_service.create_project("BatchPreviewB")
    folder_rid = folder_rule_service.create_or_update_folder_rule(
        "D:\\BatchPreviewFolder", project_a
    )
    keyword_rid = rule_service.create_rule("batchkw", project_b)
    _create_closed_activity(file_path_hint="D:\\BatchPreviewFolder\\Doc.docx")
    _create_closed_activity(
        app_name="Excel",
        process_name="excel.exe",
        window_title="batchkw-report.xlsx - Excel",
    )
    result = rule_api.preview_project_rules_batch_impact(
        [_folder_rule_entry(folder_rid), _keyword_rule_entry(keyword_rid)]
    )
    assert result["ok"] is True
    impact = result["impact"]
    assert "rules" in impact
    assert "counts" in impact
    assert "samples" in impact
    assert len(impact["rules"]) == 2
    # Aggregate matched count should be >= 2 (one per rule).
    assert impact["counts"]["matched_count"] >= 2


def test_batch_preview_is_read_only(temp_db):
    project = project_service.create_project("ReadOnly")
    folder_rid = folder_rule_service.create_or_update_folder_rule(
        "D:\\ReadOnlyFolder", project
    )
    aid = _create_closed_activity(file_path_hint="D:\\ReadOnlyFolder\\Doc.docx")
    activity_before = _activity_row(aid)
    rule_api.preview_project_rules_batch_impact([_folder_rule_entry(folder_rid)])
    activity_after = _activity_row(aid)
    # Preview must not change the activity's project_id.
    assert activity_before["project_id"] == activity_after["project_id"]


def test_batch_preview_display_safe(temp_db):
    project = project_service.create_project("DisplaySafe")
    folder_rid = folder_rule_service.create_or_update_folder_rule(
        "D:\\DisplaySafeFolder", project
    )
    _create_closed_activity(
        file_path_hint="D:\\DisplaySafeFolder\\SecretDoc.docx",
        window_title="Confidential SecretDoc.docx - Word",
    )
    result = rule_api.preview_project_rules_batch_impact(
        [_folder_rule_entry(folder_rid)]
    )
    assert result["ok"] is True
    _assert_no_sensitive_tokens(result)


def test_batch_preview_json_serializable(temp_db):
    project = project_service.create_project("JsonSer")
    folder_rid = folder_rule_service.create_or_update_folder_rule(
        "D:\\JsonSerFolder", project
    )
    _create_closed_activity(file_path_hint="D:\\JsonSerFolder\\Doc.docx")
    result = rule_api.preview_project_rules_batch_impact(
        [_folder_rule_entry(folder_rid)]
    )
    assert result["ok"] is True
    _assert_json_serializable(result)


def test_batch_preview_dedupe_preserves_first_occurrence(temp_db):
    project = project_service.create_project("Dedupe")
    folder_rid = folder_rule_service.create_or_update_folder_rule(
        "D:\\DedupeFolder", project
    )
    # Same rule sent twice — should dedupe to 1.
    result = rule_api.preview_project_rules_batch_impact(
        [_folder_rule_entry(folder_rid), _folder_rule_entry(folder_rid)]
    )
    assert result["ok"] is True
    assert len(result["impact"]["rules"]) == 1


def test_batch_preview_disabled_rule_returns_zero_counts(temp_db):
    project = project_service.create_project("DisabledPreview")
    folder_rid = folder_rule_service.create_or_update_folder_rule(
        "D:\\DisabledPreviewFolder", project
    )
    folder_rule_service.set_folder_rule_enabled(folder_rid, False)
    _create_closed_activity(file_path_hint="D:\\DisabledPreviewFolder\\Doc.docx")
    result = rule_api.preview_project_rules_batch_impact(
        [_folder_rule_entry(folder_rid)]
    )
    assert result["ok"] is True
    rule_summary = result["impact"]["rules"][0]
    assert rule_summary["counts"]["matched_count"] == 0


# Batch apply success


def test_batch_apply_success(temp_db):
    project_a = project_service.create_project("ApplyA")
    project_b = project_service.create_project("ApplyB")
    folder_rid = folder_rule_service.create_or_update_folder_rule(
        "D:\\ApplyFolder", project_a
    )
    keyword_rid = rule_service.create_rule("applykw", project_b)
    aid1 = _create_closed_activity(file_path_hint="D:\\ApplyFolder\\Doc.docx")
    aid2 = _create_closed_activity(
        app_name="Excel",
        process_name="excel.exe",
        window_title="applykw-report.xlsx - Excel",
    )
    result = rule_api.backfill_project_rules_batch(
        [_folder_rule_entry(folder_rid), _keyword_rule_entry(keyword_rid)]
    )
    assert result["ok"] is True
    res = result["result"]
    assert res["counts"]["updated_count"] == 2
    # Verify the activities were actually updated.
    assert int(_activity_row(aid1)["project_id"]) == project_a
    assert int(_activity_row(aid2)["project_id"]) == project_b
    # Verify auto_classified = 1, manual_override = 0.
    assert int(_activity_row(aid1)["auto_classified"]) == 1
    assert int(_activity_row(aid1)["manual_override"]) == 0
    # Verify assignment fields.
    a1 = _assignment_row(aid1)
    assert a1["source"] == "folder_rule"
    assert int(a1["confidence"]) == 85
    assert int(a1["is_manual"]) == 0


def test_batch_apply_display_safe(temp_db):
    project = project_service.create_project("ApplySafe")
    folder_rid = folder_rule_service.create_or_update_folder_rule(
        "D:\\ApplySafeFolder", project
    )
    _create_closed_activity(
        file_path_hint="D:\\ApplySafeFolder\\SecretDoc.docx",
        window_title="Confidential SecretDoc.docx - Word",
    )
    result = rule_api.backfill_project_rules_batch([_folder_rule_entry(folder_rid)])
    assert result["ok"] is True
    _assert_no_sensitive_tokens(result)


def test_batch_apply_json_serializable(temp_db):
    project = project_service.create_project("ApplyJson")
    folder_rid = folder_rule_service.create_or_update_folder_rule(
        "D:\\ApplyJsonFolder", project
    )
    _create_closed_activity(file_path_hint="D:\\ApplyJsonFolder\\Doc.docx")
    result = rule_api.backfill_project_rules_batch([_folder_rule_entry(folder_rid)])
    assert result["ok"] is True
    _assert_json_serializable(result)


# Batch apply: total cap 100 + too_many_matches writes nothing


def test_batch_apply_total_cap_100(temp_db):
    project = project_service.create_project("Cap100")
    folder_rid = folder_rule_service.create_or_update_folder_rule(
        "D:\\Cap100Folder", project
    )
    # Create 101 activities — exceeds the 100 cap.
    for i in range(rule_batch_service.MAX_BATCH_BACKFILL_ACTIVITIES + 1):
        _create_closed_activity(
            file_path_hint=f"D:\\Cap100Folder\\Doc{i}.docx",
            start_time=f"2026-06-18 0{i % 10}:00:00" if i < 10 else f"2026-06-18 10:0{i % 10}:00",
            end_time=f"2026-06-18 0{i % 10}:10:00" if i < 10 else f"2026-06-18 10:1{i % 10}:00",
        )
    result = rule_api.backfill_project_rules_batch([_folder_rule_entry(folder_rid)])
    assert result["ok"] is False
    assert result["error"] == "too_many_matches"


def test_batch_apply_too_many_matches_writes_nothing(temp_db):
    project = project_service.create_project("NothingWritten")
    folder_rid = folder_rule_service.create_or_update_folder_rule(
        "D:\\NothingWrittenFolder", project
    )
    aids = []
    for i in range(rule_batch_service.MAX_BATCH_BACKFILL_ACTIVITIES + 1):
        aid = _create_closed_activity(
            file_path_hint=f"D:\\NothingWrittenFolder\\Doc{i}.docx",
            start_time=f"2026-06-18 0{i % 10}:00:00" if i < 10 else f"2026-06-18 10:0{i % 10}:00",
            end_time=f"2026-06-18 0{i % 10}:10:00" if i < 10 else f"2026-06-18 10:1{i % 10}:00",
        )
        aids.append(aid)
    result = rule_api.backfill_project_rules_batch([_folder_rule_entry(folder_rid)])
    assert result["ok"] is False
    # Verify NO activity was updated.
    for aid in aids:
        activity = _activity_row(aid)
        assert int(activity["project_id"]) != project
        assert int(activity["auto_classified"]) == 0


# Batch apply: collision first-rule-wins


def test_batch_apply_collision_first_rule_wins(temp_db):
    project_a = project_service.create_project("FirstWins")
    project_b = project_service.create_project("SecondSkipped")
    folder_rid = folder_rule_service.create_or_update_folder_rule(
        "D:\\CollisionFolder", project_a
    )
    keyword_rid = rule_service.create_rule("collisiondoc", project_b)
    # One activity matches BOTH rules (folder path + keyword in title).
    aid = _create_closed_activity(
        file_path_hint="D:\\CollisionFolder\\collisiondoc.docx",
        window_title="collisiondoc - Word",
    )
    result = rule_api.backfill_project_rules_batch(
        [_folder_rule_entry(folder_rid), _keyword_rule_entry(keyword_rid)]
    )
    assert result["ok"] is True
    res = result["result"]
    # First rule (folder) should update the activity.
    assert res["counts"]["updated_count"] == 1
    # Second rule (keyword) should have collision_skipped_count = 1.
    keyword_rule_summary = res["rules"][1]
    assert keyword_rule_summary["counts"]["collision_skipped_count"] == 1
    # The activity should be on project_a (folder rule's project).
    assert int(_activity_row(aid)["project_id"]) == project_a


def test_batch_apply_dedupe_stable_order(temp_db):
    project = project_service.create_project("StableOrder")
    folder_rid = folder_rule_service.create_or_update_folder_rule(
        "D:\\StableOrderFolder", project
    )
    aid = _create_closed_activity(file_path_hint="D:\\StableOrderFolder\\Doc.docx")
    # Send the same rule twice — dedupe should collapse to 1 and apply once.
    result = rule_api.backfill_project_rules_batch(
        [_folder_rule_entry(folder_rid), _folder_rule_entry(folder_rid)]
    )
    assert result["ok"] is True
    assert result["result"]["counts"]["updated_count"] == 1
    assert int(_activity_row(aid)["project_id"]) == project


# Batch apply: skips


def test_batch_apply_skips_manual_override(temp_db):
    project = project_service.create_project("SkipManual")
    folder_rid = folder_rule_service.create_or_update_folder_rule(
        "D:\\SkipManualFolder", project
    )
    other = project_service.create_project("OtherManual")
    aid = _create_closed_activity(file_path_hint="D:\\SkipManualFolder\\Doc.docx")
    assign_activity_project(aid, other, manual=True)
    _set_manual_override(aid)
    result = rule_api.backfill_project_rules_batch([_folder_rule_entry(folder_rid)])
    assert result["ok"] is True
    assert result["result"]["counts"]["updated_count"] == 0
    assert int(_activity_row(aid)["project_id"]) == other


def test_batch_apply_skips_hidden(temp_db):
    project = project_service.create_project("SkipHidden")
    folder_rid = folder_rule_service.create_or_update_folder_rule(
        "D:\\SkipHiddenFolder", project
    )
    aid = _create_closed_activity(file_path_hint="D:\\SkipHiddenFolder\\Doc.docx")
    _set_hidden(aid)
    result = rule_api.backfill_project_rules_batch([_folder_rule_entry(folder_rid)])
    assert result["ok"] is True
    assert result["result"]["counts"]["updated_count"] == 0
    assert int(_activity_row(aid)["project_id"]) != project


def test_batch_apply_skips_deleted(temp_db):
    project = project_service.create_project("SkipDeleted")
    folder_rid = folder_rule_service.create_or_update_folder_rule(
        "D:\\SkipDeletedFolder", project
    )
    aid = _create_closed_activity(file_path_hint="D:\\SkipDeletedFolder\\Doc.docx")
    _set_deleted(aid)
    result = rule_api.backfill_project_rules_batch([_folder_rule_entry(folder_rid)])
    assert result["ok"] is True
    assert result["result"]["counts"]["updated_count"] == 0
    assert int(_activity_row(aid)["project_id"]) != project


def test_batch_apply_skips_in_progress(temp_db):
    project = project_service.create_project("SkipInProgress")
    folder_rid = folder_rule_service.create_or_update_folder_rule(
        "D:\\SkipInProgressFolder", project
    )
    aid = _create_closed_activity(file_path_hint="D:\\SkipInProgressFolder\\Doc.docx")
    _set_in_progress(aid)
    result = rule_api.backfill_project_rules_batch([_folder_rule_entry(folder_rid)])
    assert result["ok"] is True
    assert result["result"]["counts"]["updated_count"] == 0
    assert int(_activity_row(aid)["project_id"]) != project


def test_batch_apply_skips_non_normal(temp_db):
    project = project_service.create_project("SkipNonNormal")
    folder_rid = folder_rule_service.create_or_update_folder_rule(
        "D:\\SkipNonNormalFolder", project
    )
    aid = _create_closed_activity(
        file_path_hint="D:\\SkipNonNormalFolder\\Doc.docx", status="idle"
    )
    result = rule_api.backfill_project_rules_batch([_folder_rule_entry(folder_rid)])
    assert result["ok"] is True
    assert result["result"]["counts"]["updated_count"] == 0
    assert int(_activity_row(aid)["project_id"]) != project


def test_batch_apply_skips_already_target(temp_db):
    project = project_service.create_project("SkipAlreadyTarget")
    folder_rid = folder_rule_service.create_or_update_folder_rule(
        "D:\\SkipAlreadyTargetFolder", project
    )
    aid = _create_closed_activity(
        file_path_hint="D:\\SkipAlreadyTargetFolder\\Doc.docx", project_id=project
    )
    result = rule_api.backfill_project_rules_batch([_folder_rule_entry(folder_rid)])
    assert result["ok"] is True
    assert result["result"]["counts"]["updated_count"] == 0


# Batch apply: preflight rejections


def test_batch_apply_rejects_disabled_rule(temp_db):
    project = project_service.create_project("ApplyDisabled")
    folder_rid = folder_rule_service.create_or_update_folder_rule(
        "D:\\ApplyDisabledFolder", project
    )
    folder_rule_service.set_folder_rule_enabled(folder_rid, False)
    _create_closed_activity(file_path_hint="D:\\ApplyDisabledFolder\\Doc.docx")
    result = rule_api.backfill_project_rules_batch([_folder_rule_entry(folder_rid)])
    assert result["ok"] is False
    assert result["error"] == "rule_disabled"


def test_batch_apply_rejects_unavailable_project(temp_db):
    project = project_service.create_project("ApplyUnavailable")
    folder_rid = folder_rule_service.create_or_update_folder_rule(
        "D:\\ApplyUnavailableFolder", project
    )
    project_service.archive_project(project)
    _create_closed_activity(file_path_hint="D:\\ApplyUnavailableFolder\\Doc.docx")
    result = rule_api.backfill_project_rules_batch([_folder_rule_entry(folder_rid)])
    assert result["ok"] is False
    assert result["error"] == "project_not_available"


def test_batch_apply_rejects_not_found(temp_db):
    result = rule_api.backfill_project_rules_batch(
        [{"rule_type": "folder", "rule_id": 999999}]
    )
    assert result["ok"] is False
    assert result["error"] == "not_found"


def test_batch_apply_rejects_invalid_input(temp_db):
    result = rule_api.backfill_project_rules_batch("not a list")
    assert result["ok"] is False
    assert result["error"] == "invalid_input"


def test_batch_apply_rejects_too_many_rules(temp_db):
    project = project_service.create_project("ApplyTooMany")
    entries = []
    for i in range(rule_batch_service.MAX_BATCH_PROJECT_RULES + 1):
        rid = folder_rule_service.create_or_update_folder_rule(
            f"D:\\ApplyTooMany\\Folder{i}", project
        )
        entries.append(_folder_rule_entry(rid))
    result = rule_api.backfill_project_rules_batch(entries)
    assert result["ok"] is False
    assert result["error"] == "too_many_rules"


# Batch enable / disable


def test_batch_enable_success(temp_db):
    project = project_service.create_project("BatchEnable")
    folder_rid = folder_rule_service.create_or_update_folder_rule(
        "D:\\BatchEnableFolder", project
    )
    folder_rule_service.set_folder_rule_enabled(folder_rid, False)
    keyword_rid = rule_service.create_rule("batchenablekw", project)
    rule_service.set_rule_enabled(keyword_rid, False)
    result = rule_api.set_project_rules_batch_enabled(
        [_folder_rule_entry(folder_rid), _keyword_rule_entry(keyword_rid)], True
    )
    assert result["ok"] is True
    res = result["result"]
    assert res["enabled"] is True
    assert res["count"] == 2
    # Verify rules are actually enabled.
    with get_connection() as conn:
        folder_row = conn.execute(
            "SELECT enabled FROM folder_project_rule WHERE id = ?", (folder_rid,)
        ).fetchone()
        keyword_row = conn.execute(
            "SELECT enabled FROM project_rule WHERE id = ?", (keyword_rid,)
        ).fetchone()
    assert int(folder_row["enabled"]) == 1
    assert int(keyword_row["enabled"]) == 1


def test_batch_disable_success(temp_db):
    project = project_service.create_project("BatchDisable")
    folder_rid = folder_rule_service.create_or_update_folder_rule(
        "D:\\BatchDisableFolder", project
    )
    keyword_rid = rule_service.create_rule("batchdisablekw", project)
    result = rule_api.set_project_rules_batch_enabled(
        [_folder_rule_entry(folder_rid), _keyword_rule_entry(keyword_rid)], False
    )
    assert result["ok"] is True
    res = result["result"]
    assert res["enabled"] is False
    assert res["count"] == 2
    with get_connection() as conn:
        folder_row = conn.execute(
            "SELECT enabled FROM folder_project_rule WHERE id = ?", (folder_rid,)
        ).fetchone()
        keyword_row = conn.execute(
            "SELECT enabled FROM project_rule WHERE id = ?", (keyword_rid,)
        ).fetchone()
    assert int(folder_row["enabled"]) == 0
    assert int(keyword_row["enabled"]) == 0


def test_batch_toggle_all_or_nothing_not_found(temp_db):
    project = project_service.create_project("AllOrNothing")
    folder_rid = folder_rule_service.create_or_update_folder_rule(
        "D:\\AllOrNothingFolder", project
    )
    # Mix a valid rule with a nonexistent one.
    result = rule_api.set_project_rules_batch_enabled(
        [_folder_rule_entry(folder_rid), {"rule_type": "folder", "rule_id": 999999}],
        False,
    )
    assert result["ok"] is False
    assert result["error"] == "not_found"
    # The valid rule must NOT have been toggled (all-or-nothing).
    with get_connection() as conn:
        row = conn.execute(
            "SELECT enabled FROM folder_project_rule WHERE id = ?", (folder_rid,)
        ).fetchone()
    assert int(row["enabled"]) == 1  # Still enabled (original state)


def test_batch_toggle_rejects_invalid_input(temp_db):
    result = rule_api.set_project_rules_batch_enabled("not a list", True)
    assert result["ok"] is False
    assert result["error"] == "invalid_input"


def test_batch_toggle_rejects_non_bool_enabled(temp_db):
    project = project_service.create_project("NonBool")
    folder_rid = folder_rule_service.create_or_update_folder_rule(
        "D:\\NonBoolFolder", project
    )
    result = rule_api.set_project_rules_batch_enabled(
        [_folder_rule_entry(folder_rid)], 1  # int, not bool
    )
    assert result["ok"] is False
    assert result["error"] == "invalid_input"


def test_batch_toggle_rejects_too_many_rules(temp_db):
    project = project_service.create_project("ToggleTooMany")
    entries = []
    for i in range(rule_batch_service.MAX_BATCH_PROJECT_RULES + 1):
        rid = folder_rule_service.create_or_update_folder_rule(
            f"D:\\ToggleTooMany\\Folder{i}", project
        )
        entries.append(_folder_rule_entry(rid))
    result = rule_api.set_project_rules_batch_enabled(entries, True)
    assert result["ok"] is False
    assert result["error"] == "too_many_rules"


def test_batch_toggle_display_safe(temp_db):
    project = project_service.create_project("ToggleSafe")
    folder_rid = folder_rule_service.create_or_update_folder_rule(
        "D:\\ToggleSafeFolder", project
    )
    result = rule_api.set_project_rules_batch_enabled(
        [_folder_rule_entry(folder_rid)], True
    )
    assert result["ok"] is True
    _assert_no_sensitive_tokens(result)


def test_batch_toggle_json_serializable(temp_db):
    project = project_service.create_project("ToggleJson")
    folder_rid = folder_rule_service.create_or_update_folder_rule(
        "D:\\ToggleJsonFolder", project
    )
    result = rule_api.set_project_rules_batch_enabled(
        [_folder_rule_entry(folder_rid)], True
    )
    assert result["ok"] is True
    _assert_json_serializable(result)


def test_batch_toggle_folder_id_on_keyword_path_not_found(temp_db):
    project = project_service.create_project("ToggleCross")
    folder_rid = folder_rule_service.create_or_update_folder_rule(
        "D:\\ToggleCrossFolder", project
    )
    result = rule_api.set_project_rules_batch_enabled(
        [_keyword_rule_entry(folder_rid)], True
    )
    assert result["ok"] is False
    assert result["error"] == "not_found"


# No schema change


_SCHEMA_PATH = Path(__file__).resolve().parent.parent / "worktrace" / "schema.sql"


def test_no_schema_change_batch_service(temp_db):
    import inspect

    for module in (rule_batch_service,):
        source = inspect.getsource(module)
        assert "CREATE TABLE" not in source.upper()
        assert "ALTER TABLE" not in source.upper()
        assert "DROP TABLE" not in source.upper()
    assert _SCHEMA_PATH.exists()
    assert _SCHEMA_PATH.read_text(encoding="utf-8").strip() != ""


# Hardening lock: validation variants + preview/apply/toggle guarantees


@pytest.mark.parametrize(
    "bad_id",
    [1.5, None, [], {}, (1,), {1, 2}, frozenset({1})],
)
def test_batch_preview_rejects_non_int_rule_id_variants(temp_db, bad_id):
    # ``rule_id`` must be a real positive ``int``. Float,
    # ``None``, list, dict, tuple, set, frozenset all collapse to
    # ``invalid_input``. Existing tests cover bool / 0 / negative / numeric
    # string; this locks the remaining container / float / None variants.
    result = rule_api.preview_project_rules_batch_impact(
        [{"rule_type": "folder", "rule_id": bad_id}]
    )
    assert result["ok"] is False
    assert result["error"] == "invalid_input"


@pytest.mark.parametrize(
    "bad_item",
    [
        {"rule_id": 1},  # missing rule_type
        {"rule_type": "folder"},  # missing rule_id
        {"rule_type": None, "rule_id": 1},
        {"rule_type": 1, "rule_id": 1},
        {"rule_type": ["folder"], "rule_id": 1},
        {"rule_type": {"x": 1}, "rule_id": 1},
    ],
)
def test_batch_preview_rejects_malformed_items(temp_db, bad_item):
    # each item must be a dict with ``rule_type`` in
    # ``{"folder","keyword"}`` and a real positive int ``rule_id``. Missing
    # keys and non-string rule_type collapse to ``invalid_input``.
    result = rule_api.preview_project_rules_batch_impact([bad_item])
    assert result["ok"] is False
    assert result["error"] == "invalid_input"


def test_batch_preview_archived_project_returns_zero_counts_not_error(temp_db):
    # batch preview is informational. An archived target
    # project must contribute zero counts for that rule (availability
    # surfaced in the per-rule summary), NOT raise ``project_not_available``.
    project = project_service.create_project("ArchivedPreview")
    folder_rid = folder_rule_service.create_or_update_folder_rule(
        "D:\\ArchivedPreviewFolder", project
    )
    project_service.archive_project(project)
    _create_closed_activity(file_path_hint="D:\\ArchivedPreviewFolder\\Doc.docx")
    result = rule_api.preview_project_rules_batch_impact(
        [_folder_rule_entry(folder_rid)]
    )
    assert result["ok"] is True
    rule_summary = result["impact"]["rules"][0]
    assert rule_summary["counts"]["matched_count"] == 0
    assert rule_summary["counts"]["would_update_count"] == 0
    assert rule_summary["counts"]["eligible_count"] == 0


def test_batch_apply_never_sets_manual_override_on_all_updated_rows(temp_db):
    # batch apply must never set ``manual_override = 1`` on ANY
    # updated row. Existing test checks one row; this locks the guarantee
    # across multiple updated rows (folder + keyword paths).
    project_a = project_service.create_project("NoOverrideA")
    project_b = project_service.create_project("NoOverrideB")
    folder_rid = folder_rule_service.create_or_update_folder_rule(
        "D:\\NoOverrideA", project_a
    )
    keyword_rid = rule_service.create_rule("nooverrideb", project_b)
    aids = []
    for i in range(3):
        aids.append(
            _create_closed_activity(
                file_path_hint="D:\\NoOverrideA\\Doc" + str(i) + ".docx",
                start_time="2026-06-18 0" + str(i) + ":00:00",
                end_time="2026-06-18 0" + str(i) + ":10:00",
            )
        )
    aids.append(
        _create_closed_activity(
            app_name="Excel",
            process_name="excel.exe",
            window_title="nooverrideb.xlsx - Excel",
            start_time="2026-06-18 04:00:00",
            end_time="2026-06-18 04:10:00",
        )
    )
    result = rule_api.backfill_project_rules_batch(
        [_folder_rule_entry(folder_rid), _keyword_rule_entry(keyword_rid)]
    )
    assert result["ok"] is True
    for aid in aids:
        activity = _activity_row(aid)
        assert int(activity["manual_override"]) == 0, (
            "batch apply must not set manual_override=1 on activity " + str(aid)
        )
        assert int(activity["auto_classified"]) == 1


def test_batch_toggle_does_not_change_project_enabled_state(temp_db):
    # batch enable/disable only flips rule.enabled; it must NOT
    # change the target project's enabled flag. Lock that project.enabled is
    # unchanged after a batch disable.
    project = project_service.create_project("ProjStateLocked")
    folder_rid = folder_rule_service.create_or_update_folder_rule(
        "D:\\ProjStateLockedFolder", project
    )
    keyword_rid = rule_service.create_rule("projstatelockedkw", project)
    project_before = project_service.get_project(project)
    result = rule_api.set_project_rules_batch_enabled(
        [_folder_rule_entry(folder_rid), _keyword_rule_entry(keyword_rid)], False
    )
    assert result["ok"] is True
    project_after = project_service.get_project(project)
    assert int(project_before["enabled"]) == int(project_after["enabled"])
    assert int(project_after["enabled"]) == 1  # project still enabled


def test_batch_apply_too_many_rules_writes_nothing(temp_db):
    # the 20-rule cap is enforced in ``_normalize_rules``
    # BEFORE any DB write. Lock that the ``too_many_rules`` path writes
    # nothing (the existing apply test only checks the error code).
    project = project_service.create_project("TooManyApplyNoWrite")
    folder_rid = folder_rule_service.create_or_update_folder_rule(
        "D:\\TooManyApplyNoWrite", project
    )
    aid = _create_closed_activity(
        file_path_hint="D:\\TooManyApplyNoWrite\\Doc.docx"
    )
    entries = []
    for i in range(rule_batch_service.MAX_BATCH_PROJECT_RULES + 1):
        rid = folder_rule_service.create_or_update_folder_rule(
            "D:\\TooManyApplyNoWrite\\Sub" + str(i), project
        )
        entries.append(_folder_rule_entry(rid))
    activity_before = _activity_row(aid)
    result = rule_api.backfill_project_rules_batch(entries)
    assert result["ok"] is False
    assert result["error"] == "too_many_rules"
    activity_after = _activity_row(aid)
    assert activity_after["project_id"] == activity_before["project_id"]
    assert int(activity_after["auto_classified"]) == int(
        activity_before["auto_classified"]
    )


def test_batch_toggle_too_many_rules_writes_nothing(temp_db):
    # the 20-rule cap on toggle is enforced before any write.
    # Lock that the first rule's enabled state is unchanged.
    project = project_service.create_project("TooManyToggleNoWrite")
    folder_rid = folder_rule_service.create_or_update_folder_rule(
        "D:\\TooManyToggleNoWrite", project
    )
    entries = []
    for i in range(rule_batch_service.MAX_BATCH_PROJECT_RULES + 1):
        rid = folder_rule_service.create_or_update_folder_rule(
            "D:\\TooManyToggleNoWrite\\Sub" + str(i), project
        )
        entries.append(_folder_rule_entry(rid))
    with get_connection() as conn:
        enabled_before = int(
            conn.execute(
                "SELECT enabled FROM folder_project_rule WHERE id = ?",
                (folder_rid,),
            ).fetchone()["enabled"]
        )
    result = rule_api.set_project_rules_batch_enabled(entries, False)
    assert result["ok"] is False
    assert result["error"] == "too_many_rules"
    with get_connection() as conn:
        enabled_after = int(
            conn.execute(
                "SELECT enabled FROM folder_project_rule WHERE id = ?",
                (folder_rid,),
            ).fetchone()["enabled"]
        )
    assert enabled_after == enabled_before


def test_batch_apply_folder_id_on_keyword_path_writes_nothing(temp_db):
    # a folder id sent on the keyword path must return
    # ``not_found`` and write nothing. Locks rule-table isolation on the
    # apply path (existing test only covers preview cross-path).
    project = project_service.create_project("CrossPathApplyNoWrite")
    folder_rid = folder_rule_service.create_or_update_folder_rule(
        "D:\\CrossPathApplyNoWrite", project
    )
    aid = _create_closed_activity(
        file_path_hint="D:\\CrossPathApplyNoWrite\\Doc.docx"
    )
    activity_before = _activity_row(aid)
    result = rule_api.backfill_project_rules_batch(
        [_keyword_rule_entry(folder_rid)]
    )
    assert result["ok"] is False
    assert result["error"] == "not_found"
    activity_after = _activity_row(aid)
    assert activity_after["project_id"] == activity_before["project_id"]
    assert int(activity_after["auto_classified"]) == int(
        activity_before["auto_classified"]
    )
