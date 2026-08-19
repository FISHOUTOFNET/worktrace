from __future__ import annotations

import pytest

from worktrace.platforms.base import ActiveWindow
from worktrace.resources.browser_detector import BrowserDetector

pytestmark = [pytest.mark.unit, pytest.mark.parallel_safe]


@pytest.mark.parametrize(
    "window_title",
    [
        "ChatGPT - Valuation 和另外 1 个页面 - Microsoft Edge",
        "ChatGPT - Valuation 和另外 7 个页面 - 个人 - Microsoft Edge",
        "ChatGPT - Valuation 和另外 10 个页面",
        "ChatGPT - Valuation 和另外 10 个页面 ‐ 个人 ‐ Microsoft Edge",
        "ChatGPT - Valuation and 1 more page - Personal - Microsoft Edge",
        "ChatGPT - Valuation and 12 more pages - Profile 1 - Microsoft Edge Dev",
    ],
)
def test_dynamic_window_suffix_does_not_change_page_identity(window_title: str):
    detector = BrowserDetector()
    baseline = detector.detect(
        ActiveWindow(
            app_name="Edge",
            process_name="msedge.exe",
            window_title="ChatGPT - Valuation - Microsoft Edge",
        )
    )
    result = detector.detect(
        ActiveWindow(
            app_name="Edge",
            process_name="msedge.exe",
            window_title=window_title,
        )
    )

    assert baseline is not None
    assert result is not None
    assert result.display_name == "ChatGPT - Valuation"
    assert result.identity_key == baseline.identity_key
    assert result.window_title == window_title


def test_observed_edge_title_is_normalized():
    title = "WorkTrace - 规范化浏览器标题 和另外 10 个页面 - 个人 - Microsoft Edge"
    result = BrowserDetector().detect(
        ActiveWindow(app_name="Edge", process_name="msedge.exe", window_title=title)
    )

    assert result is not None
    assert result.display_name == "WorkTrace - 规范化浏览器标题"
    assert result.window_title == title


def test_dynamic_window_suffix_is_cleaned_before_blank_page_detection():
    result = BrowserDetector().detect(
        ActiveWindow(
            app_name="Edge",
            process_name="msedge.exe",
            window_title="New Tab and 2 more pages - Personal - Microsoft Edge Canary",
        )
    )

    assert result is not None
    assert result.display_name == "New Tab"
    assert result.identity_key == "browser_blank:msedge.exe"
    assert result.is_anchor is False


@pytest.mark.parametrize(
    ("app_name", "process_name", "brand"),
    [
        ("Chrome", "chrome.exe", "Google Chrome"),
        ("Edge", "msedge.exe", "Microsoft Edge"),
        ("Firefox", "firefox.exe", "Mozilla Firefox"),
        ("Brave", "brave.exe", "Brave"),
        ("Opera", "opera.exe", "Opera"),
        ("Vivaldi", "vivaldi.exe", "Vivaldi"),
    ],
)
def test_page_count_cleanup_applies_to_supported_browsers(
    app_name: str,
    process_name: str,
    brand: str,
):
    result = BrowserDetector().detect(
        ActiveWindow(
            app_name=app_name,
            process_name=process_name,
            window_title=f"Guide 和另外 2 个页面 - {brand}",
        )
    )

    assert result is not None
    assert result.display_name == "Guide"


def test_unconfirmed_other_tabs_wording_is_not_collapsed():
    result = BrowserDetector().detect(
        ActiveWindow(
            app_name="Edge",
            process_name="msedge.exe",
            window_title="Guide and 2 other tabs - Microsoft Edge",
        )
    )

    assert result is not None
    assert result.display_name == "Guide and 2 other tabs"


def test_profile_like_page_title_is_preserved_without_dynamic_page_count():
    result = BrowserDetector().detect(
        ActiveWindow(
            app_name="Edge",
            process_name="msedge.exe",
            window_title="Project - Personal - Microsoft Edge",
        )
    )

    assert result is not None
    assert result.display_name == "Project - Personal"
