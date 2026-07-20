"""Named Settings, Privacy, and local-data capabilities for the UI."""

from __future__ import annotations

import os
from typing import Any

from ..constants import PRIVACY_NOTICE_TEXT
from ..services import (
    database_maintenance_service,
    export_service,
    privacy_gate_service,
)
from ..services.secure_backup_service import (
    BackupCorruptedError,
    BackupDecryptionError,
    BackupImportInProgressError,
    BackupVersionNotSupportedError,
    SecureBackupError,
)
from ..services.settings_service import (
    get_bool_setting,
    get_int_setting,
    get_setting,
    set_setting,
)
from ..write_gate import DATABASE_RECOVERY_ERROR
from . import backup_api


def first_run_notice_accepted() -> bool:
    return privacy_gate_service.is_privacy_notice_accepted()


def accept_first_run_notice() -> None:
    privacy_gate_service.accept_privacy_notice()


def is_user_paused() -> bool:
    return get_bool_setting("user_paused", False)


def set_user_paused(value: bool) -> None:
    set_setting("user_paused", "true" if value else "false")


def get_collector_status() -> str:
    return get_setting("collector_status", "stopped") or "stopped"


def get_collector_health_state() -> str:
    return get_setting("collector_health_state", "stopped") or "stopped"


def get_collector_last_successful_observation_at() -> str:
    return get_setting("collector_last_successful_observation_at", "") or ""


def get_collector_last_failure_code() -> str:
    return get_setting("collector_last_failure_kind", "") or ""


def get_collector_consecutive_failures() -> int:
    return get_int_setting("collector_consecutive_failures", 0)


def set_collector_status(value: str) -> None:
    set_setting("collector_status", value)


def is_paused() -> bool:
    return is_user_paused() or get_collector_status() == "paused"


def get_export_path() -> str:
    return get_setting("export_path", "") or ""


def get_ui_refresh_seconds() -> int:
    return get_int_setting("ui_refresh_seconds", 10)


def is_clipboard_capture_enabled() -> bool:
    return get_bool_setting("clipboard_capture_enabled", False)


def set_clipboard_capture_enabled(value: bool) -> None:
    set_setting("clipboard_capture_enabled", "true" if value else "false")


def clear_all_local_data(confirm: bool) -> None:
    export_service.clear_all_local_data(confirm=confirm)


def _maintenance_status() -> dict[str, object]:
    return database_maintenance_service.maintenance_status().to_dict()


def get_settings_privacy_status() -> dict[str, Any]:
    try:
        notice_accepted = first_run_notice_accepted()
        maintenance = _maintenance_status()
        return {
            "ok": True,
            "status": {
                "page": "settings_privacy",
                "storage_model": "local_only",
                "clipboard_capture_enabled": is_clipboard_capture_enabled(),
                "export_path_configured": bool(get_export_path()),
                **maintenance,
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
            },
        }
    except Exception:
        return {"ok": False, "error": "加载设置状态失败"}


def recover_database_maintenance_for_webview() -> dict[str, Any]:
    """Run the sole explicit fail-closed recovery protocol for the UI."""

    before = _maintenance_status()
    if not bool(before.get("recovery_blocked")):
        return {
            "ok": True,
            "message": "当前无需维护恢复",
            "maintenance": before,
        }
    try:
        database_maintenance_service.recover_fail_closed()
    except database_maintenance_service.MaintenanceRecoveryError as exc:
        return {
            "ok": False,
            "error": str(exc) or DATABASE_RECOVERY_ERROR,
            "maintenance": _maintenance_status(),
        }
    except Exception:
        return {
            "ok": False,
            "error": DATABASE_RECOVERY_ERROR,
            "maintenance": _maintenance_status(),
        }
    status = _maintenance_status()
    if not bool(status.get("maintenance_restored")):
        return {
            "ok": False,
            "error": DATABASE_RECOVERY_ERROR,
            "maintenance": status,
        }
    return {
        "ok": True,
        "message": "维护恢复已确认",
        "maintenance": status,
    }


def export_encrypted_backup_for_webview(
    output_path: str,
    passphrase: str,
    confirm_passphrase: str,
) -> dict[str, Any]:
    if not isinstance(output_path, str) or not output_path.strip():
        return {"ok": False, "error": "请选择有效的备份保存位置"}
    if not isinstance(passphrase, str) or not passphrase.strip():
        return {"ok": False, "error": "请输入备份口令"}
    if not isinstance(confirm_passphrase, str) or confirm_passphrase != passphrase:
        return {"ok": False, "error": "两次输入的备份口令不一致"}
    normalized_path = output_path
    if not normalized_path.lower().endswith(".wtbackup"):
        normalized_path += ".wtbackup"
    try:
        backup_api.export_encrypted_backup(normalized_path, passphrase)
    except Exception:
        return {"ok": False, "error": "导出加密备份失败"}
    return {
        "ok": True,
        "filename": os.path.basename(normalized_path),
        "message": "加密备份已导出",
        "maintenance": _maintenance_status(),
    }


def preview_encrypted_backup_manifest_for_webview(
    input_path: str,
) -> dict[str, Any]:
    if (
        not isinstance(input_path, str)
        or not input_path.strip()
        or not input_path.lower().endswith(".wtbackup")
    ):
        return {"ok": False, "error": "请选择有效的加密备份文件"}
    try:
        info = backup_api.parse_encrypted_backup_manifest(input_path)
    except Exception:
        return {"ok": False, "error": "读取备份清单失败"}
    return {
        "ok": True,
        "filename": os.path.basename(input_path),
        "manifest": {
            "version": int(info.version),
            "app_version": str(info.app_version),
            "created_at": str(info.created_at),
            "kdf_algorithm": str(info.kdf_algorithm),
            "payload_format": str(info.payload_format),
            "payload_alg": str(info.payload_alg),
        },
    }


def _maintenance_result_message(status: dict[str, object]) -> str:
    if not bool(status.get("maintenance_restored")):
        return "操作已完成，但维护恢复失败，当前保持阻断"
    if bool(status.get("user_paused")):
        return "操作已完成；因用户此前已暂停，当前保持暂停"
    if bool(status.get("collector_running")):
        return "操作已完成，记录状态已恢复"
    if str(status.get("collector_status") or "") == "stopped":
        return "操作已完成；当前未运行记录功能"
    return "操作已完成，运行状态已按维护前状态恢复"


def import_encrypted_backup_for_webview(
    input_path: str,
    passphrase: str,
    confirm_text: str,
) -> dict[str, Any]:
    if (
        not isinstance(input_path, str)
        or not input_path.strip()
        or not input_path.lower().endswith(".wtbackup")
    ):
        return {"ok": False, "error": "请选择有效的加密备份文件"}
    if not isinstance(passphrase, str) or not passphrase.strip():
        return {"ok": False, "error": "请输入备份口令"}
    if not isinstance(confirm_text, str) or confirm_text.strip() != "导入并替换":
        return {"ok": False, "error": "请输入确认文字：导入并替换"}
    try:
        result = backup_api.import_encrypted_backup(
            input_path,
            passphrase,
            mode="replace",
        )
    except BackupImportInProgressError:
        return {"ok": False, "error": "已有数据库维护操作正在进行"}
    except (BackupDecryptionError, BackupCorruptedError):
        return {"ok": False, "error": "备份口令错误或文件已损坏"}
    except BackupVersionNotSupportedError:
        return {"ok": False, "error": "备份文件版本不受支持"}
    except (SecureBackupError, RuntimeError):
        return {"ok": False, "error": "导入加密备份失败"}
    except Exception:
        return {"ok": False, "error": "导入加密备份失败"}
    imported_tables = result.imported_tables or {}
    status = dict(result.maintenance_status or _maintenance_status())
    return {
        "ok": True,
        "message": _maintenance_result_message(status),
        "imported_table_count": len(imported_tables),
        "imported_row_count": sum(imported_tables.values()),
        "folder_index_reset": bool(result.folder_index_reset),
        "maintenance": status,
    }


def clear_all_local_data_for_webview(confirm_text: str) -> dict[str, Any]:
    if not isinstance(confirm_text, str) or confirm_text.strip() != "清空本地数据":
        return {"ok": False, "error": "请输入确认文字：清空本地数据"}
    try:
        export_service.clear_all_local_data(confirm=True)
    except Exception:
        return {"ok": False, "error": "清空本地数据失败"}
    status = _maintenance_status()
    result: dict[str, Any] = {
        "ok": True,
        "message": _maintenance_result_message(status),
        "maintenance": status,
    }
    status_result = get_settings_privacy_status()
    if status_result.get("ok"):
        result["status"] = status_result["status"]
    return result


def set_clipboard_capture_enabled_for_webview(enabled: bool) -> dict[str, Any]:
    if enabled is not True and enabled is not False:
        return {"ok": False, "error": "请选择有效的剪贴板记录状态"}
    try:
        set_clipboard_capture_enabled(enabled)
        status_result = get_settings_privacy_status()
        if not status_result.get("ok"):
            return {"ok": False, "error": "设置剪贴板记录失败"}
        return {"ok": True, "status": status_result["status"]}
    except Exception:
        return {"ok": False, "error": "设置剪贴板记录失败"}


_FIRST_RUN_NOTICE_HIGHLIGHTS = [
    "本地保存",
    "不截屏录屏",
    "不主动读正文",
    "用户可清空",
]
_FIRST_RUN_NOTICE_TITLE = "WorkTrace 隐私说明"


def get_first_run_notice_for_webview() -> dict[str, Any]:
    try:
        accepted = first_run_notice_accepted()
    except Exception:
        return {
            "ok": False,
            "error": "隐私说明加载失败。为保护隐私，WorkTrace 暂不会启动记录。请重启应用或重新安装。",
        }
    return {
        "ok": True,
        "notice": {
            "title": _FIRST_RUN_NOTICE_TITLE,
            "text": PRIVACY_NOTICE_TEXT,
            "highlights": list(_FIRST_RUN_NOTICE_HIGHLIGHTS),
            "accepted": accepted,
            "accept_required": not accepted,
        },
    }


def accept_first_run_notice_for_webview() -> dict[str, Any]:
    try:
        accept_first_run_notice()
    except Exception:
        return {"ok": False, "error": "确认隐私说明失败"}
    return {"ok": True, "accepted": True}


__all__ = [
    "accept_first_run_notice",
    "accept_first_run_notice_for_webview",
    "clear_all_local_data",
    "clear_all_local_data_for_webview",
    "export_encrypted_backup_for_webview",
    "first_run_notice_accepted",
    "get_collector_consecutive_failures",
    "get_collector_health_state",
    "get_collector_last_failure_code",
    "get_collector_last_successful_observation_at",
    "get_collector_status",
    "get_export_path",
    "get_first_run_notice_for_webview",
    "get_settings_privacy_status",
    "get_ui_refresh_seconds",
    "import_encrypted_backup_for_webview",
    "is_clipboard_capture_enabled",
    "is_paused",
    "is_user_paused",
    "preview_encrypted_backup_manifest_for_webview",
    "recover_database_maintenance_for_webview",
    "set_clipboard_capture_enabled",
    "set_clipboard_capture_enabled_for_webview",
    "set_collector_status",
    "set_user_paused",
]
