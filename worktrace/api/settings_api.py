"""Settings, privacy, and collector-status facade for the UI.

Wraps ``settings_service`` and the reset-database path from ``export_service``.
Also consolidates the duplicated current-activity snapshot JSON parsing that
previously lived inside each UI view.
"""

from __future__ import annotations

import json
import os
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
            "phase": "6C",
            "storage_model": "local_only",
            "clipboard_capture_enabled": clipboard_enabled,
            "export_path_configured": export_path_configured,
            "secure_import_in_progress": secure_import_in_progress,
            "encrypted_backup": {
                "supported": True,
                "export_available_in_webview": True,
                "import_available_in_webview": False,
                "manifest_preview_available_in_webview": True,
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


# --- Settings / Privacy encrypted backup export (Phase 6C) -------------


def export_encrypted_backup_for_webview(
    output_path: str,
    passphrase: str,
    confirm_passphrase: str,
) -> dict[str, Any]:
    """Export an encrypted ``.wtbackup`` file from the WebView UI.

    Phase 6C narrow write facade. Accepts a non-empty ``output_path`` string,
    a non-empty ``passphrase`` string, and a ``confirm_passphrase`` string
    that must exactly match ``passphrase``. If the chosen path does not end
    with ``.wtbackup`` (case-insensitive) the suffix is appended before
    calling the backend.

    On success returns ``{"ok": True, "filename": "<basename.wtbackup>",
    "message": "加密备份已导出"}``. Only the basename is surfaced; the full
    local path never leaves this facade.

    On failure returns ``{"ok": False, "error": "<chinese>"}``:
    - missing passphrase: ``请输入备份口令``
    - mismatched confirm passphrase: ``两次输入的备份口令不一致``
    - invalid output_path: ``请选择有效的备份保存位置``
    - any service-layer exception: ``导出加密备份失败``

    The payload never carries the full path, passphrase, raw exception,
    SQL, traceback, or any sensitive metadata. This facade does not call
    backup import, manifest preview, ``clear_all_local_data``, or
    ``set_setting_value``.
    """
    # Strict type checks: output_path must be a non-empty string (bool /
    # None / int / list / dict / object rejected). A whitespace-only path
    # is also rejected.
    if not isinstance(output_path, str) or isinstance(output_path, bool):
        return {"ok": False, "error": "请选择有效的备份保存位置"}
    if not output_path or not output_path.strip():
        return {"ok": False, "error": "请选择有效的备份保存位置"}
    # passphrase must be a non-empty string; whitespace-only rejected.
    if not isinstance(passphrase, str) or isinstance(passphrase, bool):
        return {"ok": False, "error": "请输入备份口令"}
    if not passphrase or not passphrase.strip():
        return {"ok": False, "error": "请输入备份口令"}
    # confirm_passphrase must be a string; mismatch uses exact comparison
    # (no trim) so the user is not surprised by silently dropped spaces.
    if not isinstance(confirm_passphrase, str) or isinstance(confirm_passphrase, bool):
        return {"ok": False, "error": "两次输入的备份口令不一致"}
    if confirm_passphrase != passphrase:
        return {"ok": False, "error": "两次输入的备份口令不一致"}
    # Normalize the suffix: append .wtbackup if missing (case-insensitive).
    normalized_path = output_path
    if not normalized_path.lower().endswith(".wtbackup"):
        normalized_path = normalized_path + ".wtbackup"
    try:
        backup_api.export_encrypted_backup(normalized_path, passphrase)
    except Exception:
        # Collapse any service-layer exception to a generic message.
        # Never expose raw exception text / traceback / SQL / path.
        return {"ok": False, "error": "导出加密备份失败"}
    # Return only the basename so the full path never reaches the UI.
    filename = os.path.basename(normalized_path)
    return {"ok": True, "filename": filename, "message": "加密备份已导出"}


# --- Settings / Privacy encrypted backup manifest preview (Phase 6C) ---


def preview_encrypted_backup_manifest_for_webview(
    input_path: str,
) -> dict[str, Any]:
    """Preview the non-sensitive manifest of a ``.wtbackup`` file.

    Phase 6C narrow read facade. Accepts a non-empty ``input_path`` string
    that looks like a ``.wtbackup`` file path (case-insensitive suffix).
    Does not require a passphrase and does not decrypt the payload.

    On success returns ``{"ok": True, "filename": "<basename.wtbackup>",
    "manifest": {...}}`` where ``manifest`` contains only display-safe
    fields: ``version``, ``app_version``, ``created_at``,
    ``kdf_algorithm``, ``payload_format``, ``payload_alg``.

    On failure returns ``{"ok": False, "error": "<chinese>"}``:
    - invalid path: ``请选择有效的加密备份文件``
    - manifest parse failure / corruption / unsupported version / any
      service-layer exception: ``读取备份清单失败``

    The payload never carries the full path, salt, ciphertext, payload,
    database content, clipboard content, window title, file path hint,
    note, SQL, traceback, or raw exception. This facade does not call
    backup import, backup export, ``clear_all_local_data``, or
    ``set_setting_value``.
    """
    # Strict type checks: input_path must be a non-empty string that ends
    # with .wtbackup (case-insensitive). bool / None / int / list / dict /
    # object rejected.
    if not isinstance(input_path, str) or isinstance(input_path, bool):
        return {"ok": False, "error": "请选择有效的加密备份文件"}
    if not input_path or not input_path.strip():
        return {"ok": False, "error": "请选择有效的加密备份文件"}
    if not input_path.lower().endswith(".wtbackup"):
        return {"ok": False, "error": "请选择有效的加密备份文件"}
    try:
        info = backup_api.parse_encrypted_backup_manifest(input_path)
    except Exception:
        # Collapse BackupCorruptedError / BackupVersionNotSupportedError /
        # RuntimeError / any service-layer exception to a generic message.
        # Never expose raw exception text / traceback / SQL / path.
        return {"ok": False, "error": "读取备份清单失败"}
    # Build the display-safe manifest dict. Only the six non-sensitive
    # fields are surfaced; salt / ciphertext / payload / DB content are
    # never included.
    filename = os.path.basename(input_path)
    manifest: dict[str, Any] = {
        "version": int(info.version),
        "app_version": str(info.app_version),
        "created_at": str(info.created_at),
        "kdf_algorithm": str(info.kdf_algorithm),
        "payload_format": str(info.payload_format),
        "payload_alg": str(info.payload_alg),
    }
    return {"ok": True, "filename": filename, "manifest": manifest}


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
    "export_encrypted_backup_for_webview",
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
    "preview_encrypted_backup_manifest_for_webview",
    "set_clipboard_capture_enabled",
    "set_clipboard_capture_enabled_for_webview",
    "set_collector_status",
    "set_current_activity_snapshot",
    "set_list_setting_value",
    "set_setting_value",
    "set_user_paused",
]
