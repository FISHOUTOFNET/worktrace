"""ViewModel API facade — sole bridge-facing entry for page display payloads.

This is the ONLY module through which ``worktrace.webview_ui`` (the bridge
layer) reaches the page ViewModel constructor in
``worktrace.services.view_model_service`` and the display-safe helper
functions in ``worktrace.services.live_display_service``. It re-exports the
service functions as thin pass-throughs so the bridge never imports
``worktrace.services`` directly (enforced by
``tests/test_ui_backend_boundary.py``).

Boundary rules:

- This module may import ``worktrace.services.view_model_service`` and
  ``worktrace.services.live_display_service`` and stdlib only.
- Every re-export is a plain function wrapper (no business logic). The
  Activity Display Model semantics are owned by
  ``worktrace.services.activity_display_model_service`` and enter page
  payloads through ``view_model_service``; this facade must not construct or
  reinterpret live display state.
- ``live_display_service`` exports used here are low-level display-safe
  helpers (current-activity summary / refresh revision), not a separate page
  live-display model owner.
- Returned payloads are display-safe JSON-serializable dicts.
"""

from __future__ import annotations

from typing import Any

from ..services.live_display_service import build_current_activity_summary
from ..services.view_model_service import (
    get_overview_view_model,
    get_refresh_state_view_model,
    get_session_activity_summary_view_model,
    get_timeline_view_model,
)


__all__ = [
    "build_current_activity_summary",
    "get_overview_view_model",
    "get_refresh_state_view_model",
    "get_session_activity_summary_view_model",
    "get_timeline_view_model",
]
