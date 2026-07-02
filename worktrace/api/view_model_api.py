"""ViewModel API facade — sole entry for page display ViewModels.

This is the ONLY module through which ``worktrace.webview_ui`` (the bridge
layer) reaches the ViewModel constructor in
``worktrace.services.view_model_service``. It re-exports the service
functions as thin pass-throughs so the bridge never imports
``worktrace.services`` directly (enforced by
``tests/test_ui_backend_boundary.py``).

Boundary rules:

- This module may import ``worktrace.services.view_model_service`` and
  stdlib only.
- Every re-export is a plain function wrapper (no business logic) so the
  service remains the single source of truth for page display payloads.
- Returned payloads are display-safe JSON-serializable dicts.
"""

from __future__ import annotations

from typing import Any

from ..services.view_model_service import (
    get_overview_view_model,
    get_refresh_state_view_model,
    get_session_details_view_model,
    get_timeline_view_model,
)


__all__ = [
    "get_overview_view_model",
    "get_refresh_state_view_model",
    "get_session_details_view_model",
    "get_timeline_view_model",
]
