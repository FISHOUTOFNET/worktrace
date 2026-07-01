"""Unified live-display API facade.

This is the ONLY entry point through which ``worktrace.webview_ui`` (the
bridge layer) reaches the unified live-display model in
``worktrace.services.live_display_service``. It re-exports the service
functions as thin pass-throughs so the bridge never imports
``worktrace.services`` directly (enforced by
``tests/test_ui_backend_boundary.py``).

Boundary rules:

- This module may import ``worktrace.services.live_display_service`` and
  stdlib only.
- Every re-export is a plain function wrapper (no business logic) so the
  service remains the single source of truth for live-projection
  decisions.
- Returned payloads are display-safe JSON-serializable dicts / scalars.
  Raw ``window_title``, ``file_path_hint``, ``note``, ``clipboard``,
  SQL, and tracebacks are never surfaced.
"""

from __future__ import annotations

from typing import Any

from ..services.live_display_service import (
    build_current_activity_summary,
    build_persisted_open_overlay,
    build_virtual_detail_row,
    build_virtual_session,
    carry_baseline_seconds,
    classify_live_state,
    compute_refresh_revision,
    is_live_eligible_for_normal,
    persisted_open_live_seconds,
    sync_carry_state,
)


__all__ = [
    "build_current_activity_summary",
    "build_persisted_open_overlay",
    "build_virtual_detail_row",
    "build_virtual_session",
    "carry_baseline_seconds",
    "classify_live_state",
    "compute_refresh_revision",
    "is_live_eligible_for_normal",
    "persisted_open_live_seconds",
    "sync_carry_state",
]
