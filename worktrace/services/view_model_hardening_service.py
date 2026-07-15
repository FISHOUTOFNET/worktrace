"""Compatibility facade for the page-owned ViewModel services.

Production bridge calls enter the page owners through ``api.view_model_api``.
This module remains only for internal callers that have not yet updated their
import path; it contains no projection or post-processing logic.
"""

from __future__ import annotations

from .overview_view_model_service import get_overview_view_model
from .refresh_state_view_model_service import get_refresh_state_view_model
from .session_detail_view_model_service import (
    get_session_activity_summary_view_model,
)
from .timeline_view_model_service import get_timeline_view_model

__all__ = [
    "get_overview_view_model",
    "get_refresh_state_view_model",
    "get_session_activity_summary_view_model",
    "get_timeline_view_model",
]
