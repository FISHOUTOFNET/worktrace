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


pytestmark = [pytest.mark.unit, pytest.mark.contract, pytest.mark.parallel_safe]

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
        "expected_source_version": SOURCE_VERSION,
    }
    values.update(overrides)
    return FDWorkEntryRequest(**values)


def _service(projection):
    calls = []

    def read(report_date):
        calls.append(report_date)
        return projection

    return FDWorkEntryService(projection_reader=read), calls


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
        ({"expected_source_version": "stale"}, {}),
        ({"expected_projection_revision": "stale"}, {}),
        ({}, {"projection_revision": "new-revision"}),
    ],
)
def test_stale_source_or_projection_revision_is_rejected(
    request_overrides,
    entry_overrides,
):
    source = (
        SOURCE_VERSION
        if request_overrides.get("expected_source_version") != "stale"
        else "current-source"
    )
    service, _ = _service(_projection(_entry(**entry_overrides), source_version=source))

    with pytest.raises(FDWorkEntryError, match="stale_selection") as raised:
        service.build_draft(_request(**request_overrides))

    assert raised.value.code == "stale_selection"


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
