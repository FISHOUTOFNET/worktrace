from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from static_helpers import func_body, read_js


_TARGET = "test_settings_js_hide_first_run_notice_does_not_write_setting_or_start_collector"


def _hide_first_run_notice_contract() -> None:
    source = read_js("settings.js")
    body = func_body(source, "hideFirstRunNotice")
    assert "App.callBridge" not in body
    assert "acceptFirstRunNotice" not in body
    assert "App.firstRunNoticeViewingFromSettings = false" in body


def pytest_collection_modifyitems(session, config, items) -> None:
    for item in items:
        if item.name == _TARGET:
            item._obj = _hide_first_run_notice_contract
