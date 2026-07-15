"""Settings / Privacy bridge mixin.

This module stays on the API side of the WebView boundary and never imports
services, runtime internals, database code, or sensitive data structures.
"""

from __future__ import annotations

import logging
from typing import Any

from ..api import app_api, settings_api

logger = logging.getLogger(__name__)


class SettingsBridgeMixin:
    """Settings / Privacy bridge methods."""

    def get_first_run_notice(self) -> dict[str, Any]:
        try:
            return settings_api.get_first_run_notice_for_webview()
        except Exception:
            logger.exception("webview bridge get_first_run_notice failed")
            return {"ok": False, "error": "加载隐私说明失败"}

    def accept_first_run_notice(self) -> dict[str, Any]:
        """Accept the notice and report collector startup separately."""
        try:
            result = settings_api.accept_first_run_notice_for_webview()
            if not result.get("ok"):
                return result
            try:
                start_result = app_api.start_collection_after_privacy_gate()
            except Exception:
                logger.exception(
                    "webview bridge accept_first_run_notice: collector start raised"
                )
                start_result = {
                    "ok": False,
                    "error": "collector_start_failed",
                }
            if not start_result.get("ok"):
                return {
                    "ok": False,
                    "accepted": True,
                    "error": "隐私说明已确认，但记录功能未能启动，请点击恢复记录重试",
                }

            payload: dict[str, Any] = {
                "ok": True,
                "accepted": True,
                "message": "已确认隐私说明",
                "background_worker_degraded": bool(
                    start_result.get("background_worker_degraded")
                ),
            }
            try:
                status_result = self.get_status()
                if status_result.get("ok"):
                    payload["status"] = status_result
            except Exception:
                logger.exception(
                    "webview bridge accept_first_run_notice: status refresh failed"
                )
            return payload
        except Exception:
            logger.exception("webview bridge accept_first_run_notice failed")
            return {"ok": False, "error": "确认隐私说明失败"}

    def get_settings_privacy_status(self) -> dict[str, Any]:
        try:
            return settings_api.get_settings_privacy_status()
        except Exception:
            logger.exception("webview bridge get_settings_privacy_status failed")
            return {"ok": False, "error": "加载设置状态失败"}

    def set_clipboard_capture_enabled(self, enabled) -> dict[str, Any]:
        """Apply a clipboard toggle to runtime and persisted settings atomically."""
        try:
            if enabled is not True and enabled is not False:
                return {"ok": False, "error": "请选择有效的剪贴板记录状态"}
            if enabled and not settings_api.first_run_notice_accepted():
                return {"ok": False, "error": "请先确认隐私说明"}
            previous = bool(settings_api.is_clipboard_capture_enabled())
            app_api.set_clipboard_capture_enabled(enabled)
            result = settings_api.set_clipboard_capture_enabled_for_webview(enabled)
            if result.get("ok"):
                return {"ok": True, "status": result["status"]}
            app_api.set_clipboard_capture_enabled(previous)
            return {
                "ok": False,
                "error": result.get("error") or "设置剪贴板记录失败",
            }
        except Exception:
            logger.exception("webview bridge set_clipboard_capture_enabled failed")
            try:
                app_api.set_clipboard_capture_enabled(False)
            except Exception:
                logger.exception("clipboard fail-closed rollback failed")
            return {"ok": False, "error": "设置剪贴板记录失败"}

    def export_encrypted_backup(
        self,
        passphrase,
        confirm_passphrase,
    ) -> dict[str, Any]:
        try:
            output_path = self._choose_backup_save_path()
            if output_path is None:
                return {"ok": False, "error": "已取消导出"}
            result = settings_api.export_encrypted_backup_for_webview(
                output_path,
                passphrase,
                confirm_passphrase,
            )
            if result.get("ok"):
                return {
                    "ok": True,
                    "filename": str(result.get("filename") or ""),
                    "message": str(result.get("message") or "加密备份已导出"),
                }
            return {
                "ok": False,
                "error": result.get("error") or "导出加密备份失败",
            }
        except Exception:
            logger.exception("webview bridge export_encrypted_backup failed")
            return {"ok": False, "error": "导出加密备份失败"}

    def preview_encrypted_backup_manifest(self) -> dict[str, Any]:
        try:
            input_path = self._choose_backup_open_path()
            if input_path is None:
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
            return {
                "ok": False,
                "error": result.get("error") or "读取备份清单失败",
            }
        except Exception:
            logger.exception("webview bridge preview_encrypted_backup_manifest failed")
            return {"ok": False, "error": "读取备份清单失败"}

    def import_encrypted_backup(
        self,
        passphrase,
        confirm_text,
    ) -> dict[str, Any]:
        try:
            input_path = self._choose_backup_open_path()
            if input_path is None:
                return {"ok": False, "error": "已取消导入"}
            result = settings_api.import_encrypted_backup_for_webview(
                input_path,
                passphrase,
                confirm_text,
            )
            if result.get("ok"):
                return {
                    "ok": True,
                    "message": str(result.get("message") or ""),
                    "imported_table_count": int(
                        result.get("imported_table_count") or 0
                    ),
                    "imported_row_count": int(
                        result.get("imported_row_count") or 0
                    ),
                    "folder_index_reset": bool(
                        result.get("folder_index_reset")
                    ),
                }
            return {
                "ok": False,
                "error": result.get("error") or "导入加密备份失败",
            }
        except Exception:
            logger.exception("webview bridge import_encrypted_backup failed")
            return {"ok": False, "error": "导入加密备份失败"}

    def clear_all_local_data(self, confirm_text) -> dict[str, Any]:
        try:
            result = settings_api.clear_all_local_data_for_webview(confirm_text)
            if result.get("ok"):
                payload: dict[str, Any] = {
                    "ok": True,
                    "message": str(
                        result.get("message") or "本地数据已清空"
                    ),
                }
                if "status" in result:
                    payload["status"] = result["status"]
                return payload
            return {
                "ok": False,
                "error": result.get("error") or "清空本地数据失败",
            }
        except Exception:
            logger.exception("webview bridge clear_all_local_data failed")
            return {"ok": False, "error": "清空本地数据失败"}


__all__ = ["SettingsBridgeMixin"]
