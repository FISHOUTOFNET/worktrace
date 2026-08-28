from __future__ import annotations

from pathlib import Path


def test_statistics_live_projection_is_shipping_local_and_non_deferred():
    root = Path(__file__).resolve().parents[1]
    ui = root / "worktrace" / "webview_ui"
    index = (ui / "index_fd_work_v5.html").read_text(encoding="utf-8")
    statistics = (ui / "js" / "statistics.js").read_text(encoding="utf-8")
    compatibility = (ui / "js" / "statistics_live_projection.js").read_text(
        encoding="utf-8"
    )
    spec = (root / "WorkTrace.spec").read_text(encoding="utf-8")

    assert index.index("js/statistics.js") < index.index("js/statistics_live_projection.js")
    assert index.index("js/statistics_live_projection.js") < index.index("js/page_lifecycle.js")
    assert "statistics_live_projection.js" in spec
    assert "deferred: false" in statistics
    assert "preservePresentation: true" in statistics

    ticker = statistics.split("function applyStatisticsLocalTicker()", 1)[1].split(
        "function showStatisticsError", 1
    )[0]
    assert "App.bridge" not in ticker
    assert "statisticsLiveSummaryAtNow" not in ticker
    assert "patchStatisticsLiveProjection" in ticker
    assert "buildStatisticsGroupIndex" in statistics
    assert "statisticsRowIndex && statisticsRowIndex.owner === owner" in statistics
    assert "target.textContent !== value" in statistics
    assert "target.style.width !== value" in statistics

    assert "App.statistics =" not in compatibility
    assert "App.handleResult =" not in compatibility
    assert "App.applyStatisticsLocalTicker =" not in compatibility
