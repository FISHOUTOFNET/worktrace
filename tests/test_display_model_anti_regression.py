"""Static contracts for the unified Activity Display Model.

These tests keep live display semantics owned by
``worktrace.services.activity_display_model_service``. Page ViewModels
consume Activity Display Model spans: anchored spans overlay DB rows, and
unanchored ``virtual_pending`` spans may materialize display-only rows.
Bridge and frontend code must not own live semantics or derive live
seconds from structural caches.

Covered invariants:

1. ``view_model_service.py`` does NOT import/call removed
   ``build_virtual_session`` / ``build_virtual_detail_row`` /
   ``build_persisted_open_overlay`` / ``apply_persisted_open_overlay_to_row``.
2. ``view_model_api.py`` does NOT re-export removed virtual builders.
3. No test under ``tests/`` imports ``build_virtual_session`` /
   ``build_virtual_detail_row`` as a POSITIVE contract.
4. (Covered in ``test_heartbeat_projection_contract.py``:
   ``applyLocalTicker()`` must not read structural caches as live-seconds
   source.)
5. ``overview.js`` / ``timeline.js`` render live rows with ``data-display-span-id``.
6. Page ViewModels consume Activity Display Model spans: anchored spans
   overlay DB rows; unanchored ``virtual_pending`` spans may materialize
   display-only rows.
7. (Covered in ``test_live_display_project_transition_contract.py``:
   ``build_activity_display_model()`` visibility flags for the 3 states;
   ``absorbed_pending`` projection never writes DB.)
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = [pytest.mark.contract, pytest.mark.webview_static, pytest.mark.live_display]

REPO_ROOT = Path(__file__).resolve().parents[1]
TESTS_DIR = REPO_ROOT / "tests"
WEBVIEW_UI_DIR = REPO_ROOT / "worktrace" / "webview_ui"
JS_DIR = WEBVIEW_UI_DIR / "js"


# --- Invariant 1: view_model_service consumes display spans only ---


_LEGACY_VIRTUAL_SYMBOLS = (
    "build_virtual_session(",
    "build_virtual_detail_row(",
    "build_persisted_open_overlay(",
    "apply_persisted_open_overlay_to_row(",
)


def test_view_model_service_does_not_reference_legacy_virtual_builders():
    """``view_model_service.py`` must consume Activity Display Model
    spans instead of removed virtual-row builders."""
    vms_path = REPO_ROOT / "worktrace" / "services" / "view_model_service.py"
    source = vms_path.read_text(encoding="utf-8")
    for symbol in _LEGACY_VIRTUAL_SYMBOLS:
        assert symbol not in source, (
            "view_model_service.py must not reference removed helper "
            + symbol
            + " — the page ViewModel path consumes Activity Display "
              "Model spans only"
        )


# --- Invariant 2: view_model_api exposes ViewModel entry points only ---


def test_view_model_api_does_not_re_export_legacy_virtual_builders():
    """``worktrace.api.view_model_api`` must NOT re-export
    ``build_virtual_session`` / ``build_virtual_detail_row``. The bridge
    facade exposes low-level pure helpers and ViewModel getters."""
    import importlib

    # Bridge-facing live display entry points live in view_model_api.
    try:
        importlib.import_module("worktrace.api.live_display_api")
    except ModuleNotFoundError:
        pass
    else:
        raise AssertionError(
            "worktrace.api.live_display_api module must NOT exist anymore; "
            "all exports moved to worktrace.api.view_model_api"
        )

    from worktrace.api import view_model_api

    api_all = set(getattr(view_model_api, "__all__", []))
    for symbol in (
        "build_virtual_session",
        "build_virtual_detail_row",
        "build_persisted_open_overlay",
        "apply_persisted_open_overlay_to_row",
    ):
        assert symbol not in api_all, (
            "view_model_api.__all__ must not re-export " + symbol
        )
        assert not hasattr(view_model_api, symbol), (
            "view_model_api must not expose " + symbol + " as an attribute"
        )

    # The new view_model_api must export the canonical ViewModel entry points.
    for symbol in (
        "build_current_activity_summary",
        "compute_refresh_revision",
        "get_overview_view_model",
        "get_refresh_state_view_model",
        "get_session_details_view_model",
        "get_timeline_view_model",
    ):
        assert symbol in api_all or hasattr(view_model_api, symbol), (
            "view_model_api must export " + symbol
        )


# --- Invariant 3: tests do not import virtual builders as positive contract ---


# Pattern matches an actual import statement for removed builders.
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
    """No test under ``tests/`` may import
    ``build_virtual_session`` / ``build_virtual_detail_row`` as a POSITIVE
    contract. Tests should assert Activity Display Model / ViewModel
    materialization rather than scattered builder APIs."""
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
    """``overview.js`` must emit ``data-display-span-id``
    on every live recent row so the unified ticker can validate the
    accepted live runtime identity instead
    of reading a structural cache as a live-seconds source."""
    source = (JS_DIR / "overview.js").read_text(encoding="utf-8")
    assert "data-display-span-id" in source, (
        "overview.js must render recent live rows with the "
        "data-display-span-id attribute (unified live clock contract)"
    )


def test_timeline_js_renders_live_rows_with_display_span_id():
    """``timeline.js`` must emit ``data-display-span-id``
    on every live timeline session row AND every live detail row so the
    unified ticker can validate runtime identity for both surfaces."""
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


# --- Invariant reinforcement: live_display_service __all__ does not export builders ---


def test_live_display_service_all_does_not_export_legacy_virtual_builders():
    """The public ``__all__`` of
    ``worktrace.services.live_display_service`` must NOT include the
    removed virtual session / detail builders."""
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


# --- DB-only / report-only service boundary static tests ---


# Live-projection helpers that MUST NEVER appear in any DB-only service.
_LIVE_PROJECTION_FORBIDDEN_SYMBOLS = (
    "_read_current_activity_snapshot",
    "persisted_open_live_seconds",
    "snapshot_elapsed_seconds",
    "snapshot_extra_seconds",
)

# The settings key ``current_activity_snapshot`` is forbidden in
# timeline_service / statistics_service (strict DB-only). export_service
# may manage the settings key in its ``_destructive_reset_guard``
# (save / restore / clear during a destructive reset — settings mgmt).
_STRICT_DB_ONLY_SERVICES = (
    "worktrace/services/timeline_service.py",
    "worktrace/services/statistics_service.py",
)

_DB_ONLY_SERVICES = (
    "worktrace/services/timeline_service.py",
    "worktrace/services/statistics_service.py",
    "worktrace/services/export_service.py",
)


def test_db_only_services_do_not_read_current_activity_snapshot():
    """Section 七: DB-only services MUST NOT contain live-projection
    helpers (``_read_current_activity_snapshot``, ``persisted_open_live_seconds``,
    ``snapshot_elapsed_seconds``, ``snapshot_extra_seconds``).

    timeline_service / statistics_service also MUST NOT reference the
    ``current_activity_snapshot`` settings key. export_service may manage
    the key in ``_destructive_reset_guard`` (settings management, not
    live projection). Live projection is the sole responsibility of
    ``activity_display_model_service`` + ``view_model_service``.
    """
    offenders: list[str] = []
    for rel_path in _DB_ONLY_SERVICES:
        source = (REPO_ROOT / rel_path).read_text(encoding="utf-8")
        for symbol in _LIVE_PROJECTION_FORBIDDEN_SYMBOLS:
            if symbol in source:
                offenders.append(f"{rel_path}: {symbol}")
    for rel_path in _STRICT_DB_ONLY_SERVICES:
        source = (REPO_ROOT / rel_path).read_text(encoding="utf-8")
        if "current_activity_snapshot" in source:
            offenders.append(f"{rel_path}: current_activity_snapshot")
    assert not offenders, (
        "DB-only / report-only services MUST NOT reference live-projection "
        "symbols; offenders: " + "; ".join(offenders)
    )


def test_db_only_services_do_not_import_live_display_service():
    """Section 七: ``timeline_service.py`` / ``statistics_service.py`` /
    ``export_service.py`` MUST NOT import from ``live_display_service``
    or ``activity_display_model_service`` so the DB/report layer cannot
    accidentally invoke live-projection helpers."""
    forbidden_imports = (
        "from .live_display_service import",
        "from worktrace.services.live_display_service import",
        "from .activity_display_model_service import",
        "from worktrace.services.activity_display_model_service import",
    )
    offenders: list[str] = []
    for rel_path in _DB_ONLY_SERVICES:
        source = (REPO_ROOT / rel_path).read_text(encoding="utf-8")
        for symbol in forbidden_imports:
            if symbol in source:
                offenders.append(f"{rel_path}: {symbol}")
    assert not offenders, (
        "DB-only services MUST NOT import live_display_service / "
        "activity_display_model_service; offenders: " + "; ".join(offenders)
    )


# --- Section 七: frontend / bridge live-seconds derivation boundary ---


def test_bridge_does_not_derive_live_seconds_independently():
    """Section 七: the WebView bridge MUST NOT re-derive live duration.
    It may only call ``view_model_api`` entry points. The bridge source
    MUST NOT compute ``elapsed_seconds`` / ``persisted_open_live_seconds``
    / ``snapshot_elapsed_seconds`` directly."""
    bridge_dir = REPO_ROOT / "worktrace" / "webview_ui"
    forbidden_symbols = (
        "persisted_open_live_seconds",
        "snapshot_elapsed_seconds",
        "snapshot_extra_seconds",
        "_read_current_activity_snapshot",
    )
    offenders: list[str] = []
    for py_file in bridge_dir.glob("bridge*.py"):
        source = py_file.read_text(encoding="utf-8")
        for symbol in forbidden_symbols:
            if symbol in source:
                offenders.append(f"{py_file.name}: {symbol}")
    assert not offenders, (
        "bridge MUST NOT reference live-projection helpers; offenders: "
        + "; ".join(offenders)
    )


def test_frontend_js_ticker_only_reads_accepted_live_runtime():
    """Section 七: the frontend ticker MUST only read from the
    accepted live runtime (``App.liveRuntime`` via ``getActiveLiveClock``).
    It MUST NOT derive
    live seconds from ``lastOverviewSnapshot`` / ``lastTimelineData`` /
    ``lastRecentData`` / ``lastSessionDetailsViewModel`` — those are
    structural caches only, never a live-seconds source.

    This test verifies the ticker function body does not read these
    caches as a live-seconds source. The caches may be read for OTHER
    purposes (e.g. KPI base values) but never as the live-seconds
    source itself.
    """
    source = (JS_DIR / "core.js").read_text(encoding="utf-8")
    assert "getActiveLiveClock()" in source, (
        "core.js ticker must call getActiveLiveClock() to read the "
        "accepted live runtime"
    )
    assert "App.liveRuntime" in source, (
        "core.js must define App.liveRuntime as the accepted runtime"
    )
    for token in ("App.activeSpanClockByPage", "App.liveClockByPage", "App.liveClockBySpanId"):
        assert token not in source


def test_current_activity_clock_builder_is_removed():
    source = (
        REPO_ROOT / "worktrace" / "services" / "activity_display_model_service.py"
    ).read_text(encoding="utf-8")
    assert "return dict(live_clock)" not in source, (
        "the removed current activity clock path must not copy live_clock"
    )
    assert "def _build_current_activity_clock" not in source
    assert '"current_activity_clock"' not in source


def test_current_activity_elapsed_does_not_read_project_duration_sample():
    source = (
        REPO_ROOT / "worktrace" / "services" / "activity_display_model_service.py"
    ).read_text(encoding="utf-8")
    match = re.search(
        r"def\s+_build_current_activity_display\b(?P<body>.*?)(?=\ndef\s+_signature_project_dict\b)",
        source,
        re.S,
    )
    assert match is not None
    body = match.group("body")
    assert "current_elapsed = int(snapshot_elapsed_seconds(snapshot))" in body
    forbidden = (
        'live_clock.get("duration_seconds_at_sample")',
        "live_clock['duration_seconds_at_sample']",
    )
    for token in forbidden:
        assert token not in body, (
            "current_activity.elapsed_seconds must use snapshot elapsed, "
            "not the project display live_clock sample"
        )


def test_activity_display_model_remains_single_display_semantics_owner():
    forbidden_service_names = (
        "current_timer_service.py",
        "recent_timer_service.py",
        "timeline_timer_service.py",
        "current_live_projection_service.py",
        "recent_live_projection_service.py",
    )
    offenders = [
        path.name
        for path in (REPO_ROOT / "worktrace" / "services").glob("*.py")
        if path.name in forbidden_service_names
    ]
    assert not offenders, (
        "Activity Display Model must remain the display semantics owner; "
        "unexpected live projection services: " + ", ".join(offenders)
    )


def test_persisted_open_overlay_does_not_reverse_engineer_base_from_db_duration():
    source = (
        REPO_ROOT / "worktrace" / "services" / "activity_display_model_service.py"
    ).read_text(encoding="utf-8")
    match = re.search(
        r"if state == \"persisted_open\":(?P<body>.*?)(?=\n    else:)",
        source,
        re.S,
    )
    assert match is not None
    branch = match.group("body")
    assert "row_raw" not in branch
    for token in (
        "row_raw - current_elapsed_at_sample",
        "row_raw - active_elapsed_at_sample",
        "int(row_raw) - current_elapsed_at_sample",
        "int(row_raw) - active_elapsed_at_sample",
    ):
        assert token not in source


def test_current_live_projection_branch_never_uses_aggregate_base_fields():
    source = (
        REPO_ROOT / "worktrace" / "services" / "activity_display_model_service.py"
    ).read_text(encoding="utf-8")
    match = re.search(
        r"if semantic == CURRENT_LIVE:(?P<body>.*?)(?=\n    else:)",
        source,
        re.S,
    )
    assert match is not None
    branch = match.group("body")
    assert 'row["display_base_seconds"] = 0' in branch
    assert 'row["live_base_seconds"] = 0' in branch
    for token in (
        "closed_duration_seconds",
        "snapshot_extra_seconds",
        "aggregate_display_base_seconds",
        "aggregate_base",
    ):
        assert token not in branch


def test_live_projection_function_requires_row_kind_contract():
    source = (
        REPO_ROOT / "worktrace" / "services" / "activity_display_model_service.py"
    ).read_text(encoding="utf-8")
    signature = re.search(
        r"def\s+apply_live_span_to_row\((?P<body>.*?)\)\s*->\s*dict\[str,\s*Any\]:",
        source,
        re.S,
    )
    assert signature is not None
    assert "row_kind: str" in signature.group("body")
    assert "duration_semantic:" not in signature.group("body")
    assert "def _duration_semantic_for_row_kind" in source


def test_session_projection_branch_does_not_overwrite_session_start_time():
    source = (
        REPO_ROOT / "worktrace" / "services" / "activity_display_model_service.py"
    ).read_text(encoding="utf-8")
    match = re.search(
        r"if state == \"persisted_open\":(?P<body>.*?)(?=\n    return row)",
        source,
        re.S,
    )
    assert match is not None
    branch = match.group("body")
    assert 'if row_kind in _CURRENT_LIVE_ROW_KINDS:' in branch
    assert 'row["start_time"] = str(span.get("start_time")' in branch


def test_viewmodel_no_visible_hidden_live_projection_dual_track():
    source = (
        REPO_ROOT / "worktrace" / "services" / "view_model_service.py"
    ).read_text(encoding="utf-8")
    for token in (
        "display_rows",
        "aggregate_rows",
        "duration_semantic=CURRENT_LIVE",
        "duration_semantic=AGGREGATE_LIVE",
    ):
        assert token not in source


def test_viewmodel_and_bridge_do_not_reintroduce_independent_live_clock_fields():
    forbidden = (
        "baseline_epoch_ms",
        "snapshot_at_epoch_ms",
        "snapshot_baseline_epoch_ms",
    )
    offenders = []
    for rel_path in (
        "worktrace/services/view_model_service.py",
        "worktrace/webview_ui/bridge.py",
        "worktrace/webview_ui/bridge_common.py",
        "worktrace/webview_ui/bridge_overview.py",
        "worktrace/webview_ui/bridge_timeline.py",
    ):
        source = (REPO_ROOT / rel_path).read_text(encoding="utf-8")
        for token in forbidden:
            if token in source:
                offenders.append(f"{rel_path}: {token}")
    assert not offenders, (
        "ViewModel / bridge must not publish an independent live clock; "
        + "; ".join(offenders)
    )
