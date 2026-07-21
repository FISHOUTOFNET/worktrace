from tests.support import runtime_state_fixture
from tests.support.application import FakeOverviewCapability, build_test_bridge
import pytest

from worktrace.db import get_connection
from worktrace.services import settings_service

pytestmark = [pytest.mark.db, pytest.mark.integration, pytest.mark.contract]


def _boundary_count() -> int:
    with get_connection() as conn:
        return int(conn.execute("SELECT COUNT(*) AS c FROM session_boundary").fetchone()["c"])


def test_overview_read_failure_does_not_mutate_runtime_or_activity_state(temp_db):
    settings_service.set_setting("collector_status", "running")
    settings_service.set_setting("collector_health_state", "healthy")
    runtime_state_fixture.set_setting("pending_short_seconds", "23")
    runtime_state_fixture.set_setting("current_activity_snapshot", '{"status":"normal","token":"keep"}')
    before_boundaries = _boundary_count()

    overview = FakeOverviewCapability()
    overview.get_overview_view_model_side_effect = RuntimeError("read failed")
    bridge = build_test_bridge(overview=overview)

    result = bridge.get_overview()

    assert result["ok"] is False
    assert settings_service.get_setting("collector_status") == "running"
    assert settings_service.get_setting("collector_health_state") == "healthy"
    assert runtime_state_fixture.get_setting("pending_short_seconds") == "0"
    assert runtime_state_fixture.get_setting("current_activity_snapshot") == '{"status":"normal","token":"keep"}'
    assert _boundary_count() == before_boundaries


def test_refresh_state_read_failure_does_not_mutate_runtime_or_activity_state(temp_db):
    settings_service.set_setting("collector_status", "running")
    settings_service.set_setting("collector_health_state", "degraded")
    runtime_state_fixture.set_setting("pending_short_seconds", "29")
    runtime_state_fixture.set_setting("current_activity_snapshot", '{"status":"normal","token":"keep"}')
    before_boundaries = _boundary_count()

    overview = FakeOverviewCapability()
    overview.get_refresh_state_view_model_side_effect = RuntimeError("read failed")
    bridge = build_test_bridge(overview=overview)

    result = bridge.get_refresh_state()

    assert result["ok"] is False
    assert settings_service.get_setting("collector_status") == "running"
    assert settings_service.get_setting("collector_health_state") == "degraded"
    assert runtime_state_fixture.get_setting("pending_short_seconds") == "0"
    assert runtime_state_fixture.get_setting("current_activity_snapshot") == '{"status":"normal","token":"keep"}'
    assert _boundary_count() == before_boundaries
