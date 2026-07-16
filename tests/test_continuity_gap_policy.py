import pytest

from tests.support import activity_factory as activity_service
from worktrace.constants import STATUS_ERROR, STATUS_EXCLUDED, STATUS_IDLE, STATUS_NORMAL, STATUS_PAUSED
from worktrace.services import activity_continuity_service, settings_service

pytestmark = [pytest.mark.db, pytest.mark.unit]


def _activity(name: str, status: str, start: str, end: str):
    activity_id = activity_service.insert_activity_row(
        app_name=name,
        process_name=name + ".exe",
        window_title=name,
        status=status,
        start_time=start,
    )
    activity_service.close_activity(activity_id, end)
    return activity_id


def test_excluded_and_short_idle_do_not_create_hard_continuity_boundary(temp_db):
    _activity("A", STATUS_NORMAL, "2026-06-18 09:00:00", "2026-06-18 09:10:00")
    _activity("Excluded", STATUS_EXCLUDED, "2026-06-18 09:10:00", "2026-06-18 09:11:00")
    _activity("Idle", STATUS_IDLE, "2026-06-18 09:11:00", "2026-06-18 09:12:00")
    _activity("B", STATUS_NORMAL, "2026-06-18 09:12:00", "2026-06-18 09:20:00")

    assert not activity_continuity_service.has_hard_boundary_between(
        "2026-06-18 09:10:00",
        "2026-06-18 09:12:00",
    )


def test_paused_and_long_idle_error_are_hard_status_boundaries(temp_db):
    _activity("Pause", STATUS_PAUSED, "2026-06-18 09:00:00", "2026-06-18 09:01:00")
    _activity("Idle", STATUS_IDLE, "2026-06-18 10:00:00", "2026-06-18 10:20:00")
    _activity("Error", STATUS_ERROR, "2026-06-18 11:00:00", "2026-06-18 11:20:00")

    assert activity_continuity_service.has_hard_boundary_between(
        "2026-06-18 09:00:00",
        "2026-06-18 09:01:00",
    )
    assert activity_continuity_service.has_hard_boundary_between(
        "2026-06-18 10:00:00",
        "2026-06-18 10:20:00",
    )
    assert activity_continuity_service.has_hard_boundary_between(
        "2026-06-18 11:00:00",
        "2026-06-18 11:20:00",
    )


def test_unrecorded_gap_policy_keeps_long_unknown_gaps_as_boundaries(temp_db):
    settings_service.set_setting("unrecorded_gap_boundary_seconds", "120")

    assert activity_continuity_service.is_true_unrecorded_gap_boundary(
        "2026-06-18 09:00:00",
        "2026-06-18 09:05:00",
    )
    assert not activity_continuity_service.is_true_unrecorded_gap_boundary(
        "2026-06-18 09:00:00",
        "2026-06-18 09:01:00",
    )


def test_same_resource_stall_recovery_is_soft_but_explicit_boundaries_are_not(monkeypatch):
    previous = {"status": STATUS_NORMAL, "resource_identity_key": "file:report"}
    recovered = {"status": STATUS_NORMAL, "resource_identity_key": "file:report"}
    monkeypatch.setattr(activity_continuity_service, "_last_normal_activity_before", lambda _at: previous)
    monkeypatch.setattr(activity_continuity_service, "_current_snapshot", lambda: recovered)
    monkeypatch.setattr(activity_continuity_service, "_has_explicit_boundary_between", lambda *_: False)
    monkeypatch.setattr(activity_continuity_service, "_has_boundary_status_between", lambda *_: False)
    monkeypatch.setattr(
        activity_continuity_service,
        "get_setting",
        lambda key, default="": "degraded" if key == "collector_health_state" else default,
    )

    assert activity_continuity_service.is_same_resource_stall_recovery_gap(
        "2026-06-18 09:00:00", "2026-06-18 09:05:00"
    )
    assert activity_continuity_service.is_soft_collector_gap(
        "2026-06-18 09:00:00", "2026-06-18 09:05:00"
    )

    recovered["resource_identity_key"] = "file:other"
    assert not activity_continuity_service.is_same_resource_stall_recovery_gap(
        "2026-06-18 09:00:00", "2026-06-18 09:05:00"
    )

    recovered["resource_identity_key"] = "file:report"
    monkeypatch.setattr(activity_continuity_service, "_has_explicit_boundary_between", lambda *_: True)
    assert not activity_continuity_service.is_same_resource_stall_recovery_gap(
        "2026-06-18 09:00:00", "2026-06-18 09:05:00"
    )
