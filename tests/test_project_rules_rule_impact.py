"""rule impact preview + safe single-rule backfill service/API tests.

Covers ``worktrace.services.rule_impact_service`` and the stable
``worktrace.api.rule_api.preview_project_rule_impact`` /
``backfill_project_rule`` facades. The bridge / static-contract layers are
covered by ``tests/test_webview_project_rules_bridge.py`` and
``tests/webview/test_project_rules_static_contract.py``.

Locked behavior:

- Preview is read-only and returns display-safe fields only.
- Backfill only affects eligible existing activities (not deleted / hidden /
  in-progress / non-normal / manual_override / is_manual / already_target).
- Backfill never sets ``manual_override = 1``; it writes
  ``auto_classified = 1`` and upserts the assignment with
  ``is_manual = 0``, ``source = "folder_rule" | "keyword_rule"``, and the
  inference confidence (85 folder / 80 keyword).
- Backfill is capped at 100 updates per call; exceeding the cap returns
  ``too_many_matches`` and writes nothing.
- Backfill runs in a single transaction with a rowcount guard so any
  partial write is rolled back.
- No raw ``window_title`` / ``file_path_hint`` / ``path_hint`` / clipboard /
  note / SQL / traceback / raw row is ever returned in a payload.
- Folder id on keyword path / keyword id on folder path -> ``not_found``.
"""

from __future__ import annotations
from tests.support.db_helpers import assign_activity_project

import json
import re

import pytest

from worktrace.api import rule_api
from worktrace.db import get_connection, now_str
from worktrace.services import (
    activity_service,
    folder_rule_service,
    project_service,
    rule_impact_service,
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
    """Create a closed activity (end_time set) with the given fields."""
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
            "UPDATE activity_project_assignment SET is_manual = 1, updated_at = ? WHERE activity_id = ?",
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
            "UPDATE activity_log SET end_time = NULL, duration_seconds = NULL, updated_at = ? WHERE id = ?",
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


_FORBIDDEN_TOKENS = [
    "window_title",
    "file_path_hint",
    "path_hint",
    "clipboard",
    "note",
    "traceback",
    "SELECT",
    "INSERT",
    "UPDATE",
    "DELETE",
    "sqlite3",
    "OperationalError",
    "C:\\Secret",
]

# SQL keywords that must use word-boundary matching so they don't false-positive
# on legitimate field names like ``would_update_count`` or ``updated_count``.
_SQL_KEYWORD_TOKENS = {"SELECT", "INSERT", "UPDATE", "DELETE"}


def _assert_no_sensitive_tokens(payload: dict) -> None:
    """Assert no forbidden token appears anywhere in the JSON-serialized payload."""
    serialized = json.dumps(payload, ensure_ascii=False, default=str).lower()
    for token in _FORBIDDEN_TOKENS:
        token_lower = token.lower()
        if token in _SQL_KEYWORD_TOKENS:
            # Word-boundary regex: \b treats underscore as a word char, so
            # \bupdate\b won't match inside would_update_count / updated_count.
            pattern = r"\b" + re.escape(token_lower) + r"\b"
            assert re.search(pattern, serialized) is None, (
                f"forbidden token '{token}' found in payload"
            )
        elif token == "note":
            # ``note`` is a common substring; only flag it when it appears as a
            # key name or a value boundary, not as a substring of another word.
            assert '"note"' not in serialized, f"forbidden token '{token}' found in payload"
        elif token == "path_hint":
            assert "path_hint" not in serialized, f"forbidden token '{token}' found in payload"
        else:
            assert token_lower not in serialized, f"forbidden token '{token}' found in payload"


# Preview: folder rule


def test_preview_folder_rule_success(temp_db):
    project = project_service.create_project("FolderProject")
    rule_id = folder_rule_service.create_or_update_folder_rule("D:\\CaseA", project)
    aid = _create_closed_activity(
        file_path_hint="D:\\CaseA\\Doc.docx",
        window_title="Doc.docx - Word",
    )
    result = rule_impact_service.preview_rule_impact("folder", rule_id)
    assert result["rule"]["kind"] == "folder"
    assert result["rule"]["id"] == rule_id
    assert result["rule"]["enabled"] is True
    assert result["rule"]["project_id"] == project
    assert result["rule"]["project_name"] == "FolderProject"
    assert result["rule"]["target"] == "D:\\CaseA"
    counts = result["counts"]
    assert counts["matched_count"] == 1
    assert counts["eligible_count"] == 1
    assert counts["would_update_count"] == 1
    assert counts["already_target_count"] == 0
    assert len(result["samples"]) == 1
    sample = result["samples"][0]
    assert sample["activity_id"] == aid
    assert sample["target_project_name"] == "FolderProject"
    assert sample["match_source"] == "folder_rule"


def test_preview_folder_rule_only_display_safe_fields(temp_db):
    project = project_service.create_project("FolderProject")
    rule_id = folder_rule_service.create_or_update_folder_rule("D:\\CaseA", project)
    _create_closed_activity(
        file_path_hint="D:\\CaseA\\Secret.docx",
        window_title="C:\\Secret\\path clipboard note SELECT",
    )
    result = rule_impact_service.preview_rule_impact("folder", rule_id)
    sample = result["samples"][0]
    allowed_keys = {
        "activity_id",
        "start_time",
        "end_time",
        "duration_seconds",
        "resource_name",
        "current_project_name",
        "target_project_name",
        "match_source",
    }
    assert set(sample.keys()) == allowed_keys
    serialized = json.dumps(result, ensure_ascii=False, default=str).lower()
    assert "c:\\secret" not in serialized
    assert "clipboard" not in serialized
    assert "select" not in serialized
    # The raw window_title must not leak into resource_name.
    assert "SELECT" not in sample["resource_name"]


def test_preview_folder_rule_counts_skips_correctly(temp_db):
    project = project_service.create_project("FolderProject")
    other_project = project_service.create_project("Other")
    rule_id = folder_rule_service.create_or_update_folder_rule("D:\\CaseA", project)

    # Create all activities first. create_activity auto-closes any open
    # activities (end_time IS NULL), so skip states that null out end_time
    # (in_progress) must be applied AFTER all creates to avoid being undone.
    # Eligible + matched + would_update
    _create_closed_activity(file_path_hint="D:\\CaseA\\Eligible.docx")

    # Eligible + matched + already_target
    already_aid = _create_closed_activity(file_path_hint="D:\\CaseA\\Already.docx")
    assign_activity_project(already_aid, project, manual=False)
    with get_connection() as conn:
        conn.execute(
            "UPDATE activity_project_assignment SET source = 'folder_rule' WHERE activity_id = ?",
            (already_aid,),
        )

    # Manual override -> skipped
    manual_aid = _create_closed_activity(file_path_hint="D:\\CaseA\\Manual.docx")

    # Hidden -> skipped
    hidden_aid = _create_closed_activity(file_path_hint="D:\\CaseA\\Hidden.docx")

    # Deleted -> skipped
    deleted_aid = _create_closed_activity(file_path_hint="D:\\CaseA\\Deleted.docx")

    # In-progress -> skipped
    in_progress_aid = _create_closed_activity(file_path_hint="D:\\CaseA\\InProgress.docx")

    # Non-normal -> skipped
    non_normal_aid = _create_closed_activity(file_path_hint="D:\\CaseA\\NonNormal.docx")

    # Apply skip states AFTER all creates (create_activity auto-closes open
    # activities, which would undo _set_in_progress's end_time=NULL).
    _set_manual_override(manual_aid)
    _set_hidden(hidden_aid)
    _set_deleted(deleted_aid)
    _set_in_progress(in_progress_aid)
    _set_non_normal(non_normal_aid)

    result = rule_impact_service.preview_rule_impact("folder", rule_id)
    counts = result["counts"]
    assert counts["matched_count"] == 2  # eligible + already_target
    assert counts["eligible_count"] == 2
    assert counts["would_update_count"] == 1
    assert counts["already_target_count"] == 1
    assert counts["manual_skipped_count"] == 1
    assert counts["hidden_skipped_count"] == 1
    assert counts["deleted_skipped_count"] == 1
    assert counts["in_progress_skipped_count"] == 1
    assert counts["non_normal_skipped_count"] == 1


# Preview: keyword rule


def test_preview_keyword_rule_success(temp_db):
    project = project_service.create_project("KeywordProject")
    rule_id = rule_service.create_rule("invoice", project)
    aid = _create_closed_activity(
        app_name="Excel",
        process_name="excel.exe",
        window_title="invoice-2026.xlsx - Excel",
    )
    result = rule_impact_service.preview_rule_impact("keyword", rule_id)
    assert result["rule"]["kind"] == "keyword"
    assert result["rule"]["id"] == rule_id
    assert result["rule"]["enabled"] is True
    assert result["rule"]["project_id"] == project
    assert result["rule"]["project_name"] == "KeywordProject"
    assert result["rule"]["target"] == "invoice"
    counts = result["counts"]
    assert counts["matched_count"] == 1
    assert counts["eligible_count"] == 1
    assert counts["would_update_count"] == 1
    assert len(result["samples"]) == 1
    sample = result["samples"][0]
    assert sample["activity_id"] == aid
    assert sample["match_source"] == "keyword_rule"


def test_preview_keyword_rule_no_sensitive_leak(temp_db):
    project = project_service.create_project("KeywordProject")
    rule_id = rule_service.create_rule("invoice", project)
    _create_closed_activity(
        app_name="Excel",
        process_name="excel.exe",
        window_title="C:\\Secret\\invoice clipboard note SELECT",
        file_path_hint="C:\\Secret\\invoice.xlsx",
    )
    result = rule_impact_service.preview_rule_impact("keyword", rule_id)
    serialized = json.dumps(result, ensure_ascii=False, default=str).lower()
    assert "c:\\secret" not in serialized
    assert "clipboard" not in serialized
    assert "select" not in serialized


# Preview: invalid input


@pytest.mark.parametrize("bad_rule_type", [None, 123, True, False, [], {}, "invalid", "FOLDER"])
def test_preview_rejects_invalid_rule_type(temp_db, bad_rule_type):
    with pytest.raises(rule_impact_service.RuleImpactError) as exc_info:
        rule_impact_service.preview_rule_impact(bad_rule_type, 1)
    assert exc_info.value.code == "not_found"


@pytest.mark.parametrize("bad_rule_id", [True, False, "1", "abc", 0, -1, 1.0, 2.5, None, [], {}])
def test_preview_rejects_invalid_rule_id(temp_db, bad_rule_id):
    with pytest.raises(rule_impact_service.RuleImpactError) as exc_info:
        rule_impact_service.preview_rule_impact("folder", bad_rule_id)
    assert exc_info.value.code == "not_found"


def test_preview_folder_id_on_keyword_path_returns_not_found(temp_db):
    project = project_service.create_project("P")
    folder_rule_id = folder_rule_service.create_or_update_folder_rule("D:\\CaseA", project)
    with pytest.raises(rule_impact_service.RuleImpactError) as exc_info:
        rule_impact_service.preview_rule_impact("keyword", folder_rule_id)
    assert exc_info.value.code == "not_found"


def test_preview_keyword_id_on_folder_path_returns_not_found(temp_db):
    project = project_service.create_project("P")
    keyword_rule_id = rule_service.create_rule("keyword", project)
    with pytest.raises(rule_impact_service.RuleImpactError) as exc_info:
        rule_impact_service.preview_rule_impact("folder", keyword_rule_id)
    assert exc_info.value.code == "not_found"


# Preview: disabled rule + unavailable project


def test_preview_disabled_rule_returns_zero_counts(temp_db):
    project = project_service.create_project("P")
    rule_id = folder_rule_service.create_or_update_folder_rule("D:\\CaseA", project)
    folder_rule_service.set_folder_rule_enabled(rule_id, False)
    _create_closed_activity(file_path_hint="D:\\CaseA\\Doc.docx")
    result = rule_impact_service.preview_rule_impact("folder", rule_id)
    assert result["rule"]["enabled"] is False
    assert result["counts"]["matched_count"] == 0
    assert result["counts"]["would_update_count"] == 0
    assert result["samples"] == []


def test_preview_unavailable_project_returns_zero_counts(temp_db):
    project = project_service.create_project("P")
    rule_id = folder_rule_service.create_or_update_folder_rule("D:\\CaseA", project)
    project_service.set_project_enabled(project, False)
    _create_closed_activity(file_path_hint="D:\\CaseA\\Doc.docx")
    result = rule_impact_service.preview_rule_impact("folder", rule_id)
    assert result["rule"]["project_available"] is False
    assert result["counts"]["matched_count"] == 0
    assert result["counts"]["would_update_count"] == 0
    assert result["samples"] == []


def test_preview_archived_project_returns_zero_counts(temp_db):
    project = project_service.create_project("P")
    rule_id = folder_rule_service.create_or_update_folder_rule("D:\\CaseA", project)
    project_service.archive_project(project)
    _create_closed_activity(file_path_hint="D:\\CaseA\\Doc.docx")
    result = rule_impact_service.preview_rule_impact("folder", rule_id)
    assert result["rule"]["project_available"] is False
    assert result["counts"]["would_update_count"] == 0


def test_preview_excluded_project_returns_zero_counts(temp_db):
    excluded_id = project_service.get_or_create_excluded_project()
    rule_id = folder_rule_service.create_or_update_folder_rule("D:\\CaseA", excluded_id)
    _create_closed_activity(file_path_hint="D:\\CaseA\\Doc.docx")
    result = rule_impact_service.preview_rule_impact("folder", rule_id)
    assert result["rule"]["project_available"] is False
    assert result["counts"]["would_update_count"] == 0


# Backfill: folder rule success


def test_backfill_folder_rule_success(temp_db):
    project = project_service.create_project("FolderProject")
    rule_id = folder_rule_service.create_or_update_folder_rule("D:\\CaseA", project)
    aid = _create_closed_activity(file_path_hint="D:\\CaseA\\Doc.docx")
    result = rule_impact_service.backfill_rule_impact("folder", rule_id)
    assert result["updated_count"] == 1
    assert result["matched_count"] == 1
    assert result["would_update_count"] == 1
    assert result["too_many_matches"] is False
    activity = _activity_row(aid)
    assert activity["project_id"] == project
    assert int(activity["auto_classified"]) == 1
    assert int(activity["manual_override"]) == 0
    assignment = _assignment_row(aid)
    assert assignment["project_id"] == project
    assert assignment["source"] == "folder_rule"
    assert int(assignment["confidence"]) == 85
    assert int(assignment["is_manual"]) == 0


def test_backfill_folder_rule_does_not_set_manual_override(temp_db):
    project = project_service.create_project("FolderProject")
    rule_id = folder_rule_service.create_or_update_folder_rule("D:\\CaseA", project)
    aid = _create_closed_activity(file_path_hint="D:\\CaseA\\Doc.docx")
    rule_impact_service.backfill_rule_impact("folder", rule_id)
    activity = _activity_row(aid)
    assert int(activity["manual_override"]) == 0


def test_backfill_folder_rule_modifies_only_expected_fields(temp_db):
    project = project_service.create_project("FolderProject")
    rule_id = folder_rule_service.create_or_update_folder_rule("D:\\CaseA", project)
    aid = _create_closed_activity(file_path_hint="D:\\CaseA\\Doc.docx")
    before = _activity_row(aid)
    rule_impact_service.backfill_rule_impact("folder", rule_id)
    after = _activity_row(aid)
    # project_id changed (from uncategorized to project)
    assert before["project_id"] != after["project_id"]
    assert after["project_id"] == project
    # auto_classified changed to 1
    assert int(after["auto_classified"]) == 1
    # manual_override stays 0
    assert int(after["manual_override"]) == 0
    # source / note / duration / start_time / end_time / window_title unchanged
    assert before["source"] == after["source"]
    assert before["note"] == after["note"]
    assert before["duration_seconds"] == after["duration_seconds"]
    assert before["start_time"] == after["start_time"]
    assert before["end_time"] == after["end_time"]
    assert before["window_title"] == after["window_title"]
    assert before["file_path_hint"] == after["file_path_hint"]


# Backfill: keyword rule success


def test_backfill_keyword_rule_success(temp_db):
    project = project_service.create_project("KeywordProject")
    rule_id = rule_service.create_rule("invoice", project)
    aid = _create_closed_activity(
        app_name="Excel",
        process_name="excel.exe",
        window_title="invoice-2026.xlsx - Excel",
    )
    result = rule_impact_service.backfill_rule_impact("keyword", rule_id)
    assert result["updated_count"] == 1
    assert result["matched_count"] == 1
    activity = _activity_row(aid)
    assert activity["project_id"] == project
    assert int(activity["auto_classified"]) == 1
    assert int(activity["manual_override"]) == 0
    assignment = _assignment_row(aid)
    assert assignment["project_id"] == project
    assert assignment["source"] == "keyword_rule"
    assert int(assignment["confidence"]) == 80
    assert int(assignment["is_manual"]) == 0


# Backfill: rejects disabled rule / unavailable project


def test_backfill_rejects_disabled_rule(temp_db):
    project = project_service.create_project("P")
    rule_id = folder_rule_service.create_or_update_folder_rule("D:\\CaseA", project)
    folder_rule_service.set_folder_rule_enabled(rule_id, False)
    aid = _create_closed_activity(file_path_hint="D:\\CaseA\\Doc.docx")
    with pytest.raises(rule_impact_service.RuleImpactError) as exc_info:
        rule_impact_service.backfill_rule_impact("folder", rule_id)
    assert exc_info.value.code == "rule_disabled"
    # Nothing written
    activity = _activity_row(aid)
    assert int(activity["auto_classified"]) == 0


def test_backfill_rejects_unavailable_project(temp_db):
    project = project_service.create_project("P")
    rule_id = folder_rule_service.create_or_update_folder_rule("D:\\CaseA", project)
    project_service.set_project_enabled(project, False)
    aid = _create_closed_activity(file_path_hint="D:\\CaseA\\Doc.docx")
    with pytest.raises(rule_impact_service.RuleImpactError) as exc_info:
        rule_impact_service.backfill_rule_impact("folder", rule_id)
    assert exc_info.value.code == "project_not_available"
    activity = _activity_row(aid)
    assert int(activity["auto_classified"]) == 0


def test_backfill_rejects_archived_project(temp_db):
    project = project_service.create_project("P")
    rule_id = folder_rule_service.create_or_update_folder_rule("D:\\CaseA", project)
    project_service.archive_project(project)
    with pytest.raises(rule_impact_service.RuleImpactError) as exc_info:
        rule_impact_service.backfill_rule_impact("folder", rule_id)
    assert exc_info.value.code == "project_not_available"


def test_backfill_rejects_excluded_project(temp_db):
    excluded_id = project_service.get_or_create_excluded_project()
    rule_id = folder_rule_service.create_or_update_folder_rule("D:\\CaseA", excluded_id)
    with pytest.raises(rule_impact_service.RuleImpactError) as exc_info:
        rule_impact_service.backfill_rule_impact("folder", rule_id)
    assert exc_info.value.code == "project_not_available"


# Backfill: does not modify ineligible activities


def test_backfill_does_not_modify_manual_override_activity(temp_db):
    project = project_service.create_project("P")
    rule_id = folder_rule_service.create_or_update_folder_rule("D:\\CaseA", project)
    aid = _create_closed_activity(file_path_hint="D:\\CaseA\\Doc.docx")
    _set_manual_override(aid)
    result = rule_impact_service.backfill_rule_impact("folder", rule_id)
    assert result["updated_count"] == 0
    assert result["manual_skipped_count"] == 1
    activity = _activity_row(aid)
    assert int(activity["manual_override"]) == 1


def test_backfill_does_not_modify_hidden_activity(temp_db):
    project = project_service.create_project("P")
    rule_id = folder_rule_service.create_or_update_folder_rule("D:\\CaseA", project)
    aid = _create_closed_activity(file_path_hint="D:\\CaseA\\Doc.docx")
    _set_hidden(aid)
    result = rule_impact_service.backfill_rule_impact("folder", rule_id)
    assert result["updated_count"] == 0
    assert result["hidden_skipped_count"] == 1
    assert int(_activity_row(aid)["is_hidden"]) == 1


def test_backfill_does_not_modify_deleted_activity(temp_db):
    project = project_service.create_project("P")
    rule_id = folder_rule_service.create_or_update_folder_rule("D:\\CaseA", project)
    aid = _create_closed_activity(file_path_hint="D:\\CaseA\\Doc.docx")
    _set_deleted(aid)
    result = rule_impact_service.backfill_rule_impact("folder", rule_id)
    assert result["updated_count"] == 0
    assert result["deleted_skipped_count"] == 1


def test_backfill_does_not_modify_in_progress_activity(temp_db):
    project = project_service.create_project("P")
    rule_id = folder_rule_service.create_or_update_folder_rule("D:\\CaseA", project)
    aid = _create_closed_activity(file_path_hint="D:\\CaseA\\Doc.docx")
    _set_in_progress(aid)
    result = rule_impact_service.backfill_rule_impact("folder", rule_id)
    assert result["updated_count"] == 0
    assert result["in_progress_skipped_count"] == 1


def test_backfill_does_not_modify_non_normal_activity(temp_db):
    project = project_service.create_project("P")
    rule_id = folder_rule_service.create_or_update_folder_rule("D:\\CaseA", project)
    aid = _create_closed_activity(
        file_path_hint="D:\\CaseA\\Doc.docx", status="idle"
    )
    result = rule_impact_service.backfill_rule_impact("folder", rule_id)
    assert result["updated_count"] == 0
    assert result["non_normal_skipped_count"] == 1


def test_backfill_does_not_modify_already_target_activity(temp_db):
    project = project_service.create_project("P")
    rule_id = folder_rule_service.create_or_update_folder_rule("D:\\CaseA", project)
    aid = _create_closed_activity(file_path_hint="D:\\CaseA\\Doc.docx")
    assign_activity_project(aid, project, manual=False)
    with get_connection() as conn:
        conn.execute(
            "UPDATE activity_project_assignment SET source = 'folder_rule' WHERE activity_id = ?",
            (aid,),
        )
    result = rule_impact_service.backfill_rule_impact("folder", rule_id)
    assert result["updated_count"] == 0
    assert result["already_target_count"] == 1


@pytest.mark.parametrize("source", ["same_project_context", "anchor_context"])
def test_backfill_upgrades_context_source_when_project_id_already_matches(temp_db, source):
    project = project_service.create_project("P")
    rule_id = folder_rule_service.create_or_update_folder_rule("D:\\CaseA", project)
    aid = _create_closed_activity(file_path_hint="D:\\CaseA\\Doc.docx")
    assign_activity_project(aid, project, manual=False)
    with get_connection() as conn:
        conn.execute(
            "UPDATE activity_project_assignment SET source = ? WHERE activity_id = ?",
            (source, aid),
        )
    result = rule_impact_service.backfill_rule_impact("folder", rule_id)
    assert result["updated_count"] == 1
    assert result["already_target_count"] == 0
    assignment = _assignment_row(aid)
    assert assignment["project_id"] == project
    assert assignment["source"] == "folder_rule"
    assert int(assignment["is_manual"]) == 0


# Backfill: too_many_matches


def test_backfill_too_many_matches_writes_nothing(temp_db):
    project = project_service.create_project("P")
    rule_id = folder_rule_service.create_or_update_folder_rule("D:\\CaseA", project)
    # Create 101 eligible matched activities (> MAX_RULE_BACKFILL_ACTIVITIES)
    for i in range(101):
        _create_closed_activity(
            file_path_hint=f"D:\\CaseA\\Doc{i}.docx",
            start_time=f"2026-06-18 {i // 60:02d}:{i % 60:02d}:00",
            end_time=f"2026-06-18 {(i + 1) // 60:02d}:{(i + 1) % 60:02d}:00",
        )
    with pytest.raises(rule_impact_service.RuleImpactError) as exc_info:
        rule_impact_service.backfill_rule_impact("folder", rule_id)
    assert exc_info.value.code == "too_many_matches"
    # Verify nothing was written — all activities still have auto_classified=0
    with get_connection() as conn:
        count = conn.execute(
            "SELECT COUNT(*) AS c FROM activity_log WHERE auto_classified = 1"
        ).fetchone()
    assert int(count["c"]) == 0


# Backfill: transaction rollback on rowcount guard


def test_backfill_rolls_back_on_rowcount_guard(temp_db, monkeypatch):
    project = project_service.create_project("P")
    rule_id = folder_rule_service.create_or_update_folder_rule("D:\\CaseA", project)
    aid = _create_closed_activity(file_path_hint="D:\\CaseA\\Doc.docx")

    # Simulate manual_override flipping to 1 between read and write by
    # setting it to 1 right before backfill runs the UPDATE. The
    # rowcount guard (WHERE manual_override = 0) should produce rowcount=0
    # -> operation_failed -> rollback.
    real_backfill = rule_impact_service.backfill_rule_impact

    def _sabotage(*args, **kwargs):
        # Flip manual_override after classification but before the write.
        # We patch _classify_activities to flip it right before returning.
        original_classify = rule_impact_service._classify_activities

        def _flip_classify(activities, rule, rule_type, conn):
            result = original_classify(activities, rule, rule_type, conn)
            for activity in result.get("would_update", []):
                conn.execute(
                    "UPDATE activity_log SET manual_override = 1 WHERE id = ?",
                    (int(activity.get("id") or 0),),
                )
            return result

        monkeypatch.setattr(rule_impact_service, "_classify_activities", _flip_classify)
        return real_backfill(*args, **kwargs)

    monkeypatch.setattr(rule_impact_service, "backfill_rule_impact", _sabotage)
    with pytest.raises(rule_impact_service.RuleImpactError) as exc_info:
        rule_impact_service.backfill_rule_impact("folder", rule_id)
    assert exc_info.value.code == "operation_failed"
    # The transaction rolled back; the activity's manual_override is still 0
    # (the conn-level sabotage happened inside the transaction that rolled back).
    # However, since we used a separate conn for the flip inside the same
    # transaction, the rollback should undo it.
    activity = _activity_row(aid)
    assert int(activity["manual_override"]) == 0
    assert int(activity["auto_classified"]) == 0


# API layer: stable facades


def test_api_preview_folder_rule_success(temp_db):
    project = project_service.create_project("P")
    rule_id = folder_rule_service.create_or_update_folder_rule("D:\\CaseA", project)
    _create_closed_activity(file_path_hint="D:\\CaseA\\Doc.docx")
    result = rule_api.preview_project_rule_impact("folder", rule_id)
    assert result["ok"] is True
    assert "impact" in result
    assert result["impact"]["counts"]["would_update_count"] == 1
    _assert_no_sensitive_tokens(result)


def test_api_preview_keyword_rule_success(temp_db):
    project = project_service.create_project("P")
    rule_id = rule_service.create_rule("invoice", project)
    _create_closed_activity(
        app_name="Excel",
        process_name="excel.exe",
        window_title="invoice.xlsx - Excel",
    )
    result = rule_api.preview_project_rule_impact("keyword", rule_id)
    assert result["ok"] is True
    assert result["impact"]["counts"]["would_update_count"] == 1
    _assert_no_sensitive_tokens(result)


def test_api_backfill_folder_rule_success(temp_db):
    project = project_service.create_project("P")
    rule_id = folder_rule_service.create_or_update_folder_rule("D:\\CaseA", project)
    aid = _create_closed_activity(file_path_hint="D:\\CaseA\\Doc.docx")
    result = rule_api.backfill_project_rule("folder", rule_id)
    assert result["ok"] is True
    assert "result" in result
    assert result["result"]["updated_count"] == 1
    _assert_no_sensitive_tokens(result)
    assert _activity_row(aid)["project_id"] == project


def test_api_backfill_keyword_rule_success(temp_db):
    project = project_service.create_project("P")
    rule_id = rule_service.create_rule("invoice", project)
    aid = _create_closed_activity(
        app_name="Excel",
        process_name="excel.exe",
        window_title="invoice.xlsx - Excel",
    )
    result = rule_api.backfill_project_rule("keyword", rule_id)
    assert result["ok"] is True
    assert result["result"]["updated_count"] == 1
    _assert_no_sensitive_tokens(result)
    assert _activity_row(aid)["project_id"] == project


# API layer: invalid input rejection


@pytest.mark.parametrize("bad_rule_type", [None, 123, True, False, [], {}, "invalid"])
def test_api_preview_rejects_invalid_rule_type(temp_db, bad_rule_type):
    result = rule_api.preview_project_rule_impact(bad_rule_type, 1)
    assert result == {"ok": False, "error": "invalid_input"}


@pytest.mark.parametrize("bad_rule_id", [True, False, "1", "abc", 0, -1, 1.0, 2.5, None, [], {}])
def test_api_preview_rejects_invalid_rule_id(temp_db, bad_rule_id):
    result = rule_api.preview_project_rule_impact("folder", bad_rule_id)
    assert result == {"ok": False, "error": "invalid_input"}


@pytest.mark.parametrize("bad_rule_type", [None, 123, True, False, [], {}, "invalid"])
def test_api_backfill_rejects_invalid_rule_type(temp_db, bad_rule_type):
    result = rule_api.backfill_project_rule(bad_rule_type, 1)
    assert result == {"ok": False, "error": "invalid_input"}


@pytest.mark.parametrize("bad_rule_id", [True, False, "1", "abc", 0, -1, 1.0, 2.5, None, [], {}])
def test_api_backfill_rejects_invalid_rule_id(temp_db, bad_rule_id):
    result = rule_api.backfill_project_rule("folder", bad_rule_id)
    assert result == {"ok": False, "error": "invalid_input"}


def test_api_preview_not_found(temp_db):
    result = rule_api.preview_project_rule_impact("folder", 99999)
    assert result == {"ok": False, "error": "not_found"}


def test_api_backfill_not_found(temp_db):
    result = rule_api.backfill_project_rule("keyword", 99999)
    assert result == {"ok": False, "error": "not_found"}


def test_api_preview_folder_id_on_keyword_path_not_found(temp_db):
    project = project_service.create_project("P")
    folder_rule_id = folder_rule_service.create_or_update_folder_rule("D:\\CaseA", project)
    result = rule_api.preview_project_rule_impact("keyword", folder_rule_id)
    assert result == {"ok": False, "error": "not_found"}


def test_api_preview_keyword_id_on_folder_path_not_found(temp_db):
    project = project_service.create_project("P")
    keyword_rule_id = rule_service.create_rule("kw", project)
    result = rule_api.preview_project_rule_impact("folder", keyword_rule_id)
    assert result == {"ok": False, "error": "not_found"}


# API layer: disabled rule / unavailable project / too_many_matches


def test_api_backfill_rejects_disabled_rule(temp_db):
    project = project_service.create_project("P")
    rule_id = folder_rule_service.create_or_update_folder_rule("D:\\CaseA", project)
    folder_rule_service.set_folder_rule_enabled(rule_id, False)
    result = rule_api.backfill_project_rule("folder", rule_id)
    assert result == {"ok": False, "error": "rule_disabled"}


def test_api_backfill_rejects_unavailable_project(temp_db):
    project = project_service.create_project("P")
    rule_id = folder_rule_service.create_or_update_folder_rule("D:\\CaseA", project)
    project_service.set_project_enabled(project, False)
    result = rule_api.backfill_project_rule("folder", rule_id)
    assert result == {"ok": False, "error": "project_not_available"}


def test_api_backfill_too_many_matches(temp_db):
    project = project_service.create_project("P")
    rule_id = folder_rule_service.create_or_update_folder_rule("D:\\CaseA", project)
    for i in range(101):
        _create_closed_activity(
            file_path_hint=f"D:\\CaseA\\Doc{i}.docx",
            start_time=f"2026-06-18 {i // 60:02d}:{i % 60:02d}:00",
            end_time=f"2026-06-18 {(i + 1) // 60:02d}:{(i + 1) % 60:02d}:00",
        )
    result = rule_api.backfill_project_rule("folder", rule_id)
    assert result == {"ok": False, "error": "too_many_matches"}


# API layer: JSON serializable + no sensitive payload


def test_api_preview_payload_json_serializable(temp_db):
    project = project_service.create_project("P")
    rule_id = folder_rule_service.create_or_update_folder_rule("D:\\CaseA", project)
    _create_closed_activity(file_path_hint="D:\\CaseA\\Doc.docx")
    result = rule_api.preview_project_rule_impact("folder", rule_id)
    json.dumps(result, ensure_ascii=False)


def test_api_backfill_payload_json_serializable(temp_db):
    project = project_service.create_project("P")
    rule_id = folder_rule_service.create_or_update_folder_rule("D:\\CaseA", project)
    _create_closed_activity(file_path_hint="D:\\CaseA\\Doc.docx")
    result = rule_api.backfill_project_rule("folder", rule_id)
    json.dumps(result, ensure_ascii=False)


def test_api_preview_failure_payload_no_sensitive_tokens(temp_db):
    project = project_service.create_project("P")
    rule_id = folder_rule_service.create_or_update_folder_rule("D:\\CaseA", project)
    _create_closed_activity(
        file_path_hint="D:\\CaseA\\Doc.docx",
        window_title="C:\\Secret clipboard note SELECT",
    )
    result = rule_api.preview_project_rule_impact("folder", rule_id)
    _assert_no_sensitive_tokens(result)


def test_api_backfill_failure_payload_no_sensitive_tokens(temp_db):
    project = project_service.create_project("P")
    rule_id = folder_rule_service.create_or_update_folder_rule("D:\\CaseA", project)
    folder_rule_service.set_folder_rule_enabled(rule_id, False)
    result = rule_api.backfill_project_rule("folder", rule_id)
    _assert_no_sensitive_tokens(result)


def test_api_preview_exception_collapse(temp_db, monkeypatch):
    project = project_service.create_project("P")
    rule_id = folder_rule_service.create_or_update_folder_rule("D:\\CaseA", project)

    def _boom(*args, **kwargs):
        raise RuntimeError("boom SELECT * FROM activity_log traceback C:\\Secret")

    monkeypatch.setattr(rule_impact_service, "preview_rule_impact", _boom)
    result = rule_api.preview_project_rule_impact("folder", rule_id)
    assert result == {"ok": False, "error": "operation_failed"}
    _assert_no_sensitive_tokens(result)


def test_api_backfill_exception_collapse(temp_db, monkeypatch):
    project = project_service.create_project("P")
    rule_id = folder_rule_service.create_or_update_folder_rule("D:\\CaseA", project)

    def _boom(*args, **kwargs):
        raise RuntimeError("boom SELECT * FROM activity_log traceback C:\\Secret")

    monkeypatch.setattr(rule_impact_service, "backfill_rule_impact", _boom)
    result = rule_api.backfill_project_rule("folder", rule_id)
    assert result == {"ok": False, "error": "operation_failed"}
    _assert_no_sensitive_tokens(result)


# Regression: existing CRUD / toggle / lifecycle still work


def test_existing_folder_crud_still_works(temp_db):
    project = project_service.create_project("P")
    rule_id = folder_rule_service.create_or_update_folder_rule("D:\\CaseA", project)
    assert rule_id > 0
    folder_rule_service.update_folder_rule(rule_id, "D:\\CaseB", recursive=False)
    folder_rule_service.delete_folder_rule(rule_id)


def test_existing_keyword_crud_still_works(temp_db):
    project = project_service.create_project("P")
    rule_id = rule_service.create_rule("kw", project)
    assert rule_id > 0
    rule_service.update_rule(rule_id, "kw2")
    rule_service.delete_rule(rule_id)


def test_existing_rule_toggle_still_works(temp_db):
    project = project_service.create_project("P")
    rule_id = rule_service.create_rule("kw", project)
    result = rule_api.set_project_rule_enabled("keyword", rule_id, False)
    assert result["ok"] is True
    assert result["enabled"] is False


def test_existing_project_lifecycle_still_works(temp_db):
    from worktrace.api import project_api
    create_result = project_api.create_project_for_rules("LifecycleTest", "desc")
    assert create_result["ok"] is True
    pid = create_result["project"]["id"]
    toggle_result = project_api.set_project_enabled_for_rules(pid, False)
    assert toggle_result["ok"] is True
    assert toggle_result["project"]["enabled"] is False
