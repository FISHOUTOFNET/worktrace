from __future__ import annotations

import pytest

from worktrace.services.refresh_state_view_model_service import (
    get_refresh_state_view_model,
)

pytestmark = [pytest.mark.db, pytest.mark.integration]


def test_refresh_state_exposes_only_live_and_page_revision(temp_db):
    result = get_refresh_state_view_model("2026-07-01")
    assert result["report_date"] == "2026-07-01"
    assert result["live_revision"]
    assert result["page_revision"]
    for alias in (
        "refresh_revision",
        "live_state_revision",
        "display_projection_revision",
        "page_structure_revision",
    ):
        assert alias not in result
