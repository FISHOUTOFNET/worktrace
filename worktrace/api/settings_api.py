"""Settings, privacy, and collector-status facade for the UI.

Wraps ``settings_service`` and the reset-database path from ``export_service``.
Also consolidates the duplicated current-activity snapshot JSON parsing that
previously lived inside each UI view.
"""

from __future__ import annotations

import json
from typing import Any

from . import backup_api
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


# --- settings / privacy read-only status (Phase 6A) ---------------------

def get_settings_privacy_status() -> dict[str, Any]:
    """Return a read-only status snapshot for the Settings / Privacy WebView page.

    Phase 6A exposes only safety-status booleans. No path, no clipboard
    content, no passphrase, no DB write, no backup export/import action is
    surfaced here. All return values must be JSON-serializable.
    """
    try:
        export_path_configured = bool(get_export_path())
        clipboard_enabled = bool(is_clipboard_capture_enabled())
        try:
            secure_import_in_progress = bool(backup_api.is_secure_import_in_progress())
        except Exception:
            # Defensive: never let the backup facade leak tracebacks to the UI.
            secure_import_in_progress = False
        status: dict[str, Any] = {
            "page": "settings_privacy",
            "phase": "6A",
            "storage_model": "local_only",
            "clipboard_capture_enabled": clipboard_enabled,
            "export_path_configured": export_path_configured,
            "secure_import_in_progress": secure_import_in_progress,
            "encrypted_backup": {
                "supported": True,
                "export_available_in_webview": False,
                "import_available_in_webview": False,
                "manifest_preview_available_in_webview": False,
            },
            "destructive_actions": {
                "clear_all_local_data_available_in_webview": False,
            },
        }
        return {"ok": True, "status": status}
    except Exception:
        # Collapse any unexpected error to a generic UI-facing message.
        # Never expose raw exception text / traceback / SQL / paths.
        return {"ok": False, "error": "加载设置状态失败"}


# --- Settings / Privacy clipboard capture toggle write (Phase 6B) -------


def set_clipboard_capture_enabled_for_webview(enabled: bool) -> dict[str, Any]:
    """Write the ``clipboard_capture_enabled`` flag from the WebView UI.

    Phase 6B narrow write facade. Accepts only a real ``bool``; any other
    type (``None``, ``"true"`` / ``"false"`` strings, ``0`` / ``1`` ints,
    lists, dicts, objects, etc.) is rejected with a stable Chinese message
    and does NOT mutate the underlying setting. On success the updated
    Settings / Privacy status snapshot is returned so the frontend can
    re-render without a second round-trip.

    The payload never carries the setting key name, clipboard content,
    export path, passphrase, traceback, SQL, or raw exception text. This
    facade does not call backup export / import / manifest,
    ``clear_all_local_data``, or any schema mutation.
    """
    # Strict bool check: ``enabled is True`` / ``enabled is False`` only.
    # ``isinstance(enabled, bool)`` would also accept ``True``/``False``
    # but ``is`` is the clearest expression of "real bool only".
    if enabled is not True and enabled is not False:
        return {"ok": False, "error": "请选择有效的剪贴板记录状态"}
    try:
        set_clipboard_capture_enabled(enabled)
        status_result = get_settings_privacy_status()
        if not status_result.get("ok"):
            # The status read failed after a successful write. Surface a
            # generic failure so the frontend can re-load the status.
            return {"ok": False, "error": "设置剪贴板记录失败"}
        return {"ok": True, "status": status_result["status"]}
    except Exception:
        # Collapse any unexpected error to a generic UI-facing message.
        # Never expose raw exception text / traceback / SQL / paths.
        return {"ok": False, "error": "设置剪贴板记录失败"}


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
    "get_settings_privacy_status",
    "get_ui_refresh_seconds",
    "is_clipboard_capture_enabled",
    "is_paused",
    "is_user_paused",
    "set_clipboard_capture_enabled",
    "set_clipboard_capture_enabled_for_webview",
    "set_collector_status",
    "set_current_activity_snapshot",
    "set_list_setting_value",
    "set_setting_value",
    "set_user_paused",
]
