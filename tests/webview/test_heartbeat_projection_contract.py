from __future__ import annotations

from pathlib import Path


def test_heartbeat_uses_report_date_and_two_non_overlapping_revisions():
    root = Path(__file__).resolve().parents[2]
    source = (root / "worktrace" / "webview_ui" / "js" / "init.js").read_text(encoding="utf-8")
    assert "App.timelineDate" in source
    assert "page_revision" in source
    assert "live_revision" in source
    for alias in ("refresh_revision", "live_state_revision", "display_projection_revision", "page_structure_revision"):
        assert alias not in source
