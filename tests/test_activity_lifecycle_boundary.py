"""Static boundary tests for the ActivityLifecycle Command Facade architecture.

These tests enforce the architecture invariants established by the
ActivityLifecycle hard cutover (see architecture.md §"Write side"):

- ``activity_lifecycle_service`` is the sole production command owner for
  open-row lifecycle transitions (start / persist / close / close-all /
  midnight / recovery).
- ``activity_service`` is a pure low-level CRUD helper: it must NOT import
  ``activity_lifecycle_service`` and its low-level lifecycle helpers
  (``create_activity`` / ``close_activity``) must NOT be called from
  production paths for open-row lifecycle.
- Production callers (collector / state_machine / runtime / recovery) must
  NOT use direct SQL ``UPDATE activity_log SET end_time`` to close open rows;
  they must route through ``activity_lifecycle_service``.
- ``activity_lifecycle_service`` must NOT delegate close-finalize to the
  old ``activity_service.close_activity()`` method; it owns the close +
  finalize itself.
- ``recovery_service`` must NOT close open rows via direct SQL; it must
  delegate to the lifecycle recovery helpers.

These are static source-level checks so they run without a database and
guard against architectural regression.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SERVICES_DIR = REPO_ROOT / "worktrace" / "services"
COLLECTOR_DIR = REPO_ROOT / "worktrace" / "collector"
RUNTIME_DIR = REPO_ROOT / "worktrace" / "runtime"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# activity_service must not import activity_lifecycle_service
# ---------------------------------------------------------------------------


def test_activity_service_does_not_import_activity_lifecycle_service() -> None:
    """``activity_service`` is a low-level CRUD helper. It must NOT import
    ``activity_lifecycle_service`` — that would re-create the circular /
    layered coupling the hard cutover removed. The lifecycle facade depends
    on the CRUD helper, never the reverse."""
    source = _read(SERVICES_DIR / "activity_service.py")
    for forbidden in (
        "import activity_lifecycle_service",
        "from .activity_lifecycle_service import",
        "from worktrace.services.activity_lifecycle_service import",
    ):
        assert forbidden not in source, (
            "activity_service.py must not import activity_lifecycle_service; "
            "it is a low-level CRUD helper, not a lifecycle owner. Found: "
            + forbidden
        )


# ---------------------------------------------------------------------------
# activity_lifecycle_service must not delegate close-finalize to old methods
# ---------------------------------------------------------------------------


def test_activity_lifecycle_service_does_not_call_old_lifecycle_close_methods() -> None:
    """``activity_lifecycle_service`` must own close + finalize itself. It
    must NOT delegate the close-finalize step to the old
    ``activity_service.close_activity()`` /
    ``activity_service.create_activity()`` methods — those are low-level
    CRUD helpers that no longer carry lifecycle semantics.

    The facade IS allowed to call low-level helpers
    (``close_all_open_rows`` / ``close_activity_row`` /
    ``insert_activity_row`` / ``finalize_created_activity`` /
    ``apply_midnight_anchor_assignment``) because those are pure CRUD
    writes with no lifecycle semantics."""
    source = _read(SERVICES_DIR / "activity_lifecycle_service.py")
    for forbidden in (
        "activity_service.close_activity(",
        "activity_service.create_activity(",
    ):
        assert forbidden not in source, (
            "activity_lifecycle_service.py must not delegate to the old "
            "lifecycle method " + forbidden + "; it must own close + "
            "finalize itself via low-level helpers."
        )


# ---------------------------------------------------------------------------
# collector / state_machine must route close-all through the lifecycle facade
# ---------------------------------------------------------------------------


def test_state_machine_routes_close_all_through_lifecycle_facade() -> None:
    """``collector/state_machine.py`` stopped / paused / time_jump paths
    must use ``activity_lifecycle_service.close_all_open_activities(...)``
    to close open rows. ``activity_service`` low-level helpers must NOT be
    called directly for close-all."""
    source = _read(COLLECTOR_DIR / "state_machine.py")
    # The state machine must route close-all through the lifecycle facade.
    assert "activity_lifecycle_service.close_all_open_activities" in source, (
        "state_machine.py must call activity_lifecycle_service.close_all_open_activities "
        "for stopped / paused / time_jump close-all"
    )


# ---------------------------------------------------------------------------
# runtime / app_runtime must route close-all through the lifecycle facade
# ---------------------------------------------------------------------------


def test_app_runtime_routes_close_all_through_lifecycle_facade() -> None:
    """``runtime/app_runtime.py`` shutdown must use
    ``activity_lifecycle_service.close_all_open_activities(...)`` to close
    open rows. The runtime should not import ``activity_service`` just for
    close-all."""
    source = _read(RUNTIME_DIR / "app_runtime.py")
    # The runtime must route shutdown close-all through the lifecycle facade.
    assert "activity_lifecycle_service.close_all_open_activities" in source, (
        "app_runtime.py must call activity_lifecycle_service.close_all_open_activities "
        "for shutdown close-all"
    )


# ---------------------------------------------------------------------------
# recovery_service must not close open rows via direct SQL
# ---------------------------------------------------------------------------


def test_recovery_service_does_not_direct_sql_close_open_row() -> None:
    """``recovery_service.py`` non-cross-midnight recovery must NOT close
    open rows via direct SQL ``UPDATE activity_log SET end_time``. It must
    delegate to ``activity_lifecycle_service.recover_close_activity`` (or
    the cross-midnight helpers) so the close + finalize is owned by the
    lifecycle facade.

    This static check scans for the direct-SQL close pattern. The recovery
    service IS allowed to READ open rows and compute durations / cross-
    midnight splits; only the actual close write must go through the
    lifecycle facade."""
    source = _read(SERVICES_DIR / "recovery_service.py")
    # The direct-SQL close pattern: UPDATE activity_log SET end_time
    # (with optional whitespace / case variation).
    pattern = re.compile(
        r"UPDATE\s+activity_log\s+SET\s+end_time",
        re.IGNORECASE,
    )
    assert pattern.search(source) is None, (
        "recovery_service.py must not close open rows via direct SQL "
        "'UPDATE activity_log SET end_time'; use "
        "activity_lifecycle_service.recover_close_activity instead"
    )
    # The recovery service must import the lifecycle recovery helpers.
    assert "recover_close_activity" in source, (
        "recovery_service.py must import recover_close_activity from "
        "activity_lifecycle_service for the non-cross-midnight path"
    )


def test_recovery_service_does_not_call_old_close_entries() -> None:
    """``recovery_service.py`` must not call the old
    ``activity_service.close_activity()`` for recovery close. It must use
    the lifecycle recovery helpers."""
    source = _read(SERVICES_DIR / "recovery_service.py")
    for forbidden in (
        "activity_service.close_activity(",
    ):
        assert forbidden not in source, (
            "recovery_service.py must not call " + forbidden + "; use "
            "activity_lifecycle_service recovery helpers instead"
        )


# ---------------------------------------------------------------------------
# activity_service low-level helpers must not carry finalize semantics
# ---------------------------------------------------------------------------


def test_activity_service_close_methods_do_not_call_finalize() -> None:
    """The ``activity_service.close_activity()`` method is a low-level CRUD
    helper for tests / fixtures. It must NOT call
    ``finalize_closed_activity_ids`` or
    ``project_inference_service.process_new_activity`` — those lifecycle
    semantics live only in the lifecycle facade now.

    Note: the function docstrings may *mention* ``activity_lifecycle_service``
    as a reference (telling developers which facade to use instead); that is
    a docstring reference, not an actual call. The import-level boundary is
    enforced by ``test_activity_service_does_not_import_activity_lifecycle_service``.
    This test checks for actual finalize / inference *calls*."""
    source = _read(SERVICES_DIR / "activity_service.py")
    # Locate the close_activity function body and verify it does not
    # call the finalize helper or project inference.
    for func_name in ("close_activity",):
        pos = source.find("def " + func_name + "(")
        if pos == -1:
            continue  # function may have been removed entirely — that's fine
        # Slice to the next top-level def.
        next_def = source.find("\ndef ", pos + 1)
        body = source[pos:next_def if next_def != -1 else pos + 3000]
        for forbidden in (
            "finalize_closed_activity_ids",
            "process_new_activity",
        ):
            assert forbidden not in body, (
                func_name + " must not call " + forbidden + "; "
                "close-finalize semantics live only in activity_lifecycle_service"
            )


def test_activity_service_create_activity_does_not_close_old_rows() -> None:
    """``activity_service.create_activity()`` is a pure low-level insert.
    It must NOT close pre-existing open rows — that is the responsibility
    of ``activity_lifecycle_service.start_activity``."""
    source = _read(SERVICES_DIR / "activity_service.py")
    pos = source.find("def create_activity(")
    assert pos != -1, "activity_service must define create_activity"
    next_def = source.find("\ndef ", pos + 1)
    body = source[pos:next_def if next_def != -1 else pos + 3000]
    # Must not call close_all_open_rows / close_activity_row inside
    # create_activity (closing old rows is the lifecycle facade's job).
    for forbidden in (
        "close_all_open_rows",
        "close_activity_row",
        "finalize_closed_activity_ids",
    ):
        assert forbidden not in body, (
            "create_activity must not call " + forbidden + "; it is a pure "
            "low-level insert. Closing pre-existing open rows is the job "
            "of activity_lifecycle_service.start_activity"
        )
