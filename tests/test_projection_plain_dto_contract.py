from __future__ import annotations

import json

import pytest

from worktrace.api import timeline_api
from worktrace.services import activity_service, project_service
from worktrace.services import report_session_projection_service as projection_service


pytestmark = [pytest.mark.db, pytest.mark.integration, pytest.mark.contract]
DATE = "2026-07-04"


def _assert_plain_data(value, path: str = "$") -> None:
    if value is None or isinstance(value, (str, int, float, bool)):
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _assert_plain_data(item, f"{path}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            assert isinstance(key, str), f"non-string DTO key at {path}: {key!r}"
            _assert_plain_data(item, f"{path}.{key}")
        return
    pytest.fail(f"non-plain DTO value at {path}: {type(value).__name__}")


def _closed_activity() -> int:
    project_id = project_service.create_project("DTO Project")
    activity_id = activity_service.create_activity(
        "Word",
        "winword.exe",
        "DTO.docx",
        project_id=project_id,
        start_time=f"{DATE} 09:00:00",
    )
    activity_service.finalize_created_activity(activity_id)
    activity_service.close_activity(activity_id, f"{DATE} 09:10:00")
    return activity_id


def test_timeline_session_api_returns_recursively_plain_detached_dto(temp_db):
    activity_id = _closed_activity()

    sessions = timeline_api.get_project_sessions_by_date(DATE)

    assert len(sessions) == 1
    session = sessions[0]
    assert isinstance(session["activity_ids"], list)
    assert session["activity_ids"] == [activity_id]
    assert isinstance(session["activity_member_hash"], str)
    assert isinstance(session["member_slices"], list)
    assert isinstance(session["member_slices"][0], dict)
    _assert_plain_data(sessions)
    json.dumps(sessions, ensure_ascii=False)

    session["activity_ids"].append(999)
    fresh = timeline_api.get_project_sessions_by_date(DATE)
    assert fresh[0]["activity_ids"] == [activity_id]


def test_projected_contribution_adapter_returns_recursively_plain_records(temp_db):
    _closed_activity()

    contributions = projection_service.get_projected_activity_contributions_by_range(DATE, DATE)

    assert contributions
    _assert_plain_data(contributions)
    json.dumps(contributions, ensure_ascii=False)
