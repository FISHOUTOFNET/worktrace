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


def _clear_refresh_marker(rule_id: int, *, last_indexed_at: str | None = None) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE folder_rule_index_state
            SET refresh_requested = 0,
                build_status = 'ready',
                status = 'ready',
                last_indexed_at = ?
            WHERE folder_rule_id = ?
            """,
            (last_indexed_at, int(rule_id)),
        )


def test_manual_project_refresh_targets_only_selected_project(temp_db):
    project_a = project_service.create_project("Manual A")
    project_b = project_service.create_project("Manual B")
    rule_a = folder_rule_service.create_or_update_folder_rule(
        r"D:\ManualA", project_a, True
    )
    rule_b = folder_rule_service.create_or_update_folder_rule(
        r"D:\ManualB", project_b, True
    )
    _clear_refresh_marker(rule_a)
    _clear_refresh_marker(rule_b)

    queued = folder_index_maintenance_service.request_refresh_for_project(project_a)

    assert queued == 1
    with get_connection() as conn:
        states = {
            int(row["folder_rule_id"]): int(row["refresh_requested"] or 0)
            for row in conn.execute(
                """
                SELECT folder_rule_id, refresh_requested
                FROM folder_rule_index_state
                WHERE folder_rule_id IN (?, ?)
                """,
                (rule_a, rule_b),
            ).fetchall()
        }
    assert states[rule_a] == 1
    assert states[rule_b] == 0


def test_hot_refresh_uses_recent_projects_and_respects_freshness(temp_db):
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


def test_plain_index_miss_does_not_request_refresh(
    temp_db,
    monkeypatch,
):
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
        "request_refresh_for_project",
        lambda _project_id: calls.append("project"),
    )

    result = assign_project_for_activity(activity_id)

    assert result["source"] in {"uncategorized", "suggested_project_name"}
    assert calls == []
