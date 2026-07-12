from __future__ import annotations

from worktrace.services.activity_display_projection import build_revision_parts


def test_live_display_revision_parts_have_single_roles():
    parts = build_revision_parts({}, {}, snapshot_status="", collector_status="stopped", user_paused=False, today="2026-07-01", report_date="2026-07-01")
    assert set(parts) == {"live_revision", "page_revision"}
