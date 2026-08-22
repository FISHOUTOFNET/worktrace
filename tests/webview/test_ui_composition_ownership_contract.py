from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
JS_DIR = ROOT / "worktrace" / "webview_ui" / "js"


def source(name: str) -> str:
    return (JS_DIR / name).read_text(encoding="utf-8")


def test_rules_and_settings_own_refresh_state_and_requests():
    composition = source("ui_composition.js")
    rules = source("rules.js")
    settings = source("settings.js")

    forbidden_private_state = (
        "App.rulesLoaded",
        "App.rulesLoading",
        "App.rulesLoadPromise",
        "App.rulesRefreshPending",
        "App.rulesBackgroundRefreshPromise",
        "App.settingsLoaded",
        "App.settingsLoading",
        "App.settingsLoadPromise",
        "App.settingsRequestToken",
        "App.lastSettingsStatus",
        "App.settingsRefreshPending",
        "App.settingsBackgroundRefreshPromise",
    )
    for private_name in forbidden_private_state:
        assert private_name not in composition

    assert "getProjectRules" not in composition
    assert "getSettingsPrivacyStatus" not in composition
    assert "onDataChanged" in rules
    assert "onPageEntered" in rules
    assert "onDataChanged" in settings
    assert "onPageEntered" in settings
    assert "App.rules.onDataChanged" in composition
    assert "App.settings.onDataChanged" in composition

