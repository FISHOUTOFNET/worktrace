from __future__ import annotations

from pathlib import Path

import pytest

from worktrace import db
from worktrace.services import (
    refresh_state_view_model_service,
    runtime_activity_state_service,
    timeline_service,
    view_model_service,
)

pytestmark = [pytest.mark.db, pytest.mark.integration, pytest.mark.serial]


def test_page_and_heartbeat_use_one_revision_owner(temp_db):
    runtime_activity_state_service.clear_runtime_activity_state(
        "architecture_validation"
    )
    today = timeline_service.get_default_report_date()
    page = view_model_service.get_overview_view_model(today)
    heartbeat = refresh_state_view_model_service.get_refresh_state_view_model(
        today
    )
    assert page["structure_revision"] == heartbeat["structure_revision"]
    assert page["page_revision"] == heartbeat["page_revision"]


def test_schema_trigger_surface_is_constraint_only(temp_db):
    with db.get_connection() as conn:
        names = {
            str(row["name"])
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'trigger'"
            ).fetchall()
        }
    assert names == {
        "validate_report_split_operation",
        "validate_report_operation_receipt_members",
    }


def test_frontend_uses_explicit_bridge_and_settings_bindings():
    root = Path(__file__).resolve().parents[1]
    init_source = (root / "worktrace/webview_ui/js/init.js").read_text(
        encoding="utf-8"
    )
    assert "App.callBridge =" not in init_source
    assert "MutationObserver" not in init_source
    assert 'bind("settings-clear-local-data-btn", "click", App.clearAllLocalData)' in init_source


def test_shipping_windows_adapter_has_no_global_legacy_patch():
    root = Path(__file__).resolve().parents[1]
    source = (
        root / "worktrace/platforms/hardened_windows_adapter.py"
    ).read_text(encoding="utf-8")
    assert "legacy." not in source
    assert "_run_with_timeout =" not in source


def test_continuity_reads_typed_runtime_state_not_settings_json():
    root = Path(__file__).resolve().parents[1]
    source = (
        root / "worktrace/services/activity_continuity_service.py"
    ).read_text(encoding="utf-8")
    assert "sample_runtime_activity_state" in source
    assert 'get_setting("current_activity_snapshot"' not in source
    assert "json.loads" not in source


def test_page_wrapper_services_are_removed():
    root = Path(__file__).resolve().parents[1]
    for name in (
        "overview_view_model_service.py",
        "timeline_view_model_service.py",
        "session_detail_view_model_service.py",
    ):
        assert not (root / "worktrace/services" / name).exists()
