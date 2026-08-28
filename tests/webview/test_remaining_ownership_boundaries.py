from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
JS_DIR = ROOT / "worktrace" / "webview_ui" / "js"


def source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def js_source(name: str) -> str:
    return (JS_DIR / name).read_text(encoding="utf-8")


def test_statistics_has_one_live_projection_owner() -> None:
    statistics = js_source("statistics.js")
    compatibility = js_source("statistics_live_projection.js")

    assert "acceptStatisticsRuntimeSync(data.runtime_sync)" in statistics
    assert "App.liveSampleFresh" in statistics
    assert "App.liveSampleRebaseDue" in statistics
    assert "App.statistics = Object.freeze" in statistics

    for forbidden in (
        "App.handleResult =",
        "App.statistics =",
        "App.applyStatisticsLocalTicker =",
        "baseCapability",
    ):
        assert forbidden not in compatibility


def test_desktop_collection_projection_is_not_owned_by_shell_composition() -> None:
    entry = source("worktrace/webview_main.py")
    projection = source("worktrace/desktop/collection_icon_projection.py")

    assert "CollectionIconProjectionHost(" in entry
    assert "collection_active_provider=app_control.is_collection_active" in entry
    assert "tray.set_collection_active(app_control.is_collection_active())" not in entry

    shell_call = entry.split("shell = ui.DesktopShellController(", 1)[1].split(")\n", 1)[0]
    assert "collection_active_provider" not in shell_call

    assert 'name="WorkTraceCollectionIcon"' in projection
    assert "attach_window_icons" in projection
