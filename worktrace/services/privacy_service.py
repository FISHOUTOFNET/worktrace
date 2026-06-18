from __future__ import annotations

from ..constants import (
    EXCLUDED_APP_NAME,
    EXCLUDED_PROCESS_NAME,
    EXCLUDED_WINDOW_TITLE,
    STATUS_EXCLUDED,
)
from ..platforms.base import ActiveWindow
from .settings_service import get_list_setting, set_list_setting


def get_exclude_keywords() -> list[str]:
    return get_list_setting("exclude_keywords", [])


def set_exclude_keywords(keywords: list[str]) -> None:
    set_list_setting("exclude_keywords", keywords)


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
        "is_billable": False,
        "is_confirmed": False,
        "file_path_hint": None,
    }
