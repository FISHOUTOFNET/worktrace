"""Overview page bridge mixin.

Collection lifecycle and status semantics are owned by ``app_api``. This bridge
only invokes API capabilities and maps unexpected exceptions.
"""

from __future__ import annotations

import logging
from typing import Any

from ..api import app_api, view_model_api
from .bridge_common import _GENERIC_ERROR

logger = logging.getLogger(__name__)


class OverviewBridgeMixin:
    """Overview page bridge methods."""

    def get_status(self) -> dict[str, Any]:
        try:
            return app_api.get_collection_status()
        except Exception:
            logger.exception("webview bridge get_status failed")
            return dict(_GENERIC_ERROR)

    def toggle_pause(self) -> dict[str, Any]:
        try:
            return app_api.toggle_collection()
        except Exception:
            logger.exception("webview bridge toggle_pause failed")
            return dict(_GENERIC_ERROR)

    def get_overview(self) -> dict[str, Any]:
        try:
            return view_model_api.get_overview_view_model()
        except Exception:
            logger.exception("webview bridge get_overview failed")
            return dict(_GENERIC_ERROR)

    def get_recent_activities(self) -> dict[str, Any]:
        try:
            vm = view_model_api.get_overview_view_model()
            return {
                "ok": True,
                "activities": vm.get("activities", []),
                "live_clock": vm.get("live_clock", {}),
                "display_span_id": vm.get("display_span_id", ""),
                "activity_display_model": vm.get("activity_display_model", {}),
                "sample_id": vm.get("sample_id", ""),
            }
        except Exception:
            logger.exception("webview bridge get_recent_activities failed")
            return dict(_GENERIC_ERROR)

    def get_refresh_state(self, report_date=None) -> dict[str, Any]:
        try:
            return view_model_api.get_refresh_state_view_model(report_date)
        except Exception:
            logger.exception("webview bridge get_refresh_state failed")
            return dict(_GENERIC_ERROR)


__all__ = ["OverviewBridgeMixin"]
