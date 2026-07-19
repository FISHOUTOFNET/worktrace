from __future__ import annotations

import pytest

from worktrace.webview_ui.bridge import WebViewBridge

pytestmark = [pytest.mark.db, pytest.mark.integration]


def test_historical_refresh_scope_is_respected(temp_db):
    result = WebViewBridge().get_refresh_state("2026-07-01")
    assert result["ok"] is True
    runtime = result["runtime"]
    assert runtime["scope_report_date"] == "2026-07-01"
    assert runtime["snapshot"]["revision"]
    assert runtime["revisions"]["page"]
    assert "live_revision" not in result
    assert "page_revision" not in result
