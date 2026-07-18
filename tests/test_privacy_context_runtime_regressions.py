from __future__ import annotations

import threading
from datetime import date

import pytest

from worktrace.services import system_project_service

from worktrace.collector.collector import run_collector
from worktrace.collector.state_machine import CollectorStateMachine
from worktrace.constants import EXCLUDED_WINDOW_TITLE
from worktrace.platforms.base import ActiveWindow
from tests.support import activity_factory as activity_service
from worktrace.services import (
    privacy_gate_service,
    folder_rule_service,
    privacy_service,
    project_service,
    settings_service,
    statistics_service,
)
from worktrace.services.report_session_builder import _finalize_session_semantics

pytestmark = [pytest.mark.db, pytest.mark.integration, pytest.mark.contract]


class _OneShotAdapter:
    def __init__(self, window: ActiveWindow) -> None:
        self.window = window
        self.clipboard_enabled = False

    def get_active_window(self) -> ActiveWindow:
        return self.window

    def get_idle_seconds(self) -> int:
        return 0

    def set_clipboard_capture_enabled(self, enabled: bool) -> None:
        self.clipboard_enabled = bool(enabled)

    def get_clipboard_events(self):
        return []


def test_collector_turns_unresolved_privacy_observation_into_excluded_row(
    temp_db,
    monkeypatch,
):
    privacy_gate_service.accept_privacy_notice()
    settings_service.set_setting("user_paused", "false")
    stop = threading.Event()

    def unresolved(_window):
        stop.set()
        raise privacy_service.PrivacyResolutionPending(
            "privacy_path_unresolved"
        )

    monkeypatch.setattr(privacy_service, "is_excluded", unresolved)
    run_collector(
        _OneShotAdapter(
            ActiveWindow(
                "Word",
                "winword.exe",
                "Sensitive.docx - Word",
                privacy_path_required=True,
            )
        ),
        stop,
    )

    rows = activity_service.get_activities_by_date(date.today().isoformat())
    excluded = [row for row in rows if row["status"] == "excluded"]
    assert excluded
    assert excluded[-1]["window_title"] == EXCLUDED_WINDOW_TITLE


def test_same_resource_late_excluded_path_redacts_its_existing_row(temp_db):
    excluded_id = system_project_service.require_excluded_project_id()
    project_service.set_project_enabled(excluded_id, True)
    folder_rule_service.create_or_update_folder_rule(
        "D:\\Private",
        excluded_id,
    )
    machine = CollectorStateMachine()
    machine.transition_to(
        "recording",
        ActiveWindow("Word", "winword.exe", "Spec.docx - Word"),
        at_time="2026-07-15 09:00:00",
    )
    previous_id = int(activity_service.get_open_activity()["id"])

    machine.transition_to(
        "recording",
        ActiveWindow(
            "Word",
            "winword.exe",
            "Spec.docx - Word",
            "D:\\Private\\Spec.docx",
        ),
        at_time="2026-07-15 09:01:00",
    )

    previous = activity_service.get_activity(previous_id)
    current = activity_service.get_open_activity()
    assert previous["status"] == "excluded"
    assert previous["window_title"] == EXCLUDED_WINDOW_TITLE
    assert previous["file_path_hint"] is None
    assert current is not None
    assert current["status"] == "excluded"


def test_session_project_semantics_do_not_depend_on_first_contribution():
    context = {
        "id": 1,
        "start_time": "2026-07-15 09:00:00",
        "report_project_id": 7,
        "report_project_name": "A",
        "report_project_description": "",
        "report_project_key": "project:7",
        "is_report_project": True,
        "is_report_classified": True,
        "is_report_uncategorized": False,
        "is_official_project": False,
        "report_attribution_kind": "report_context_short_gap",
    }
    official = {
        **context,
        "id": 2,
        "start_time": "2026-07-15 09:01:00",
        "is_official_project": True,
        "report_attribution_kind": "official_direct",
    }
    base = {
        "project_id": 7,
        "project_name": "A",
        "project_description": "",
    }

    forward = _finalize_session_semantics(dict(base), [context, official])
    reverse = _finalize_session_semantics(dict(base), [official, context])
    fields = (
        "project_id",
        "project_name",
        "is_official_project",
        "report_attribution_kind",
        "is_report_project",
        "is_report_classified",
        "is_report_uncategorized",
    )
    assert {field: forward[field] for field in fields} == {
        field: reverse[field] for field in fields
    }
    assert forward["is_official_project"] is True
    assert forward["report_attribution_kind"] == "official_direct"


def test_cross_midnight_activity_count_is_not_report_slice_count(temp_db):
    project_id = project_service.create_project("Cross Midnight")
    activity_id = activity_service.create_activity(
        "Word",
        "word.exe",
        "Overnight.docx",
        project_id=project_id,
        start_time="2026-07-15 23:50:00",
    )
    activity_service.close_activity(activity_id, "2026-07-16 00:10:00")

    summary = statistics_service.get_statistics_export_summary(
        "2026-07-15",
        "2026-07-16",
    )

    assert summary["activity_count"] == 1
    assert summary["report_slice_count"] == 2
    assert summary["export_preview"]["included_activity_count"] == 1
    assert summary["export_preview"]["included_report_slice_count"] == 2
