from __future__ import annotations

import re

from ..platforms.base import ActiveWindow
from .resource_policy import validate_resource_kind, validate_resource_subtype
from .types import DetectedResource

BROWSER_PROCESS_NAMES = frozenset({
    "chrome.exe", "chrome",
    "msedge.exe", "msedge",
    "firefox.exe", "firefox",
    "brave.exe", "brave",
    "opera.exe", "opera",
    "vivaldi.exe", "vivaldi",
})

_BROWSER_TITLE_SUFFIXES = [
    "- Google Chrome",
    "- Microsoft Edge",
    "- Mozilla Firefox",
    "- Brave",
    "- Opera",
    "- Vivaldi",
    "— Google Chrome",
    "— Microsoft Edge",
    "— Mozilla Firefox",
]

# Patterns for new tab / blank pages
_BLANK_PAGE_PATTERNS = re.compile(
    r"^(新标签页|新标签|New Tab|NewTabPage|about:blank|about:home|about:newtab|空白页)$",
    re.IGNORECASE,
)

# Simple URL/domain extraction from title
_DOMAIN_PATTERN = re.compile(
    r"(?:https?://)?([a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?)+)",
)


class BrowserDetector:
    def detect(self, active_window: ActiveWindow) -> DetectedResource | None:
        process_lower = (active_window.process_name or "").strip().lower()
        if process_lower not in BROWSER_PROCESS_NAMES:
            return None

        title = (active_window.window_title or "").strip()
        cleaned_title = self._clean_title(title)
        uri_host = self._extract_uri_host(title)
        is_blank = self._is_blank_page(cleaned_title)

        if is_blank:
            return DetectedResource(
                resource_kind=validate_resource_kind("browser_tab"),
                resource_subtype=validate_resource_subtype("browser_page"),
                display_name=cleaned_title or "新标签页",
                identity_key=f"browser_blank:{process_lower}",
                is_anchor=False,
                confidence=90,
                source="browser_detector",
                app_name=active_window.app_name or "",
                process_name=active_window.process_name or "",
                window_title=active_window.window_title or "",
            )

        normalized_title = _normalize_for_key(cleaned_title)
        if uri_host:
            identity_key = f"browser_host_title:{uri_host.lower()}:{normalized_title}"
        else:
            identity_key = f"browser_title:{process_lower}:{normalized_title}"

        return DetectedResource(
            resource_kind=validate_resource_kind("browser_tab"),
            resource_subtype=validate_resource_subtype("browser_page"),
            display_name=cleaned_title or "浏览器",
            identity_key=identity_key,
            is_anchor=True,
            confidence=75,
            source="browser_detector",
            app_name=active_window.app_name or "",
            process_name=active_window.process_name or "",
            window_title=active_window.window_title or "",
            uri_host=uri_host,
        )

    def _clean_title(self, title: str) -> str:
        cleaned = title
        for suffix in _BROWSER_TITLE_SUFFIXES:
            if cleaned.endswith(suffix):
                cleaned = cleaned[: -len(suffix)].strip()
                break
        # Also try regex-based cleanup for variations
        cleaned = re.sub(
            r"\s*[-–—]\s*(Google Chrome|Microsoft Edge|Mozilla Firefox|Brave|Opera|Vivaldi)\s*$",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
        return cleaned.strip()

    def _extract_uri_host(self, text: str) -> str | None:
        match = _DOMAIN_PATTERN.search(text)
        if match:
            return match.group(1)
        return None

    def _is_blank_page(self, title: str) -> bool:
        if not title:
            return True
        return bool(_BLANK_PAGE_PATTERNS.match(title.strip()))


def _normalize_for_key(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"\s+", "-", value)
    value = re.sub(r"[^a-z0-9._\-\u4e00-\u9fff]+", "-", value)
    return value.strip("-") or "unknown"
