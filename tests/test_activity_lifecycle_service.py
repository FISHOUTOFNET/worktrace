"""ActivityLifecycle Command Facade contract tests.

These tests verify the architecture invariants for the open-row state
machine (see architecture.md §"Write side"):

- ``activity_lifecycle_service`` is the sole command owner for open-row
  lifecycle transitions.
- ``activity_service`` is a pure low-level CRUD helper: ``create_activity``
  does NOT close pre-existing open rows and does NOT run project inference.
  Production open-row lifecycle must use ``activity_lifecycle_service``.
- ``start_activity`` closes pre-existing open rows, finalizes them via
  the unified ``finalize_closed_activity_ids`` helper, then inserts the
  new open row.
- Manual assignments / ``manual_override`` are never overridden.
- Clipboard force-persist bypasses the 30-second threshold but is
  restricted to ``STATUS_NORMAL``; it does not pollute the normal
  threshold.
- Midnight split / midnight-anchor persistence preserves the anchor
  project assignment.
- Recovery cross-midnight no longer retains a second unconverged
  lifecycle path.
- An inference failure on one row does not block the remaining rows.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from worktrace.constants import (
    SOURCE_AUTO,
    STATUS_NORMAL,
    TIME_FORMAT,
    UNCATEGORIZED_PROJECT,
)
from worktrace.services import (
    activity_service,
    folder_rule_service,
    project_service,
    recovery_service,
    session_boundary_service,
    settings_service,
)
from worktrace.services.activity_lifecycle_service import (
    close_activity as lifecycle_close_activity,
    finalize_closed_activity_ids,
    force_persist_open_activity_for_clipboard,
    persist_midnight_anchor,
    persist_open_activity_if_ready,
    recover_cross_midnight_segment,
    start_activity,
)
from worktrace.services.project_inference_service import (
    get_assignment_for_activity,
    sync_persisted_open_activity_project,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def temp_db_setup(temp_db):
    """Common setup: clear settings cache + accept first-run notice."""
    settings_service.clear_settings_cache()
    settings_service.set_setting("first_run_notice_accepted", "true")
    settings_service.clear_settings_cache()
    return temp_db


# ---------------------------------------------------------------------------
# start_activity closes old open rows + triggers inference
# ---------------------------------------------------------------------------


def test_start_activity_finalizes_closed_rows_with_folder_rule(temp_db_setup):
    """``start_activity`` closes pre-existing open rows and finalizes them
    via the unified ``finalize_closed_activity_ids`` helper so project
    inference / automatic rules converge on every closed row.

    Setup: a folder rule that maps ``D:\\ProjA`` to a concrete project.
    An open activity with ``file_path_hint`` under that folder is created
    via the low-level ``create_activity`` helper. A subsequent
    ``start_activity`` call closes the first row and finalizes it. The
    first row's assignment must converge to the concrete project (not stay
    ``uncategorized``).
    """
    pid = project_service.create_project("ProjA")
    folder_rule_service.create_or_update_folder_rule("D:\\ProjA", pid)

    # Create an open activity whose file_path_hint matches the folder rule.
    first = activity_service.create_activity(
        "Word", "winword.exe", "Doc",
        start_time="2026-07-01 09:00:00",
        file_path_hint="D:\\ProjA\\spec.docx",
    )
    # The open row is uncategorized (process_new_activity skips in-progress).
    assert activity_service.get_activity(first)["project_name"] == UNCATEGORIZED_PROJECT

    # start_activity closes the first row via the lifecycle facade.
    second = start_activity(
        start_time="2026-07-01 09:10:00",
        source=SOURCE_AUTO,
        payload={
            "app_name": "Mail",
            "process_name": "mail.exe",
            "window_title": "Inbox",
            "status": STATUS_NORMAL,
        },
    )

    # The first row must now be closed.
    first_row = activity_service.get_activity(first)
    assert first_row["end_time"] == "2026-07-01 09:10:00"

    # The first row's assignment must have converged to the concrete
    # project via finalize_closed_activity_ids.
    assignment = get_assignment_for_activity(first)
    assert int(assignment["project_id"]) == pid
    assert assignment["source"] == "folder_rule"

    # The second row is the current open row.
    assert activity_service.get_activity(second)["end_time"] is None


def test_start_activity_finalizes_closed_rows_manual_not_overridden(temp_db_setup):
    """Manual assignments must NOT be overridden by the close-finalize
    inference. The ``process_new_activity`` guard skips manual rows."""
    manual_pid = project_service.create_project("ManualProj")
    auto_pid = project_service.create_project("AutoProj")
    folder_rule_service.create_or_update_folder_rule("D:\\AutoFolder", auto_pid)

    # Create an open activity with a MANUAL project assignment.
    first = activity_service.create_activity(
        "Word", "winword.exe", "Doc",
        start_time="2026-07-01 09:00:00",
        file_path_hint="D:\\AutoFolder\\spec.docx",
        project_id=manual_pid,
    )
    # The manual assignment is present.
    assert activity_service.get_activity(first)["project_name"] == "ManualProj"

    # start_activity closes the first row via the lifecycle facade.
    start_activity(
        start_time="2026-07-01 09:10:00",
        source=SOURCE_AUTO,
        payload={
            "app_name": "Mail",
            "process_name": "mail.exe",
            "window_title": "Inbox",
            "status": STATUS_NORMAL,
        },
    )

    # The manual assignment must NOT be overridden by the folder rule.
    assignment = get_assignment_for_activity(first)
    assert int(assignment["project_id"]) == manual_pid
    assert assignment["is_manual"] == 1


def test_create_activity_no_open_rows_does_not_fail(temp_db_setup):
    """When there are no open rows, create_activity must not fail."""
    aid = activity_service.create_activity(
        "App", "app.exe", "Title",
        start_time="2026-07-01 09:00:00",
    )
    assert activity_service.get_activity(aid) is not None


# ---------------------------------------------------------------------------
# lifecycle.close_activity triggers inference
# ---------------------------------------------------------------------------


def test_lifecycle_close_activity_triggers_inference(temp_db_setup):
    """``lifecycle_close_activity`` must route through the unified
    close-finalize helper so project inference runs on the closed row."""
    pid = project_service.create_project("ProjB")
    folder_rule_service.create_or_update_folder_rule("D:\\ProjB", pid)

    aid = activity_service.create_activity(
        "Word", "winword.exe", "Doc",
        start_time="2026-07-01 09:00:00",
        file_path_hint="D:\\ProjB\\spec.docx",
    )
    lifecycle_close_activity(aid, "2026-07-01 09:30:00")

    assignment = get_assignment_for_activity(aid)
    assert int(assignment["project_id"]) == pid
    assert assignment["source"] == "folder_rule"


# ---------------------------------------------------------------------------
# lifecycle.persist_open_activity_if_ready
# ---------------------------------------------------------------------------


def test_persist_open_activity_if_ready_syncs_open_row_project(temp_db_setup):
    """``persist_open_activity_if_ready`` must create + finalize + sync
    the open-row project so the virtual → persisted_open transition does
    not revert a concrete inferred project to ``uncategorized``."""
    pid = project_service.create_project("ProjC")
    folder_rule_service.create_or_update_folder_rule("D:\\ProjC", pid)

    payload = {
        "app_name": "Word",
        "process_name": "winword.exe",
        "window_title": "Doc",
        "file_path_hint": "D:\\ProjC\\spec.docx",
        "status": STATUS_NORMAL,
    }
    aid = persist_open_activity_if_ready(
        start_time="2026-07-01 09:00:00",
        source=SOURCE_AUTO,
        payload=payload,
    )

    # The open row's project must have converged to the concrete project.
    assignment = get_assignment_for_activity(aid)
    assert int(assignment["project_id"]) == pid
    assert assignment["source"] == "folder_rule"
    # The row is still open.
    assert activity_service.get_activity(aid)["end_time"] is None


def test_force_persist_open_activity_for_clipboard_creates_open_row(temp_db_setup):
    """``force_persist_open_activity_for_clipboard`` must create an open
    row (bypassing the 30-second threshold). The threshold gate lives in
    the caller, not the facade."""
    payload = {
        "app_name": "Word",
        "process_name": "winword.exe",
        "window_title": "Doc",
        "status": STATUS_NORMAL,
    }
    aid = force_persist_open_activity_for_clipboard(
        start_time="2026-07-01 09:00:00",
        source=SOURCE_AUTO,
        payload=payload,
    )
    row = activity_service.get_activity(aid)
    assert row is not None
    assert row["end_time"] is None


# ---------------------------------------------------------------------------
# lifecycle.persist_midnight_anchor
# ---------------------------------------------------------------------------


def test_persist_midnight_anchor_applies_midnight_anchor_assignment(temp_db_setup):
    """``persist_midnight_anchor`` must create an open row and apply the
    ``midnight_anchor`` assignment source (confidence 90)."""
    pid = project_service.create_project("ProjD")
    payload = {
        "app_name": "Word",
        "process_name": "winword.exe",
        "window_title": "Doc",
        "status": STATUS_NORMAL,
    }
    aid = persist_midnight_anchor(
        start_time="2026-07-01 00:00:00",
        source=SOURCE_AUTO,
        payload=payload,
        project_id=pid,
    )
    assignment = get_assignment_for_activity(aid)
    assert int(assignment["project_id"]) == pid
    assert assignment["source"] == "midnight_anchor"
    # The row is still open.
    assert activity_service.get_activity(aid)["end_time"] is None


# ---------------------------------------------------------------------------
# lifecycle.recover_cross_midnight_segment
# ---------------------------------------------------------------------------


def test_recover_cross_midnight_segment_creates_and_closes(temp_db_setup):
    """``recover_cross_midnight_segment`` must create + close a segment
    with the midnight_anchor assignment when a concrete project_id is
    provided."""
    pid = project_service.create_project("ProjE")
    payload = {
        "app_name": "Word",
        "process_name": "winword.exe",
        "window_title": "Doc",
    }
    aid = recover_cross_midnight_segment(
        start_time="2026-07-01 00:00:00",
        end_time="2026-07-01 02:00:00",
        source=SOURCE_AUTO,
        status=STATUS_NORMAL,
        payload=payload,
        project_id=pid,
    )
    row = activity_service.get_activity(aid)
    assert row["end_time"] == "2026-07-01 02:00:00"
    assert int(row["duration_seconds"]) == 7200

    assignment = get_assignment_for_activity(aid)
    assert int(assignment["project_id"]) == pid
    assert assignment["source"] == "midnight_anchor"


# ---------------------------------------------------------------------------
# Recovery cross-midnight convergence (no second lifecycle path)
# ---------------------------------------------------------------------------


def test_recovery_cross_midnight_converges_project(temp_db_setup):
    """Recovery cross-midnight must route through the lifecycle facade
    so the recovered segments carry the midnight_anchor assignment
    (no second unconverged lifecycle path)."""
    pid = project_service.create_project("ProjF")
    settings_service.set_setting("last_collector_heartbeat", "2026-07-02 00:10:00")
    aid = activity_service.create_activity(
        "Word", "word.exe", "Doc",
        project_id=pid,
        start_time="2026-07-01 23:50:00",
    )

    recovery_service.recover_unclosed_records()

    first = activity_service.get_activity(aid)
    assert first["end_time"] == "2026-07-02 00:00:00"
    assert first["duration_seconds"] == 10 * 60

    rows = activity_service.get_activities_by_date("2026-07-02")
    assert len(rows) == 1
    assert rows[0]["start_time"] == "2026-07-02 00:00:00"
    assert rows[0]["end_time"] == "2026-07-02 00:10:00"
    assert rows[0]["project_id"] == pid
    # The recovered segment must carry the midnight_anchor assignment.
    segment_assignment = get_assignment_for_activity(rows[0]["id"])
    assert segment_assignment["source"] == "midnight_anchor"


# ---------------------------------------------------------------------------
# finalize_closed_activity_ids resilience
# ---------------------------------------------------------------------------


def test_finalize_closed_activity_ids_empty_list_is_noop(temp_db_setup):
    """An empty closed_ids list must be a safe no-op."""
    finalize_closed_activity_ids([])
    finalize_closed_activity_ids(None)  # type: ignore[arg-type]


def test_finalize_closed_activity_ids_inference_failure_does_not_block(temp_db_setup, monkeypatch):
    """An inference failure on one row must not block the remaining rows.

    We monkeypatch ``process_new_activity`` to raise on the first call
    and succeed on subsequent calls. Both rows must be finalized (the
    second row must not be skipped)."""
    pid = project_service.create_project("ProjG")
    folder_rule_service.create_or_update_folder_rule("D:\\ProjG", pid)

    aid1 = activity_service.create_activity(
        "Word", "winword.exe", "Doc1",
        start_time="2026-07-01 09:00:00",
        file_path_hint="D:\\ProjG\\a.docx",
    )
    aid2 = activity_service.create_activity(
        "Word", "winword.exe", "Doc2",
        start_time="2026-07-01 09:10:00",
        file_path_hint="D:\\ProjG\\b.docx",
    )
    # Close both rows explicitly via the lifecycle facade (create_activity
    # is now a pure low-level insert and does NOT close pre-existing rows).
    lifecycle_close_activity(aid1, "2026-07-01 09:05:00")
    lifecycle_close_activity(aid2, "2026-07-01 09:20:00")

    # We verify that finalize_closed_activity_ids doesn't raise even
    # if one row's inference fails.

    call_count = [0]
    original = activity_service.finalize_created_activity

    def flaky_process_new_activity(activity_id):
        call_count[0] += 1
        if call_count[0] == 1:
            raise RuntimeError("simulated inference failure")
        # Subsequent calls: do nothing (the assignment is already set)

    import worktrace.services.project_inference_service as pis

    original_pna = pis.process_new_activity
    monkeypatch.setattr(pis, "process_new_activity", flaky_process_new_activity)

    # Must not raise even though the first row's inference fails.
    finalize_closed_activity_ids([aid1, aid2])

    monkeypatch.setattr(pis, "process_new_activity", original_pna)
    assert call_count[0] == 2  # Both rows were attempted


# ---------------------------------------------------------------------------
# 30-second threshold preservation (collector behavior unchanged)
# ---------------------------------------------------------------------------


def test_persist_open_activity_if_ready_does_not_recheck_threshold(temp_db_setup):
    """The lifecycle facade does NOT re-check the 30-second threshold.
    The threshold gate lives in the caller (AutoActivityRecorder).
    The facade executes the persist command unconditionally once called."""
    from worktrace.constants import HISTORY_PERSIST_THRESHOLD_SECONDS

    payload = {
        "app_name": "Word",
        "process_name": "winword.exe",
        "window_title": "Doc",
        "status": STATUS_NORMAL,
    }
    # Even with a 0-second elapsed, the facade persists (threshold is
    # the caller's responsibility).
    aid = persist_open_activity_if_ready(
        start_time="2026-07-01 09:00:00",
        source=SOURCE_AUTO,
        payload=payload,
    )
    assert activity_service.get_activity(aid) is not None
    # The threshold constant is unchanged.
    assert HISTORY_PERSIST_THRESHOLD_SECONDS == 30
