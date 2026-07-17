"""Overview page bridge mixin."""

from __future__ import annotations

import logging
from typing import Any

from ..api import view_model_api
from .bridge_common import _GENERIC_ERROR

logger = logging.getLogger(__name__)


class OverviewBridgeMixin:
    """Overview page bridge methods."""

    def get_status(self) -> dict[str, Any]:
        try:
            return self.application_control.get_collection_status()
        except Exception:
            logger.exception("webview bridge get_status failed")
            return dict(_GENERIC_ERROR)

    def toggle_pause(self) -> dict[str, Any]:
        try:
            return self.application_control.toggle_collection()
        except Exception:
            logger.exception("webview bridge toggle_pause failed")
            return dict(_GENERIC_ERROR)

    def get_overview(self) -> dict[str, Any]:
        try:
            return view_model_api.get_overview_view_model()
        except Exception:
            logger.exception("webview bridge get_overview failed")
            return dict(_GENERIC_ERROR)

    def get_refresh_state(self, report_date=None) -> dict[str, Any]:
        try:
            return view_model_api.get_refresh_state_view_model(report_date)
        except Exception:
            logger.exception("webview bridge get_refresh_state failed")
            return dict(_GENERIC_ERROR)


__all__ = ["OverviewBridgeMixin"]
