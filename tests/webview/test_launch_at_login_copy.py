from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = [pytest.mark.contract, pytest.mark.webview_static]

ROOT = Path(__file__).resolve().parents[2]
INDEX = ROOT / "worktrace" / "webview_ui" / "index_fd_work_v5.html"


def test_launch_at_login_copy_is_concise() -> None:
    index = INDEX.read_text(encoding="utf-8")
    assert ">开机自启动<" in index
    assert "登录 Windows 时自动启动有迹" not in index
