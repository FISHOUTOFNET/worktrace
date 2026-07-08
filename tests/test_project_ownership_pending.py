"""Project ownership pending state machine tests.

Locks the display-level project ownership fields:

- **Resource identity immediate** — a resource switch is reflected in the
  snapshot's ``resource_display_name`` / ``activity_display_name`` right
  away; the UI must NOT continue to show the old resource.
- **Project ownership delayed** — when the new resource's candidate
  project differs from the last confirmed project, a 30-second pending
  window starts. During pending:
    * ``display_project`` continues to show the last confirmed project;
    * ``candidate_project`` holds the new resource's inferred project;
    * ``project_transition.pending`` is ``True``.
  After 30 seconds the candidate is confirmed and becomes the display
  project (``pending = False``).
- **History persistence independent** — clipboard force-persist can turn
  a virtual activity into ``persisted_open`` BEFORE the 30-second
  ownership threshold, but the live display still follows
  ``display_project`` until the pending window elapses. The two concerns
  (DB persistence / project ownership) are intentionally orthogonal.
- **Session boundaries** — pause / stop / midnight split / restart
  recovery clear the ownership state so the previous session's display
  project is NOT inherited into a new session.

These tests do NOT assert on the short-activity blind merge policy —
that is locked separately in ``test_short_activity_buffer.py`` and is
intentionally project-blind.
"""

from __future__ import annotations

import json

from worktrace.collector.state_machine import CollectorStateMachine
from worktrace.platforms.base import ActiveWindow
from worktrace.services import folder_rule_service, project_service, settings_service
import pytest

pytestmark = [pytest.mark.db, pytest.mark.live_display, pytest.mark.contract]


def _snapshot() -> dict:
    raw = settings_service.get_setting("current_activity_snapshot", "") or ""
    if not raw:
        return {}
    return json.loads(raw)


def _normal(title: str, app: str = "Code", process: str = "code.exe", path: str | None = None) -> ActiveWindow:
    return ActiveWindow(app, process, title, file_path_hint=path)


def _setup_two_projects(temp_db):
    """Create two projects with folder rules so resource switches produce
    different candidate projects."""
    project_a = project_service.create_project("ProjectA")
    project_b = project_service.create_project("ProjectB")
    folder_rule_service.create_or_update_folder_rule("D:\\ProjectA", project_a)
    folder_rule_service.create_or_update_folder_rule("D:\\ProjectB", project_b)
    return project_a, project_b


def test_resource_switch_under_30s_shows_new_resource_but_inherited_display_project(temp_db):
    """Section 一.1 / 一.2: <30s after a resource switch the snapshot's
    resource fields reflect the NEW resource, but ``display_project`` is
    still the last confirmed project and ``project_transition.pending``
    is ``True``."""
    project_a, project_b = _setup_two_projects(temp_db)
    machine = CollectorStateMachine()
    # First resource: ProjectA folder. First activity has no prior
    # confirmed project, so display == candidate immediately (no pending).
    machine.transition_to(
        "recording",
        _normal("a.py", path="D:\\ProjectA\\a.py"),
        at_time="2026-06-18 09:00:00",
    )
    snap = _snapshot()
    assert snap["display_project"]["name"] == "ProjectA"
    assert snap["candidate_project"]["name"] == "ProjectA"
    assert snap["project_transition"]["pending"] is False

    # Continue ProjectA past 30s so it becomes the confirmed project.
    machine.transition_to(
        "recording",
        _normal("a.py", path="D:\\ProjectA\\a.py"),
        at_time="2026-06-18 09:00:35",
    )
    snap = _snapshot()
    assert snap["display_project"]["name"] == "ProjectA"
    assert snap["project_transition"]["pending"] is False

    # Switch to ProjectB resource. Resource identity is immediate;
    # project ownership enters the 30-second pending window.
    machine.transition_to(
        "recording",
        _normal("b.py", path="D:\\ProjectB\\b.py"),
        at_time="2026-06-18 09:00:36",
    )
    snap = _snapshot()
    assert snap["activity_display_name"] == "b.py"
    assert snap["resource_display_name"] == "b.py"
    # Project ownership delayed: display stays as last confirmed (ProjectA),
    # candidate is the new project (ProjectB), pending is True.
    assert snap["display_project"]["name"] == "ProjectA"
    assert snap["candidate_project"]["name"] == "ProjectB"
    assert snap["project_transition"]["pending"] is True
    assert snap["project_transition"]["from_project_id"] == project_a
    assert snap["project_transition"]["to_project_id"] == project_b
    assert snap["project_transition_pending"] is True


def test_candidate_confirmed_after_30_seconds_when_different(temp_db):
    """>=30s after the switch, when the candidate differs
    from the last confirmed project, the candidate is confirmed and
    becomes the display project (``pending = False``)."""
    _setup_two_projects(temp_db)
    machine = CollectorStateMachine()
    machine.transition_to(
        "recording",
        _normal("a.py", path="D:\\ProjectA\\a.py"),
        at_time="2026-06-18 09:00:00",
    )
    machine.transition_to(
        "recording",
        _normal("a.py", path="D:\\ProjectA\\a.py"),
        at_time="2026-06-18 09:00:35",
    )
    machine.transition_to(
        "recording",
        _normal("b.py", path="D:\\ProjectB\\b.py"),
        at_time="2026-06-18 09:00:36",
    )
    assert _snapshot()["project_transition"]["pending"] is True
    # 29 seconds into the pending window — still pending.
    machine.transition_to(
        "recording",
        _normal("b.py", path="D:\\ProjectB\\b.py"),
        at_time="2026-06-18 09:01:05",
    )
    assert _snapshot()["project_transition"]["pending"] is True
    # 30 seconds into the pending window — candidate confirmed.
    machine.transition_to(
        "recording",
        _normal("b.py", path="D:\\ProjectB\\b.py"),
        at_time="2026-06-18 09:01:06",
    )
    snap = _snapshot()
    assert snap["display_project"]["name"] == "ProjectB"
    assert snap["candidate_project"]["name"] == "ProjectB"
    assert snap["project_transition"]["pending"] is False
    assert snap["project_transition_pending"] is False


def test_candidate_same_as_last_confirmed_no_pending(temp_db):
    """when the candidate matches the last confirmed
    project, no pending window opens — the display project is unchanged
    and ``pending`` stays ``False``."""
    _setup_two_projects(temp_db)
    machine = CollectorStateMachine()
    machine.transition_to(
        "recording",
        _normal("a1.py", path="D:\\ProjectA\\a1.py"),
        at_time="2026-06-18 09:00:00",
    )
    machine.transition_to(
        "recording",
        _normal("a1.py", path="D:\\ProjectA\\a1.py"),
        at_time="2026-06-18 09:00:35",
    )
    # Switch to a different resource that maps to the SAME project.
    machine.transition_to(
        "recording",
        _normal("a2.py", path="D:\\ProjectA\\a2.py"),
        at_time="2026-06-18 09:00:36",
    )
    snap = _snapshot()
    assert snap["activity_display_name"] == "a2.py"
    # No pending window because candidate == last confirmed.
    assert snap["display_project"]["name"] == "ProjectA"
    assert snap["candidate_project"]["name"] == "ProjectA"
    assert snap["project_transition"]["pending"] is False


def test_uncategorized_candidate_under_30s_inherits_last_confirmed(temp_db):
    """when the new resource's candidate is uncategorized,
    the display project continues to show the last confirmed project.
    No pending transition is created (transitions only happen between
    official candidates)."""
    project_a, _ = _setup_two_projects(temp_db)
    machine = CollectorStateMachine()
    machine.transition_to(
        "recording",
        _normal("a.py", path="D:\\ProjectA\\a.py"),
        at_time="2026-06-18 09:00:00",
    )
    machine.transition_to(
        "recording",
        _normal("a.py", path="D:\\ProjectA\\a.py"),
        at_time="2026-06-18 09:00:35",
    )
    # Switch to a resource with NO folder rule -> uncategorized candidate.
    machine.transition_to(
        "recording",
        _normal("tmp", path="D:\\Unmapped\\tmp"),
        at_time="2026-06-18 09:00:36",
    )
    snap = _snapshot()
    assert snap["activity_display_name"] == "tmp"
    # Display stays as last confirmed; candidate is uncategorized.
    assert snap["display_project"]["name"] == "ProjectA"
    assert snap["candidate_project"]["is_uncategorized"] is True
    assert snap["candidate_project"]["name"] == "未归类"
    assert snap["project_transition"]["pending"] is False


def test_uncategorized_candidate_stays_inherited_after_30_seconds(temp_db):
    """>=30s after the switch to an uncategorized
    candidate, the display project continues to show the last confirmed
    project. Non-official candidates are NEVER confirmed via
    advance_ownership — the display does not switch to uncategorized."""
    _setup_two_projects(temp_db)
    machine = CollectorStateMachine()
    machine.transition_to(
        "recording",
        _normal("a.py", path="D:\\ProjectA\\a.py"),
        at_time="2026-06-18 09:00:00",
    )
    machine.transition_to(
        "recording",
        _normal("a.py", path="D:\\ProjectA\\a.py"),
        at_time="2026-06-18 09:00:35",
    )
    machine.transition_to(
        "recording",
        _normal("tmp", path="D:\\Unmapped\\tmp"),
        at_time="2026-06-18 09:00:36",
    )
    assert _snapshot()["display_project"]["name"] == "ProjectA"
    machine.transition_to(
        "recording",
        _normal("tmp", path="D:\\Unmapped\\tmp"),
        at_time="2026-06-18 09:01:06",
    )
    snap = _snapshot()
    assert snap["display_project"]["name"] == "ProjectA"
    assert snap["project_transition"]["pending"] is False


def test_clipboard_force_persist_under_30s_persists_db_row_but_display_still_pending(temp_db):
    """Section 一.3 / 四.5: clipboard force-persist can create a real
    open DB row BEFORE the 30-second ownership threshold, but the live
    display still follows ``display_project`` (inherited) until the
    pending window elapses. The two concerns are orthogonal."""
    project_a, project_b = _setup_two_projects(temp_db)
    machine = CollectorStateMachine()
    machine.transition_to(
        "recording",
        _normal("a.py", path="D:\\ProjectA\\a.py"),
        at_time="2026-06-18 09:00:00",
    )
    machine.transition_to(
        "recording",
        _normal("a.py", path="D:\\ProjectA\\a.py"),
        at_time="2026-06-18 09:00:35",
    )
    # Switch to ProjectB at 09:00:36 — pending window starts.
    machine.transition_to(
        "recording",
        _normal("b.py", path="D:\\ProjectB\\b.py"),
        at_time="2026-06-18 09:00:36",
    )
    assert _snapshot()["project_transition"]["pending"] is True

    # Clipboard force-persist at 09:00:40 (4 seconds into pending).
    # This creates a real open DB row while the ownership pending is
    # still active.
    persisted_id = machine.recorder.ensure_persisted_for_clipboard("2026-06-18 09:00:40")
    assert persisted_id is not None and persisted_id > 0
    snap = _snapshot()
    assert snap["is_persisted"] is True
    assert snap["persisted_activity_id"] == persisted_id
    assert snap["display_project"]["name"] == "ProjectA"
    assert snap["candidate_project"]["name"] == "ProjectB"
    assert snap["project_transition"]["pending"] is True
    assert snap["project_transition_pending"] is True

    # After 30 seconds, the candidate is confirmed — even though the
    # activity was persisted early via clipboard force-persist.
    machine.transition_to(
        "recording",
        _normal("b.py", path="D:\\ProjectB\\b.py"),
        at_time="2026-06-18 09:01:06",
    )
    snap = _snapshot()
    assert snap["display_project"]["name"] == "ProjectB"
    assert snap["project_transition"]["pending"] is False


def test_stop_clears_ownership_state_so_next_session_does_not_inherit(temp_db):
    """``stop`` is a session boundary — the ownership state
    is cleared so the previous session's display project is NOT inherited
    into a new session."""
    _setup_two_projects(temp_db)
    machine = CollectorStateMachine()
    machine.transition_to(
        "recording",
        _normal("a.py", path="D:\\ProjectA\\a.py"),
        at_time="2026-06-18 09:00:00",
    )
    machine.transition_to(
        "recording",
        _normal("a.py", path="D:\\ProjectA\\a.py"),
        at_time="2026-06-18 09:00:35",
    )
    assert _snapshot()["display_project"]["name"] == "ProjectA"

    # Stop — session boundary clears ownership.
    machine.transition_to("stopped", at_time="2026-06-18 09:00:40")

    # New session: an unmapped resource. With ownership cleared, the
    # display project should be the candidate (uncategorized), NOT the
    # previous session's ProjectA.
    machine.transition_to(
        "recording",
        _normal("tmp", path="D:\\Unmapped\\tmp"),
        at_time="2026-06-18 10:00:00",
    )
    snap = _snapshot()
    assert snap["display_project"]["is_uncategorized"] is True
    assert snap["project_transition"]["pending"] is False


def test_pause_clears_ownership_state(temp_db):
    """``pause`` is a session boundary — the ownership
    state is cleared so the previous session's display project is NOT
    inherited after resume."""
    _setup_two_projects(temp_db)
    machine = CollectorStateMachine()
    machine.transition_to(
        "recording",
        _normal("a.py", path="D:\\ProjectA\\a.py"),
        at_time="2026-06-18 09:00:00",
    )
    machine.transition_to(
        "recording",
        _normal("a.py", path="D:\\ProjectA\\a.py"),
        at_time="2026-06-18 09:00:35",
    )
    assert _snapshot()["display_project"]["name"] == "ProjectA"

    machine.transition_to("paused", at_time="2026-06-18 09:00:40")

    # After pause, a new unmapped resource: ownership cleared, so display
    # is uncategorized (not inherited ProjectA).
    machine.transition_to(
        "recording",
        _normal("tmp", path="D:\\Unmapped\\tmp"),
        at_time="2026-06-18 09:05:00",
    )
    snap = _snapshot()
    assert snap["display_project"]["is_uncategorized"] is True
    assert snap["project_transition"]["pending"] is False


def test_idle_does_not_inherit_previous_normal_project(temp_db):
    """``idle`` is a system status — it does not
    participate in normal project pending and must not inherit the
    previous normal session's display project."""
    _setup_two_projects(temp_db)
    machine = CollectorStateMachine()
    machine.transition_to(
        "recording",
        _normal("a.py", path="D:\\ProjectA\\a.py"),
        at_time="2026-06-18 09:00:00",
    )
    machine.transition_to(
        "recording",
        _normal("a.py", path="D:\\ProjectA\\a.py"),
        at_time="2026-06-18 09:00:35",
    )
    assert _snapshot()["display_project"]["name"] == "ProjectA"

    # Idle is a system status — ownership is cleared.
    machine.transition_to("idle", at_time="2026-06-18 09:00:40")
    snap = _snapshot()
    assert snap["status"] == "idle"
    # System status snapshot's display_project is uncategorized (no
    # inheritance from the previous normal session).
    assert snap["display_project"]["is_uncategorized"] is True


def test_midnight_split_does_not_inherit_previous_project(temp_db):
    """midnight split is a session boundary — the ownership
    state is cleared and re-confirmed for the continuing resource. A
    pending transition from before midnight does NOT leak into the new
    day: the new day starts with the current resource's candidate as
    the confirmed display project, not the previous day's inherited
    display project."""
    project_a, project_b = _setup_two_projects(temp_db)
    machine = CollectorStateMachine()
    machine.transition_to(
        "recording",
        _normal("a.py", path="D:\\ProjectA\\a.py"),
        at_time="2026-06-18 23:50:00",
    )
    machine.transition_to(
        "recording",
        _normal("a.py", path="D:\\ProjectA\\a.py"),
        at_time="2026-06-18 23:55:00",
    )
    # Switch to ProjectB at 23:58 — enters pending (display=ProjectA
    # inherited, candidate=ProjectB).
    machine.transition_to(
        "recording",
        _normal("b.py", path="D:\\ProjectB\\b.py"),
        at_time="2026-06-18 23:58:00",
    )
    snap = _snapshot()
    assert snap["display_project"]["name"] == "ProjectA"
    assert snap["candidate_project"]["name"] == "ProjectB"
    assert snap["project_transition"]["pending"] is True

    # Midnight split — session boundary clears the pending state.
    machine.split_at_midnight("2026-06-19 00:00:00")
    snap = _snapshot()
    # The same ProjectB resource continues, but ownership is re-confirmed.
    # The previous day's inherited display project (ProjectA) does NOT
    # leak into the new day — display is now ProjectB (confirmed).
    assert snap["display_project"]["name"] == "ProjectB"
    assert snap["project_transition"]["pending"] is False


def test_time_jump_clears_ownership_state(temp_db):
    """time jump recovery is a session boundary — the
    ownership state is cleared so the pre-jump session's display project
    is NOT inherited into the post-jump session."""
    _setup_two_projects(temp_db)
    machine = CollectorStateMachine()
    machine.transition_to(
        "recording",
        _normal("a.py", path="D:\\ProjectA\\a.py"),
        at_time="2026-06-18 09:00:00",
    )
    machine.transition_to(
        "recording",
        _normal("a.py", path="D:\\ProjectA\\a.py"),
        at_time="2026-06-18 09:00:35",
    )
    assert _snapshot()["display_project"]["name"] == "ProjectA"

    # Time jump recovery — session boundary.
    machine.reset_for_time_jump("2026-06-18 11:00:00")

    # After time jump, an unmapped resource: ownership cleared.
    machine.transition_to(
        "recording",
        _normal("tmp", path="D:\\Unmapped\\tmp"),
        at_time="2026-06-18 11:00:00",
    )
    snap = _snapshot()
    assert snap["display_project"]["is_uncategorized"] is True


def test_first_activity_no_pending_when_candidate_is_uncategorized(temp_db):
    """the first activity of a session has no prior
    confirmed project, so display == candidate immediately (no pending
    window). When the candidate is uncategorized, display is
    uncategorized."""
    _setup_two_projects(temp_db)
    machine = CollectorStateMachine()
    machine.transition_to(
        "recording",
        _normal("tmp", path="D:\\Unmapped\\tmp"),
        at_time="2026-06-18 09:00:00",
    )
    snap = _snapshot()
    assert snap["display_project"]["is_uncategorized"] is True
    assert snap["candidate_project"]["is_uncategorized"] is True
    assert snap["project_transition"]["pending"] is False


def test_first_activity_no_pending_when_candidate_is_concrete_project(temp_db):
    """the first activity of a session has no prior
    confirmed project, so display == candidate immediately (no pending
    window) even when the candidate is a concrete project."""
    project_a, _ = _setup_two_projects(temp_db)
    machine = CollectorStateMachine()
    machine.transition_to(
        "recording",
        _normal("a.py", path="D:\\ProjectA\\a.py"),
        at_time="2026-06-18 09:00:00",
    )
    snap = _snapshot()
    assert snap["display_project"]["name"] == "ProjectA"
    assert snap["display_project"]["id"] == project_a
    assert snap["candidate_project"]["name"] == "ProjectA"
    assert snap["project_transition"]["pending"] is False


def test_inferred_project_name_mirrors_display_project(temp_db):
    """The ``inferred_project_name`` field
    mirrors ``display_project.name`` so readers (statistics live
    projection, refresh-revision) see the display project, not the
    candidate."""
    _setup_two_projects(temp_db)
    machine = CollectorStateMachine()
    machine.transition_to(
        "recording",
        _normal("a.py", path="D:\\ProjectA\\a.py"),
        at_time="2026-06-18 09:00:00",
    )
    machine.transition_to(
        "recording",
        _normal("a.py", path="D:\\ProjectA\\a.py"),
        at_time="2026-06-18 09:00:35",
    )
    machine.transition_to(
        "recording",
        _normal("b.py", path="D:\\ProjectB\\b.py"),
        at_time="2026-06-18 09:00:36",
    )
    snap = _snapshot()
    # Pending: inferred_project_name mirrors display (ProjectA), NOT
    # candidate (ProjectB).
    assert snap["project_transition"]["pending"] is True
    assert snap["inferred_project_name"] == "ProjectA"
    assert snap["inferred_project_name"] == snap["display_project"]["name"]
