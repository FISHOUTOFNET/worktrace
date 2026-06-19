from __future__ import annotations

import time

from ..constants import (
    EXCLUDED_APP_NAME,
    EXCLUDED_PROCESS_NAME,
    EXCLUDED_WINDOW_TITLE,
    STATUS_EXCLUDED,
)
from ..db import get_db_path
from ..platforms.base import ActiveWindow
from .settings_service import get_list_setting, set_list_setting

_EXCLUDE_KEYWORD_CACHE_TTL_SECONDS = 5.0
_EXCLUDE_KEYWORD_CACHE: dict[str, tuple[float, list[str]]] = {}


def clear_exclude_keywords_cache() -> None:
    _EXCLUDE_KEYWORD_CACHE.pop(str(get_db_path().resolve()), None)


def get_exclude_keywords() -> list[str]:
    cache_key = str(get_db_path().resolve())
    now = time.monotonic()
    cached = _EXCLUDE_KEYWORD_CACHE.get(cache_key)
    if cached is not None and cached[0] >= now:
        return list(cached[1])
    keywords = get_list_setting("exclude_keywords", [])
    _EXCLUDE_KEYWORD_CACHE[cache_key] = (now + _EXCLUDE_KEYWORD_CACHE_TTL_SECONDS, keywords)
    return list(keywords)


def set_exclude_keywords(keywords: list[str]) -> None:
    cleaned = [item.strip() for item in keywords if item.strip()]
    set_list_setting("exclude_keywords", cleaned)
    _EXCLUDE_KEYWORD_CACHE[str(get_db_path().resolve())] = (
        time.monotonic() + _EXCLUDE_KEYWORD_CACHE_TTL_SECONDS,
        cleaned,
    )


def is_excluded(active_window: ActiveWindow) -> bool:
    haystack = " ".join(
        [
            active_window.app_name,
            active_window.process_name,
            active_window.window_title,
            active_window.file_path_hint or "",
        ]
    ).lower()
    return any(keyword.lower() in haystack for keyword in get_exclude_keywords() if keyword.strip())


def make_excluded_activity_payload() -> dict:
    return {
        "app_name": EXCLUDED_APP_NAME,
        "process_name": EXCLUDED_PROCESS_NAME,
        "window_title": EXCLUDED_WINDOW_TITLE,
        "status": STATUS_EXCLUDED,
        "file_path_hint": None,
    }
