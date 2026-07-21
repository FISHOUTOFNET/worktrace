from __future__ import annotations

import pytest

from tests.support.application import build_test_bridge

pytestmark = [pytest.mark.db, pytest.mark.integration]


def test_historical_refresh_scope_is_respected(temp_db):
    result = build_test_bridge().get_refresh_state("2026-07-01")
    assert result["ok"] is True
    runtime = result["runtime"]
    assert runtime["scope_report_date"] == "2026-07-01"
    assert runtime["snapshot"]["revision"]
    assert runtime["revisions"]["page"]
    assert "live_revision" not in result
    assert "page_revision" not in result
