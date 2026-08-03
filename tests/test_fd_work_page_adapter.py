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
from worktrace.integrations.fd_work.integration_service import (
    FD_WORK_CASE_LABEL_MAX_LENGTH,
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


def test_login_credentials_and_confirmation_are_distinct_url_hints():
    adapter = FDWorkPageAdapter()

    assert adapter.detect_page_hint("https://work.fangdalaw.com/Login") == "login_credentials"
    assert adapter.detect_page_hint("https://work.fangdalaw.com/LoginToken") == "login_confirmation"


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
    assert adapter.adapter_version == 4
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


def test_page_phase_probe_models_login_confirmation_without_credentials():
    scripts = []

    class Window:
        def evaluate_js(self, script, callback=None):
            scripts.append(script)
            assert callback is None
            return {"ready": True}

    results = []
    FDWorkPageAdapter().probe_page_phase(Window(), results.append)

    assert results == [{"ready": True}]
    assert len(scripts) == 1
    assert 'path === "/login"' in scripts[0]
    assert 'path === "/logintoken"' in scripts[0]
    confirmation = scripts[0].split('path === "/logintoken"', 1)[1]
    assert 'input[type="password"]' not in confirmation
    assert "login_confirmation" in confirmation


def test_page_phase_probe_distinguishes_work_shell_from_interactive_handshake():
    scripts = []

    class Window:
        def evaluate_js(self, script, callback=None):
            scripts.append(script)
            assert callback is None
            return {"ready": True}

    results = []
    FDWorkPageAdapter().probe_page_phase(Window(), results.append)

    assert results == [{"ready": True}]
    assert len(scripts) == 1
    assert "form#basic" in scripts[0]
    assert '#basic_caseId[role="combobox"]' in scripts[0]
    assert "work_shell" in scripts[0]
    assert "work_interactive" not in scripts[0]


def test_async_javascript_result_is_received_through_pywebview_callback():
    class Window:
        def __init__(self):
            self.calls = []

        def evaluate_js(self, script, callback=None):
            self.calls.append((script, callback))
            if callback is not None:
                callback({"ok": True, "status": "filled"})

    window = Window()

    adapter = FDWorkPageAdapter()
    assert adapter.install_adapter(window)["ok"] is True
    result = adapter.fill_entry(window, _draft(), timeout_seconds=1.0)

    assert result == {"ok": True, "status": "filled"}
    assert len(window.calls) == 2
    assert window.calls[0][1] is None
    assert callable(window.calls[-1][1])


def test_search_script_serializes_query_and_calls_adapter_search_contract():
    adapter = FDWorkPageAdapter()

    script = adapter.build_search_script('CASE-"quoted"')

    assert "searchCases" in script
    assert json.dumps('CASE-"quoted"', ensure_ascii=True) in script
    assert 'CASE-"quoted"' not in script
    assert '"max_options":20' in script
    assert f'"max_label_length":{FD_WORK_CASE_LABEL_MAX_LENGTH}' in script
    assert '"version":4' in script


def test_search_script_accepts_empty_recent_query_and_one_character_query():
    adapter = FDWorkPageAdapter()
    assert "searchCases" in adapter.build_search_script("")
    assert json.dumps("A") in adapter.build_search_script("A")


def test_search_cases_validates_and_normalizes_the_callback_shape():
    class Window:
        def __init__(self):
            self.calls = []

        def evaluate_js(self, script, callback=None):
            self.calls.append((script, callback))
            if callback is not None:
                callback({"ok": True, "labels": [" CASE A ", "CASE B"]})

    window = Window()

    result = FDWorkPageAdapter().search_cases(window, "ca", timeout_seconds=1.0)

    assert result == {"ok": True, "labels": ["CASE A", "CASE B"]}
    assert len(window.calls) == 1
    assert callable(window.calls[0][1])


def test_adapter_source_is_cached_and_actions_do_not_reinject(monkeypatch):
    reads = []
    original = Path.read_text

    def tracked_read(path, *args, **kwargs):
        reads.append(path)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", tracked_read)

    class Window:
        def __init__(self):
            self.calls = []

        def evaluate_js(self, script, callback=None):
            self.calls.append((script, callback))
            if callback is not None:
                callback({"ok": True, "labels": []})

    adapter = FDWorkPageAdapter()
    window = Window()
    assert adapter.install_adapter(window)["ok"] is True
    assert adapter.install_adapter(window)["ok"] is True
    assert adapter.search_cases(window, "A", timeout_seconds=1.0)["ok"] is True
    assert adapter.search_cases(window, "B", timeout_seconds=1.0)["ok"] is True

    assert len(reads) == 1
    large_scripts = [
        script
        for script, callback in window.calls
        if callback is None and len(script) > 10_000
    ]
    assert len(large_scripts) == 2
    assert sum(callable(callback) for _script, callback in window.calls) == 2


def test_adapter_mismatch_is_replaced_and_injection_failure_is_explicit():
    class Window:
        def __init__(self, result):
            self.result = result
            self.scripts = []

        def evaluate_js(self, script, callback=None):
            assert callback is None
            self.scripts.append(script)
            return self.result

    repaired = Window({"ok": True, "version": 4})
    assert FDWorkPageAdapter().install_adapter(repaired) == {
        "ok": True,
        "version": 4,
    }
    assert "version === 4" in repaired.scripts[0]

    failed = Window({"ok": False, "error": "adapter_injection_failed"})
    assert FDWorkPageAdapter().install_adapter(failed) == {
        "ok": False,
        "error": "adapter_injection_failed",
    }


@pytest.mark.parametrize(
    "remote_result",
    [
        None,
        {"ok": True, "labels": "CASE A"},
        {"ok": True, "labels": ["CASE"] * 21},
        {"ok": True, "labels": [""]},
        {"ok": True, "labels": ["X" * (FD_WORK_CASE_LABEL_MAX_LENGTH + 1)]},
        {"ok": True, "labels": ["CASE A", "\u3000CASE A\u00a0"]},
        {"ok": True, "labels": [1]},
    ],
)
def test_search_cases_rejects_malformed_or_duplicate_remote_results(remote_result):
    class Window:
        def evaluate_js(self, _script, callback=None):
            if callback is not None:
                callback(remote_result)

    result = FDWorkPageAdapter().search_cases(Window(), "ca")

    expected = (
        "duplicate_case_label"
        if isinstance(remote_result, dict)
        and isinstance(remote_result.get("labels"), list)
        and len(remote_result["labels"]) == 2
        else "page_contract_changed"
    )
    assert result == {"ok": False, "error": expected}
