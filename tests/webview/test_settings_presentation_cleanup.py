"""Static contracts for the concise Settings presentation."""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = [pytest.mark.contract, pytest.mark.webview_static]

ROOT = Path(__file__).resolve().parents[2]
UI_ROOT = ROOT / "worktrace" / "webview_ui"
INDEX = UI_ROOT / "index_fd_work_v5.html"
SETTINGS_JS = UI_ROOT / "js" / "settings.js"


def test_general_settings_show_only_the_real_local_data_location() -> None:
    index = INDEX.read_text(encoding="utf-8")
    assert 'id="settings-storage-card"' in index
    assert 'id="settings-local-data-path"' in index
    assert 'data-settings-key="export_path_configured"' not in index
    assert ">本机<" not in index
    assert ">本地目录<" not in index


def test_advanced_settings_do_not_render_internal_diagnostics() -> None:
    index = INDEX.read_text(encoding="utf-8")
    assert "技术诊断" not in index
    assert "diagnostic-list" not in index


def test_local_data_location_is_rendered_from_authoritative_status() -> None:
    source = SETTINGS_JS.read_text(encoding="utf-8")
    assert 'element("settings-local-data-path")' in source
    assert "status.local_data_path" in source
    assert 'target.textContent = path || "未加载";' in source
    assert "target.title = path;" in source
    assert "请在高级诊断中查看阻断原因" not in source
    assert "请在高级设置中尝试恢复" in source
