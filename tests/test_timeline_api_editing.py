from __future__ import annotations

import pytest

from tests.support import activity_factory as activity_service
from worktrace.api import timeline_api
from worktrace.services import project_service

DATE = "2026-07-02"

pytestmark = [pytest.mark.db, pytest.mark.integration]


def _session():
    project_id = project_service.create_project("P")
    activity_id = activity_service.create_activity(
        "App", "app.exe", "A", project_id=project_id, start_time=f"{DATE} 09:00:00"
    )
    activity_service.finalize_created_activity(activity_id)
    activity_service.close_activity(activity_id, f"{DATE} 09:10:00")
    return timeline_api.get_project_sessions_by_date(DATE)[0]


def test_projection_key_edit_api_returns_post_state(temp_db):
    source = _session()
    result = timeline_api.save_timeline_session_edit(
        DATE,
        source["projection_instance_key"],
        source["projection_revision"],
        "edit-1",
        None,
        60,
        "note",
    )
    assert result["ok"] is True
    assert result["selection_hint"]["projection_revision"] != source["projection_revision"]
    assert result["snapshot_revision"]


def test_projection_edit_api_rejects_stale_revision(temp_db):
    source = _session()
    with pytest.raises(Exception, match="revision_conflict"):
        timeline_api.save_timeline_session_edit(
            DATE, source["projection_instance_key"], "0" * 40,
            "edit-stale", None, None, "",
        )


def test_activity_id_edit_protocol_is_absent():
    assert not hasattr(timeline_api, "save_activity_session_override")
    assert not hasattr(timeline_api, "get_session_activity_details")
