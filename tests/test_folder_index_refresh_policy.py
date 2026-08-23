from __future__ import annotations

from pathlib import Path

import pytest

from tests.support import activity_factory as activity_service
from worktrace.db import get_connection, now_str
from worktrace.services import (
    folder_index_maintenance_service,
    folder_index_query_service,
    folder_index_service,
    folder_rule_service,
    project_service,
)
from worktrace.services.project_inference_service import assign_project_for_activity

pytestmark = [pytest.mark.db, pytest.mark.integration]


def _clear_refresh_marker(
    rule_id: int,
    *,
    last_indexed_at: str | None = None,
    valid_from: str | None = None,
) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE folder_rule_index_state
            SET refresh_requested = 0,
                build_status = 'ready',
                status = 'ready',
                last_indexed_at = ?,
                valid_from = ?
            WHERE folder_rule_id = ?
            """,
            (last_indexed_at, valid_from, int(rule_id)),
        )


def test_hot_refresh_uses_recent_projects_and_respects_freshness(
    temp_db,
    monkeypatch,
):
    hot_project = project_service.create_project("Hot")
    fresh_project = project_service.create_project("Fresh")
    cold_project = project_service.create_project("Cold")
    hot_rule = folder_rule_service.create_or_update_folder_rule(r"D:\Hot", hot_project, True)
    fresh_rule = folder_rule_service.create_or_update_folder_rule(
        r"D:\Fresh", fresh_project, True
    )
    cold_rule = folder_rule_service.create_or_update_folder_rule(
        r"D:\Cold", cold_project, True
    )

    current = now_str()
    for project_id, title in ((hot_project, "hot.docx"), (fresh_project, "fresh.docx")):
        activity_id = activity_service.create_activity(
            "Word",
            "winword.exe",
            title,
            project_id=project_id,
            start_time=current,
        )
        activity_service.close_activity_row(activity_id, current)

    _clear_refresh_marker(hot_rule, last_indexed_at="2000-01-01 00:00:00")
    _clear_refresh_marker(fresh_rule, last_indexed_at=current)
    _clear_refresh_marker(cold_rule, last_indexed_at="2000-01-01 00:00:00")

    # This test verifies candidate selection/freshness rather than the independent
    # process-level query throttle. A concurrently exercised runtime worker may
    # legitimately reserve the same per-database throttle during the full suite.
    monkeypatch.setattr(
        folder_index_maintenance_service,
        "_reserve_refresh",
        lambda *args, **kwargs: True,
    )
    queued = folder_index_maintenance_service.request_refresh_for_hot_projects()

    assert queued == 1
    with get_connection() as conn:
        states = {
            int(row["folder_rule_id"]): int(row["refresh_requested"] or 0)
            for row in conn.execute(
                """
                SELECT folder_rule_id, refresh_requested
                FROM folder_rule_index_state
                WHERE folder_rule_id IN (?, ?, ?)
                """,
                (hot_rule, fresh_rule, cold_rule),
            ).fetchall()
        }
    assert states[hot_rule] == 1
    assert states[fresh_rule] == 0
    assert states[cold_rule] == 0


def test_new_deep_file_converges_after_index_refresh(
    temp_db,
    tmp_path,
    allow_sensitive_runtime,
):
    project_id = project_service.create_project("Deep Matter")
    root = tmp_path / "Matter"
    deep = root / "child" / "grandchild" / "great-grandchild"
    deep.mkdir(parents=True)
    (root / "existing.docx").write_text("existing", encoding="utf-8")
    rule_id = folder_rule_service.create_or_update_folder_rule(
        str(root), project_id, True
    )
    assert folder_index_service.rebuild_folder_index(rule_id)

    new_file = deep / "NewDocument.docx"
    new_file.write_text("new", encoding="utf-8")
    activity_id = activity_service.create_activity(
        "Word",
        "winword.exe",
        "NewDocument.docx - Word",
        start_time=now_str(),
    )

    before = assign_project_for_activity(activity_id)
    assert before["source"] == "uncategorized"
    assert before["_defer_reason"] == "folder_index_refresh"
    assert folder_index_query_service.lookup_indexed_paths_for_file_name(
        "NewDocument.docx", now_str()
    ) == []

    assert folder_index_service.rebuild_folder_index(rule_id)
    reconciled = folder_index_maintenance_service.reconcile_open_unclassified_activities()

    assert reconciled >= 1
    after = activity_service.get_activity(activity_id)
    assert after["project_id"] == project_id
    matches = folder_index_query_service.lookup_indexed_paths_for_file_name(
        "NewDocument.docx", now_str()
    )
    assert len(matches) == 1
    assert Path(matches[0]["file_path"]).name == "NewDocument.docx"


def test_pathless_file_index_miss_only_signals_unresolved_maintenance(
    temp_db,
    monkeypatch,
):
    project_id = project_service.create_project("Potential Folder Owner")
    folder_rule_service.create_or_update_folder_rule(
        r"D:\PotentialOwner",
        project_id,
        True,
    )
    activity_id = activity_service.create_activity(
        "Word",
        "winword.exe",
        "TrulyUnclassified.docx - Word",
        start_time=now_str(),
    )
    calls: list[str] = []

    monkeypatch.setattr(
        folder_index_service,
        "request_refresh_for_enabled_rules",
        lambda *args, **kwargs: calls.append("full"),
    )
    monkeypatch.setattr(
        folder_index_maintenance_service,
        "request_refresh_for_hot_projects",
        lambda: calls.append("hot"),
    )
    monkeypatch.setattr(
        folder_index_maintenance_service,
        "note_unresolved_file_miss",
        lambda *_args, **_kwargs: calls.append("miss"),
    )

    result = assign_project_for_activity(activity_id)

    assert result["source"] in {"uncategorized", "suggested_project_name"}
    assert result["_defer_reason"] == "folder_index_refresh"
    assert calls == ["miss"]


def test_non_file_unclassified_activity_does_not_signal_folder_refresh(
    temp_db,
    monkeypatch,
):
    activity_id = activity_service.create_activity(
        "Chrome",
        "chrome.exe",
        "Unclassified page - Google Chrome",
        start_time=now_str(),
    )
    calls: list[str] = []
    monkeypatch.setattr(
        folder_index_maintenance_service,
        "note_unresolved_file_miss",
        lambda *_args, **_kwargs: calls.append("miss"),
    )

    result = assign_project_for_activity(activity_id)

    assert result["source"] == "uncategorized"
    assert "_defer_reason" not in result
    assert calls == []


def test_unresolved_miss_refresh_includes_cold_projects_without_target_hint(
    temp_db,
    monkeypatch,
):
    project_a = project_service.create_project("Cold A")
    project_b = project_service.create_project("Cold B")
    rule_a = folder_rule_service.create_or_update_folder_rule(r"D:\ColdA", project_a, True)
    rule_b = folder_rule_service.create_or_update_folder_rule(r"D:\ColdB", project_b, True)
    _clear_refresh_marker(rule_a, valid_from="2000-01-01 00:00:00")
    _clear_refresh_marker(rule_b, valid_from="2000-01-01 00:00:00")
    queued_rule_ids: list[int] = []
    monkeypatch.setattr(
        folder_index_maintenance_service,
        "_reserve_refresh",
        lambda *args, **kwargs: True,
    )
    monkeypatch.setattr(
        folder_index_maintenance_service,
        "_queue_rule_ids",
        lambda rule_ids: queued_rule_ids.extend(rule_ids) or len(rule_ids),
    )

    folder_index_maintenance_service.note_unresolved_file_miss(
        "2026-08-18 20:00:00"
    )
    queued = folder_index_maintenance_service.request_refresh_for_unresolved_file_misses()

    assert queued == 2
    assert queued_rule_ids == [rule_a, rule_b]


def test_unresolved_refresh_status_requires_generation_started_after_miss(temp_db):
    project_id = project_service.create_project("Boundary")
    rule_id = folder_rule_service.create_or_update_folder_rule(
        r"D:\Boundary", project_id, True
    )
    boundary = "2026-08-18 20:00:00"
    _clear_refresh_marker(
        rule_id,
        last_indexed_at="2026-08-18 20:01:00",
        valid_from="2026-08-18 19:59:00",
    )
    assert not folder_index_maintenance_service.unresolved_file_indexes_refreshed_since(
        boundary
    )

    # Same-second ordering is ambiguous at the schema's timestamp precision.
    _clear_refresh_marker(
        rule_id,
        last_indexed_at="2026-08-18 20:01:00",
        valid_from="2026-08-18 20:00:00",
    )
    assert not folder_index_maintenance_service.unresolved_file_indexes_refreshed_since(
        boundary
    )

    _clear_refresh_marker(
        rule_id,
        last_indexed_at="2026-08-18 20:01:01",
        valid_from="2026-08-18 20:00:01",
    )
    assert folder_index_maintenance_service.unresolved_file_indexes_refreshed_since(
        boundary
    )


def test_failed_enabled_rule_refresh_does_not_consume_retry_cooldown(
    temp_db,
    monkeypatch,
):
    project_id = project_service.create_project("Retryable Refresh")
    rule_id = folder_rule_service.create_or_update_folder_rule(
        r"D:\RetryableRefresh",
        project_id,
        True,
    )
    folder_index_service._MISS_REFRESH_TIMES.clear()
    calls: list[int] = []

    def fail_rebuild(value):
        calls.append(int(value))
        raise RuntimeError("transient rebuild enqueue failure")

    monkeypatch.setattr(
        folder_index_service,
        "request_rebuild_for_rule",
        fail_rebuild,
    )
    with pytest.raises(RuntimeError, match="transient rebuild enqueue failure"):
        folder_index_service.request_refresh_for_enabled_rules()

    monkeypatch.setattr(
        folder_index_service,
        "request_rebuild_for_rule",
        lambda value: calls.append(int(value)),
    )
    folder_index_service.request_refresh_for_enabled_rules()

    assert calls == [rule_id, rule_id]
