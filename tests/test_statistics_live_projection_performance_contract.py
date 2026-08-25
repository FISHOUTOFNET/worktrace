from __future__ import annotations

from pathlib import Path


def test_statistics_live_projection_is_shipping_local_and_non_deferred():
    root = Path(__file__).resolve().parents[1]
    ui = root / "worktrace" / "webview_ui"
    index = (ui / "index_fd_work_v5.html").read_text(encoding="utf-8")
    live = (ui / "js" / "statistics_live_projection.js").read_text(encoding="utf-8")
    spec = (root / "WorkTrace.spec").read_text(encoding="utf-8")

    assert index.index("js/statistics.js") < index.index("js/statistics_live_projection.js")
    assert index.index("js/statistics_live_projection.js") < index.index("js/page_lifecycle.js")
    assert "statistics_live_projection.js" in spec
    assert "deferred: false" in live
    assert "preservePresentation: true" in live
    assert "getStatisticsExportSummary" not in live
    assert "exportStatisticsCsv" not in live
    assert "cloneGroups" not in live
    assert "buildGroupIndex" in live
    assert "rowIndex && rowIndex.owner === owner" in live
    assert "target.textContent !== value" in live
    assert "target.style.width !== value" in live
