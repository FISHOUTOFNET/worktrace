"""Settings / Privacy bridge mixin."""
from __future__ import annotations

import logging
from typing import Any

from ..api import settings_api

logger = logging.getLogger(__name__)


class SettingsBridgeMixin:
    def get_first_run_notice(self) -> dict[str, Any]:
        try:
            return settings_api.get_first_run_notice_for_webview()
        except Exception:
            logger.exception("webview bridge get_first_run_notice failed")
            return {"ok": False, "error": "加载隐私说明失败"}

    def accept_first_run_notice(self) -> dict[str, Any]:
        try:
            return self._app_control.accept_privacy_notice_and_start()
        except Exception:
            logger.exception("webview bridge accept_first_run_notice failed")
            return {"ok": False, "error": "确认隐私说明失败"}

    def get_settings_privacy_status(self) -> dict[str, Any]:
        try:
            return settings_api.get_settings_privacy_status()
        except Exception:
            logger.exception("webview bridge get_settings_privacy_status failed")
            return {"ok": False, "error": "加载设置状态失败"}

    def recover_database_maintenance(self) -> dict[str, Any]:
        try:
            return settings_api.recover_database_maintenance_for_webview()
        except Exception:
            logger.exception("webview bridge recover_database_maintenance failed")
            return {
                "ok": False,
                "error": "database_maintenance_recovery_required",
            }

    def set_clipboard_capture_enabled(self, enabled) -> dict[str, Any]:
        try:
            return self._app_control.set_clipboard_capture_policy(enabled)
        except Exception:
            logger.exception("webview bridge set_clipboard_capture_enabled failed")
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
                    "maintenance": dict(result.get("maintenance") or {}),
                }
            return {"ok": False, "error": result.get("error") or "导出加密备份失败"}
        except Exception:
            logger.exception("webview bridge export_encrypted_backup failed")
            return {"ok": False, "error": "导出加密备份失败"}

    def preview_encrypted_backup_manifest(self) -> dict[str, Any]:
        try:
            input_path = self._choose_backup_open_path()
            if input_path is None:
                return {"ok": False, "error": "已取消读取备份清单"}
            result = settings_api.preview_encrypted_backup_manifest_for_webview(input_path)
            if result.get("ok"):
                return {
                    "ok": True,
                    "filename": str(result.get("filename") or ""),
                    "manifest": result.get("manifest") or {},
                }
            return {"ok": False, "error": result.get("error") or "读取备份清单失败"}
        except Exception:
            logger.exception("webview bridge preview_encrypted_backup_manifest failed")
            return {"ok": False, "error": "读取备份清单失败"}

    def import_encrypted_backup(self, passphrase, confirm_text) -> dict[str, Any]:
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
                    "imported_table_count": int(result.get("imported_table_count") or 0),
                    "imported_row_count": int(result.get("imported_row_count") or 0),
                    "folder_index_reset": bool(result.get("folder_index_reset")),
                    "maintenance": dict(result.get("maintenance") or {}),
                }
            return {"ok": False, "error": result.get("error") or "导入加密备份失败"}
        except Exception:
            logger.exception("webview bridge import_encrypted_backup failed")
            return {"ok": False, "error": "导入加密备份失败"}

    def clear_all_local_data(self, confirm_text) -> dict[str, Any]:
        try:
            result = settings_api.clear_all_local_data_for_webview(confirm_text)
            if result.get("ok"):
                payload: dict[str, Any] = {
                    "ok": True,
                    "message": str(result.get("message") or "本地数据已清空"),
                    "maintenance": dict(result.get("maintenance") or {}),
                }
                if "status" in result:
                    payload["status"] = result["status"]
                return payload
            return {"ok": False, "error": result.get("error") or "清空本地数据失败"}
        except Exception:
            logger.exception("webview bridge clear_all_local_data failed")
            return {"ok": False, "error": "清空本地数据失败"}


__all__ = ["SettingsBridgeMixin"]
