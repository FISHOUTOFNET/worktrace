from __future__ import annotations

from types import SimpleNamespace

import pytest

from worktrace.integrations.fd_work.contracts import (
    FDWorkEntryDraft,
    FDWorkEntryError,
    FDWorkEntryRequest,
)
from worktrace.integrations.fd_work.entry_service import (
    FDWorkEntryService,
    format_duration_hours,
)
from worktrace.runtime.application_services import build_application_services


pytestmark = [
    pytest.mark.unit,
    pytest.mark.contract,
    pytest.mark.integration,
    pytest.mark.parallel_safe,
]

DATE = "2026-07-31"
KEY = "base:closed-session"
REVISION = "projection-revision-1"
SOURCE_VERSION = "source-version-1"


def _entry(**overrides):
    entry = {
        "row_kind": "project_session",
        "projection_instance_key": KEY,
        "projection_revision": REVISION,
        "project_id": 17,
        "project_name": "  MATTER-2026-001  ",
        "project_is_deleted": False,
        "project_is_archived": False,
        "project_is_enabled": True,
        "project_is_system": False,
        "project_is_special": False,
        "is_report_project": True,
        "is_report_uncategorized": False,
        "is_in_progress": False,
        "duration_seconds": 5_040,
        "adjusted_duration_seconds": None,
        "session_note": "  Prepared filing summary.  ",
    }
    entry.update(overrides)
    return entry


def _projection(entry=None, *, source_version=SOURCE_VERSION):
    values = {} if entry is None else {KEY: entry}
    return SimpleNamespace(
        source_version_token=source_version,
        entry_by_key=values,
    )


def _request(**overrides):
    values = {
        "report_date": DATE,
        "projection_instance_key": KEY,
        "expected_projection_revision": REVISION,
    }
    values.update(overrides)
    return FDWorkEntryRequest(**values)


def _service(projection):
    calls = []

    def read(report_date):
        calls.append(report_date)
        return projection

    return FDWorkEntryService(
        projection_reader=read,
        enabled_reader=lambda: True,
    ), calls


def test_authoritative_projection_builds_only_the_four_field_draft():
    service, calls = _service(_projection(_entry()))

    draft = service.build_draft(_request())

    assert calls == [DATE]
    assert draft == FDWorkEntryDraft(
        work_date=DATE,
        case_number="MATTER-2026-001",
        duration_hours="1.4",
        narrative="Prepared filing summary.",
    )
    assert set(vars(draft)) == {
        "work_date",
        "case_number",
        "duration_hours",
        "narrative",
    }


@pytest.mark.parametrize(
    ("request_overrides", "entry_overrides"),
    [
        ({"expected_projection_revision": "stale"}, {}),
        ({}, {"projection_revision": "new-revision"}),
    ],
)
def test_projection_revision_change_is_rejected(request_overrides, entry_overrides):
    service, _ = _service(_projection(_entry(**entry_overrides)))

    with pytest.raises(FDWorkEntryError, match="stale_selection") as raised:
        service.build_draft(_request(**request_overrides))

    assert raised.value.code == "stale_selection"


def test_unrelated_day_source_version_change_does_not_reject_unchanged_session():
    service, _ = _service(
        _projection(_entry(), source_version="unrelated-day-change")
    )

    assert service.build_draft(_request()).case_number == "MATTER-2026-001"


def test_fd_work_is_disabled_by_default_and_direct_open_is_rejected():
    opened = []
    service = FDWorkEntryService(
        projection_reader=lambda _date: _projection(_entry()),
        window_controller=SimpleNamespace(open_entry=lambda draft: opened.append(draft)),
        enabled_reader=lambda: False,
    )

    assert service.get_settings_status() == {"supported": True, "enabled": False}
    with pytest.raises(FDWorkEntryError) as raised:
        service.open_entry(DATE, KEY, REVISION)
    assert raised.value.code == "fd_work_disabled"
    assert opened == []


def test_fd_work_enable_state_is_persisted_and_disable_delegates_to_window():
    state = {"enabled": False}
    disabled = []
    controller = SimpleNamespace(disable=lambda: disabled.append(True))
    service = FDWorkEntryService(
        window_controller=controller,
        enabled_reader=lambda: state["enabled"],
        enabled_writer=lambda enabled: state.__setitem__("enabled", enabled),
    )

    assert service.set_enabled(True) == {"supported": True, "enabled": True}
    assert state["enabled"] is True
    assert disabled == []
    assert service.set_enabled(False) == {"supported": True, "enabled": False}
    assert disabled == [True]


def test_shipping_composition_shares_one_fd_work_capability_owner():
    controller = SimpleNamespace(shutdown=lambda: None)
    services = build_application_services(
        SimpleNamespace(),
        fd_work_window_controller=controller,
    )

    assert services.settings._fd_work is services.fd_work
    assert services.fd_work._window_controller is controller


def test_missing_projection_identity_is_rejected_as_stale():
    service, _ = _service(_projection())

    with pytest.raises(FDWorkEntryError) as raised:
        service.build_draft(_request())

    assert raised.value.code == "stale_selection"


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"is_in_progress": True}, "in_progress_session"),
        ({"row_kind": "standalone_status"}, "system_project"),
        ({"is_report_project": False, "is_report_uncategorized": True}, "uncategorized_project"),
        ({"project_name": "未归类"}, "uncategorized_project"),
        ({"project_name": "已排除"}, "system_project"),
        ({"project_is_system": True}, "system_project"),
        ({"project_is_special": True}, "system_project"),
        ({"project_is_deleted": True}, "project_unavailable"),
        ({"project_is_archived": True}, "project_unavailable"),
        ({"project_is_enabled": False}, "project_unavailable"),
        ({"project_name": " \u3000 "}, "empty_project_name"),
        ({"session_note": " \n\t "}, "empty_narrative"),
        ({"duration_seconds": 0}, "invalid_duration"),
        ({"duration_seconds": -1}, "invalid_duration"),
        ({"duration_seconds": 86_041}, "duration_exceeds_limit"),
    ],
)
def test_invalid_or_non_user_session_fails_closed(overrides, code):
    service, _ = _service(_projection(_entry(**overrides)))

    with pytest.raises(FDWorkEntryError) as raised:
        service.build_draft(_request())

    assert raised.value.code == code


def test_adjusted_duration_wins_over_actual_duration():
    service, _ = _service(
        _projection(
            _entry(
                duration_seconds=3_600,
                adjusted_duration_seconds=5_040,
            )
        )
    )

    assert service.build_draft(_request()).duration_hours == "1.4"


def test_actual_duration_is_used_without_an_adjustment():
    service, _ = _service(
        _projection(
            _entry(
                duration_seconds=5_040,
                adjusted_duration_seconds=None,
            )
        )
    )

    assert service.build_draft(_request()).duration_hours == "1.4"


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (180, "0.1"),
        (179, "0.0"),
        (3_600, "1.0"),
        (5_040, "1.4"),
        (8_820, "2.5"),
        (86_040, "23.9"),
    ],
)
def test_duration_conversion_matches_timeline_one_decimal_semantics(
    seconds,
    expected,
):
    assert format_duration_hours(seconds) == expected


def test_duration_that_rounds_to_zero_is_rejected_at_remote_boundary():
    service, _ = _service(_projection(_entry(duration_seconds=179)))

    with pytest.raises(FDWorkEntryError) as raised:
        service.build_draft(_request())

    assert raised.value.code == "invalid_duration"


def test_narrative_only_strips_edge_whitespace_without_rewriting_body():
    service, _ = _service(
        _projection(
            _entry(session_note=" \nLine one.\n\n  Line two with  spaces.\t ")
        )
    )

    assert (
        service.build_draft(_request()).narrative
        == "Line one.\n\n  Line two with  spaces."
    )
