"""Python capability bridge exposed to the WebView frontend via pywebview."""

from __future__ import annotations

from typing import Any

from .bridge_dialogs import BridgeDialogMixin
from .bridge_overview import OverviewBridgeMixin
from .bridge_rules import ProjectRulesBridgeMixin
from .bridge_settings import SettingsBridgeMixin
from .bridge_statistics import StatisticsBridgeMixin
from .bridge_timeline import TimelineBridgeMixin

SHIPPING_METHODS = frozenset(
    {
        "accept_first_run_notice",
        "archive_project_for_rules",
        "automatic_rules_status",
        "backfill_project_rule",
        "backfill_project_rules_batch",
        "clear_all_local_data",
        "copy_timeline_session",
        "create_excluded_folder_rule",
        "create_excluded_keyword_rule",
        "create_project_folder_rule",
        "create_project_for_rules",
        "create_project_keyword_rule",
        "delete_project_folder_rule",
        "delete_project_for_rules",
        "delete_project_keyword_rule",
        "export_encrypted_backup",
        "export_statistics_csv",
        "get_first_run_notice",
        "get_overview",
        "get_project_rules",
        "get_recent_activities",
        "get_refresh_state",
        "get_settings_privacy_status",
        "get_statistics_export_summary",
        "get_status",
        "get_timeline",
        "get_timeline_session_activity_summary",
        "hide_timeline_session",
        "hide_timeline_session_activity",
        "import_encrypted_backup",
        "list_projects_for_timeline",
        "merge_timeline_session",
        "preview_encrypted_backup_manifest",
        "preview_project_rule_impact",
        "preview_project_rules_batch_impact",
        "save_timeline_session_edit",
        "set_clipboard_capture_enabled",
        "set_excluded_rules_enabled",
        "set_project_enabled_for_rules",
        "set_project_rule_enabled",
        "set_project_rules_batch_enabled",
        "split_timeline_session",
        "toggle_pause",
        "update_project_folder_rule",
        "update_project_for_rules",
        "update_project_keyword_rule",
    }
)


class _ShippingBridge:
    """Read-only capability view passed to pywebview as ``js_api``."""

    def __init__(self, owner: "WebViewBridge") -> None:
        self._owner = owner

    def __dir__(self) -> list[str]:
        return sorted(SHIPPING_METHODS)

    def __getattr__(self, name: str):
        if name not in SHIPPING_METHODS:
            raise AttributeError(name)
        return getattr(self._owner, name)


class WebViewBridge(
    BridgeDialogMixin,
    OverviewBridgeMixin,
    SettingsBridgeMixin,
    StatisticsBridgeMixin,
    TimelineBridgeMixin,
    ProjectRulesBridgeMixin,
):
    """Internal bridge controller with a fixed shipping capability view."""

    def __init__(self) -> None:
        self._window: Any = None
        self._shipping_api = _ShippingBridge(self)

    @property
    def shipping_api(self) -> _ShippingBridge:
        return self._shipping_api

    def set_window(self, window: Any) -> None:
        """Inject the already-created pywebview window for native dialogs."""

        self._window = window


__all__ = ["SHIPPING_METHODS", "WebViewBridge"]
