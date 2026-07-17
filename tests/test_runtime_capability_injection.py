from __future__ import annotations

from pathlib import Path

import pytest

from worktrace.api.app_api import ApplicationControl
from worktrace.runtime.maintenance_coordinator import RuntimeMaintenanceCoordinator
from worktrace.services import settings_service
from worktrace.webview_ui.bridge import WebViewBridge

pytestmark = [pytest.mark.db, pytest.mark.integration, pytest.mark.contract]

ROOT = Path(__file__).resolve().parents[1]


def test_production_runtime_has_no_callback_registry_or_global_runtime() -> None:
    app_api = (ROOT / "worktrace/api/app_api.py").read_text(encoding="utf-8")
    runtime = (ROOT / "worktrace/runtime/app_runtime.py").read_text(encoding="utf-8")
    backup = (ROOT / "worktrace/services/secure_backup_service.py").read_text(
        encoding="utf-8"
    )
    barrier = (ROOT / "worktrace/services/runtime_snapshot_barrier.py").read_text(
        encoding="utf-8"
    )
    assert "_runtime:" not in app_api
    assert "def set_runtime(" not in app_api
    assert "register_collector_pause_handler" not in runtime + backup
    assert "register_collector_reset_handler" not in runtime + backup
    assert "register_quiesce_handler" not in runtime + barrier


def test_application_control_without_runtime_fails_without_fake_pause(temp_db):
    settings_service.set_setting("user_paused", "false")
    settings_service.set_setting("collector_status", "running")

    result = ApplicationControl(None).pause_collection_now()

    assert result == {"ok": False, "error": "runtime_not_available"}
    assert settings_service.get_bool_setting("user_paused", True) is False
    assert settings_service.get_setting("collector_status", "") == "running"


def test_bridge_receives_runtime_capabilities_explicitly():
    runtime = type("Runtime", (), {})()
    control = ApplicationControl(runtime)
    maintenance = RuntimeMaintenanceCoordinator(runtime)

    bridge = WebViewBridge(control, maintenance)

    assert bridge.application_control is control
    assert bridge.maintenance is maintenance
