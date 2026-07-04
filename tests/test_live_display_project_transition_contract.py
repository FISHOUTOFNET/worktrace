"""Activity Display Model contract tests for live-state classification,
display-span projection, and pending project-transition behavior.

These tests verify the NEW display model owner
(``worktrace.services.activity_display_model_service``) — NOT the legacy
virtual session / detail row builders. The legacy
``build_virtual_session`` / ``build_virtual_detail_row`` helpers have been
removed entirely from the codebase and are no longer part of the public
contract (the bridge-facing facade is now ``worktrace.api.view_model_api``).

Covered cases (spec 一.4 a–f):

a. pending unpersisted snapshot with NO absorb anchor → ``virtual_pending``,
   ``is_visible_in_recent/timeline/details`` all ``False``.
b. pending unpersisted snapshot WITH a previous confirmed normal anchor →
   ``absorbed_pending``, span projects onto the anchor DB row, but the DB
   is NEVER written.
c. persisted_open → ``persisted_open``, the real DB row is overlaid.
d. pending project transition: ``display_project`` is the inherited
   project; ``candidate_project`` is exposed separately.
e. No raw ``window_title`` / ``file_path_hint`` / clipboard / note / SQL /
   traceback leaks from any display-model payload.
f. The legacy virtual session / detail builders are no longer a contract.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest

pytestmark = [pytest.mark.contract, pytest.mark.db, pytest.mark.live_display]

from worktrace.constants import STATUS_NORMAL, TIME_FORMAT, UNCATEGORIZED_PROJECT
from worktrace.services import activity_service, settings_service, timeline_service
from worktrace.services.activity_display_model_service import (
    apply_live_span_to_row,
    build_activity_display_model,
    classify_display_live_state,
    get_live_span,
)


# Snapshot / DB helpers


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
    leak into the display model.
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
    elapsed_seconds: int = 12,
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
        elapsed_seconds=elapsed_seconds,
        threshold_seconds=30,
        from_project_id=12,
        to_project_id=18,
    )
    return _snapshot(
        elapsed_seconds=elapsed_seconds,
        is_persisted=is_persisted,
        persisted_activity_id=persisted_activity_id,
        display_project=display,
        candidate_project=candidate,
        project_transition=transition,
        project_transition_pending=True,
        inferred_project_name="ProjectA",
    )


def _today_report_date() -> str:
    return timeline_service.get_default_report_date()


def _create_closed_anchor_activity(
    *,
    elapsed_seconds: int = 300,
    project_name: str = "ProjectA",
) -> tuple[int, str]:
    """Create a real closed (confirmed) normal activity row to serve as
    an absorption anchor. Returns ``(activity_id, start_time)``.

    The row is closed (``end_time`` set), auto-sourced, normal, not
    deleted / hidden — i.e. a valid absorb anchor per
    ``_is_absorbable_anchor``.

    The start_time is pinned to ``today 00:01:00`` (not ``datetime.now()
    - 360s``) so the anchor is always on ``today``'s report date — this
    avoids a flaky date-boundary failure when the test runs within 6
    minutes of midnight (where ``now - 360s`` falls on yesterday and
    ``get_activities_by_date(today)`` would miss the anchor).
    """
    today = _today_report_date()
    anchor_start_dt = datetime.strptime(today + " 00:01:00", TIME_FORMAT)
    start_time = anchor_start_dt.strftime(TIME_FORMAT)
    end_time = (anchor_start_dt + timedelta(seconds=elapsed_seconds)).strftime(TIME_FORMAT)
    aid = activity_service.create_activity(
        "Code",
        "code.exe",
        "main.py - VS Code",
        file_path_hint=None,
        start_time=start_time,
    )
    activity_service.close_activity(aid, end_time)
    activity_service.set_activity_duration(aid, elapsed_seconds)
    # Assign the project so the anchor row carries ProjectA when the
    # project already exists. The anchor is valid either way; this just
    # makes the row more realistic.
    try:
        from worktrace.services import project_service

        row = project_service.get_project_by_name(project_name)
        if row:
            activity_service.update_activity_project(aid, int(row.get("id") or 0))
    except Exception:
        pass
    return aid, start_time


def _pending_start_time_today() -> str:
    """Return a start_time on ``today`` that is guaranteed to be AFTER the
    anchor's ``00:01:00`` start. Used by the absorbed_pending tests so the
    pending snapshot's start_time is always on ``today`` and always after
    the anchor (satisfying ``_is_absorbable_anchor``'s
    ``anchor_start <= pending_start`` check)."""
    today = _today_report_date()
    return datetime.strptime(today + " 00:07:00", TIME_FORMAT).strftime(TIME_FORMAT)


# Fixtures


@pytest.fixture(autouse=True)
def _isolate_snapshot(temp_db):
    """Ensure each test starts with a clean snapshot setting."""
    settings_service.clear_settings_cache()
    _set_snapshot(None)
    yield
    _set_snapshot(None)
    settings_service.clear_settings_cache()


# Case a: virtual_pending (no anchor)


def test_virtual_pending_no_anchor_live_state_and_visibility():
    """Case (a): a pending unpersisted snapshot with NO previous
    confirmed normal anchor resolves to ``virtual_pending``. The span is
    display-only and visible in current / recent / timeline / details,
    but never exportable or editable.
    """
    snap = _pending_snapshot(is_persisted=False, elapsed_seconds=12)
    _set_snapshot(snap)
    today = _today_report_date()

    state = classify_display_live_state(snap, today, today)
    assert state == "virtual_pending", (
        "pending unpersisted snapshot with no anchor must classify as virtual_pending"
    )

    model = build_activity_display_model(report_date=today, today=today)
    assert model["ok"] is True
    assert model["live_clock"]["live_state"] == "virtual_pending"

    span = get_live_span(model)
    assert span is not None
    assert span["source"] == "snapshot"
    assert int(span["activity_id"]) == 0
    assert int(span["anchor_activity_id"]) == 0
    assert span["is_visible_in_current"] is True
    assert span["is_visible_in_recent"] is True
    assert span["is_visible_in_timeline"] is True
    assert span["is_visible_in_details"] is True
    assert span["exportable"] is False
    assert span["editable"] is False
    assert span["edit_disabled"] is True
    assert span["is_display_only"] is True
    current = model["current_activity"]
    assert current["live_state"] == "virtual_pending"
    assert current["is_virtual_live"] is True
    assert current["is_in_progress"] is False


def test_virtual_pending_no_anchor_no_db_write():
    """Case (a) supplement: virtual_pending MUST NOT write the DB. No
    activity row is created or updated for a <30s unpersisted pending
    resource. The snapshot setting alone drives the display model."""
    snap = _pending_snapshot(is_persisted=False, elapsed_seconds=12)
    _set_snapshot(snap)
    today = _today_report_date()

    before_count = len(activity_service.get_activities_by_date(today))
    build_activity_display_model(report_date=today, today=today)
    after_count = len(activity_service.get_activities_by_date(today))
    assert after_count == before_count, (
        "virtual_pending must not create or write any DB activity row"
    )


# Case b: absorbed_pending (with anchor)


def test_absorbed_pending_with_anchor_live_state_and_span():
    """Case (b): a pending unpersisted snapshot WITH a previous confirmed
    normal anchor resolves to ``absorbed_pending``. A display span is
    produced and projects onto the anchor DB row (display-only)."""
    anchor_id, _ = _create_closed_anchor_activity(
        elapsed_seconds=300, project_name="ProjectA"
    )
    snap = _pending_snapshot(is_persisted=False, elapsed_seconds=12)
    snap["start_time"] = _pending_start_time_today()
    _set_snapshot(snap)
    today = _today_report_date()

    state = classify_display_live_state(snap, today, today)
    assert state == "absorbed_pending", (
        "pending unpersisted snapshot with a confirmed normal anchor must classify "
        "as absorbed_pending"
    )

    model = build_activity_display_model(report_date=today, today=today)
    span = get_live_span(model)
    assert span is not None, (
        "absorbed_pending must produce a display span that projects onto the anchor"
    )
    assert span["live_state"] == "absorbed_pending"
    assert span["anchor_activity_id"] == anchor_id, (
        "absorbed_pending span must anchor onto the previous confirmed normal activity"
    )
    assert span["is_visible_in_recent"] is True
    assert span["is_visible_in_timeline"] is True
    assert span["is_visible_in_details"] is True
    assert span["is_absorbed_pending"] is True
    # Absorbed_pending is NOT virtual_live and NOT in_progress in the
    # legacy sense — it is a display-only projection.
    assert span["is_virtual"] is False
    assert span["is_persisted"] is False


def test_absorbed_pending_apply_live_span_to_row_projects_onto_anchor():
    """Case (b): ``apply_live_span_to_row`` overlays the absorbed_pending
    live clock onto the anchor DB row. The anchor row's raw duration is
    preserved (``raw_duration_seconds``) and the projected duration is
    raw + pending_elapsed_at_sample."""
    anchor_id, _ = _create_closed_anchor_activity(
        elapsed_seconds=300, project_name="ProjectA"
    )
    snap = _pending_snapshot(is_persisted=False, elapsed_seconds=12)
    snap["start_time"] = _pending_start_time_today()
    _set_snapshot(snap)
    today = _today_report_date()

    model = build_activity_display_model(report_date=today, today=today)
    span = get_live_span(model)

    anchor_row = activity_service.get_activity(anchor_id)
    raw_duration = int(anchor_row.get("duration_seconds") or 0)

    overlaid = apply_live_span_to_row(dict(anchor_row), span)
    assert overlaid["live_state"] == "absorbed_pending"
    assert overlaid["is_live_projected"] is True
    assert overlaid["is_absorbed_pending"] is True
    assert overlaid["edit_disabled"] is True
    # The raw duration is preserved.
    assert overlaid["raw_duration_seconds"] == raw_duration
    # The projected duration is raw + pending_at_sample (>= raw).
    assert int(overlaid["duration_seconds"]) >= raw_duration


def test_current_activity_uses_resource_elapsed_project_rows_use_projection():
    anchor_id, _ = _create_closed_anchor_activity(
        elapsed_seconds=300, project_name="ProjectA"
    )
    snap = _pending_snapshot(is_persisted=False, elapsed_seconds=12)
    snap["start_time"] = _pending_start_time_today()
    _set_snapshot(snap)
    today = _today_report_date()

    model = build_activity_display_model(report_date=today, today=today)
    span = get_live_span(model)
    anchor_row = activity_service.get_activity(anchor_id)
    overlaid = apply_live_span_to_row(dict(anchor_row), span)

    current = model["current_activity"]
    assert current["elapsed_seconds"] == 12
    assert current["resource_elapsed_seconds"] == 12
    assert model["current_activity_clock"]["duration_seconds_at_sample"] == 12
    assert model["current_activity_clock"]["carry_seconds"] == 0
    assert model["current_activity_clock"]["project_duration_live"] is False
    assert model["current_activity_clock"]["display_span_id"] != model["live_clock"]["display_span_id"]
    assert model["live_clock"]["duration_seconds_at_sample"] == 312
    assert model["live_clock"]["display_base_seconds"] == 300
    assert model["live_clock"]["current_elapsed_at_sample"] == 12
    assert int(overlaid["duration_seconds"]) == 312


def test_persisted_open_current_elapsed_and_project_projection_no_double_count():
    anchor_id, start_time = _create_closed_anchor_activity(
        elapsed_seconds=300, project_name="ProjectA"
    )
    snap = _pending_snapshot(
        is_persisted=True,
        persisted_activity_id=anchor_id,
        elapsed_seconds=12,
    )
    snap["start_time"] = start_time
    snap["extra_seconds"] = 300
    _set_snapshot(snap)
    today = _today_report_date()

    model = build_activity_display_model(report_date=today, today=today)
    span = get_live_span(model)
    row = activity_service.get_activity(anchor_id)
    overlaid = apply_live_span_to_row(dict(row), span)

    assert model["live_clock"]["live_state"] == "persisted_open"
    assert model["current_activity"]["elapsed_seconds"] == 12
    assert model["current_activity"]["resource_elapsed_seconds"] == 12
    assert model["current_activity_clock"]["duration_seconds_at_sample"] == 12
    assert model["current_activity_clock"]["carry_seconds"] == 0
    assert model["live_clock"]["duration_seconds_at_sample"] == 312
    assert model["live_clock"]["display_base_seconds"] == 300
    assert int(overlaid["duration_seconds"]) == 312
    assert int(overlaid["raw_duration_seconds"]) == 300


def test_virtual_pending_to_persisted_open_same_resource_current_clock_continuity():
    start_time = _pending_start_time_today()
    virtual = _pending_snapshot(is_persisted=False, elapsed_seconds=29)
    virtual["start_time"] = start_time
    _set_snapshot(virtual)
    today = _today_report_date()
    virtual_model = build_activity_display_model(report_date=today, today=today)

    persisted = _pending_snapshot(
        is_persisted=True,
        persisted_activity_id=42,
        elapsed_seconds=30,
    )
    persisted["start_time"] = start_time
    _set_snapshot(persisted)
    persisted_model = build_activity_display_model(report_date=today, today=today)

    assert (
        persisted_model["current_activity_clock"]["display_span_id"]
        == virtual_model["current_activity_clock"]["display_span_id"]
    )
    assert persisted_model["current_activity"]["elapsed_seconds"] == 30
    assert persisted_model["current_activity_clock"]["duration_seconds_at_sample"] == 30
    assert persisted_model["current_activity_clock"]["carry_seconds"] == 0
    assert persisted_model["live_clock"]["duration_seconds_at_sample"] == 30


def test_window_switch_resets_current_activity_elapsed_not_project_projection():
    today = _today_report_date()
    old_start = datetime.strptime(today + " 09:00:00", TIME_FORMAT).strftime(TIME_FORMAT)
    old_snap = _snapshot(
        elapsed_seconds=300,
        start_time=old_start,
        resource_display_name="WindowA",
        activity_display_name="WindowA",
    )
    old_snap["resource_identity_key"] = "app:WindowA"
    _set_snapshot(old_snap)
    old_model = build_activity_display_model(report_date=today, today=today)

    new_start = datetime.strptime(today + " 09:05:00", TIME_FORMAT).strftime(TIME_FORMAT)
    new_snap = _snapshot(
        elapsed_seconds=1,
        start_time=new_start,
        resource_display_name="WindowB",
        activity_display_name="WindowB",
    )
    new_snap["resource_identity_key"] = "app:WindowB"
    _set_snapshot(new_snap)
    new_model = build_activity_display_model(report_date=today, today=today)

    assert old_model["current_activity"]["elapsed_seconds"] == 300
    assert new_model["current_activity"]["elapsed_seconds"] == 1
    assert new_model["current_activity"]["resource_elapsed_seconds"] == 1
    assert new_model["current_activity_clock"]["duration_seconds_at_sample"] == 1
    assert (
        new_model["current_activity_clock"]["display_span_id"]
        != old_model["current_activity_clock"]["display_span_id"]
    )
    assert new_model["live_clock"]["duration_seconds_at_sample"] == 1


def test_absorbed_pending_does_not_write_db():
    """Case (b) invariant: absorbed_pending projection is display-only.
    Building the model and applying the span MUST NOT call any DB write
    path (``increment_activity_duration`` / ``set_activity_duration`` /
    ``persist_open_activity_if_ready``)."""
    anchor_id, _ = _create_closed_anchor_activity(
        elapsed_seconds=300, project_name="ProjectA"
    )
    snap = _pending_snapshot(is_persisted=False, elapsed_seconds=12)
    snap["start_time"] = _pending_start_time_today()
    _set_snapshot(snap)
    today = _today_report_date()

    write_paths = [
        "worktrace.services.activity_display_model_service.activity_service.increment_activity_duration",
        "worktrace.services.activity_display_model_service.activity_service.set_activity_duration",
    ]
    try:
        persist_path = (
            "worktrace.services.activity_display_model_service.activity_service"
            ".persist_open_activity_if_ready"
        )
        write_paths.append(persist_path)
    except AttributeError:
        pass

    with pytest.MonkeyPatch().context() as mp:
        called = {"count": 0}

        def _fail(*args, **kwargs):
            called["count"] += 1
            raise AssertionError(
                "absorbed_pending must not invoke a DB write path; "
                "got call with args=%r kwargs=%r" % (args, kwargs)
            )

        for path in write_paths:
            try:
                mp.setattr(path, _fail)
            except (AttributeError, TypeError):
                pass
        model = build_activity_display_model(report_date=today, today=today)
        span = get_live_span(model)
        anchor_row = activity_service.get_activity(anchor_id)
        apply_live_span_to_row(dict(anchor_row), span)
        assert called["count"] == 0, (
            "absorbed_pending must not call any DB write path"
        )

    # The anchor row's stored DB duration is unchanged after projection.
    post_db_row = activity_service.get_activity(anchor_id)
    assert int(post_db_row["duration_seconds"]) == int(
        anchor_row["duration_seconds"]
    ), "absorbed_pending projection must not mutate the anchor DB row's duration"


# Case c: persisted_open


def test_persisted_open_live_state_and_overlay():
    """Case (c): a persisted_open snapshot (real open DB row) classifies
    as ``persisted_open``. The span overlays the real DB row's project
    fields and live clock."""
    aid, start_time = _create_real_open_activity(elapsed_seconds=60)
    snap = _pending_snapshot(
        is_persisted=True, persisted_activity_id=aid, elapsed_seconds=60
    )
    # Override start_time to match the real DB row.
    snap["start_time"] = start_time
    _set_snapshot(snap)
    today = _today_report_date()

    state = classify_display_live_state(snap, today, today)
    assert state == "persisted_open"

    model = build_activity_display_model(report_date=today, today=today)
    span = get_live_span(model)
    assert span is not None
    assert span["live_state"] == "persisted_open"
    assert span["anchor_activity_id"] == aid
    assert span["is_visible_in_recent"] is True
    assert span["is_visible_in_timeline"] is True
    assert span["is_visible_in_details"] is True
    assert span["is_virtual"] is False
    assert span["is_persisted"] is True

    # apply_live_span_to_row overlays the real DB row.
    db_row = activity_service.get_activity(aid)
    overlaid = apply_live_span_to_row(dict(db_row), span)
    assert overlaid["live_state"] == "persisted_open"
    assert overlaid["is_live_projected"] is True
    assert overlaid["is_in_progress"] is True
    # Project fields come from the snapshot's display_project block.
    assert overlaid["project_name"] == "ProjectA"
    assert overlaid["display_project"]["name"] == "ProjectA"
    assert overlaid["candidate_project"]["name"] == "ProjectB"
    assert overlaid["project_transition_pending"] is True


def _create_real_open_activity(
    *,
    app_name: str = "Code",
    process_name: str = "code.exe",
    window_title: str = "main.py - VS Code",
    file_path_hint: str | None = None,
    elapsed_seconds: int = 60,
) -> tuple[int, str]:
    """Create a real open (``end_time IS NULL``) activity row and return
    ``(activity_id, start_time)``."""
    start = datetime.now() - timedelta(seconds=elapsed_seconds)
    start_time = start.strftime(TIME_FORMAT)
    aid = activity_service.create_activity(
        app_name,
        process_name,
        window_title,
        file_path_hint=file_path_hint,
        start_time=start_time,
    )
    return aid, start_time


# Case d: pending project transition display vs candidate


def test_pending_transition_display_project_is_inherited_not_candidate():
    """Case (d): during a pending project transition the display model
    surfaces the INHERITED display project (ProjectA), NOT the candidate
    (ProjectB). The candidate is exposed as a separate field."""
    snap = _pending_snapshot(is_persisted=False, elapsed_seconds=12)
    _set_snapshot(snap)
    today = _today_report_date()

    model = build_activity_display_model(report_date=today, today=today)
    current = model["current_activity"]
    assert current["display_project"]["name"] == "ProjectA"
    assert current["candidate_project"]["name"] == "ProjectB"
    assert current["project_transition_pending"] is True
    # Convenience label fields follow display_project, not candidate.
    assert current["project_name"] == "ProjectA"
    # The project_transition block carries from_project_id (inherited)
    # and to_project_id (candidate).
    assert current["project_transition"]["pending"] is True
    assert current["project_transition"]["from_project_id"] == 12
    assert current["project_transition"]["to_project_id"] == 18


def test_pending_persisted_open_display_project_is_inherited_not_candidate():
    """Case (d) supplement: even when the DB row exists (persisted_open),
    during the pending window the display project is still the inherited
    ProjectA. The candidate ProjectB is exposed separately."""
    aid, start_time = _create_real_open_activity(elapsed_seconds=60)
    snap = _pending_snapshot(
        is_persisted=True, persisted_activity_id=aid, elapsed_seconds=60
    )
    snap["start_time"] = start_time
    _set_snapshot(snap)
    today = _today_report_date()

    model = build_activity_display_model(report_date=today, today=today)
    current = model["current_activity"]
    assert current["display_project"]["name"] == "ProjectA"
    assert current["candidate_project"]["name"] == "ProjectB"
    assert current["project_transition_pending"] is True
    assert current["persisted_activity_id"] == aid


# Case e: no sensitive field leaks


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


def test_display_model_does_not_leak_sensitive_fields_virtual_pending():
    """Case (e): the display model for a virtual_pending snapshot must
    not leak raw window_title / file_path_hint / clipboard / note / SQL /
    traceback."""
    snap = _pending_snapshot(is_persisted=False, elapsed_seconds=12)
    _set_snapshot(snap)
    today = _today_report_date()
    model = build_activity_display_model(report_date=today, today=today)
    _assert_no_sensitive_keys(model, "activity_display_model")
    _assert_no_sensitive_values(model, "activity_display_model")
    serialized = json.dumps(model)
    for marker in SENSITIVE_VALUE_MARKERS:
        assert marker not in serialized, (
            f"activity_display_model serialized payload leaked marker: {marker}"
        )


def test_display_model_does_not_leak_sensitive_fields_absorbed_pending():
    """Case (e) supplement: absorbed_pending projection also must not
    leak sensitive fields."""
    _create_closed_anchor_activity(elapsed_seconds=300, project_name="ProjectA")
    snap = _pending_snapshot(is_persisted=False, elapsed_seconds=12)
    snap["start_time"] = _pending_start_time_today()
    _set_snapshot(snap)
    today = _today_report_date()
    model = build_activity_display_model(report_date=today, today=today)
    _assert_no_sensitive_keys(model, "activity_display_model")
    _assert_no_sensitive_values(model, "activity_display_model")


def test_display_model_does_not_leak_sensitive_fields_persisted_open():
    """Case (e) supplement: persisted_open projection also must not leak
    sensitive fields."""
    aid, start_time = _create_real_open_activity(elapsed_seconds=60)
    snap = _pending_snapshot(
        is_persisted=True, persisted_activity_id=aid, elapsed_seconds=60
    )
    snap["start_time"] = start_time
    _set_snapshot(snap)
    today = _today_report_date()
    model = build_activity_display_model(report_date=today, today=today)
    _assert_no_sensitive_keys(model, "activity_display_model")
    _assert_no_sensitive_values(model, "activity_display_model")


# Case f: legacy virtual session/detail builders are no longer a contract


def test_legacy_virtual_builders_not_in_live_display_api_exports():
    """Case (f): ``build_virtual_session`` / ``build_virtual_detail_row``
    / ``build_persisted_open_overlay`` / ``apply_persisted_open_overlay_to_row``
    / ``build_live_row_contract`` must NOT be re-exported by
    ``worktrace.api.view_model_api``. They are no longer part of the
    bridge-facing public contract."""
    from worktrace.api import view_model_api

    api_all = set(getattr(view_model_api, "__all__", []))
    for symbol in (
        "build_virtual_session",
        "build_virtual_detail_row",
        "build_persisted_open_overlay",
        "apply_persisted_open_overlay_to_row",
        "build_live_row_contract",
    ):
        assert symbol not in api_all, (
            "view_model_api must not re-export " + symbol
        )
        assert not hasattr(view_model_api, symbol), (
            "view_model_api must not expose " + symbol + " as an attribute"
        )


def test_legacy_virtual_builders_not_in_live_display_service_all():
    """Case (f): the public ``__all__`` of
    ``worktrace.services.live_display_service`` must NOT include the
    legacy virtual session / detail builders. They have been removed
    entirely from the codebase (no private aliases either)."""
    from worktrace.services import live_display_service

    service_all = set(getattr(live_display_service, "__all__", []))
    for symbol in (
        "build_virtual_session",
        "build_virtual_detail_row",
        "build_persisted_open_overlay",
        "apply_persisted_open_overlay_to_row",
        "build_live_row_contract",
        "_build_virtual_session",
        "_build_virtual_detail_row",
    ):
        assert symbol not in service_all, (
            "live_display_service.__all__ must not export " + symbol
        )


# Supplementary: model shape / live_clock contract


def test_display_model_carries_unified_live_clock_and_span_id():
    """The display model always carries a ``live_clock`` block with a
    non-empty ``display_span_id`` when the snapshot is live-eligible, so
    the frontend can register the unified clock from any payload."""
    snap = _pending_snapshot(is_persisted=False, elapsed_seconds=12)
    _set_snapshot(snap)
    today = _today_report_date()
    model = build_activity_display_model(report_date=today, today=today)
    assert "live_clock" in model
    clock = model["live_clock"]
    assert clock["display_span_id"], (
        "live_clock.display_span_id must be non-empty for a live snapshot"
    )
    assert clock["stable_live_key_hash"]
    assert clock["live_state"] in (
        "virtual_pending",
        "absorbed_pending",
        "persisted_open",
    )
    assert "live_started_at_epoch_ms" in clock
    assert "carry_seconds" in clock
    assert "duration_seconds_at_sample" in clock


def test_empty_snapshot_returns_none_live_state():
    """An empty snapshot yields ``live_state == "none"`` and no display
    span. The model still carries an empty live_clock block."""
    _set_snapshot(None)
    today = _today_report_date()
    model = build_activity_display_model(report_date=today, today=today)
    assert model["ok"] is True
    assert model["live_clock"]["live_state"] == "none"
    assert get_live_span(model) is None
    assert model["current_activity"]["active"] is False


def test_historical_date_suppresses_live_projection():
    """A historical date (report_date != today) suppresses live
    projection. A virtual snapshot on a past date collapses to
    ``live_state == "none"`` and produces no display span."""
    snap = _pending_snapshot(is_persisted=False, elapsed_seconds=12)
    _set_snapshot(snap)
    today = _today_report_date()
    # Build a date string that is definitely not today.
    historical = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    model = build_activity_display_model(report_date=historical, today=today)
    assert model["is_today"] is False
    assert model["live_clock"]["live_state"] == "none"
    assert get_live_span(model) is None
