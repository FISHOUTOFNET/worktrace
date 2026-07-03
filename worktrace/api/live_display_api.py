"""Low-level live-display helper facade for the bridge layer.

This module is a thin pass-through that lets ``worktrace.webview_ui`` (the
bridge layer) reach the low-level helpers in
``worktrace.services.live_display_service`` without importing
``worktrace.services`` directly (enforced by
``tests/test_ui_backend_boundary.py``).

The page live display model owner is
``worktrace.services.activity_display_model_service`` — NOT this module.
Page ViewModels must go through ``worktrace.api.view_model_api`` /
``activity_display_model_service`` for live-display semantics (live clock,
display span, ``<30s`` pending absorption, persisted_open overlay). This
facade only re-exports low-level pure helpers (stable key, refresh
revision, current-activity summary, short-activity carry, classification)
needed by the bridge and settings layers.

Boundary rules:

- This module may import ``worktrace.services.live_display_service`` and
  stdlib only.
- Every re-export is a plain function wrapper (no business logic) so the
  service remains the single source of truth.
- Returned payloads are display-safe JSON-serializable dicts / scalars.
  Raw ``window_title``, ``file_path_hint``, ``note``, ``clipboard``,
  SQL, and tracebacks are never surfaced.
"""

from __future__ import annotations

from typing import Any

from ..services.live_display_service import (
    LIVE_ROW_CONTRACT_FIELDS,
    apply_live_row_contract,
    assert_live_row_contract,
    build_current_activity_summary,
    build_live_projection,
    build_live_row_contract,
    short_activity_carry_seconds,
    classify_live_state,
    compute_refresh_revision,
    is_live_eligible_for_normal,
    persisted_open_live_seconds,
    stable_live_key,
    stable_live_key_hash,
    sync_carry_state,
    virtual_session_id,
)


__all__ = [
    "LIVE_ROW_CONTRACT_FIELDS",
    "apply_live_row_contract",
    "assert_live_row_contract",
    "build_current_activity_summary",
    "build_live_projection",
    "build_live_row_contract",
    "short_activity_carry_seconds",
    "classify_live_state",
    "compute_refresh_revision",
    "is_live_eligible_for_normal",
    "persisted_open_live_seconds",
    "stable_live_key",
    "stable_live_key_hash",
    "sync_carry_state",
    "virtual_session_id",
]
