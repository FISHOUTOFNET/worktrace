from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from worktrace.api import export_api, statistics_api
from worktrace.api.app_api import ApplicationControlService
from worktrace.api.application_capabilities import (
    BackupApplicationService,
    OverviewApplicationService,
    RulesApplicationService,
    SettingsApplicationService,
    StatisticsApplicationService,
    TimelineApplicationService,
)
from worktrace.api.application_services import ApplicationServices
from worktrace.runtime.contracts import RuntimeStartResult
from worktrace.webview_ui.bridge import WebViewBridge


@dataclass
class TestRuntime:
    """Explicit runtime fake for bridge tests; never installed globally."""

    start_result: RuntimeStartResult | None = None
    pause_result: dict[str, object] | None = None
    clipboard_accepted: bool = True
    phase: str = "running"

    def start_authorized_collection(self) -> RuntimeStartResult:
        return self.start_result or RuntimeStartResult(
            ok=True,
            collector_ready=True,
            workers={},
            already_running=False,
            degraded=False,
            error_code=None,
        )

    def pause_collection_now(self) -> dict[str, object]:
        return self.pause_result or {"ok": True, "pause_pending": False}

    def set_clipboard_capture_enabled(self, enabled: bool) -> bool:
        return bool(self.clipboard_accepted)

    def request_shutdown(self) -> None:
        return None

    def worker_registry_snapshot(self) -> dict[str, object]:
        return {}

    def worker_health_snapshot(self) -> dict[str, object]:
        return {"workers": {}, "degraded_workers": []}


@dataclass
class TestMaintenance:
    """Explicit maintenance-state fake used by composed bridge tests."""

    blocked_reason: str | None = None

    @contextmanager
    def external_runtime_mutation_guard(self):
        if self.blocked_reason is not None:
            from worktrace.services.database_maintenance_service import (
                MaintenanceInProgressError,
            )
            from worktrace.write_gate import DATABASE_RECOVERY_ERROR

            raise MaintenanceInProgressError(DATABASE_RECOVERY_ERROR)
        yield


class _OperationalHoldState:
    value = "operational"


class _OperationalCollectorControl:
    hold_state = _OperationalHoldState()

    def query_command(self, command_id: str):
        return None


class TestRuntimeMaintenanceControl:
    """Stopped, operational runtime boundary for service integration tests."""

    def __init__(self) -> None:
        self.collector_control = _OperationalCollectorControl()

    @staticmethod
    def _ack(command_kind: str, terminal_state: str) -> dict[str, object]:
        return {
            "ok": True,
            "command_id": f"test-{command_kind}",
            "command_kind": command_kind,
            "command_state": "completed",
            "command_state_unknown": False,
            "terminal_state": terminal_state,
        }

    def is_collection_running_for_maintenance(self) -> bool:
        return False

    def quiesce_collection_for_maintenance(self, timeout_seconds=5.0):
        return self._ack("maintenance_hold", "held")

    def reset_after_database_replacement(self, timeout_seconds=5.0):
        return self._ack("database_reset", "held")

    def restore_after_maintenance(self, state, timeout_seconds=5.0):
        return self._ack("maintenance_release", "operational")


class FakeOverviewCapability:
    """Fake OverviewCapability with explicit signatures and call tracking."""

    def __init__(self) -> None:
        self.get_overview_view_model_return: dict[str, Any] = {"ok": True}
        self.get_overview_view_model_side_effect: BaseException | None = None
        self.get_overview_view_model_calls: list[tuple] = []
        self.get_refresh_state_view_model_return: dict[str, Any] = {"ok": True}
        self.get_refresh_state_view_model_side_effect: BaseException | None = None
        self.get_refresh_state_view_model_calls: list[tuple] = []

    def get_overview_view_model(self, *, runtime, collector_status):
        self.get_overview_view_model_calls.append((runtime, collector_status))
        if self.get_overview_view_model_side_effect is not None:
            raise self.get_overview_view_model_side_effect
        return self.get_overview_view_model_return

    def get_refresh_state_view_model(self, report_date, *, runtime, collector_status):
        self.get_refresh_state_view_model_calls.append(
            (report_date, runtime, collector_status)
        )
        if self.get_refresh_state_view_model_side_effect is not None:
            raise self.get_refresh_state_view_model_side_effect
        return self.get_refresh_state_view_model_return


class FakeSettingsCapability:
    """Fake SettingsCapability with explicit signatures and call tracking."""

    def __init__(self) -> None:
        self.get_first_run_notice_for_webview_return: dict[str, Any] = {"ok": True}
        self.get_first_run_notice_for_webview_side_effect: BaseException | None = None
        self.get_first_run_notice_for_webview_calls: list[tuple] = []
        self.get_settings_privacy_status_return: dict[str, Any] = {"ok": True}
        self.get_settings_privacy_status_side_effect: BaseException | None = None
        self.get_settings_privacy_status_calls: list[tuple] = []
        self.recover_database_maintenance_for_webview_return: dict[str, Any] = {"ok": True}
        self.recover_database_maintenance_for_webview_side_effect: BaseException | None = None
        self.recover_database_maintenance_for_webview_calls: list[tuple] = []
        self.clear_all_local_data_for_webview_return: dict[str, Any] = {"ok": True}
        self.clear_all_local_data_for_webview_side_effect: BaseException | None = None
        self.clear_all_local_data_for_webview_calls: list[tuple] = []

    def get_first_run_notice_for_webview(self):
        self.get_first_run_notice_for_webview_calls.append(())
        if self.get_first_run_notice_for_webview_side_effect is not None:
            raise self.get_first_run_notice_for_webview_side_effect
        return self.get_first_run_notice_for_webview_return

    def get_settings_privacy_status(self):
        self.get_settings_privacy_status_calls.append(())
        if self.get_settings_privacy_status_side_effect is not None:
            raise self.get_settings_privacy_status_side_effect
        return self.get_settings_privacy_status_return

    def recover_database_maintenance_for_webview(self):
        self.recover_database_maintenance_for_webview_calls.append(())
        if self.recover_database_maintenance_for_webview_side_effect is not None:
            raise self.recover_database_maintenance_for_webview_side_effect
        return self.recover_database_maintenance_for_webview_return

    def clear_all_local_data_for_webview(self, confirm_text):
        self.clear_all_local_data_for_webview_calls.append((confirm_text,))
        if self.clear_all_local_data_for_webview_side_effect is not None:
            raise self.clear_all_local_data_for_webview_side_effect
        return self.clear_all_local_data_for_webview_return


class FakeBackupCapability:
    """Fake BackupCapability with explicit signatures and call tracking."""

    def __init__(self) -> None:
        self.export_encrypted_backup_for_webview_return: dict[str, Any] = {"ok": True}
        self.export_encrypted_backup_for_webview_side_effect: BaseException | None = None
        self.export_encrypted_backup_for_webview_calls: list[tuple] = []
        self.preview_encrypted_backup_manifest_for_webview_return: dict[str, Any] = {"ok": True}
        self.preview_encrypted_backup_manifest_for_webview_side_effect: BaseException | None = None
        self.preview_encrypted_backup_manifest_for_webview_calls: list[tuple] = []
        self.import_encrypted_backup_for_webview_return: dict[str, Any] = {"ok": True}
        self.import_encrypted_backup_for_webview_side_effect: BaseException | None = None
        self.import_encrypted_backup_for_webview_calls: list[tuple] = []

    def export_encrypted_backup_for_webview(self, output_path, passphrase, confirm_passphrase):
        self.export_encrypted_backup_for_webview_calls.append(
            (output_path, passphrase, confirm_passphrase)
        )
        if self.export_encrypted_backup_for_webview_side_effect is not None:
            raise self.export_encrypted_backup_for_webview_side_effect
        return self.export_encrypted_backup_for_webview_return

    def preview_encrypted_backup_manifest_for_webview(self, input_path):
        self.preview_encrypted_backup_manifest_for_webview_calls.append((input_path,))
        if self.preview_encrypted_backup_manifest_for_webview_side_effect is not None:
            raise self.preview_encrypted_backup_manifest_for_webview_side_effect
        return self.preview_encrypted_backup_manifest_for_webview_return

    def import_encrypted_backup_for_webview(self, input_path, passphrase, confirm_text):
        self.import_encrypted_backup_for_webview_calls.append(
            (input_path, passphrase, confirm_text)
        )
        if self.import_encrypted_backup_for_webview_side_effect is not None:
            raise self.import_encrypted_backup_for_webview_side_effect
        return self.import_encrypted_backup_for_webview_return


class FakeStatisticsCapability:
    """Fake StatisticsCapability with explicit signatures and call tracking."""

    StatisticsSummaryError = statistics_api.StatisticsSummaryError
    StatisticsExportError = export_api.StatisticsExportError

    def __init__(self) -> None:
        self.get_statistics_export_view_model_return: dict[str, Any] = {"ok": True}
        self.get_statistics_export_view_model_side_effect: BaseException | None = None
        self.get_statistics_export_view_model_calls: list[tuple] = []
        self.format_export_duration_return: str = ""
        self.format_export_duration_side_effect: BaseException | None = None
        self.format_export_duration_calls: list[tuple] = []
        self.export_statistics_csv_return: dict[str, Any] = {"ok": True}
        self.export_statistics_csv_side_effect: BaseException | None = None
        self.export_statistics_csv_calls: list[tuple] = []

    def get_statistics_export_view_model(self, date_from, date_to, project_id=None):
        call = (date_from, date_to) if project_id is None else (date_from, date_to, project_id)
        self.get_statistics_export_view_model_calls.append(call)
        if self.get_statistics_export_view_model_side_effect is not None:
            raise self.get_statistics_export_view_model_side_effect
        return self.get_statistics_export_view_model_return

    def format_export_duration(self, duration_seconds):
        self.format_export_duration_calls.append((duration_seconds,))
        if self.format_export_duration_side_effect is not None:
            raise self.format_export_duration_side_effect
        return self.format_export_duration_return

    def export_statistics_csv(self, date_from, date_to, output_path, expected_export_ticket_revision, project_id=None):
        call = (date_from, date_to, output_path, expected_export_ticket_revision)
        if project_id is not None:
            call = (*call, project_id)
        self.export_statistics_csv_calls.append(call)
        if self.export_statistics_csv_side_effect is not None:
            raise self.export_statistics_csv_side_effect
        return self.export_statistics_csv_return


class FakeTimelineCapability:
    """Fake TimelineCapability with explicit signatures and call tracking."""

    TIMELINE_NOTE_MAX_LENGTH = 2000

    def __init__(self) -> None:
        self.get_timeline_view_model_return: dict[str, Any] = {"ok": True}
        self.get_timeline_view_model_side_effect: BaseException | None = None
        self.get_timeline_view_model_calls: list[tuple] = []
        self.get_session_activity_summary_view_model_return: dict[str, Any] = {"ok": True}
        self.get_session_activity_summary_view_model_side_effect: BaseException | None = None
        self.get_session_activity_summary_view_model_calls: list[tuple] = []
        self.list_selectable_projects_return: list[dict[str, Any]] = []
        self.list_selectable_projects_side_effect: BaseException | None = None
        self.list_selectable_projects_calls: list[tuple] = []
        self.save_timeline_session_edit_return: dict[str, Any] = {"ok": True}
        self.save_timeline_session_edit_side_effect: BaseException | None = None
        self.save_timeline_session_edit_calls: list[tuple] = []
        self.hide_timeline_session_return: dict[str, Any] = {"ok": True}
        self.hide_timeline_session_side_effect: BaseException | None = None
        self.hide_timeline_session_calls: list[tuple] = []
        self.merge_timeline_session_return: dict[str, Any] = {"ok": True}
        self.merge_timeline_session_side_effect: BaseException | None = None
        self.merge_timeline_session_calls: list[tuple] = []
        self.split_timeline_session_return: dict[str, Any] = {"ok": True}
        self.split_timeline_session_side_effect: BaseException | None = None
        self.split_timeline_session_calls: list[tuple] = []
        self.copy_timeline_session_return: dict[str, Any] = {"ok": True}
        self.copy_timeline_session_side_effect: BaseException | None = None
        self.copy_timeline_session_calls: list[tuple] = []
        self.hide_timeline_session_activity_return: dict[str, Any] = {"ok": True}
        self.hide_timeline_session_activity_side_effect: BaseException | None = None
        self.hide_timeline_session_activity_calls: list[tuple] = []

    def get_timeline_view_model(self, date, *, runtime, collector_status):
        self.get_timeline_view_model_calls.append((date, runtime, collector_status))
        if self.get_timeline_view_model_side_effect is not None:
            raise self.get_timeline_view_model_side_effect
        return self.get_timeline_view_model_return

    def get_session_activity_summary_view_model(
        self,
        *,
        report_date,
        projection_instance_key,
        expected_projection_revision,
        runtime,
        collector_status,
    ):
        self.get_session_activity_summary_view_model_calls.append(
            (
                report_date,
                projection_instance_key,
                expected_projection_revision,
                runtime,
                collector_status,
            )
        )
        if self.get_session_activity_summary_view_model_side_effect is not None:
            raise self.get_session_activity_summary_view_model_side_effect
        return self.get_session_activity_summary_view_model_return

    def list_selectable_projects(self):
        self.list_selectable_projects_calls.append(())
        if self.list_selectable_projects_side_effect is not None:
            raise self.list_selectable_projects_side_effect
        return self.list_selectable_projects_return

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
        self.save_timeline_session_edit_calls.append(
            (
                report_date,
                projection_instance_key,
                projection_revision,
                request_id,
                project_id,
                adjusted_duration_seconds,
                note,
            )
        )
        if self.save_timeline_session_edit_side_effect is not None:
            raise self.save_timeline_session_edit_side_effect
        return self.save_timeline_session_edit_return

    def hide_timeline_session(
        self, report_date, projection_instance_key, projection_revision, request_id
    ):
        self.hide_timeline_session_calls.append(
            (report_date, projection_instance_key, projection_revision, request_id)
        )
        if self.hide_timeline_session_side_effect is not None:
            raise self.hide_timeline_session_side_effect
        return self.hide_timeline_session_return

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
        self.merge_timeline_session_calls.append(
            (
                report_date,
                projection_instance_key,
                direction,
                projection_revision,
                request_id,
                target_projection_instance_key,
                target_projection_revision,
            )
        )
        if self.merge_timeline_session_side_effect is not None:
            raise self.merge_timeline_session_side_effect
        return self.merge_timeline_session_return

    def split_timeline_session(
        self, report_date, projection_instance_key, projection_revision, request_id
    ):
        self.split_timeline_session_calls.append(
            (report_date, projection_instance_key, projection_revision, request_id)
        )
        if self.split_timeline_session_side_effect is not None:
            raise self.split_timeline_session_side_effect
        return self.split_timeline_session_return

    def copy_timeline_session(
        self, report_date, projection_instance_key, projection_revision, request_id
    ):
        self.copy_timeline_session_calls.append(
            (report_date, projection_instance_key, projection_revision, request_id)
        )
        if self.copy_timeline_session_side_effect is not None:
            raise self.copy_timeline_session_side_effect
        return self.copy_timeline_session_return

    def hide_timeline_session_activity(
        self, report_date, projection_instance_key, summary_id, projection_revision, request_id
    ):
        self.hide_timeline_session_activity_calls.append(
            (
                report_date,
                projection_instance_key,
                summary_id,
                projection_revision,
                request_id,
            )
        )
        if self.hide_timeline_session_activity_side_effect is not None:
            raise self.hide_timeline_session_activity_side_effect
        return self.hide_timeline_session_activity_return


class FakeRulesCapability:
    """Fake RulesCapability with explicit signatures and call tracking."""

    def __init__(self) -> None:
        self.list_project_bindings_return: list[dict[str, Any]] = []
        self.list_project_bindings_side_effect: BaseException | None = None
        self.list_project_bindings_calls: list[tuple] = []
        self.create_project_for_rules_return: dict[str, Any] = {"ok": False, "error": "operation_failed"}
        self.create_project_for_rules_side_effect: BaseException | None = None
        self.create_project_for_rules_calls: list[tuple] = []
        self.update_project_for_rules_return: dict[str, Any] = {"ok": False, "error": "operation_failed"}
        self.update_project_for_rules_side_effect: BaseException | None = None
        self.update_project_for_rules_calls: list[tuple] = []
        self.set_project_enabled_for_rules_return: dict[str, Any] = {"ok": False, "error": "operation_failed"}
        self.set_project_enabled_for_rules_side_effect: BaseException | None = None
        self.set_project_enabled_for_rules_calls: list[tuple] = []
        self.set_excluded_rules_enabled_return: dict[str, Any] = {"ok": False, "error": "operation_failed"}
        self.set_excluded_rules_enabled_side_effect: BaseException | None = None
        self.set_excluded_rules_enabled_calls: list[tuple] = []
        self.archive_project_for_rules_return: dict[str, Any] = {"ok": False, "error": "operation_failed"}
        self.archive_project_for_rules_side_effect: BaseException | None = None
        self.archive_project_for_rules_calls: list[tuple] = []
        self.delete_project_for_rules_return: dict[str, Any] = {"ok": False, "error": "operation_failed"}
        self.delete_project_for_rules_side_effect: BaseException | None = None
        self.delete_project_for_rules_calls: list[tuple] = []
        self.set_project_rule_enabled_return: dict[str, Any] = {"ok": False, "error": "operation_failed"}
        self.set_project_rule_enabled_side_effect: BaseException | None = None
        self.set_project_rule_enabled_calls: list[tuple] = []
        self.create_project_keyword_rule_return: dict[str, Any] = {"ok": False, "error": "operation_failed"}
        self.create_project_keyword_rule_side_effect: BaseException | None = None
        self.create_project_keyword_rule_calls: list[tuple] = []
        self.delete_project_keyword_rule_return: dict[str, Any] = {"ok": False, "error": "operation_failed"}
        self.delete_project_keyword_rule_side_effect: BaseException | None = None
        self.delete_project_keyword_rule_calls: list[tuple] = []
        self.update_project_keyword_rule_return: dict[str, Any] = {"ok": False, "error": "operation_failed"}
        self.update_project_keyword_rule_side_effect: BaseException | None = None
        self.update_project_keyword_rule_calls: list[tuple] = []
        self.create_project_folder_rule_return: dict[str, Any] = {"ok": False, "error": "operation_failed"}
        self.create_project_folder_rule_side_effect: BaseException | None = None
        self.create_project_folder_rule_calls: list[tuple] = []
        self.create_excluded_keyword_rule_for_webview_return: dict[str, Any] = {"ok": False, "error": "operation_failed"}
        self.create_excluded_keyword_rule_for_webview_side_effect: BaseException | None = None
        self.create_excluded_keyword_rule_for_webview_calls: list[tuple] = []
        self.create_excluded_folder_rule_for_webview_return: dict[str, Any] = {"ok": False, "error": "operation_failed"}
        self.create_excluded_folder_rule_for_webview_side_effect: BaseException | None = None
        self.create_excluded_folder_rule_for_webview_calls: list[tuple] = []
        self.update_project_folder_rule_return: dict[str, Any] = {"ok": False, "error": "operation_failed"}
        self.update_project_folder_rule_side_effect: BaseException | None = None
        self.update_project_folder_rule_calls: list[tuple] = []
        self.delete_project_folder_rule_return: dict[str, Any] = {"ok": False, "error": "operation_failed"}
        self.delete_project_folder_rule_side_effect: BaseException | None = None
        self.delete_project_folder_rule_calls: list[tuple] = []
        self.preview_project_rule_impact_return: dict[str, Any] = {"ok": False, "error": "operation_failed"}
        self.preview_project_rule_impact_side_effect: BaseException | None = None
        self.preview_project_rule_impact_calls: list[tuple] = []
        self.backfill_project_rule_return: dict[str, Any] = {"ok": False, "error": "operation_failed"}
        self.backfill_project_rule_side_effect: BaseException | None = None
        self.backfill_project_rule_calls: list[tuple] = []
        self.preview_project_rules_batch_impact_return: dict[str, Any] = {"ok": False, "error": "operation_failed"}
        self.preview_project_rules_batch_impact_side_effect: BaseException | None = None
        self.preview_project_rules_batch_impact_calls: list[tuple] = []
        self.backfill_project_rules_batch_return: dict[str, Any] = {"ok": False, "error": "operation_failed"}
        self.backfill_project_rules_batch_side_effect: BaseException | None = None
        self.backfill_project_rules_batch_calls: list[tuple] = []
        self.set_project_rules_batch_enabled_return: dict[str, Any] = {"ok": False, "error": "operation_failed"}
        self.set_project_rules_batch_enabled_side_effect: BaseException | None = None
        self.set_project_rules_batch_enabled_calls: list[tuple] = []
        self.automatic_rules_status_return: dict[str, Any] = {"ok": False, "error": "operation_failed"}
        self.automatic_rules_status_side_effect: BaseException | None = None
        self.automatic_rules_status_calls: list[tuple] = []

    def list_project_bindings(self):
        self.list_project_bindings_calls.append(())
        if self.list_project_bindings_side_effect is not None:
            raise self.list_project_bindings_side_effect
        return self.list_project_bindings_return

    def create_project_for_rules(self, name, description, language):
        self.create_project_for_rules_calls.append((name, description, language))
        if self.create_project_for_rules_side_effect is not None:
            raise self.create_project_for_rules_side_effect
        return self.create_project_for_rules_return

    def update_project_for_rules(self, project_id, name, description, language):
        self.update_project_for_rules_calls.append((project_id, name, description, language))
        if self.update_project_for_rules_side_effect is not None:
            raise self.update_project_for_rules_side_effect
        return self.update_project_for_rules_return

    def set_project_enabled_for_rules(self, project_id, enabled):
        self.set_project_enabled_for_rules_calls.append((project_id, enabled))
        if self.set_project_enabled_for_rules_side_effect is not None:
            raise self.set_project_enabled_for_rules_side_effect
        return self.set_project_enabled_for_rules_return

    def set_excluded_rules_enabled(self, enabled):
        self.set_excluded_rules_enabled_calls.append((enabled,))
        if self.set_excluded_rules_enabled_side_effect is not None:
            raise self.set_excluded_rules_enabled_side_effect
        return self.set_excluded_rules_enabled_return

    def archive_project_for_rules(self, project_id):
        self.archive_project_for_rules_calls.append((project_id,))
        if self.archive_project_for_rules_side_effect is not None:
            raise self.archive_project_for_rules_side_effect
        return self.archive_project_for_rules_return

    def delete_project_for_rules(self, project_id):
        self.delete_project_for_rules_calls.append((project_id,))
        if self.delete_project_for_rules_side_effect is not None:
            raise self.delete_project_for_rules_side_effect
        return self.delete_project_for_rules_return

    def set_project_rule_enabled(self, rule_type, rule_id, enabled):
        self.set_project_rule_enabled_calls.append((rule_type, rule_id, enabled))
        if self.set_project_rule_enabled_side_effect is not None:
            raise self.set_project_rule_enabled_side_effect
        return self.set_project_rule_enabled_return

    def create_project_keyword_rule(self, project_id, keyword):
        self.create_project_keyword_rule_calls.append((project_id, keyword))
        if self.create_project_keyword_rule_side_effect is not None:
            raise self.create_project_keyword_rule_side_effect
        return self.create_project_keyword_rule_return

    def delete_project_keyword_rule(self, rule_id, apply_to_history):
        self.delete_project_keyword_rule_calls.append((rule_id, apply_to_history))
        if self.delete_project_keyword_rule_side_effect is not None:
            raise self.delete_project_keyword_rule_side_effect
        return self.delete_project_keyword_rule_return

    def update_project_keyword_rule(self, rule_id, keyword):
        self.update_project_keyword_rule_calls.append((rule_id, keyword))
        if self.update_project_keyword_rule_side_effect is not None:
            raise self.update_project_keyword_rule_side_effect
        return self.update_project_keyword_rule_return

    def create_project_folder_rule(self, project_id, folder_path, recursive):
        self.create_project_folder_rule_calls.append((project_id, folder_path, recursive))
        if self.create_project_folder_rule_side_effect is not None:
            raise self.create_project_folder_rule_side_effect
        return self.create_project_folder_rule_return

    def create_excluded_keyword_rule_for_webview(self, keyword):
        self.create_excluded_keyword_rule_for_webview_calls.append((keyword,))
        if self.create_excluded_keyword_rule_for_webview_side_effect is not None:
            raise self.create_excluded_keyword_rule_for_webview_side_effect
        return self.create_excluded_keyword_rule_for_webview_return

    def create_excluded_folder_rule_for_webview(self, folder_path, recursive):
        self.create_excluded_folder_rule_for_webview_calls.append((folder_path, recursive))
        if self.create_excluded_folder_rule_for_webview_side_effect is not None:
            raise self.create_excluded_folder_rule_for_webview_side_effect
        return self.create_excluded_folder_rule_for_webview_return

    def update_project_folder_rule(self, rule_id, folder_path, recursive):
        self.update_project_folder_rule_calls.append((rule_id, folder_path, recursive))
        if self.update_project_folder_rule_side_effect is not None:
            raise self.update_project_folder_rule_side_effect
        return self.update_project_folder_rule_return

    def delete_project_folder_rule(self, rule_id, apply_to_history):
        self.delete_project_folder_rule_calls.append((rule_id, apply_to_history))
        if self.delete_project_folder_rule_side_effect is not None:
            raise self.delete_project_folder_rule_side_effect
        return self.delete_project_folder_rule_return

    def preview_project_rule_impact(self, rule_type, rule_id):
        self.preview_project_rule_impact_calls.append((rule_type, rule_id))
        if self.preview_project_rule_impact_side_effect is not None:
            raise self.preview_project_rule_impact_side_effect
        return self.preview_project_rule_impact_return

    def backfill_project_rule(self, rule_type, rule_id):
        self.backfill_project_rule_calls.append((rule_type, rule_id))
        if self.backfill_project_rule_side_effect is not None:
            raise self.backfill_project_rule_side_effect
        return self.backfill_project_rule_return

    def preview_project_rules_batch_impact(self, rules):
        self.preview_project_rules_batch_impact_calls.append((rules,))
        if self.preview_project_rules_batch_impact_side_effect is not None:
            raise self.preview_project_rules_batch_impact_side_effect
        return self.preview_project_rules_batch_impact_return

    def backfill_project_rules_batch(self, rules):
        self.backfill_project_rules_batch_calls.append((rules,))
        if self.backfill_project_rules_batch_side_effect is not None:
            raise self.backfill_project_rules_batch_side_effect
        return self.backfill_project_rules_batch_return

    def set_project_rules_batch_enabled(self, rules, enabled):
        self.set_project_rules_batch_enabled_calls.append((rules, enabled))
        if self.set_project_rules_batch_enabled_side_effect is not None:
            raise self.set_project_rules_batch_enabled_side_effect
        return self.set_project_rules_batch_enabled_return

    def automatic_rules_status(self):
        self.automatic_rules_status_calls.append(())
        if self.automatic_rules_status_side_effect is not None:
            raise self.automatic_rules_status_side_effect
        return self.automatic_rules_status_return


def build_test_application_services(
    runtime: TestRuntime | None = None,
    maintenance: TestMaintenance | None = None,
    *,
    overview: FakeOverviewCapability | None = None,
    settings: FakeSettingsCapability | None = None,
    backup: FakeBackupCapability | None = None,
    statistics: FakeStatisticsCapability | None = None,
    timeline: FakeTimelineCapability | None = None,
    rules: FakeRulesCapability | None = None,
) -> ApplicationServices:
    runtime_capability = runtime if runtime is not None else TestRuntime()
    maintenance_capability = maintenance if maintenance is not None else TestMaintenance()
    return ApplicationServices(
        app_control=ApplicationControlService(
            runtime_capability,
            maintenance_capability,
        ),
        runtime_view=runtime_capability,
        overview=overview if overview is not None else OverviewApplicationService(),
        settings=settings if settings is not None else SettingsApplicationService(),
        backup=backup if backup is not None else BackupApplicationService(),
        statistics=statistics if statistics is not None else StatisticsApplicationService(),
        timeline=timeline if timeline is not None else TimelineApplicationService(),
        rules=rules if rules is not None else RulesApplicationService(),
    )


def build_test_bridge(
    runtime: TestRuntime | None = None,
    maintenance: TestMaintenance | None = None,
    *,
    overview: FakeOverviewCapability | None = None,
    settings: FakeSettingsCapability | None = None,
    backup: FakeBackupCapability | None = None,
    statistics: FakeStatisticsCapability | None = None,
    timeline: FakeTimelineCapability | None = None,
    rules: FakeRulesCapability | None = None,
) -> WebViewBridge:
    return WebViewBridge(
        build_test_application_services(
            runtime,
            maintenance,
            overview=overview,
            settings=settings,
            backup=backup,
            statistics=statistics,
            timeline=timeline,
            rules=rules,
        )
    )


__all__ = [
    "FakeBackupCapability",
    "FakeOverviewCapability",
    "FakeRulesCapability",
    "FakeSettingsCapability",
    "FakeStatisticsCapability",
    "FakeTimelineCapability",
    "TestMaintenance",
    "TestRuntime",
    "TestRuntimeMaintenanceControl",
    "build_test_application_services",
    "build_test_bridge",
]
