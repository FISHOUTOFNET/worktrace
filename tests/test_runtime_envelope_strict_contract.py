from __future__ import annotations

from pathlib import Path

import pytest

from worktrace.api import view_model_api

pytestmark = [pytest.mark.db, pytest.mark.integration, pytest.mark.contract]
ROOT = Path(__file__).resolve().parents[1]


def test_page_view_models_publish_versioned_runtime_envelope(temp_db):
    for payload in (
        view_model_api.get_overview_view_model(),
        view_model_api.get_timeline_view_model(),
        view_model_api.get_refresh_state_view_model(),
    ):
        runtime = payload.get("runtime")
        assert isinstance(runtime, dict)
        assert runtime["schema_version"] == 1
        assert runtime["surface"]
        assert runtime["scope_report_date"]
        assert runtime["live_report_date"]
        assert isinstance(runtime["current_activity"], dict)


def test_frontend_never_accepts_page_payload_as_runtime_fallback():
    source = (ROOT / "worktrace/webview_ui/js/init.js").read_text(encoding="utf-8")
    assert "? value.runtime : value" not in source
    assert "? value.runtime : null" in source
    assert "Number(envelope.schema_version || 0) !== 1" in source
    assert "if (!scopeDate || !liveDate) return null" in source
