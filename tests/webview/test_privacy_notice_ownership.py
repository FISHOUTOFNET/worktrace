"""Application-level privacy notice ownership contracts."""

from __future__ import annotations

import re
from pathlib import Path

import pytest


pytestmark = [
    pytest.mark.contract,
    pytest.mark.webview_static,
    pytest.mark.security_privacy,
]

ROOT = Path(__file__).resolve().parents[2]
UI_ROOT = ROOT / "worktrace" / "webview_ui"
JS_ROOT = UI_ROOT / "js"

PRIVACY_GLOBALS = (
    "App.privacyGateState",
    "App.firstRunNoticeLoaded",
    "App.firstRunNoticeLoading",
    "App.firstRunNoticeRequired",
    "App.firstRunNoticeAcceptInProgress",
    "App.firstRunNoticeViewingFromSettings",
)


def source(name: str) -> str:
    return (JS_ROOT / name).read_text(encoding="utf-8")


def function_body(js: str, name: str) -> str:
    start = js.index("function " + name)
    next_function = js.find("\n    function ", start + 1)
    end_iife = js.find("\n})();", start + 1)
    ends = [position for position in (next_function, end_iife) if position != -1]
    return js[start : min(ends)] if ends else js[start:]


def test_privacy_notice_is_loaded_and_packaged_before_consumers() -> None:
    index = (UI_ROOT / "index_fd_work_v5.html").read_text(encoding="utf-8")
    spec = (ROOT / "WorkTrace.spec").read_text(encoding="utf-8")
    assert (JS_ROOT / "privacy_notice.js").is_file()
    privacy = index.index('src="js/privacy_notice.js?v=')
    settings = index.index('src="js/settings.js?v=')
    init = index.index('src="js/init_fd_work_v5.js?v=')
    assert privacy < settings < init
    assert "'privacy_notice.js'" in spec


def test_privacy_notice_is_the_only_first_run_bridge_owner() -> None:
    owners: dict[str, set[str]] = {}
    for path in JS_ROOT.glob("*.js"):
        calls = set(
            re.findall(
                r"\bApp\.bridge\.(getFirstRunNotice|acceptFirstRunNotice)\s*\(",
                path.read_text(encoding="utf-8"),
            )
        )
        if calls:
            owners[path.name] = calls
    assert owners == {
        "privacy_notice.js": {"acceptFirstRunNotice", "getFirstRunNotice"}
    }


def test_retired_privacy_globals_are_absent_from_production() -> None:
    combined = "\n".join(
        path.read_text(encoding="utf-8") for path in JS_ROOT.glob("*.js")
    )
    for name in PRIVACY_GLOBALS:
        assert name not in combined


def test_settings_owners_do_not_own_global_privacy_modal_or_gate() -> None:
    settings = source("settings.js")
    transient = source("settings_transient_ui.js")
    presentation = source("settings_presentation.js")
    for forbidden in (
        "privacyGateState",
        "privacyNoticeLoaded",
        "privacyNoticeLoading",
        "privacyNoticeAccepting",
        "privacyNoticeRequestToken",
        "getFirstRunNotice",
        "acceptFirstRunNotice",
        "loadFirstRunNotice",
        "retryFirstRunNotice",
        "continueStartupAfterPrivacyGate",
    ):
        assert forbidden not in settings
    for forbidden in (
        "privacyNoticeMode",
        "privacyNoticeReturnFocus",
        "privacyNoticeViewToken",
        "first-run-notice-overlay",
        "hideFirstRunNotice",
        "showFirstRunNotice",
    ):
        assert forbidden not in transient
    for forbidden in (
        "renderFirstRunNotice",
        "showFirstRunNoticeBlockingError",
        "settleFirstRunNoticeControls",
        "setFirstRunNoticeAcceptDisabled",
        "setFirstRunNoticeError",
    ):
        assert forbidden not in presentation
    reset = function_body(settings, "resetSettingsGeneration")
    assert "privacyNotice" not in reset
    assert "privacyGate" not in reset


def test_init_owns_post_consent_startup_direction() -> None:
    init = source("init_fd_work_v5.js")
    privacy = source("privacy_notice.js")
    assert "App.privacyNotice" in init
    assert "App.settings.privacy" not in init
    assert "continueStartupAfterPrivacyGate" not in privacy
    init_body = function_body(init, "init()")
    assert "App.privacyNotice.loadGate()" in init_body
    assert "continueStartupAfterPrivacyGate()" in init_body


def test_privacy_notice_exposes_read_only_capability_without_raw_state() -> None:
    privacy = source("privacy_notice.js")
    assert "App.privacyNotice = Object.freeze({" in privacy
    for capability in (
        "loadGate",
        "acceptGate",
        "retryGate",
        "openFromSettings",
        "closeView",
        "isReady",
        "state",
    ):
        assert re.search(rf"\b{capability}\s*:", privacy)
    assert "rawState" not in privacy
