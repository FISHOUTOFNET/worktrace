"""Live display project-transition contract tests.

Locks the project ownership fields returned by
``live_display_service.build_live_projection`` /
``build_current_activity_summary`` /
``build_virtual_session`` /
``build_virtual_detail_row``.

Locked behavior:

- **Orthogonality** — ``live_state`` (virtual | persisted_open | idle |
  paused | excluded | error | none) and ``project_transition_pending``
  (True | False) are independent axes. A clipboard force-persist can
  make an activity ``persisted_open`` while ``project_transition_pending``
  is still ``True``.
- **Pending virtual** — during a 30-second pending window the virtual
  projection surfaces the *inherited* display project, NOT the
  candidate. ``candidate_project`` is exposed as a separate field for
  the "确认中" indicator.
- **Pending persisted_open** — same as pending virtual: the DB row may
  exist (clipboard force-persist) but the display project still follows
  the inherited last-confirmed project until the pending window
  elapses.
- **Virtual session/detail description** — ``project_description`` is
  no longer hardcoded to ``""``; it comes from
  ``display_project.description``.
- **Candidate does not preempt display** — ``candidate_project`` NEVER
  overwrites ``display_project`` in the projection, even when the
  candidate is a concrete project and the display is uncategorized.
- **Display-safe** — the projection / virtual session / virtual detail
  payloads MUST NOT leak raw ``window_title`` / ``file_path_hint`` /
  clipboard / note / SQL / traceback.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest

from worktrace.constants import STATUS_NORMAL, TIME_FORMAT, UNCATEGORIZED_PROJECT
from worktrace.services import settings_service
from worktrace.services.live_display_service import (
    build_current_activity_summary,
    build_live_projection,
    build_virtual_detail_row,
    build_virtual_session,
)
from worktrace.services import timeline_service


# ---------------------------------------------------------------------------
# Snapshot helpers
# ---------------------------------------------------------------------------


def _set_snapshot(snapshot: dict | None) -> None:
    settings_service.set_setting(
        "current_activity_snapshot", json.dumps(snapshot) if snapshot else ""
    )
    settings_service.clear_settings_cache()


def _project_dict(
    *,
    name: str,
    project_id: int | None = None,
    description: str = "",
    source: str = "folder_rule",
    is_uncategorized: bool = False,
    is_suggested_project: bool = False,
) -> dict:
    return {
        "id": project_id,
        "name": name,
        "description": description,
        "source": source,
        "is_uncategorized": is_uncategorized,
        "is_suggested_project": is_suggested_project,
    }


def _transition_dict(
    *,
    pending: bool,
    started_at: str = "",
    elapsed_seconds: int = 0,
    threshold_seconds: int = 30,
    from_project_id: int | None = None,
    to_project_id: int | None = None,
) -> dict:
    return {
        "pending": pending,
        "started_at": started_at,
        "elapsed_seconds": elapsed_seconds,
        "threshold_seconds": threshold_seconds,
        "from_project_id": from_project_id,
        "to_project_id": to_project_id,
    }


def _snapshot(
    *,
    elapsed_seconds: int = 120,
    status: str = STATUS_NORMAL,
    is_persisted: bool = False,
    persisted_activity_id: int = 0,
    display_project: dict | None = None,
    candidate_project: dict | None = None,
    project_transition: dict | None = None,
    project_transition_pending: bool = False,
    inferred_project_name: str | None = None,
    resource_display_name: str = "main.py",
    activity_display_name: str = "main.py",
    app_name: str = "Code",
    process_name: str = "code.exe",
    window_title: str = "main.py - VS Code - SECRET_TITLE",
    file_path_hint: str = "D:\\Secret\\main.py",
    start_time: str | None = None,
) -> dict:
    """Build a snapshot mirroring the structure written by
    ``AutoActivityRecorder._write_snapshot``.

    ``window_title`` / ``file_path_hint`` are populated with sentinel
    secret values so display-safety assertions can verify they do NOT
    leak into the projection.
    """
    if start_time is None:
        start = datetime.now() - timedelta(seconds=elapsed_seconds)
        start_time = start.strftime(TIME_FORMAT)
    if display_project is None:
        display_project = _project_dict(
            name="ProjectA",
            project_id=12,
            description="Project A description",
            source="folder_rule",
        )
    if candidate_project is None:
        candidate_project = display_project
    if project_transition is None:
        project_transition = _transition_dict(pending=project_transition_pending)
    if inferred_project_name is None:
        inferred_project_name = display_project.get("name") or UNCATEGORIZED_PROJECT
    return {
        "app_name": app_name,
        "process_name": process_name,
        "window_title": window_title,
        "file_path_hint": file_path_hint,
        "activity_display_name": activity_display_name,
        "resource_kind": "code_file",
        "resource_subtype": "python_source",
        "resource_display_name": resource_display_name,
        "resource_identity_key": "file_path:D:\\Secret\\main.py",
        "resource_path_hint": file_path_hint,
        "resource_uri_host": None,
        "inferred_project_name": inferred_project_name,
        "status": status,
        "start_time": start_time,
        "elapsed_seconds": elapsed_seconds,
        "extra_seconds": 0,
        "persisted_activity_id": persisted_activity_id,
        "is_persisted": is_persisted,
        "display_project": display_project,
        "candidate_project": candidate_project,
        "project_transition": project_transition,
        "project_transition_pending": project_transition_pending,
    }


def _pending_snapshot(
    *,
    is_persisted: bool = False,
    persisted_activity_id: int = 0,
) -> dict:
    """A snapshot in the 30-second pending window: display project is
    ProjectA (inherited), candidate is ProjectB (new resource)."""
    display = _project_dict(
        name="ProjectA",
        project_id=12,
        description="Project A description",
        source="inherited",
    )
    candidate = _project_dict(
        name="ProjectB",
        project_id=18,
        description="Project B description",
        source="folder_rule",
    )
    transition = _transition_dict(
        pending=True,
        started_at="2026-06-18 09:00:36",
        elapsed_seconds=12,
        threshold_seconds=30,
        from_project_id=12,
        to_project_id=18,
    )
    return _snapshot(
        elapsed_seconds=12,
        is_persisted=is_persisted,
        persisted_activity_id=persisted_activity_id,
        display_project=display,
        candidate_project=candidate,
        project_transition=transition,
        project_transition_pending=True,
        inferred_project_name="ProjectA",
    )


# ---------------------------------------------------------------------------
# 1. live_state / project_transition_pending orthogonality
# ---------------------------------------------------------------------------


def test_empty_snapshot_returns_none_live_state_and_not_pending():
    """An empty snapshot yields ``live_state == "none"`` and
    ``project_transition_pending == False``. The two fields are
    independently observable."""
    projection = build_live_projection(None)
    assert projection["live_state"] == "none"
    assert projection["project_transition_pending"] is False
    assert projection["display_project"] is None
    assert projection["candidate_project"] is None


def test_pending_virtual_live_state_is_virtual_and_pending_true():
    """Pending virtual: ``live_state == "virtual"`` AND
    ``project_transition_pending == True``. The two axes coexist."""
    snap = _pending_snapshot(is_persisted=False)
    projection = build_live_projection(snap)
    assert projection["live_state"] == "virtual"
    assert projection["is_virtual_live"] is True
    assert projection["is_in_progress"] is False
    assert projection["project_transition_pending"] is True


def test_pending_persisted_open_live_state_is_persisted_open_and_pending_true():
    """Clipboard force-persist orthogonality: the DB row exists
    (``live_state == "persisted_open"``) but the display project is
    still pending (``project_transition_pending == True``). The two
    concerns are intentionally independent."""
    snap = _pending_snapshot(is_persisted=True, persisted_activity_id=42)
    projection = build_live_projection(snap)
    assert projection["live_state"] == "persisted_open"
    assert projection["is_virtual_live"] is False
    assert projection["is_in_progress"] is True
    assert projection["persisted_activity_id"] == 42
    # Pending is STILL True even though the row is persisted.
    assert projection["project_transition_pending"] is True


def test_confirmed_virtual_live_state_is_virtual_and_pending_false():
    """Confirmed (post-30s) virtual: ``live_state == "virtual"`` AND
    ``project_transition_pending == False``."""
    display = _project_dict(name="ProjectB", project_id=18, description="Project B", source="confirmed")
    snap = _snapshot(
        elapsed_seconds=45,
        display_project=display,
        candidate_project=display,
        project_transition=_transition_dict(pending=False),
        project_transition_pending=False,
        inferred_project_name="ProjectB",
    )
    projection = build_live_projection(snap)
    assert projection["live_state"] == "virtual"
    assert projection["project_transition_pending"] is False


# ---------------------------------------------------------------------------
# 2. Pending virtual / persisted_open surface the INHERITED display project
# ---------------------------------------------------------------------------


def test_pending_virtual_display_project_is_inherited_not_candidate():
    """During pending, ``display_project`` is the inherited ProjectA,
    NOT the candidate ProjectB. The candidate is exposed separately."""
    snap = _pending_snapshot(is_persisted=False)
    projection = build_live_projection(snap)
    assert projection["display_project"]["name"] == "ProjectA"
    assert projection["display_project"]["id"] == 12
    assert projection["display_project"]["description"] == "Project A description"
    assert projection["candidate_project"]["name"] == "ProjectB"
    assert projection["candidate_project"]["id"] == 18
    # The convenience label fields follow display_project, not candidate.
    assert projection["project_name"] == "ProjectA"
    assert projection["project_description"] == "Project A description"


def test_pending_persisted_open_display_project_is_inherited_not_candidate():
    """Clipboard force-persist: even though the DB row exists, the
    display project is still the inherited ProjectA until the 30-second
    pending window elapses. The candidate ProjectB is exposed
    separately for the "确认中" indicator."""
    snap = _pending_snapshot(is_persisted=True, persisted_activity_id=99)
    projection = build_live_projection(snap)
    assert projection["display_project"]["name"] == "ProjectA"
    assert projection["candidate_project"]["name"] == "ProjectB"
    assert projection["project_transition_pending"] is True
    assert projection["persisted_activity_id"] == 99


def test_current_activity_summary_pending_surfaces_inherited_display():
    """``build_current_activity_summary`` (used by Overview header /
    heartbeat) also surfaces the inherited display project during
    pending, NOT the candidate."""
    snap = _pending_snapshot(is_persisted=False)
    summary = build_current_activity_summary(snap)
    assert summary["display_project"]["name"] == "ProjectA"
    assert summary["candidate_project"]["name"] == "ProjectB"
    assert summary["project_transition_pending"] is True
    assert summary["project_name"] == "ProjectA"
    assert summary["project_description"] == "Project A description"


# ---------------------------------------------------------------------------
# 3. Virtual session / detail description no longer hardcoded empty
# ---------------------------------------------------------------------------


def _today_report_date() -> str:
    return timeline_service.get_default_report_date()


def test_virtual_session_project_description_comes_from_display_project():
    """virtual session's ``project_description`` must come
    from ``display_project.description`` — NOT be hardcoded to ``""``."""
    snap = _pending_snapshot(is_persisted=False)
    today = _today_report_date()
    session = build_virtual_session(snap, report_date=today, today=today)
    assert session is not None, "virtual session must be built for a pending virtual snapshot"
    assert session["project_name"] == "ProjectA"
    assert session["project_description"] == "Project A description"


def test_virtual_detail_row_project_description_comes_from_display_project():
    """virtual detail row's ``project_description`` must
    come from ``display_project.description`` — NOT be hardcoded to
    ``""``."""
    snap = _pending_snapshot(is_persisted=False)
    today = _today_report_date()
    detail = build_virtual_detail_row(snap, report_date=today, today=today)
    assert detail is not None, "virtual detail must be built for a pending virtual snapshot"
    assert detail["project_name"] == "ProjectA"
    assert detail["project_description"] == "Project A description"


def test_virtual_session_description_empty_when_display_project_has_no_description():
    """When the display project genuinely has no description (e.g.
    uncategorized or suggested-project candidate), the virtual session
    description is empty — but it is derived from the contract, not
    hardcoded."""
    display = _project_dict(
        name=UNCATEGORIZED_PROJECT,
        project_id=None,
        description="",
        source="uncategorized",
        is_uncategorized=True,
    )
    snap = _snapshot(
        elapsed_seconds=20,
        display_project=display,
        candidate_project=display,
        project_transition=_transition_dict(pending=False),
        project_transition_pending=False,
        inferred_project_name=UNCATEGORIZED_PROJECT,
    )
    today = _today_report_date()
    session = build_virtual_session(snap, report_date=today, today=today)
    assert session is not None
    assert session["project_description"] == ""


# ---------------------------------------------------------------------------
# 4. Candidate project NEVER preempts display project
# ---------------------------------------------------------------------------


def test_candidate_does_not_preempt_display_in_projection():
    """Even when the candidate is a concrete project and the display is
    uncategorized, ``candidate_project`` MUST NOT overwrite
    ``display_project`` in the projection. They are separate fields."""
    display = _project_dict(
        name=UNCATEGORIZED_PROJECT,
        project_id=None,
        description="",
        source="uncategorized",
        is_uncategorized=True,
    )
    candidate = _project_dict(
        name="ProjectB",
        project_id=18,
        description="Project B",
        source="folder_rule",
    )
    snap = _snapshot(
        elapsed_seconds=10,
        display_project=display,
        candidate_project=candidate,
        project_transition=_transition_dict(
            pending=True,
            from_project_id=None,
            to_project_id=18,
        ),
        project_transition_pending=True,
        inferred_project_name=UNCATEGORIZED_PROJECT,
    )
    projection = build_live_projection(snap)
    assert projection["display_project"]["name"] == UNCATEGORIZED_PROJECT
    assert projection["candidate_project"]["name"] == "ProjectB"
    assert projection["project_name"] == UNCATEGORIZED_PROJECT
    assert projection["project_transition_pending"] is True


def test_candidate_does_not_preempt_display_in_virtual_session():
    """The virtual session's ``project_name`` follows ``display_project``,
    not ``candidate_project``."""
    snap = _pending_snapshot(is_persisted=False)
    today = _today_report_date()
    session = build_virtual_session(snap, report_date=today, today=today)
    assert session is not None
    assert session["project_name"] == "ProjectA"
    # Candidate ProjectB is NOT the session's project.
    assert session["project_name"] != "ProjectB"


def test_candidate_does_not_preempt_display_in_virtual_detail():
    """The virtual detail row's ``project_name`` follows
    ``display_project``, not ``candidate_project``."""
    snap = _pending_snapshot(is_persisted=False)
    today = _today_report_date()
    detail = build_virtual_detail_row(snap, report_date=today, today=today)
    assert detail is not None
    assert detail["project_name"] == "ProjectA"
    assert detail["project_name"] != "ProjectB"


# ---------------------------------------------------------------------------
# 5. Display-safe: no raw sensitive fields leak
# ---------------------------------------------------------------------------


SENSITIVE_KEYS = {
    "window_title",
    "file_path_hint",
    "resource_path_hint",
    "resource_identity_key",
    "note",
    "clipboard",
    "sql",
    "traceback",
    "raw_window_title",
}

SENSITIVE_VALUE_MARKERS = ("SECRET_TITLE", "D:\\Secret\\main.py")


def _assert_no_sensitive_keys(payload: dict, label: str) -> None:
    for key in payload:
        assert key not in SENSITIVE_KEYS, (
            f"{label} leaked sensitive key: {key}"
        )


def _assert_no_sensitive_values(payload: dict, label: str) -> None:
    """Recursively check that no sensitive sentinel values appear
    anywhere in the payload."""
    for value in payload.values():
        if isinstance(value, str):
            for marker in SENSITIVE_VALUE_MARKERS:
                assert marker not in value, (
                    f"{label} leaked sensitive value marker: {marker}"
                )
        elif isinstance(value, dict):
            _assert_no_sensitive_keys(value, label)
            _assert_no_sensitive_values(value, label)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    _assert_no_sensitive_keys(item, label)
                    _assert_no_sensitive_values(item, label)


def test_live_projection_does_not_leak_sensitive_fields():
    """Section 二.4 / 三: ``build_live_projection`` MUST NOT leak raw
    ``window_title`` / ``file_path_hint`` / clipboard / note / SQL /
    traceback. Only display-safe fields are surfaced."""
    snap = _pending_snapshot(is_persisted=False)
    projection = build_live_projection(snap)
    _assert_no_sensitive_keys(projection, "live_projection")
    _assert_no_sensitive_values(projection, "live_projection")


def test_current_activity_summary_does_not_leak_sensitive_fields():
    snap = _pending_snapshot(is_persisted=False)
    summary = build_current_activity_summary(snap)
    _assert_no_sensitive_keys(summary, "current_activity_summary")
    _assert_no_sensitive_values(summary, "current_activity_summary")


def test_virtual_session_does_not_leak_sensitive_fields():
    snap = _pending_snapshot(is_persisted=False)
    today = _today_report_date()
    session = build_virtual_session(snap, report_date=today, today=today)
    assert session is not None
    _assert_no_sensitive_keys(session, "virtual_session")
    _assert_no_sensitive_values(session, "virtual_session")


def test_virtual_detail_does_not_leak_sensitive_fields():
    snap = _pending_snapshot(is_persisted=False)
    today = _today_report_date()
    detail = build_virtual_detail_row(snap, report_date=today, today=today)
    assert detail is not None
    _assert_no_sensitive_keys(detail, "virtual_detail")
    _assert_no_sensitive_values(detail, "virtual_detail")


# ---------------------------------------------------------------------------
# 6. live_projection carries all required contract fields
# ---------------------------------------------------------------------------


REQUIRED_PROJECTION_FIELDS = {
    "resource_name",
    "app_name",
    "display_project",
    "candidate_project",
    "project_transition",
    "project_transition_pending",
    "duration_seconds",
    "live_started_at_epoch_ms",
    "carry_seconds",
    "stable_live_key",
    "stable_live_key_hash",
    "live_state",
    "is_virtual_live",
    "is_in_progress",
    "persisted_activity_id",
    "activity_id",
    "source",
    "edit_disabled",
    "disable_reason",
    "project_name",
    "project_description",
    "is_uncategorized",
    "is_classified",
    "status",
    "start_time",
}


def test_live_projection_carries_all_required_contract_fields():
    """``live_projection`` must carry every field listed in
    the contract so consumers do not need to fall back to removed
    fields."""
    snap = _pending_snapshot(is_persisted=False)
    projection = build_live_projection(snap)
    missing = REQUIRED_PROJECTION_FIELDS - set(projection.keys())
    assert not missing, f"live_projection missing required fields: {missing}"


def test_live_projection_resource_name_reflects_new_resource():
    """the projection's ``resource_name`` reflects the NEW
    resource immediately (resource identity is immediate), even while
    the project ownership is still pending."""
    snap = _pending_snapshot(is_persisted=False)
    projection = build_live_projection(snap)
    # The pending snapshot uses resource_display_name="main.py" by default.
    assert projection["resource_name"] == "main.py"
    assert projection["app_name"] == "Code"


def test_live_projection_project_transition_block_is_surfacable():
    """The full ``project_transition`` block (pending / started_at /
    elapsed_seconds / threshold_seconds / from_project_id /
    to_project_id) is surfaced so the frontend can render a "确认中"
    indicator with a real progress bar."""
    snap = _pending_snapshot(is_persisted=False)
    projection = build_live_projection(snap)
    transition = projection["project_transition"]
    assert transition["pending"] is True
    assert transition["started_at"] == "2026-06-18 09:00:36"
    assert transition["threshold_seconds"] == 30
    assert transition["from_project_id"] == 12
    assert transition["to_project_id"] == 18


# ---------------------------------------------------------------------------
# 7. Idle / paused / excluded / error do NOT carry a normal display project
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "status",
    ["idle", "paused", "excluded", "error"],
)
def test_system_status_snapshots_have_no_pending_display_project(status):
    """idle / paused / excluded / error do not participate
    in normal project pending. Their ``display_project`` is uncategorized
    and ``project_transition_pending`` is False (no normal project
    inheritance)."""
    snap = _snapshot(
        elapsed_seconds=10,
        status=status,
        display_project=_project_dict(
            name=UNCATEGORIZED_PROJECT,
            source="uncategorized",
            is_uncategorized=True,
        ),
        candidate_project=_project_dict(
            name=UNCATEGORIZED_PROJECT,
            source="uncategorized",
            is_uncategorized=True,
        ),
        project_transition=_transition_dict(pending=False),
        project_transition_pending=False,
        inferred_project_name=UNCATEGORIZED_PROJECT,
    )
    projection = build_live_projection(snap)
    assert projection["live_state"] == status
    assert projection["project_transition_pending"] is False
    # System status must NOT contribute to normal project live duration.
    assert projection["is_in_progress"] is False
    assert projection["is_virtual_live"] is False
