"""Current live-display projection contracts.

Only persisted open activities may be projected onto report surfaces.  This
module deliberately keeps candidate metadata and transition history out of
the display contract.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest

from worktrace.constants import STATUS_NORMAL, TIME_FORMAT
from worktrace.services import activity_service, settings_service, timeline_service
from worktrace.services.activity_display_model_service import build_activity_display_model
from worktrace.services.activity_display_policy import classify_display_live_state
from worktrace.services.activity_row_overlay import ROW_KIND_ACTIVITY_DETAIL_ROW, apply_live_span_to_row


pytestmark = [pytest.mark.contract, pytest.mark.db, pytest.mark.live_display]


def _set_snapshot(snapshot: dict | None) -> None:
    settings_service.set_setting("current_activity_snapshot", json.dumps(snapshot) if snapshot else "")
    settings_service.clear_settings_cache()


def _snapshot(*, persisted_id: int = 0, elapsed: int = 30, candidate: str = "Candidate", transition: dict | None = None) -> dict:
    start = (datetime.now() - timedelta(seconds=elapsed)).strftime(TIME_FORMAT)
    return {
        "app_name": "Code", "process_name": "code.exe", "status": STATUS_NORMAL,
        "start_time": start, "elapsed_seconds": elapsed, "extra_seconds": 0,
        "is_persisted": bool(persisted_id), "persisted_activity_id": persisted_id,
        "display_project": {"id": 1, "name": "Official", "description": "", "source": "manual"},
        "candidate_project": {"id": 2, "name": candidate, "description": "private"},
        "suggested_project_name": candidate, "inferred_project_name": candidate,
        "project_transition": transition or {"pending": True, "to_project_id": 2},
        "window_title": "SECRET_TITLE", "file_path_hint": "D:/secret.py",
        "clipboard": "SECRET_CLIPBOARD", "note": "SECRET_NOTE", "traceback": "SECRET_TRACEBACK", "sql": "SECRET_SQL",
    }


@pytest.fixture(autouse=True)
def _clean_snapshot(temp_db):
    _set_snapshot(None)
    yield
    _set_snapshot(None)


def test_normal_unpersisted_snapshot_fails_closed_on_all_display_surfaces():
    snapshot = _snapshot()
    today = timeline_service.get_default_report_date()
    _set_snapshot(snapshot)

    assert classify_display_live_state(snapshot, today, today) == "none"
    model = build_activity_display_model(report_date=today, today=today)
    assert model["live_clock"]["live_state"] == "none"
    assert model["display_spans"] == []


def test_persisted_open_projects_only_its_own_row():
    start = (datetime.now() - timedelta(seconds=30)).strftime(TIME_FORMAT)
    own_id = activity_service.create_activity("Code", "code.exe", "own.py", start_time=start)
    other_id = activity_service.create_activity("Code", "code.exe", "other.py", start_time=start)
    _set_snapshot(_snapshot(persisted_id=own_id))
    today = timeline_service.get_default_report_date()

    model = build_activity_display_model(report_date=today, today=today)
    span = model["display_spans"][0]
    assert span["live_state"] == "persisted_open"
    assert span["activity_id"] == own_id
    own = apply_live_span_to_row(activity_service.get_activity(own_id), span, row_kind=ROW_KIND_ACTIVITY_DETAIL_ROW)
    other = apply_live_span_to_row(activity_service.get_activity(other_id), span, row_kind=ROW_KIND_ACTIVITY_DETAIL_ROW)
    assert own["is_live_projected"] is True
    assert other.get("is_live_projected") is not True


def test_candidate_and_transition_metadata_do_not_change_display_revisions_or_signature():
    from worktrace.services.live_display_service import compute_refresh_revision

    first = _snapshot(candidate="Candidate A", transition={"pending": True, "to_project_id": 2})
    second = {**_snapshot(candidate="Candidate B", transition={"pending": False, "to_project_id": 3}), "start_time": first["start_time"]}
    today = timeline_service.get_default_report_date()
    assert compute_refresh_revision(first, "running", False, today)[0] == compute_refresh_revision(second, "running", False, today)[0]


def test_display_model_never_leaks_raw_snapshot_secrets():
    _set_snapshot(_snapshot())
    encoded = json.dumps(build_activity_display_model(), ensure_ascii=False)
    for secret in ("SECRET_TITLE", "SECRET_CLIPBOARD", "SECRET_NOTE", "SECRET_TRACEBACK", "SECRET_SQL", "D:/secret.py"):
        assert secret not in encoded
