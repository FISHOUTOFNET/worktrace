from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML_PATH = ROOT / "worktrace" / "webview_ui" / "index_fd_work_v5.html"
SETTINGS_JS_PATH = ROOT / "worktrace" / "webview_ui" / "js" / "settings.js"


def test_privacy_overlay_blocks_shell_from_first_paint() -> None:
    html = HTML_PATH.read_text(encoding="utf-8")

    assert '<div id="first-run-notice-overlay" class="modal-layer">' in html
    assert '>正在检查隐私设置…</h1>' in html
    assert (
        'id="first-run-notice-accept-btn" type="button" '
        'class="button primary" hidden>'
    ) in html


def test_privacy_policy_version_is_not_rendered_to_users() -> None:
    html = HTML_PATH.read_text(encoding="utf-8")
    settings_js = SETTINGS_JS_PATH.read_text(encoding="utf-8")

    assert "first-run-notice-version" not in html
    assert "notice.policy_version" not in settings_js
    assert "first_run_notice.policy_version" not in settings_js
