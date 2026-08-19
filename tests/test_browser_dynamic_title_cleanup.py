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
        "ChatGPT - Valuation and 1 more page - Personal - Microsoft Edge",
        "ChatGPT - Valuation and 12 more pages - Profile 1 - Microsoft Edge Dev",
    ],
)
def test_edge_dynamic_window_suffix_does_not_change_page_identity(window_title: str):
    result = BrowserDetector().detect(
        ActiveWindow(
            app_name="Edge",
            process_name="msedge.exe",
            window_title=window_title,
        )
    )

    assert result is not None
    assert result.display_name == "ChatGPT - Valuation"
    assert result.identity_key == "browser_title:msedge.exe:chatgpt-valuation"
    assert result.window_title == window_title


def test_edge_dynamic_window_suffix_is_cleaned_before_blank_page_detection():
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
