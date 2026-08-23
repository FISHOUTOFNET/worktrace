"""Settings / Privacy bridge mixin."""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class SettingsBridgeMixin:
    def get_first_run_notice(self) -> dict[str, Any]:
        try:
            return self._services.settings.get_first_run_notice_for_webview()
        except Exception:
            logger.exception("webview bridge get_first_run_notice failed")
            return {"ok": False, "error": "加载隐私说明失败"}

    def accept_first_run_notice(self) -> dict[str, Any]:
        try:
            return self._app_control.accept_privacy_notice_and_start()
        except Exception:
            logger.exception("webview bridge accept_first_run_notice failed")
            return {
                "ok": False,
                "accepted": False,
                "collector_started": False,
                "collector_status": None,
                "error_code": "privacy_accept_failed",
                "message": "确认隐私说明失败",
            }

    def _authoritative_settings_status(self) -> dict[str, Any] | None:
        result = self._services.settings.get_settings_privacy_status()
        if result.get("ok") is not True:
            return None
        status = dict(result.get("status") or {})
        status["fd_work"] = self._services.fd_work.get_settings_status()
        return status

    def _with_authoritative_settings_status(
        self,
        result: dict[str, Any],
        *,
        required_on_success: bool = False,
        include_on_failure: bool = False,
        refresh_error: str = "加载设置状态失败",
    ) -> dict[str, Any]:
        payload = dict(result or {})
        payload.pop("status", None)
        if payload.get("ok") is not True and not include_on_failure:
            return payload
        status = self._authoritative_settings_status()
        if status is not None:
            payload["status"] = status
            return payload
        if required_on_success and payload.get("ok") is True:
            return {"ok": False, "error": refresh_error}
        return payload

    def get_settings_privacy_status(self) -> dict[str, Any]:
        try:
            status = self._authoritative_settings_status()
            if status is None:
                return {"ok": False, "error": "加载设置状态失败"}
            return {"ok": True, "status": status}
        except Exception:
            logger.exception("webview bridge get_settings_privacy_status failed")
            return {"ok": False, "error": "加载设置状态失败"}

    def recover_database_maintenance(self) -> dict[str, Any]:
        try:
            result = dict(
                self._services.settings.recover_database_maintenance_for_webview()
            )
            if result.get("ok") is not True:
                result.pop("maintenance", None)
                result.pop("status", None)
                return result
            return self._with_authoritative_settings_status(result)
        except Exception:
            logger.exception("webview bridge recover_database_maintenance failed")
            return {
                "ok": False,
                "error_code": "database_maintenance_recovery_required",
                "message": "数据库维护恢复失败，请稍后重试或联系支持。",
            }

    def set_clipboard_capture_enabled(self, enabled) -> dict[str, Any]:
        try:
            result = self._app_control.set_clipboard_capture_policy(enabled)
            return self._with_authoritative_settings_status(
                result,
                required_on_success=True,
                refresh_error="设置剪贴板记录状态刷新失败",
            )
        except Exception:
            logger.exception("webview bridge set_clipboard_capture_enabled failed")
            return {"ok": False, "error": "设置剪贴板记录失败"}

    def set_launch_at_login(self, enabled) -> dict[str, Any]:
        try:
            result = self._services.settings.set_launch_at_login(enabled)
            return self._with_authoritative_settings_status(
                result,
                required_on_success=True,
                include_on_failure=True,
                refresh_error="设置登录启动状态刷新失败",
            )
        except Exception:
            logger.exception("webview bridge set_launch_at_login failed")
            return {"ok": False, "error": "设置登录启动失败"}

    def set_fd_work_enabled(self, enabled) -> dict[str, Any]:
        if enabled is not True and enabled is not False:
            return {
                "ok": False,
                "error": "请选择有效的 FD Work 插件状态",
                "status": self.get_settings_privacy_status().get("status"),
            }
        try:
            self._services.fd_work.set_enabled(enabled)
            status = self.get_settings_privacy_status().get("status")
            actual = bool(
                isinstance(status, dict)
                and isinstance(status.get("fd_work"), dict)
                and status["fd_work"].get("enabled") is True
            )
            if actual is not enabled:
                return {
                    "ok": False,
                    "error": "FD Work 插件状态未能保存",
                    "status": status,
                }
            return {"ok": True, "status": status}
        except Exception:
            logger.exception("webview bridge set_fd_work_enabled failed")
            status = self.get_settings_privacy_status()
            return {
                "ok": False,
                "error": "设置 FD Work 插件失败",
                "status": status.get("status"),
            }

    def export_encrypted_backup(
        self,
        passphrase,
        confirm_passphrase,
    ) -> dict[str, Any]:
        try:
            output_path = self._choose_backup_save_path()
            if output_path is None:
                return {"ok": False, "error": "已取消导出"}
            result = self._services.backup.export_encrypted_backup_for_webview(
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
            result = self._services.backup.preview_encrypted_backup_manifest_for_webview(input_path)
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
            result = self._services.backup.import_encrypted_backup_for_webview(
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
            result = self._services.settings.clear_all_local_data_for_webview(confirm_text)
            if result.get("ok"):
                payload: dict[str, Any] = {
                    "ok": True,
                    "message": str(result.get("message") or "本地数据已清空"),
                    "maintenance": dict(result.get("maintenance") or {}),
                }
                return self._with_authoritative_settings_status(payload)
            return {"ok": False, "error": result.get("error") or "清空本地数据失败"}
        except Exception:
            logger.exception("webview bridge clear_all_local_data failed")
            return {"ok": False, "error": "清空本地数据失败"}


__all__ = ["SettingsBridgeMixin"]
