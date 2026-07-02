"""Settings / Privacy bridge mixin.

Boundary rules (enforced by ``tests/test_ui_backend_boundary.py``):

- This module may import ``worktrace.api``, ``worktrace.constants``,
  ``worktrace.formatters``, and stdlib only. It must NOT import
  ``worktrace.services``, ``worktrace.db``, ``worktrace.collector``,
  ``worktrace.security``, ``worktrace.runtime``, or ``worktrace.config``.
- Methods return JSON-serializable dicts/lists only.
- Methods catch exceptions and return ``{"ok": false, "error": "操作失败"}``
  style payloads without tracebacks.
- Methods do not log window titles, file paths, notes, or copied text.

``WebViewBridge`` in ``bridge.py`` inherits ``SettingsBridgeMixin`` so the
Settings / Privacy page method names stay on ``WebViewBridge``. The mixin
relies on the host class also mixing in ``BridgeDialogMixin`` (for
``self._choose_backup_save_path`` / ``self._choose_backup_open_path``) and
``OverviewBridgeMixin`` (for ``self.get_status``).
"""

from __future__ import annotations

import logging
from typing import Any

from ..api import app_api, settings_api

logger = logging.getLogger(__name__)


class SettingsBridgeMixin:
    """Settings / Privacy bridge methods.

    Mixed into ``WebViewBridge`` in ``bridge.py`` so the Settings / Privacy
    method names stay on ``WebViewBridge``. The mixin must NOT add
    ``__init__``; it relies on the host class.
    """

    def get_first_run_notice(self) -> dict[str, Any]:
        """Return the display-safe first-run privacy notice payload.

        Zero parameters. Calls
        ``settings_api.get_first_run_notice_for_webview()`` and
        transparently forwards its display-safe payload.

        On any exception returns ``{"ok": False, "error":
        "加载隐私说明失败"}`` so the frontend can surface a stable
        Chinese error.

        This method does not open a file dialog, does not call the
        collector, does not call a generalized settings write entry,
        and does not return a traceback / raw exception / SQL / path /
        clipboard content.
        """
        try:
            return settings_api.get_first_run_notice_for_webview()
        except Exception:
            logger.exception("webview bridge get_first_run_notice failed")
            return {"ok": False, "error": "加载隐私说明失败"}

    def accept_first_run_notice(self) -> dict[str, Any]:
        """Accept the first-run privacy notice and start the collector."""
        try:
            result = settings_api.accept_first_run_notice_for_webview()
            if not result.get("ok"):
                # API reported failure (or a stable Chinese error). Do
                # not start the collector; forward the error payload.
                return result
            # worker is gated by the same privacy notice as the
            try:
                app_api.start_background_workers()
            except Exception:
                # The accept itself succeeded (setting is persisted). A
                # background workers start failure is logged but does
                # NOT mask the successful accept.
                logger.exception(
                    "webview bridge accept_first_run_notice: background "
                    "workers start failed after successful accept"
                )
            try:
                app_api.start_collector()
            except Exception:
                # The accept itself succeeded (setting is persisted). A
                # collector start failure is logged but does NOT mask
                # the successful accept: the user can press the sidebar
                # toggle to retry start now that the gate is open.
                logger.exception(
                    "webview bridge accept_first_run_notice: collector "
                    "start failed after successful accept"
                )
            # Build the success payload. Try to refresh the status so
            # the frontend sidebar / overview can re-render; on failure
            # still return success without ``status``.
            payload: dict[str, Any] = {
                "ok": True,
                "accepted": True,
                "message": "已确认隐私说明",
            }
            try:
                status_result = self.get_status()
                if status_result.get("ok"):
                    payload["status"] = status_result
            except Exception:
                # Do not mask the successful accept with a status error.
                logger.exception(
                    "webview bridge accept_first_run_notice: status "
                    "refresh failed; returning success without status"
                )
            return payload
        except Exception:
            logger.exception("webview bridge accept_first_run_notice failed")
            return {"ok": False, "error": "确认隐私说明失败"}


    def get_settings_privacy_status(self) -> dict[str, Any]:
        """Return the read-only Settings / Privacy status snapshot.

        Only surfaces safety-status booleans. It does not save
        settings, toggle clipboard capture, export / import encrypted
        backups, parse the backup manifest, or clear local data. The
        payload never carries paths, database locations, backup file paths,
        tracebacks, SQL, raw exception text, window titles, file path
        hints, clipboard content, notes, or passphrases.

        Returns ``{"ok": True, "status": {...}}`` on success or
        ``{"ok": False, "error": "加载设置状态失败"}`` on failure. The
        ``settings_api`` facade already collapses its own exceptions; the
        bridge wraps the call so a transport-level error never leaks
        tracebacks either.
        """
        try:
            return settings_api.get_settings_privacy_status()
        except Exception:
            logger.exception("webview bridge get_settings_privacy_status failed")
            return {"ok": False, "error": "加载设置状态失败"}


    def set_clipboard_capture_enabled(self, enabled) -> dict[str, Any]:
        """Write the ``clipboard_capture_enabled`` flag from the WebView UI.

        ``enabled`` must be a real ``bool``; any other type (``None``,
        ``"true"`` / ``"false"`` strings, ``0`` / ``1`` ints, lists,
        dicts, objects) is rejected with a stable Chinese message and
        does NOT mutate the underlying setting.

        On success the bridge returns ``{"ok": True, "status": {...}}``
        where ``status`` is the updated Settings / Privacy status snapshot
        (the same shape returned by ``get_settings_privacy_status``). On
        failure it returns ``{"ok": False, "error": "<chinese>"}``.

        The payload never carries traceback, SQL, raw exception text,
        paths, clipboard content, or passphrases. This method does not
        open backup export / import / manifest, ``clear_all_local_data``,
        native file dialogs, or any schema mutation.
        """
        try:
            # Bridge-level strict bool guard mirrors the API facade so a
            # non-bool never reaches the backend. ``is`` (not
            # ``isinstance``) is the clearest "real bool only" check.
            if enabled is not True and enabled is not False:
                return {"ok": False, "error": "请选择有效的剪贴板记录状态"}
            result = settings_api.set_clipboard_capture_enabled_for_webview(enabled)
            if result.get("ok"):
                return {"ok": True, "status": result["status"]}
            # API returned a stable Chinese error; pass it through unchanged.
            return {"ok": False, "error": result.get("error") or "设置剪贴板记录失败"}
        except Exception:
            logger.exception("webview bridge set_clipboard_capture_enabled failed")
            return {"ok": False, "error": "设置剪贴板记录失败"}


    def export_encrypted_backup(self, passphrase, confirm_passphrase) -> dict[str, Any]:
        """Export an encrypted ``.wtbackup`` file from the WebView UI."""
        try:
            output_path = self._choose_backup_save_path()
            if output_path is None:
                # User cancelled the native save dialog. This is a clean
                # cancel result, not a Python exception or "操作失败".
                return {"ok": False, "error": "已取消导出"}
            result = settings_api.export_encrypted_backup_for_webview(
                output_path, passphrase, confirm_passphrase
            )
            if result.get("ok"):
                return {
                    "ok": True,
                    "filename": str(result.get("filename") or ""),
                    "message": str(result.get("message") or "加密备份已导出"),
                }
            # API returned a stable Chinese error; pass it through unchanged.
            return {"ok": False, "error": result.get("error") or "导出加密备份失败"}
        except Exception:
            logger.exception("webview bridge export_encrypted_backup failed")
            return {"ok": False, "error": "导出加密备份失败"}


    def preview_encrypted_backup_manifest(self) -> dict[str, Any]:
        """Preview the non-sensitive manifest of a ``.wtbackup`` file."""
        try:
            input_path = self._choose_backup_open_path()
            if input_path is None:
                # User cancelled the native open dialog. This is a clean
                # cancel result, not a Python exception or "操作失败".
                return {"ok": False, "error": "已取消读取备份清单"}
            result = settings_api.preview_encrypted_backup_manifest_for_webview(
                input_path
            )
            if result.get("ok"):
                return {
                    "ok": True,
                    "filename": str(result.get("filename") or ""),
                    "manifest": result.get("manifest") or {},
                }
            # API returned a stable Chinese error; pass it through unchanged.
            return {"ok": False, "error": result.get("error") or "读取备份清单失败"}
        except Exception:
            logger.exception("webview bridge preview_encrypted_backup_manifest failed")
            return {"ok": False, "error": "读取备份清单失败"}


    def import_encrypted_backup(self, passphrase, confirm_text) -> dict[str, Any]:
        """Import an encrypted ``.wtbackup`` file from the WebView UI."""
        try:
            input_path = self._choose_backup_open_path()
            if input_path is None:
                # User cancelled the native open dialog. This is a clean
                # cancel result, not a Python exception or "操作失败".
                return {"ok": False, "error": "已取消导入"}
            result = settings_api.import_encrypted_backup_for_webview(
                input_path, passphrase, confirm_text
            )
            if result.get("ok"):
                return {
                    "ok": True,
                    "message": str(result.get("message") or ""),
                    "imported_table_count": int(result.get("imported_table_count") or 0),
                    "imported_row_count": int(result.get("imported_row_count") or 0),
                    "folder_index_reset": bool(result.get("folder_index_reset")),
                }
            # API returned a stable Chinese error; pass it through unchanged.
            return {"ok": False, "error": result.get("error") or "导入加密备份失败"}
        except Exception:
            logger.exception("webview bridge import_encrypted_backup failed")
            return {"ok": False, "error": "导入加密备份失败"}


    def clear_all_local_data(self, confirm_text) -> dict[str, Any]:
        """Clear all local data from the WebView UI."""
        try:
            result = settings_api.clear_all_local_data_for_webview(confirm_text)
            if result.get("ok"):
                payload: dict[str, Any] = {
                    "ok": True,
                    "message": str(result.get("message") or "本地数据已清空"),
                }
                if "status" in result:
                    payload["status"] = result["status"]
                return payload
            # API returned a stable Chinese error; pass it through unchanged.
            return {"ok": False, "error": result.get("error") or "清空本地数据失败"}
        except Exception:
            logger.exception("webview bridge clear_all_local_data failed")
            return {"ok": False, "error": "清空本地数据失败"}


__all__ = ["SettingsBridgeMixin"]
