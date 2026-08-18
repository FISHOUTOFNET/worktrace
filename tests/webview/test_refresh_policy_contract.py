from __future__ import annotations

from pathlib import Path


def test_statistics_background_refresh_keeps_last_accepted_presentation():
    root = Path(__file__).resolve().parents[2]
    source = (root / "worktrace" / "webview_ui" / "js" / "statistics.js").read_text(encoding="utf-8")

    assert "preservePresentation" in source
    assert "if (!preservePresentation) invalidateStatisticsSelection();" in source
    assert 'App.markPageFresh("statistics")' in source
    assert "更新失败，仍显示上次结果" in source
    assert "return beginStatisticsQuery(0, options);" in source


def test_statistics_snapshot_cache_covers_all_four_fixed_quick_ranges():
    root = Path(__file__).resolve().parents[2]
    source = (root / "worktrace" / "services" / "statistics_snapshot_provider.py").read_text(encoding="utf-8")

    assert "_MAX_SLOTS = 4" in source
