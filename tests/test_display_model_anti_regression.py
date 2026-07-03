"""Static anti-regression contracts for the unified Activity Display Model.

These tests enforce the architectural invariants from the cleanup spec
(section 三) so future code cannot re-introduce the legacy virtual-row
builder / multi-cache-ticker semantics. The display-model owner is
``worktrace.services.activity_display_model_service``; the legacy
``build_virtual_session`` / ``build_virtual_detail_row`` helpers have been
privatized and removed from the bridge-facing public API.

Covered invariants:

1. ``view_model_service.py`` does NOT import/call the legacy
   ``build_virtual_session`` / ``build_virtual_detail_row`` /
   ``build_persisted_open_overlay`` / ``apply_persisted_open_overlay_to_row``.
2. ``live_display_api.py`` does NOT re-export the legacy virtual builders.
3. No test under ``tests/`` imports ``build_virtual_session`` /
   ``build_virtual_detail_row`` as a POSITIVE contract.
4. (Covered in ``test_heartbeat_projection_contract.py``:
   ``applyLocalTicker()`` must not read structural caches as live-seconds
   source.)
5. ``overview.js`` / ``timeline.js`` render live rows with ``data-display-span-id``.
6. (Covered in ``test_bridge_refresh_state_and_projection.py``:
   ``get_timeline_session_details([], date)`` under virtual_pending returns
   ``activities == []`` but root still carries ``live_clock`` / ``display_span_id``.)
7. (Covered in ``test_live_display_project_transition_contract.py``:
   ``build_activity_display_model()`` visibility flags for the 3 states;
   ``absorbed_pending`` projection never writes DB.)
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TESTS_DIR = REPO_ROOT / "tests"
WEBVIEW_UI_DIR = REPO_ROOT / "worktrace" / "webview_ui"
JS_DIR = WEBVIEW_UI_DIR / "js"


# --- Invariant 1: view_model_service does not import / call legacy builders ---


_LEGACY_VIRTUAL_SYMBOLS = (
    "build_virtual_session(",
    "build_virtual_detail_row(",
    "build_persisted_open_overlay(",
    "apply_persisted_open_overlay_to_row(",
)


def test_view_model_service_does_not_reference_legacy_virtual_builders():
    """Invariant 三.1: ``view_model_service.py`` must NOT import or call
    the legacy virtual session / detail row / persisted-open overlay
    builders. They have been privatized out of the page ViewModel path;
    the new display model owner
    (``activity_display_model_service``) is the single source of truth."""
    vms_path = REPO_ROOT / "worktrace" / "services" / "view_model_service.py"
    source = vms_path.read_text(encoding="utf-8")
    for symbol in _LEGACY_VIRTUAL_SYMBOLS:
        assert symbol not in source, (
            "view_model_service.py must not reference the legacy helper "
            + symbol
            + " — the page ViewModel path projects only DB rows + "
              "apply_live_span_to_row overlay"
        )


# --- Invariant 2: live_display_api does not re-export legacy builders ---


def test_live_display_api_does_not_re_export_legacy_virtual_builders():
    """Invariant 三.2: ``worktrace.api.live_display_api`` must NOT re-export
    ``build_virtual_session`` / ``build_virtual_detail_row``. The bridge
    facade is no longer the unified live-display model entry; it only
    exposes low-level pure helpers (stable key, refresh revision, display
    model pass-through)."""
    from worktrace.api import live_display_api

    api_all = set(getattr(live_display_api, "__all__", []))
    for symbol in (
        "build_virtual_session",
        "build_virtual_detail_row",
        "build_persisted_open_overlay",
        "apply_persisted_open_overlay_to_row",
    ):
        assert symbol not in api_all, (
            "live_display_api.__all__ must not re-export " + symbol
        )
        assert not hasattr(live_display_api, symbol), (
            "live_display_api must not expose " + symbol + " as an attribute"
        )


# --- Invariant 3: tests do not import virtual builders as positive contract ---


# Pattern matches an actual import statement for the legacy builders.
# Docstring / assertion references (in strings or comments) do NOT match
# because they are not preceded by ``import`` / ``from ... import``.
_VIRTUAL_BUILDER_IMPORT_RE = re.compile(
    r"^\s*(?:"
    r"from\s+\S+\s+import\s+\([^)]*\b(build_virtual_session|build_virtual_detail_row)\b"
    r"|from\s+\S+\s+import\s+.*\b(build_virtual_session|build_virtual_detail_row)\b"
    r"|import\s+(build_virtual_session|build_virtual_detail_row)\b"
    r")",
    re.MULTILINE,
)


def test_tests_directory_does_not_import_virtual_builders_as_positive_contract():
    """Invariant 三.3: no test under ``tests/`` may import
    ``build_virtual_session`` / ``build_virtual_detail_row`` as a POSITIVE
    contract. The legacy builders are no longer part of the public API;
    the only allowed references are forbid-assertions / docstrings /
    comments inside the rewritten contract tests."""
    offenders = []
    for py_file in TESTS_DIR.rglob("test_*.py"):
        source = py_file.read_text(encoding="utf-8")
        for match in _VIRTUAL_BUILDER_IMPORT_RE.finditer(source):
            offenders.append((py_file.name, match.group(0).strip()))
    assert not offenders, (
        "tests/ must not import build_virtual_session / "
        "build_virtual_detail_row as a positive contract; offenders: "
        + repr(offenders)
    )


# --- Invariant 5: overview.js / timeline.js render live rows with data-display-span-id ---


def test_overview_js_renders_live_rows_with_display_span_id():
    """Invariant 三.5: ``overview.js`` must emit ``data-display-span-id``
    on every live recent row so the unified ticker walks the registered
    live clock (``App.liveClockBySpanId`` + ``App.liveSeconds()``) instead
    of reading a structural cache as a live-seconds source."""
    source = (JS_DIR / "overview.js").read_text(encoding="utf-8")
    assert "data-display-span-id" in source, (
        "overview.js must render recent live rows with the "
        "data-display-span-id attribute (unified live clock contract)"
    )


def test_timeline_js_renders_live_rows_with_display_span_id():
    """Invariant 三.5: ``timeline.js`` must emit ``data-display-span-id``
    on every live timeline session row AND every live detail row so the
    unified ticker walks the registered live clock for both surfaces."""
    source = (JS_DIR / "timeline.js").read_text(encoding="utf-8")
    assert "data-display-span-id" in source, (
        "timeline.js must render live session / detail rows with the "
        "data-display-span-id attribute (unified live clock contract)"
    )
    # At least one occurrence for the session list and one for the detail
    # list. We do not require an exact count, but the attribute must
    # appear in both rendering paths.
    occurrences = source.count("data-display-span-id")
    assert occurrences >= 2, (
        "timeline.js must use data-display-span-id in both the session "
        "list render and the detail list render; found "
        + str(occurrences)
        + " occurrence(s)"
    )


# --- Invariant reinforcement: live_display_service __all__ no longer exports them ---


def test_live_display_service_all_does_not_export_legacy_virtual_builders():
    """Reinforcement of 三.1 / 三.2: the public ``__all__`` of
    ``worktrace.services.live_display_service`` must NOT include the
    legacy virtual session / detail builders. They have been renamed to
    private ``_build_virtual_session`` / ``_build_virtual_detail_row``."""
    from worktrace.services import live_display_service

    service_all = set(getattr(live_display_service, "__all__", []))
    for symbol in (
        "build_virtual_session",
        "build_virtual_detail_row",
        "build_persisted_open_overlay",
        "apply_persisted_open_overlay_to_row",
    ):
        assert symbol not in service_all, (
            "live_display_service.__all__ must not export " + symbol
        )
