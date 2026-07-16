from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from worktrace import db
from worktrace.constants import SOURCE_AUTO, STATUS_PAUSED
from worktrace.services import (
    activity_lifecycle_service,
    activity_service,
    refresh_state_view_model_service,
    runtime_activity_state_service,
    timeline_service,
    view_model_service,
)

pytestmark = [pytest.mark.db, pytest.mark.integration, pytest.mark.serial]

_ALLOWED_SCHEMA_TRIGGERS = {
    "validate_report_split_operation",
    "validate_report_operation_receipt_members",
}
_RETIRED_SCHEMA_TRIGGERS = {
    "close_existing_open_activity_before_insert",
    "reset_empty_active_folder_generation",
    "normalize_pending_folder_generation",
    "cleanup_history_jobs_after_project_reset",
}


def _trigger_names() -> set[str]:
    with db.get_connection() as conn:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'trigger'"
        ).fetchall()
    return {str(row["name"]) for row in rows}


def test_schema_contains_only_invariant_triggers(temp_db):
    assert _trigger_names() == _ALLOWED_SCHEMA_TRIGGERS


def test_current_database_converges_retired_triggers_before_fingerprint(temp_db):
    with db.get_connection() as conn:
        conn.executescript(
            """
            CREATE TRIGGER close_existing_open_activity_before_insert
            BEFORE INSERT ON activity_log
            BEGIN SELECT 1; END;

            CREATE TRIGGER reset_empty_active_folder_generation
            AFTER DELETE ON folder_rule_file_index
            BEGIN SELECT 1; END;

            CREATE TRIGGER normalize_pending_folder_generation
            AFTER UPDATE OF status ON folder_rule_index_state
            BEGIN SELECT 1; END;

            CREATE TRIGGER cleanup_history_jobs_after_project_reset
            AFTER DELETE ON project
            BEGIN SELECT 1; END;
            """
        )
    assert _RETIRED_SCHEMA_TRIGGERS.issubset(_trigger_names())

    db.initialize_database(temp_db)

    names = _trigger_names()
    assert names == _ALLOWED_SCHEMA_TRIGGERS
    with db.get_connection() as conn:
        assert db.schema_fingerprint(conn) == db.expected_schema_fingerprint()


def test_low_level_insert_rejects_second_open_row_without_closing_first(temp_db):
    first_id = activity_service.insert_activity_row(
        "Editor",
        "editor.exe",
        "first.txt - Editor",
        status=STATUS_PAUSED,
        source=SOURCE_AUTO,
        start_time="2026-07-16 09:00:00",
    )

    with pytest.raises(sqlite3.IntegrityError):
        activity_service.insert_activity_row(
            "Browser",
            "browser.exe",
            "Second",
            status=STATUS_PAUSED,
            source=SOURCE_AUTO,
            start_time="2026-07-16 09:01:00",
        )

    with db.get_connection() as conn:
        row = conn.execute(
            "SELECT end_time FROM activity_log WHERE id = ?",
            (first_id,),
        ).fetchone()
        open_count = int(
            conn.execute(
                "SELECT COUNT(*) AS value FROM activity_log WHERE end_time IS NULL"
            ).fetchone()["value"]
        )
    assert row is not None
    assert row["end_time"] is None
    assert open_count == 1


def test_lifecycle_start_explicitly_closes_and_replaces_open_row(
    temp_db,
    monkeypatch,
):
    finalized: list[int] = []
    monkeypatch.setattr(
        activity_lifecycle_service,
        "finalize_closed_activity_ids",
        lambda ids: finalized.extend(ids),
    )
    monkeypatch.setattr(
        activity_lifecycle_service,
        "_sync_open_row_project_safely",
        lambda *args, **kwargs: None,
    )

    first_id = activity_lifecycle_service.start_activity(
        start_time="2026-07-16 10:00:00",
        source=SOURCE_AUTO,
        payload={
            "app_name": "System",
            "process_name": "system",
            "window_title": "Paused",
            "status": STATUS_PAUSED,
        },
    )
    second_id = activity_lifecycle_service.start_activity(
        start_time="2026-07-16 10:01:30",
        source=SOURCE_AUTO,
        payload={
            "app_name": "System",
            "process_name": "system",
            "window_title": "Paused again",
            "status": STATUS_PAUSED,
        },
    )

    with db.get_connection() as conn:
        first = conn.execute(
            "SELECT end_time, duration_seconds FROM activity_log WHERE id = ?",
            (first_id,),
        ).fetchone()
        second = conn.execute(
            "SELECT end_time FROM activity_log WHERE id = ?",
            (second_id,),
        ).fetchone()
        open_count = int(
            conn.execute(
                "SELECT COUNT(*) AS value FROM activity_log WHERE end_time IS NULL"
            ).fetchone()["value"]
        )
    assert first is not None and second is not None
    assert first["end_time"] == "2026-07-16 10:01:30"
    assert int(first["duration_seconds"] or 0) == 90
    assert second["end_time"] is None
    assert open_count == 1
    assert finalized == [first_id]


def test_page_and_heartbeat_share_structure_and_page_revision(temp_db):
    runtime_activity_state_service.clear_runtime_activity_state(
        "test_revision_contract"
    )
    today = timeline_service.get_default_report_date()

    page = view_model_service.get_overview_view_model(today)
    heartbeat = refresh_state_view_model_service.get_refresh_state_view_model(
        today
    )

    assert page["structure_revision"] == heartbeat["structure_revision"]
    assert page["page_revision"] == heartbeat["page_revision"]


def test_shipping_windows_adapter_has_no_legacy_monkeypatch():
    root = Path(__file__).resolve().parents[1]
    source = (
        root / "worktrace/platforms/hardened_windows_adapter.py"
    ).read_text(encoding="utf-8")
    maintenance_tests = (
        root / "tests/test_runtime_maintenance_control.py"
    ).read_text(encoding="utf-8")
    assert "legacy." not in source
    assert "_run_with_timeout =" not in source
    assert "WindowsPathResolver" in source
    assert "ClipboardMonitor" in source
    assert "_ClipboardMonitor" not in maintenance_tests
    assert "platforms.windows_clipboard import ClipboardMonitor" in maintenance_tests


def test_frontend_does_not_replace_bridge_or_patch_edit_dom_after_render():
    root = Path(__file__).resolve().parents[1]
    source = (root / "worktrace/webview_ui/js/init.js").read_text(
        encoding="utf-8"
    )
    assert "App.callBridge =" not in source
    assert "_hardeningBridgeInstalled" not in source
    assert "MutationObserver" not in source
    assert 'method.indexOf("project")' not in source
    assert 'method.indexOf("rule")' not in source


def test_rules_flow_refreshes_project_catalog_explicitly():
    root = Path(__file__).resolve().parents[1]
    source = (root / "worktrace/webview_ui/js/rules.js").read_text(
        encoding="utf-8"
    )
    assert "refreshSharedProjectCatalog" in source
    assert 'method.indexOf("project")' not in source
    assert 'method.indexOf("rule")' not in source
