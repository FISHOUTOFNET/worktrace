from __future__ import annotations

from worktrace.api import timeline_api


def test_timeline_write_surface_is_projection_only():
    assert hasattr(timeline_api, "save_timeline_session_edit")
    assert not hasattr(timeline_api, "update_session_note_and_duration")
    assert not hasattr(timeline_api, "preview_session_project_update")
