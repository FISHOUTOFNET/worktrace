from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from worktrace.integrations.fd_work.contracts import FDWorkEntryDraft
from worktrace.integrations.fd_work.page_adapter import (
    FDWorkPageAdapter,
    FDWorkPageType,
)


pytestmark = [pytest.mark.unit, pytest.mark.contract, pytest.mark.parallel_safe]


def _draft() -> FDWorkEntryDraft:
    return FDWorkEntryDraft(
        work_date="2026-07-31",
        case_number='CASE-"quoted"',
        duration_hours="1.4",
        narrative="Line one.\nLine two.",
    )


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (
            "https://work.fangdalaw.com/Works/WorkHourList?picker=day",
            FDWorkPageType.WORK_HOUR_LIST,
        ),
        (
            "https://work.fangdalaw.com/login?returnUrl=%2FWorks",
            FDWorkPageType.LOGIN,
        ),
        ("https://work.fangdalaw.com/Login", FDWorkPageType.LOGIN),
        ("https://work.fangdalaw.com/loginToken", FDWorkPageType.LOGIN),
        ("https://work.fangdalaw.com/permission", FDWorkPageType.UNAUTHORIZED),
        ("https://work.fangdalaw.com/404", FDWorkPageType.ERROR),
        ("https://work.fangdalaw.com/Works/Other", FDWorkPageType.UNKNOWN),
        ("https://example.com/login", FDWorkPageType.UNKNOWN),
    ],
)
def test_page_type_is_fail_closed(url, expected):
    assert FDWorkPageAdapter().detect_page(url) is expected


def test_navigation_allowlist_contains_only_discovered_exact_host():
    adapter = FDWorkPageAdapter()
    assert adapter.allowed_navigation_hosts == frozenset({"work.fangdalaw.com"})
    assert not adapter.navigation_allowed("https://other.fangdalaw.com/login")
    assert not adapter.navigation_allowed("https://example.com/")
    assert adapter.navigation_allowed(adapter.business_url)


def test_payload_is_json_serialized_not_interpolated_into_adapter_source():
    adapter = FDWorkPageAdapter()
    script = adapter.build_fill_script(_draft())

    payload = json.dumps(
        {
            "work_date": _draft().work_date,
            "case_number": _draft().case_number,
            "duration_hours": _draft().duration_hours,
            "narrative": _draft().narrative,
        },
        ensure_ascii=True,
        separators=(",", ":"),
    )
    assert payload in script
    assert "CASE-\"quoted\"" not in script


def test_adapter_owns_business_url_hosts_selectors_and_asset_version():
    adapter = FDWorkPageAdapter()
    assert adapter.business_url.startswith("https://work.fangdalaw.com/")
    assert adapter.adapter_version == 1
    assert set(adapter.field_contract) == {
        "case_number",
        "work_date",
        "duration_hours",
        "narrative",
    }
    asset = Path(adapter.adapter_asset_path)
    assert asset.name == "fd_work_adapter.js"


def test_login_url_is_derived_from_the_single_business_url_and_encodes_return_url():
    adapter = FDWorkPageAdapter()
    business = urlsplit(adapter.business_url)
    login = urlsplit(adapter.login_url)

    assert login.scheme == "https"
    assert login.hostname == "work.fangdalaw.com"
    assert login.path.lower() == "/login"
    assert parse_qs(login.query) == {
        "returnUrl": [business.path + "?" + business.query]
    }
    assert "%2FWorks%2FWorkHourList%3Fpicker%3Dday" in adapter.login_url


def test_login_readiness_script_checks_all_three_visible_controls():
    scripts = []

    class Window:
        def evaluate_js(self, script, callback=None):
            scripts.append(script)
            if callback is not None:
                callback({"ready": True})

    results = []
    FDWorkPageAdapter().check_login_page_ready(Window(), results.append)

    assert results == [{"ready": True}]
    assert len(scripts) == 1
    assert "password" in scripts[0]
    assert "账号" in scripts[0]
    assert "登录" in scripts[0]


def test_async_javascript_result_is_received_through_pywebview_callback():
    class Window:
        def __init__(self):
            self.calls = []

        def evaluate_js(self, script, callback=None):
            self.calls.append((script, callback))
            if callback is not None:
                callback({"ok": True, "status": "filled"})

    window = Window()

    result = FDWorkPageAdapter().fill_entry(window, _draft())

    assert result == {"ok": True, "status": "filled"}
    assert len(window.calls) == 2
    assert window.calls[0][1] is None
    assert callable(window.calls[1][1])
