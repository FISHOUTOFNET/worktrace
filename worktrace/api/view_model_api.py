"""ViewModel API facade — sole entry for page display ViewModels and the
unified live-display pure helpers consumed by the bridge layer.

This is the ONLY module through which ``worktrace.webview_ui`` (the bridge
layer) reaches the ViewModel constructor in
``worktrace.services.view_model_service`` and the pure live-display
helpers in ``worktrace.services.live_display_service``. It re-exports the
service functions as thin pass-throughs so the bridge never imports
``worktrace.services`` directly (enforced by
``tests/test_ui_backend_boundary.py``).

Boundary rules:

- This module may import ``worktrace.services.view_model_service`` and
  ``worktrace.services.live_display_service`` and stdlib only.
- Every re-export is a plain function wrapper (no business logic) so the
  service remains the single source of truth for page display payloads.
- Returned payloads are display-safe JSON-serializable dicts.
"""

from __future__ import annotations

from typing import Any

from ..services.live_display_service import (
    build_current_activity_summary,
    compute_refresh_revision,
)
from ..services.view_model_service import (
    get_overview_view_model,
    get_refresh_state_view_model,
    get_session_details_view_model,
    get_timeline_view_model,
)


__all__ = [
    "build_current_activity_summary",
    "compute_refresh_revision",
    "get_overview_view_model",
    "get_refresh_state_view_model",
    "get_session_details_view_model",
    "get_timeline_view_model",
]
