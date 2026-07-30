"""Typed grouped capability protocols and concrete adapters for the bridge.

Bridge mixins consume these capabilities through ``ApplicationServices`` so
they no longer reach for module-global API facade functions directly.
"""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable, TYPE_CHECKING

from ..platforms.windows_startup import WindowsStartupRegistration

from . import (
    export_api,
    project_api,
    rule_api,
    rule_history_api,
    settings_api,
    statistics_api,
    timeline_api,
    view_model_api,
)

if TYPE_CHECKING:
    from .app_api import ApplicationRuntimeCapability


@runtime_checkable
class OverviewCapability(Protocol):
    def get_overview_view_model(self, *, runtime, collector_status) -> dict[str, Any]: ...
    def get_refresh_state_view_model(self, report_date, *, runtime, collector_status) -> dict[str, Any]: ...


@runtime_checkable
class SettingsCapability(Protocol):
    def get_first_run_notice_for_webview(self) -> dict[str, Any]: ...
    def get_settings_privacy_status(self) -> dict[str, Any]: ...
    def recover_database_maintenance_for_webview(self) -> dict[str, Any]: ...
    def clear_all_local_data_for_webview(self, confirm_text) -> dict[str, Any]: ...
    def set_launch_at_login(self, enabled) -> dict[str, Any]: ...


@runtime_checkable
class BackupCapability(Protocol):
    def export_encrypted_backup_for_webview(self, output_path, passphrase, confirm_passphrase) -> dict[str, Any]: ...
    def preview_encrypted_backup_manifest_for_webview(self, input_path) -> dict[str, Any]: ...
    def import_encrypted_backup_for_webview(self, input_path, passphrase, confirm_text) -> dict[str, Any]: ...


@runtime_checkable
class StatisticsCapability(Protocol):
    StatisticsSummaryError: type
    StatisticsExportError: type
    def get_statistics_export_view_model(self, date_from, date_to, project_id=None) -> dict[str, Any]: ...
    def format_export_duration(self, duration_seconds) -> str: ...
    def export_statistics_csv(self, date_from, date_to, output_path, expected_export_ticket_revision, project_id=None) -> dict[str, Any]: ...


@runtime_checkable
class TimelineCapability(Protocol):
    TIMELINE_NOTE_MAX_LENGTH: int
    def get_timeline_view_model(self, date, *, runtime, collector_status) -> dict[str, Any]: ...
    def get_session_activity_summary_view_model(self, *, report_date, projection_instance_key, expected_projection_revision, expected_source_version, runtime, collector_status) -> dict[str, Any]: ...
    def list_selectable_projects(self) -> list[dict[str, Any]]: ...
    def list_filter_projects(self) -> list[dict[str, Any]]: ...
    def save_timeline_session_edit(self, report_date, projection_instance_key, projection_revision, request_id, project_id, adjusted_duration_seconds, note) -> dict[str, Any]: ...
    def hide_timeline_session(self, report_date, projection_instance_key, projection_revision, request_id) -> dict[str, Any]: ...
    def merge_timeline_session(self, report_date, projection_instance_key, direction, projection_revision, request_id, target_projection_instance_key, target_projection_revision) -> dict[str, Any]: ...
    def split_timeline_session(self, report_date, projection_instance_key, projection_revision, request_id) -> dict[str, Any]: ...
    def copy_timeline_session(self, report_date, projection_instance_key, projection_revision, request_id) -> dict[str, Any]: ...
    def hide_timeline_session_activity(self, report_date, projection_instance_key, summary_id, projection_revision, request_id) -> dict[str, Any]: ...


@runtime_checkable
class FDWorkCapability(Protocol):
    def open_entry(
        self,
        report_date,
        projection_instance_key,
        expected_projection_revision,
        expected_source_version,
    ) -> dict[str, Any]: ...


@runtime_checkable
class RulesCapability(Protocol):
    def list_project_bindings(self) -> list[dict[str, Any]]: ...
    def create_project_for_rules(self, name, description, language) -> dict[str, Any]: ...
    def update_project_for_rules(self, project_id, name, description, language) -> dict[str, Any]: ...
    def set_project_enabled_for_rules(self, project_id, enabled) -> dict[str, Any]: ...
    def set_excluded_rules_enabled(self, enabled) -> dict[str, Any]: ...
    def archive_project_for_rules(self, project_id) -> dict[str, Any]: ...
    def delete_project_for_rules(self, project_id) -> dict[str, Any]: ...
    def set_project_rule_enabled(self, rule_type, rule_id, enabled) -> dict[str, Any]: ...
    def create_project_keyword_rule(self, project_id, keyword) -> dict[str, Any]: ...
    def delete_project_keyword_rule(self, rule_id, apply_to_history) -> dict[str, Any]: ...
    def update_project_keyword_rule(self, rule_id, keyword) -> dict[str, Any]: ...
    def create_project_folder_rule(self, project_id, folder_path, recursive) -> dict[str, Any]: ...
    def create_excluded_keyword_rule_for_webview(self, keyword) -> dict[str, Any]: ...
    def create_excluded_folder_rule_for_webview(self, folder_path, recursive) -> dict[str, Any]: ...
    def update_project_folder_rule(self, rule_id, folder_path, recursive) -> dict[str, Any]: ...
    def delete_project_folder_rule(self, rule_id, apply_to_history) -> dict[str, Any]: ...
    def preview_project_rule_impact(self, rule_type, rule_id) -> dict[str, Any]: ...
    def backfill_project_rule(self, rule_type, rule_id) -> dict[str, Any]: ...
    def preview_project_rules_batch_impact(self, rules) -> dict[str, Any]: ...
    def backfill_project_rules_batch(self, rules) -> dict[str, Any]: ...
    def set_project_rules_batch_enabled(self, rules, enabled) -> dict[str, Any]: ...
    def automatic_rules_status(self) -> dict[str, Any]: ...


class OverviewApplicationService:
    """Concrete overview capability delegating to view_model_api."""

    def get_overview_view_model(self, *, runtime, collector_status):
        return view_model_api.get_overview_view_model(
            runtime=runtime, collector_status=collector_status
        )

    def get_refresh_state_view_model(self, report_date, *, runtime, collector_status):
        return view_model_api.get_refresh_state_view_model(
            report_date, runtime=runtime, collector_status=collector_status
        )


class SettingsApplicationService:
    """Concrete settings capability delegating to settings_api."""

    def __init__(
        self,
        startup_registration: WindowsStartupRegistration | None = None,
    ) -> None:
        self._startup_registration = (
            startup_registration
            if startup_registration is not None
            else WindowsStartupRegistration()
        )

    def get_first_run_notice_for_webview(self):
        return settings_api.get_first_run_notice_for_webview()

    def get_settings_privacy_status(self):
        result = settings_api.get_settings_privacy_status()
        if result.get("ok") is not True:
            return result
        status = dict(result["status"])
        status["launch_at_login"] = self._launch_at_login_status()
        return {"ok": True, "status": status}

    def recover_database_maintenance_for_webview(self):
        return settings_api.recover_database_maintenance_for_webview()

    def clear_all_local_data_for_webview(self, confirm_text):
        return settings_api.clear_all_local_data_for_webview(confirm_text)

    def set_launch_at_login(self, enabled):
        if enabled is not True and enabled is not False:
            return {
                "ok": False,
                "error": "请选择有效的登录启动状态",
                "status": self.get_settings_privacy_status().get("status"),
            }
        if not self._startup_registration.supported:
            return {
                "ok": False,
                "error": "当前平台不支持登录启动设置",
                "status": self.get_settings_privacy_status().get("status"),
            }
        error = None
        try:
            if enabled:
                self._startup_registration.enable()
            else:
                self._startup_registration.disable()
        except Exception:
            error = "设置登录启动失败"
        status_result = self.get_settings_privacy_status()
        status = status_result.get("status")
        actual = bool(
            isinstance(status, dict)
            and isinstance(status.get("launch_at_login"), dict)
            and status["launch_at_login"].get("enabled") is True
        )
        if error is not None or actual is not enabled:
            return {
                "ok": False,
                "error": error or "登录启动状态未能保存",
                "status": status,
            }
        return {"ok": True, "status": status}

    def _launch_at_login_status(self) -> dict[str, bool]:
        supported = self._startup_registration.supported
        return {
            "supported": supported,
            "enabled": (
                self._startup_registration.is_configured() if supported else False
            ),
        }


class BackupApplicationService:
    """Concrete backup capability delegating to settings_api backup functions."""

    def export_encrypted_backup_for_webview(self, output_path, passphrase, confirm_passphrase):
        return settings_api.export_encrypted_backup_for_webview(
            output_path, passphrase, confirm_passphrase
        )

    def preview_encrypted_backup_manifest_for_webview(self, input_path):
        return settings_api.preview_encrypted_backup_manifest_for_webview(input_path)

    def import_encrypted_backup_for_webview(self, input_path, passphrase, confirm_text):
        return settings_api.import_encrypted_backup_for_webview(
            input_path, passphrase, confirm_text
        )


class StatisticsApplicationService:
    """Concrete statistics capability delegating to statistics_api and export_api."""

    StatisticsSummaryError = statistics_api.StatisticsSummaryError
    StatisticsExportError = export_api.StatisticsExportError

    def get_statistics_export_view_model(self, date_from, date_to, project_id=None):
        return statistics_api.get_statistics_export_view_model(date_from, date_to, project_id)

    def format_export_duration(self, duration_seconds):
        return statistics_api.format_export_duration(duration_seconds)

    def export_statistics_csv(self, date_from, date_to, output_path, expected_export_ticket_revision, project_id=None):
        return export_api.export_statistics_csv(
            date_from, date_to, output_path, expected_export_ticket_revision, project_id
        )


class TimelineApplicationService:
    """Concrete timeline capability delegating to timeline_api, project_api, view_model_api."""

    TIMELINE_NOTE_MAX_LENGTH = timeline_api.TIMELINE_NOTE_MAX_LENGTH

    def get_timeline_view_model(self, date, *, runtime, collector_status):
        return view_model_api.get_timeline_view_model(
            date, runtime=runtime, collector_status=collector_status
        )

    def get_session_activity_summary_view_model(
        self,
        *,
        report_date,
        projection_instance_key,
        expected_projection_revision,
        expected_source_version,
        runtime,
        collector_status,
    ):
        return view_model_api.get_session_activity_summary_view_model(
            report_date=report_date,
            projection_instance_key=projection_instance_key,
            expected_projection_revision=expected_projection_revision,
            expected_source_version=expected_source_version,
            runtime=runtime,
            collector_status=collector_status,
        )

    def list_selectable_projects(self):
        return project_api.list_selectable_projects()

    def list_filter_projects(self):
        return timeline_api.list_filter_projects()

    def save_timeline_session_edit(
        self,
        report_date,
        projection_instance_key,
        projection_revision,
        request_id,
        project_id,
        adjusted_duration_seconds,
        note,
    ):
        return timeline_api.save_timeline_session_edit(
            report_date,
            projection_instance_key,
            projection_revision,
            request_id,
            project_id,
            adjusted_duration_seconds,
            note,
        )

    def hide_timeline_session(
        self, report_date, projection_instance_key, projection_revision, request_id
    ):
        return timeline_api.hide_timeline_session(
            report_date, projection_instance_key, projection_revision, request_id
        )

    def merge_timeline_session(
        self,
        report_date,
        projection_instance_key,
        direction,
        projection_revision,
        request_id,
        target_projection_instance_key,
        target_projection_revision,
    ):
        return timeline_api.merge_timeline_session(
            report_date,
            projection_instance_key,
            direction,
            projection_revision,
            request_id,
            target_projection_instance_key,
            target_projection_revision,
        )

    def split_timeline_session(
        self, report_date, projection_instance_key, projection_revision, request_id
    ):
        return timeline_api.split_timeline_session(
            report_date, projection_instance_key, projection_revision, request_id
        )

    def copy_timeline_session(
        self, report_date, projection_instance_key, projection_revision, request_id
    ):
        return timeline_api.copy_timeline_session(
            report_date, projection_instance_key, projection_revision, request_id
        )

    def hide_timeline_session_activity(
        self, report_date, projection_instance_key, summary_id, projection_revision, request_id
    ):
        return timeline_api.hide_timeline_session_activity(
            report_date, projection_instance_key, summary_id, projection_revision, request_id
        )


class RulesApplicationService:
    """Concrete rules capability delegating to project_api, rule_api, rule_history_api."""

    def list_project_bindings(self):
        return project_api.list_project_bindings()

    def create_project_for_rules(self, name, description, language):
        return project_api.create_project_for_rules(name, description, language)

    def update_project_for_rules(self, project_id, name, description, language):
        return project_api.update_project_for_rules(
            project_id, name, description, language
        )

    def set_project_enabled_for_rules(self, project_id, enabled):
        return project_api.set_project_enabled_for_rules(project_id, enabled)

    def set_excluded_rules_enabled(self, enabled):
        return project_api.set_excluded_rules_enabled(enabled)

    def archive_project_for_rules(self, project_id):
        return project_api.archive_project_for_rules(project_id)

    def delete_project_for_rules(self, project_id):
        return project_api.delete_project_for_rules(project_id)

    def set_project_rule_enabled(self, rule_type, rule_id, enabled):
        return rule_api.set_project_rule_enabled(rule_type, rule_id, enabled)

    def create_project_keyword_rule(self, project_id, keyword):
        return rule_api.create_project_keyword_rule(project_id, keyword)

    def delete_project_keyword_rule(self, rule_id, apply_to_history):
        return rule_api.delete_project_keyword_rule(rule_id, apply_to_history)

    def update_project_keyword_rule(self, rule_id, keyword):
        return rule_api.update_project_keyword_rule(rule_id, keyword)

    def create_project_folder_rule(self, project_id, folder_path, recursive):
        return rule_api.create_project_folder_rule(project_id, folder_path, recursive)

    def create_excluded_keyword_rule_for_webview(self, keyword):
        return rule_api.create_excluded_keyword_rule_for_webview(keyword)

    def create_excluded_folder_rule_for_webview(self, folder_path, recursive):
        return rule_api.create_excluded_folder_rule_for_webview(folder_path, recursive)

    def update_project_folder_rule(self, rule_id, folder_path, recursive):
        return rule_api.update_project_folder_rule(rule_id, folder_path, recursive)

    def delete_project_folder_rule(self, rule_id, apply_to_history):
        return rule_api.delete_project_folder_rule(rule_id, apply_to_history)

    def preview_project_rule_impact(self, rule_type, rule_id):
        return rule_history_api.preview_project_rule_impact(rule_type, rule_id)

    def backfill_project_rule(self, rule_type, rule_id):
        return rule_history_api.backfill_project_rule(rule_type, rule_id)

    def preview_project_rules_batch_impact(self, rules):
        return rule_history_api.preview_project_rules_batch_impact(rules)

    def backfill_project_rules_batch(self, rules):
        return rule_history_api.backfill_project_rules_batch(rules)

    def set_project_rules_batch_enabled(self, rules, enabled):
        return rule_history_api.set_project_rules_batch_enabled(rules, enabled)

    def automatic_rules_status(self):
        return rule_history_api.automatic_rules_status()


__all__ = [
    "BackupApplicationService",
    "BackupCapability",
    "OverviewApplicationService",
    "OverviewCapability",
    "RulesApplicationService",
    "RulesCapability",
    "SettingsApplicationService",
    "SettingsCapability",
    "StatisticsApplicationService",
    "StatisticsCapability",
    "TimelineApplicationService",
    "TimelineCapability",
]
