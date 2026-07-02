"""Settings, privacy, and collector-status facade for the UI.

Wraps ``settings_service`` and the reset-database path from ``export_service``.
Also consolidates the current-activity snapshot JSON parsing used by UI views.
"""

from __future__ import annotations

import json
import os

from typing import Any

from . import backup_api, live_display_api
from ..constants import PRIVACY_NOTICE_TEXT
from ..services import export_service
from ..services.secure_backup_service import (
    BackupCorruptedError,
    BackupDecryptionError,
    BackupImportInProgressError,
    BackupVersionNotSupportedError,
    SecureBackupError,
)
from ..services.settings_service import (
    clear_settings_cache,
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


# --- settings / privacy read-only status ---------------------

def get_settings_privacy_status() -> dict[str, Any]:
    """Return a read-only status snapshot for the Settings / Privacy WebView page.

    Exposes only safety-status booleans and a display-safe first-run notice
    sub-dict. No path, no clipboard content, no passphrase, no DB write, no
    backup export/import action is surfaced here. All return values must be
    JSON-serializable.
    """
    try:
        export_path_configured = bool(get_export_path())
        clipboard_enabled = bool(is_clipboard_capture_enabled())
        try:
            secure_import_in_progress = bool(backup_api.is_secure_import_in_progress())
        except Exception:
            # Defensive: never let the backup facade leak tracebacks to the UI.
            secure_import_in_progress = False
        # Display-safe first-run notice state. The raw DB setting key name
        # (``first_run_notice_accepted``) is NOT exposed; only the boolean +
        # view/accept availability flags are surfaced. ``accept_required``
        # is the negation of ``accepted`` so the frontend can decide whether
        # page offers a read-only notice viewer). ``accept_required`` is
        # the negation of ``accepted`` so the frontend can decide whether
        # to show the blocking first-run gate.
        try:
            notice_accepted = bool(first_run_notice_accepted())
        except Exception:
            # Defensive: never let a settings read failure leak a traceback.
            notice_accepted = False
        status: dict[str, Any] = {
            "page": "settings_privacy",
            "phase": "6E",
            "storage_model": "local_only",
            "clipboard_capture_enabled": clipboard_enabled,
            "export_path_configured": export_path_configured,
            "secure_import_in_progress": secure_import_in_progress,
            "encrypted_backup": {
                "supported": True,
                "export_available_in_webview": True,
                "import_available_in_webview": True,
                "manifest_preview_available_in_webview": True,
            },
            "destructive_actions": {
                "clear_all_local_data_available_in_webview": True,
            },
            "first_run_notice": {
                "accepted": notice_accepted,
                "view_available_in_webview": True,
                "accept_required": not notice_accepted,
            },
        }
        return {"ok": True, "status": status}
    except Exception:
        # Collapse any unexpected error to a generic UI-facing message.
        # Never expose raw exception text / traceback / SQL / paths.
        return {"ok": False, "error": "加载设置状态失败"}


# --- Settings / Privacy encrypted backup export -------------


def export_encrypted_backup_for_webview(
    output_path: str,
    passphrase: str,
    confirm_passphrase: str,
) -> dict[str, Any]:
    """Export an encrypted ``.wtbackup`` file from the WebView UI.

    Narrow write facade. Accepts a non-empty ``output_path`` string, a
    non-empty ``passphrase`` string, and a ``confirm_passphrase`` string
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


# --- Settings / Privacy encrypted backup manifest preview ---


def preview_encrypted_backup_manifest_for_webview(
    input_path: str,
) -> dict[str, Any]:
    """Preview the non-sensitive manifest of a ``.wtbackup`` file.

    Narrow read facade. Accepts a non-empty ``input_path`` string that
    looks like a ``.wtbackup`` file path (case-insensitive suffix). Does
    not require a passphrase and does not decrypt the payload.

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


# --- Settings / Privacy encrypted backup import ------------


def import_encrypted_backup_for_webview(
    input_path: str,
    passphrase: str,
    confirm_text: str,
) -> dict[str, Any]:
    """Import an encrypted ``.wtbackup`` file from the WebView UI.

    Narrow write facade. Replace-only: accepts a non-empty ``input_path``
    string that ends with ``.wtbackup`` (case-insensitive), a non-empty
    ``passphrase`` string, and a ``confirm_text`` string whose stripped
    value must be exactly ``导入并替换``. The suffix is NOT auto-appended;
    a wrong suffix is rejected outright.

    On success returns the narrow payload ``{"ok": True, "message":
    "加密备份已导入，WorkTrace 已暂停，请检查数据后手动恢复记录",
    "imported_table_count": int, "imported_row_count": int,
    "folder_index_reset": bool}``. The counts are aggregated from
    ``ImportResult.imported_tables``; the raw table-name -> row-count
    dict and table names are never returned to the UI.

    On failure returns ``{"ok": False, "error": "<chinese>"}``:
    - invalid path: ``请选择有效的加密备份文件``
    - invalid passphrase: ``请输入备份口令``
    - invalid confirmation: ``请输入确认文字：导入并替换``
    - ``BackupImportInProgressError``: ``已有加密备份导入正在进行``
    - ``BackupDecryptionError`` / ``BackupCorruptedError``:
      ``备份口令错误或文件已损坏``
    - ``BackupVersionNotSupportedError``: ``备份文件版本不受支持``
    - any other ``SecureBackupError`` / ``RuntimeError`` / ``Exception``:
      ``导入加密备份失败``

    The payload never carries the full path, passphrase, raw exception,
    SQL, traceback, salt, ciphertext, payload, window title, file path
    hint, note, or clipboard content. This facade does not call
    ``export_encrypted_backup``, ``parse_encrypted_backup_manifest``,
    ``clear_all_local_data``, or ``set_setting_value``.
    """
    # Strict type checks: input_path must be a non-empty string that ends
    # with .wtbackup (case-insensitive). bool / None / int / list / dict /
    # object / wrong suffix rejected. The suffix is NOT auto-appended.
    if not isinstance(input_path, str) or isinstance(input_path, bool):
        return {"ok": False, "error": "请选择有效的加密备份文件"}
    if not input_path or not input_path.strip():
        return {"ok": False, "error": "请选择有效的加密备份文件"}
    if not input_path.lower().endswith(".wtbackup"):
        return {"ok": False, "error": "请选择有效的加密备份文件"}
    # passphrase must be a non-empty string; whitespace-only rejected.
    # passphrase is NOT trimmed / normalized / written to any global state.
    if not isinstance(passphrase, str) or isinstance(passphrase, bool):
        return {"ok": False, "error": "请输入备份口令"}
    if not passphrase or not passphrase.strip():
        return {"ok": False, "error": "请输入备份口令"}
    # confirm_text must be a real string whose stripped value is exactly
    # the literal confirmation phrase.
    if not isinstance(confirm_text, str) or isinstance(confirm_text, bool):
        return {"ok": False, "error": "请输入确认文字：导入并替换"}
    if confirm_text.strip() != "导入并替换":
        return {"ok": False, "error": "请输入确认文字：导入并替换"}
    try:
        result = backup_api.import_encrypted_backup(
            input_path, passphrase, mode="replace"
        )
    except BackupImportInProgressError:
        return {"ok": False, "error": "已有加密备份导入正在进行"}
    except (BackupDecryptionError, BackupCorruptedError):
        return {"ok": False, "error": "备份口令错误或文件已损坏"}
    except BackupVersionNotSupportedError:
        return {"ok": False, "error": "备份文件版本不受支持"}
    except (SecureBackupError, RuntimeError, Exception):
        # Collapse any other service-layer exception to a generic message.
        # Never expose raw exception text / traceback / SQL / path /
        # passphrase / salt / ciphertext / payload.
        return {"ok": False, "error": "导入加密备份失败"}
    # Aggregate the imported_tables dict into display-safe counts only.
    imported_tables = result.imported_tables or {}
    imported_table_count = int(len(imported_tables))
    imported_row_count = int(sum(imported_tables.values()))
    return {
        "ok": True,
        "message": "加密备份已导入，WorkTrace 已暂停，请检查数据后手动恢复记录",
        "imported_table_count": imported_table_count,
        "imported_row_count": imported_row_count,
        "folder_index_reset": bool(result.folder_index_reset),
    }


# --- Settings / Privacy clear-all-local-data ---------------


def clear_all_local_data_for_webview(confirm_text: str) -> dict[str, Any]:
    """Clear all local data from the WebView UI.

    Narrow write facade. ``confirm_text`` must be a real string whose
    stripped value is exactly ``清空本地数据``; bool / None / int / list
    / dict / object / empty / whitespace-only are all rejected. Only when
    the confirmation matches does this facade call
    ``clear_all_local_data(confirm=True)``, which runs inside a
    destructive reset guard that pauses the collector and blocks collector
    writes for the duration of the DB replacement.

    On success returns ``{"ok": True, "message": "本地数据已清空",
    "status": <get_settings_privacy_status()["status"]>}`` so the frontend
    can re-render the Settings / Privacy status without a second
    round-trip. If the status refresh fails after a successful clear the
    facade returns ``{"ok": True, "message": "本地数据已清空"}`` so the
    successful clear is not masked by a status-read failure.

    On failure returns ``{"ok": False, "error": "<chinese>"}``:
    - invalid confirmation: ``请输入确认文字：清空本地数据``
    - any exception (including ``operation_in_progress`` from the
      destructive reset guard): ``清空本地数据失败``

    The payload never carries raw exception, traceback, SQL, path,
    clipboard content, window title, file path hint, or note. This facade
    does not call encrypted backup export / import / manifest, and does
    not call ``set_setting_value``.
    """
    # Strict type checks: confirm_text must be a real string whose
    # stripped value is exactly the literal confirmation phrase.
    if not isinstance(confirm_text, str) or isinstance(confirm_text, bool):
        return {"ok": False, "error": "请输入确认文字：清空本地数据"}
    if confirm_text.strip() != "清空本地数据":
        return {"ok": False, "error": "请输入确认文字：清空本地数据"}
    try:
        export_service.clear_all_local_data(confirm=True)
    except Exception:
        # Collapse any exception (including ValueError from the guard
        # when a destructive operation is already in progress) to the
        # stable Chinese message. Never expose raw exception text /
        # traceback / SQL / path / clipboard / window title / note.
        return {"ok": False, "error": "清空本地数据失败"}
    # Try to refresh the status so the frontend can re-render; on failure
    # still report the successful clear so it is not masked by a read error.
    try:
        status_result = get_settings_privacy_status()
        if status_result.get("ok"):
            return {
                "ok": True,
                "message": "本地数据已清空",
                "status": status_result["status"],
            }
    except Exception:
        pass
    return {"ok": True, "message": "本地数据已清空"}


# --- Settings / Privacy clipboard capture toggle write -------


def set_clipboard_capture_enabled_for_webview(enabled: bool) -> dict[str, Any]:
    """Write the ``clipboard_capture_enabled`` flag from the WebView UI.

    Narrow write facade. Accepts only a real ``bool``; any other type
    (``None``, ``"true"`` / ``"false"`` strings, ``0`` / ``1`` ints,
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


# --- Settings / Privacy first-run notice ---------------------


# Highlights shown in the WebView notice view.
# WebView notice view stays consistent with the prior UI semantics.
_FIRST_RUN_NOTICE_HIGHLIGHTS: list[str] = [
    "本地保存",
    "不截屏录屏",
    "不主动读正文",
    "用户可清空",
]

_FIRST_RUN_NOTICE_TITLE = "WorkTrace 隐私说明"


def get_first_run_notice_for_webview() -> dict[str, Any]:
    """Return the display-safe first-run privacy notice payload for WebView.

    Narrow read facade. Zero parameters. On success returns the narrow
    payload ``{"ok": True, "accepted": bool, "title": str,
    "highlights": list[str], "notice_text": str}``.

    - ``accepted`` comes from ``first_run_notice_accepted()``; a brand new
      database seeds ``first_run_notice_accepted="false"`` so the first
      run returns ``accepted=False``.
    - ``notice_text`` is sourced from ``PRIVACY_NOTICE_TEXT``.
    - ``highlights`` is the fixed list above.

    Strict fail-closed: if reading ``accepted`` raises (e.g. settings
    hiccup), the method returns ``{"ok": False, "error": "<stable
    Chinese>"}`` WITHOUT any notice_text. The frontend must display a
    blocking error overlay, must NOT render a fallback notice body, and
    must NOT allow the user to accept. The collector and folder index
    worker are not started. This is the sole notice-text source; the
    frontend does not maintain a second fallback copy.

    The payload is JSON-serializable and never carries the full path, DB
    path, export path, clipboard content, window title, file path hint,
    note, SQL, traceback, or raw exception.

    This facade does not call backup export / import / manifest,
    ``clear_all_local_data``, ``set_setting_value``, or any collector
    start / stop action.
    """
    try:
        accepted = bool(first_run_notice_accepted())
    except Exception:
        # Strict fail-closed: do NOT return a fallback notice body. The
        # frontend must show a blocking error and must not allow accept.
        # Never expose raw exception text / traceback / SQL / paths.
        return {
            "ok": False,
            "error": "隐私说明加载失败。为保护隐私，WorkTrace 暂不会启动记录。请重启应用或重新安装。",
        }
    return {
        "ok": True,
        "accepted": accepted,
        "title": _FIRST_RUN_NOTICE_TITLE,
        "highlights": list(_FIRST_RUN_NOTICE_HIGHLIGHTS),
        "notice_text": str(PRIVACY_NOTICE_TEXT),
    }


def accept_first_run_notice_for_webview() -> dict[str, Any]:
    """Accept the first-run privacy notice from the WebView UI.

    Narrow write facade. Zero parameters. Calls
    ``accept_first_run_notice()`` which writes
    ``first_run_notice_accepted="true"`` through the standard
    ``set_setting`` path (so the settings cache is refreshed in-process
    and a subsequent ``get_first_run_notice_for_webview()`` /
    ``get_settings_privacy_status()`` read sees ``accepted=True``).

    On success returns ``{"ok": True, "accepted": True,
    "message": "已确认隐私说明"}``. Idempotent: calling again after a
    previous accept still returns success.

    On any exception returns ``{"ok": False, "error": "确认隐私说明失败"}``.

    This facade does NOT call the collector (collector start is the
    bridge / ``webview_main`` startup gate's responsibility), does NOT
    call ``set_setting_value`` (it goes through the existing
    ``accept_first_run_notice`` path), and does NOT call backup
    export / import / manifest / ``clear_all_local_data``. To guarantee
    in-process read consistency the cache for
    ``first_run_notice_accepted`` is explicitly invalidated before
    returning, in addition to the cache refresh that ``set_setting``
    already performs.
    """
    try:
        accept_first_run_notice()
        # Belt-and-suspenders cache invalidation: ``set_setting`` already
        # refreshes the cache entry, but explicitly clearing it as well
        # guarantees a subsequent read re-reads from the DB and cannot
        # observe a stale TTL window. This is safe because
        # ``clear_settings_cache`` is a no-op when the key is absent.
        clear_settings_cache("first_run_notice_accepted")
        return {
            "ok": True,
            "accepted": True,
            "message": "已确认隐私说明",
        }
    except Exception:
        # Collapse any unexpected error to a generic UI-facing message.
        # Never expose raw exception text / traceback / SQL / paths.
        return {"ok": False, "error": "确认隐私说明失败"}


# --- Lightweight refresh-state (frontend heartbeat) -------------


def get_refresh_state(report_date: str | None = None) -> dict[str, Any]:
    """Return a lightweight refresh-state payload for the frontend heartbeat.

    The ``refresh_revision`` is computed by
    ``live_display_api.compute_refresh_revision`` so it covers ALL
    structural changes affecting Overview / Recent / Timeline display:

    - current snapshot identity / status / persisted state /
      persisted_activity_id / inferred_project_name;
    - pending_short_seconds / short-activity carry state;
    - the latest visible activity id / updated_at / structural kind for
      the report date (covers manual project edit, time edit, split,
      merge, hide, delete, restore, note edit, open row persisted,
      project assignment);
    - collector status / paused state;
    - the report date crossing midnight.

    It MUST NOT change when only ``elapsed_seconds`` / ``extra_seconds`` /
    ``snapshot_updated_at`` advance without any structural change.

    ``report_date`` scopes the structural signature to the currently
    viewed Timeline date. When ``report_date`` is ``None`` it defaults to
    today, matching the Overview / Recent default.
    ``report_date`` is ``None`` it defaults to today, matching the
    Overview / Recent default.

    The payload also carries the unified live clock fields
    (``live_started_at_epoch_ms``, ``carry_seconds``,
    ``stable_live_key``, ``stable_live_key_hash``) from the same
    snapshot sample so the frontend heartbeat ticker can compute
    ``display_seconds = carry_seconds + floor((Date.now() -
    live_started_at_epoch_ms) / 1000)`` without a separate bridge call.

    The payload is display-safe: no raw ``window_title``,
    ``file_path_hint``, ``note``, ``clipboard``, ``traceback`` or
    ``SQL`` is surfaced. The internal structural signature uses only
    display-safe fields, so its hash is safe to return to JS.

    On any exception returns ``{"ok": False, "error": "刷新状态加载失败"}``.
    """
    try:
        snapshot = get_current_activity_snapshot()
        collector_status = get_collector_status()
        user_paused = is_user_paused()
        paused = bool(user_paused) or collector_status == "paused"
        # Default report date (today). When the frontend passes a
        # Timeline date (historical or today), the structural signature
        # is scoped to that date so structural changes on the viewed
        # date trigger a heavy refresh.
        from . import timeline_api as _timeline_api
        today = _timeline_api.get_default_report_date()
        scoped_report_date = report_date or today
        # Unified refresh-revision computation. Delegates to
        # ``live_display_service.compute_refresh_revision`` so the
        # revision covers ALL structural changes (snapshot identity,
        # carry state, latest visible activity, collector status, etc.).
        refresh_revision, debug_inputs = live_display_api.compute_refresh_revision(
            snapshot, collector_status, user_paused, today, scoped_report_date
        )
        current_activity_key = str(debug_inputs.get("current_activity_key") or "")
        current_activity_status = str(debug_inputs.get("current_status") or "")
        is_persisted = bool(debug_inputs.get("is_persisted"))
        persisted_activity_id = int(debug_inputs.get("persisted_id") or 0)
        inferred_project_name = str(debug_inputs.get("inferred_project") or "")
        latest_activity_id = int(debug_inputs.get("latest_id") or 0)
        # Unified live clock: build the current-activity summary from the
        # SAME snapshot sample so the frontend ticker can use
        # ``live_started_at_epoch_ms`` + ``carry_seconds`` without a
        # separate bridge call. The live clock fields come from the same
        # snapshot as the refresh_revision, guaranteeing a single-sample
        # contract.
        live_summary = live_display_api.build_current_activity_summary(
            snapshot, report_date=scoped_report_date, today=today
        )
        # Map collector_status + user_paused to a display label.
        if paused or collector_status == "paused":
            status_display = "已暂停"
        elif collector_status == "running":
            status_display = "记录中"
        elif collector_status == "error":
            status_display = "状态异常"
        else:
            status_display = "采集器未运行"
        return {
            "ok": True,
            "collector_status": collector_status,
            "paused": paused,
            "status_display": status_display,
            "current_activity_key": current_activity_key,
            "current_activity_status": current_activity_status,
            "is_persisted": is_persisted,
            "persisted_activity_id": persisted_activity_id,
            "inferred_project_name": inferred_project_name,
            "refresh_revision": refresh_revision,
            "today": today,
            "report_date": scoped_report_date,
            "latest_activity_id": latest_activity_id,
            # Live clock fields. The frontend ticker computes
            # ``carry_seconds + floor((Date.now() -
            # live_started_at_epoch_ms) / 1000)``. These come from the
            # SAME snapshot sample as ``refresh_revision`` so there is no
            # clock drift between the revision check and the ticker. The
            # ``stable_live_key`` / ``stable_live_key_hash`` let the
            # frontend bind its continuity key to a stable live identity
            # that survives the virtual → persisted_open transition.
            # the virtual → persisted_open transition (item 12, 16).
            "live_started_at_epoch_ms": int(live_summary.get("live_started_at_epoch_ms") or 0),
            "carry_seconds": int(live_summary.get("carry_seconds") or 0),
            "stable_live_key": str(live_summary.get("stable_live_key") or ""),
            "stable_live_key_hash": str(live_summary.get("stable_live_key_hash") or ""),
            "live_state": str(live_summary.get("live_state") or ""),
        }
    except Exception:
        return {"ok": False, "error": "刷新状态加载失败"}


__all__ = [
    "accept_first_run_notice",
    "accept_first_run_notice_for_webview",
    "clear_all_local_data",
    "clear_all_local_data_for_webview",
    "export_encrypted_backup_for_webview",
    "first_run_notice_accepted",
    "get_bool_setting_value",
    "get_collector_status",
    "get_current_activity_snapshot",
    "get_export_path",
    "get_first_run_notice_for_webview",
    "get_int_setting_value",
    "get_list_setting_value",
    "get_refresh_state",
    "get_setting_value",
    "get_settings_privacy_status",
    "get_ui_refresh_seconds",
    "import_encrypted_backup_for_webview",
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
