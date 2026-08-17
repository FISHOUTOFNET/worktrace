from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INIT_JS = ROOT / "worktrace" / "webview_ui" / "js" / "init_fd_work_v5.js"


def test_periodic_business_refresh_has_single_coordinator() -> None:
    source = INIT_JS.read_text(encoding="utf-8")

    # Runtime invalidation is coordinated by runRevisionCheck().  Do not add a
    # second low-frequency reconcile loop to compensate for missed revisions.
    assert "function runRevisionCheck()" in source
    assert "getRefreshState" in source
    assert source.count("setInterval(") == 1
    assert "fullReconcileCollectionViews" not in source
    assert "heartbeat-lowfreq" not in source
    assert "RECONCILE_INTERVAL_MS" not in source
    assert "lastReconcileAtEpochMs" not in source
    assert "reconcileInFlight" not in source
