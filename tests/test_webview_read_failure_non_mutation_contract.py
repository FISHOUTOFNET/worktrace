from worktrace.db import get_connection
from worktrace.services import settings_service
from worktrace.webview_ui.bridge import WebViewBridge


def _boundary_count() -> int:
    with get_connection() as conn:
        return int(conn.execute("SELECT COUNT(*) AS c FROM session_boundary").fetchone()["c"])


def test_overview_read_failure_does_not_mutate_runtime_or_activity_state(temp_db, monkeypatch):
    settings_service.set_setting("collector_status", "running")
    settings_service.set_setting("collector_health_state", "healthy")
    settings_service.set_setting("pending_short_seconds", "23")
    settings_service.set_setting("current_activity_snapshot", '{"status":"normal","token":"keep"}')
    before_boundaries = _boundary_count()

    monkeypatch.setattr(
        "worktrace.webview_ui.bridge_overview.view_model_api.get_overview_view_model",
        lambda: (_ for _ in ()).throw(RuntimeError("read failed")),
    )

    result = WebViewBridge().get_overview()

    assert result["ok"] is False
    assert settings_service.get_setting("collector_status") == "running"
    assert settings_service.get_setting("collector_health_state") == "healthy"
    assert settings_service.get_setting("pending_short_seconds") == "23"
    assert settings_service.get_setting("current_activity_snapshot") == '{"status":"normal","token":"keep"}'
    assert _boundary_count() == before_boundaries


def test_refresh_state_read_failure_does_not_mutate_runtime_or_activity_state(temp_db, monkeypatch):
    settings_service.set_setting("collector_status", "running")
    settings_service.set_setting("collector_health_state", "degraded")
    settings_service.set_setting("pending_short_seconds", "29")
    settings_service.set_setting("current_activity_snapshot", '{"status":"normal","token":"keep"}')
    before_boundaries = _boundary_count()

    monkeypatch.setattr(
        "worktrace.webview_ui.bridge_overview.view_model_api.get_refresh_state_view_model",
        lambda _report_date=None: (_ for _ in ()).throw(RuntimeError("read failed")),
    )

    result = WebViewBridge().get_refresh_state()

    assert result["ok"] is False
    assert settings_service.get_setting("collector_status") == "running"
    assert settings_service.get_setting("collector_health_state") == "degraded"
    assert settings_service.get_setting("pending_short_seconds") == "29"
    assert settings_service.get_setting("current_activity_snapshot") == '{"status":"normal","token":"keep"}'
    assert _boundary_count() == before_boundaries
