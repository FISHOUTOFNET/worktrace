"""Project ownership has immediate official display and no transition DTO."""

from __future__ import annotations

import json

import pytest

from tests.support import runtime_state_fixture
from worktrace.collector.state_machine import CollectorStateMachine
from worktrace.platforms.base import ActiveWindow
from worktrace.services import folder_rule_service, project_service

pytestmark = [pytest.mark.db, pytest.mark.live_display, pytest.mark.contract]


def _snapshot() -> dict:
    raw = runtime_state_fixture.get_setting("current_activity_snapshot", "") or ""
    return json.loads(raw) if raw else {}


def _normal(title: str, path: str | None = None) -> ActiveWindow:
    return ActiveWindow("Code", "code.exe", title, file_path_hint=path)


def _setup_two_projects(temp_db):
    project_a = project_service.create_project("ProjectA")
    project_b = project_service.create_project("ProjectB")
    folder_rule_service.create_or_update_folder_rule("D:\\ProjectA", project_a)
    folder_rule_service.create_or_update_folder_rule("D:\\ProjectB", project_b)
    return project_a, project_b


def _assert_snapshot_has_only_official_project_contract(snapshot: dict) -> None:
    assert "display_project" in snapshot
    for retired in (
        "candidate_project",
        "project_transition",
        "project_transition_pending",
        "inferred_project_name",
        "extra_seconds",
        "checkpoint_seconds",
    ):
        assert retired not in snapshot


def test_resource_switch_applies_official_project_immediately(temp_db):
    _setup_two_projects(temp_db)
    machine = CollectorStateMachine()
    machine.transition_to(
        "recording",
        _normal("a.py", "D:\\ProjectA\\a.py"),
        at_time="2026-06-18 09:00:00",
    )
    first = _snapshot()
    assert first["display_project"]["name"] == "ProjectA"
    _assert_snapshot_has_only_official_project_contract(first)

    machine.transition_to(
        "recording",
        _normal("b.py", "D:\\ProjectB\\b.py"),
        at_time="2026-06-18 09:00:01",
    )
    switched = _snapshot()
    assert switched["activity_display_name"] == "b.py"
    assert switched["display_project"]["name"] == "ProjectB"
    _assert_snapshot_has_only_official_project_contract(switched)


def test_unmapped_resource_is_uncategorized_not_inherited(temp_db):
    _setup_two_projects(temp_db)
    machine = CollectorStateMachine()
    machine.transition_to(
        "recording",
        _normal("a.py", "D:\\ProjectA\\a.py"),
        at_time="2026-06-18 09:00:00",
    )
    machine.transition_to(
        "recording",
        _normal("tmp", "D:\\Unmapped\\tmp"),
        at_time="2026-06-18 09:00:01",
    )
    snapshot = _snapshot()
    assert snapshot["display_project"]["name"] == "未归类"
    assert snapshot["display_project"]["is_uncategorized"] is True
    _assert_snapshot_has_only_official_project_contract(snapshot)


def test_session_boundary_does_not_inherit_formal_project(temp_db):
    _setup_two_projects(temp_db)
    machine = CollectorStateMachine()
    machine.transition_to(
        "recording",
        _normal("a.py", "D:\\ProjectA\\a.py"),
        at_time="2026-06-18 09:00:00",
    )
    machine.transition_to("stopped", at_time="2026-06-18 09:00:05")
    machine.transition_to(
        "recording",
        _normal("tmp", "D:\\Unmapped\\tmp"),
        at_time="2026-06-18 10:00:00",
    )
    snapshot = _snapshot()
    assert snapshot["display_project"]["name"] == "未归类"
    _assert_snapshot_has_only_official_project_contract(snapshot)
