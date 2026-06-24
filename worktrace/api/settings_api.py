"""Settings, privacy, and collector-status facade for the UI.

Wraps ``settings_service`` and the reset-database path from ``export_service``.
Also consolidates the duplicated current-activity snapshot JSON parsing that
previously lived inside each UI view.
"""

from __future__ import annotations

import json
from typing import Any

from ..services import export_service
from ..services.settings_service import (
    get_bool_setting,
    get_int_setting,
    get_list_setting,
    get_setting,
    set_list_setting,
    set_setting,
)


# --- general passthrough -------------------------------------------------

def get_setting_value(key: str, default: str | None = None) -> str | None:
    return get_setting(key, default)


def set_setting_value(key: str, value: str) -> None:
    set_setting(key, value)


def get_bool_setting_value(key: str, default: bool = False) -> bool:
    return get_bool_setting(key, default)


def get_int_setting_value(key: str, default: int) -> int:
    return get_int_setting(key, default)


def get_list_setting_value(key: str, default: list[str] | None = None) -> list[str]:
    return get_list_setting(key, default)


def set_list_setting_value(key: str, values: list[str]) -> None:
    set_list_setting(key, values)


# --- current activity snapshot -------------------------------------------

def get_current_activity_snapshot() -> dict[str, Any] | None:
    """Read and parse the ``current_activity_snapshot`` setting."""
    raw = get_setting("current_activity_snapshot", "") or ""
    if not raw:
        return None
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def set_current_activity_snapshot(value: str) -> None:
    set_setting("current_activity_snapshot", value)


# --- first-run notice ----------------------------------------------------

def first_run_notice_accepted() -> bool:
    return get_bool_setting("first_run_notice_accepted", False)


def accept_first_run_notice() -> None:
    set_setting("first_run_notice_accepted", "true")


# --- user pause / collector status ---------------------------------------

def is_user_paused() -> bool:
    return get_bool_setting("user_paused", False)


def set_user_paused(value: bool) -> None:
    set_setting("user_paused", "true" if value else "false")


def get_collector_status() -> str:
    return get_setting("collector_status", "stopped") or "stopped"


def set_collector_status(value: str) -> None:
    set_setting("collector_status", value)


def is_paused() -> bool:
    """True when the user paused or the collector status is paused."""
    return is_user_paused() or get_collector_status() == "paused"


# --- export path / refresh interval / clipboard --------------------------

def get_export_path() -> str:
    return get_setting("export_path", "") or ""


def get_ui_refresh_seconds() -> int:
    return get_int_setting("ui_refresh_seconds", 10)


def is_clipboard_capture_enabled() -> bool:
    return get_bool_setting("clipboard_capture_enabled", False)


def set_clipboard_capture_enabled(value: bool) -> None:
    set_setting("clipboard_capture_enabled", "true" if value else "false")


# --- reset database ------------------------------------------------------

def clear_all_local_data(confirm: bool) -> None:
    export_service.clear_all_local_data(confirm=confirm)


__all__ = [
    "accept_first_run_notice",
    "clear_all_local_data",
    "first_run_notice_accepted",
    "get_bool_setting_value",
    "get_collector_status",
    "get_current_activity_snapshot",
    "get_export_path",
    "get_int_setting_value",
    "get_list_setting_value",
    "get_setting_value",
    "get_ui_refresh_seconds",
    "is_clipboard_capture_enabled",
    "is_paused",
    "is_user_paused",
    "set_clipboard_capture_enabled",
    "set_collector_status",
    "set_current_activity_snapshot",
    "set_list_setting_value",
    "set_setting_value",
    "set_user_paused",
]
