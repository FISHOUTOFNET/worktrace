from __future__ import annotations

from types import SimpleNamespace

import pytest

from worktrace.integrations.fd_work.contracts import (
    FDWorkEntryDraft,
    FDWorkEntryError,
    FDWorkEntryRequest,
)
from worktrace.integrations.fd_work.draft_builder import (
    FDWorkEntryDraftBuilder,
    format_duration_hours,
)


pytestmark = [
    pytest.mark.unit,
    pytest.mark.contract,
    pytest.mark.integration,
    pytest.mark.parallel_safe,
]

DATE = "2026-07-31"
KEY = "base:closed-session"
REVISION = "projection-revision-1"


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


def _projection(entry=None):
    return SimpleNamespace(entry_by_key={} if entry is None else {KEY: entry})


def _request(**overrides):
    values = {
        "report_date": DATE,
        "projection_instance_key": KEY,
        "expected_projection_revision": REVISION,
    }
    values.update(overrides)
    return FDWorkEntryRequest(**values)


class _BindingVerifier:
    def __init__(self, bound=True):
        self.bound = bound
        self.calls = []

    def require_project_binding(self, project_id, project_name):
        self.calls.append((project_id, project_name))
        if not self.bound:
            raise FDWorkEntryError("project_not_fd_work_bound")


def _builder(projection, *, bound=True):
    calls = []

    def read(report_date):
        calls.append(report_date)
        return projection

    verifier = _BindingVerifier(bound=bound)
    return FDWorkEntryDraftBuilder(
        projection_reader=read,
        binding_verifier=verifier,
    ), calls, verifier


def test_authoritative_projection_separates_full_label_from_search_query():
    builder, calls, verifier = _builder(_projection(_entry()))

    draft = builder.build_draft(_request())

    assert calls == [DATE]
    assert verifier.calls == [(17, "MATTER-2026-001")]
    assert draft == FDWorkEntryDraft(
        work_date=DATE,
        case_label="MATTER-2026-001",
        case_query="MATTER-2026-001",
        duration_hours="1.4",
        narrative="Prepared filing summary.",
    )
    assert set(vars(draft)) == {
        "work_date",
        "case_label",
        "case_query",
        "duration_hours",
        "narrative",
    }


def test_fd_work_case_label_keeps_binding_identity_and_derives_canonical_query():
    label = "#26IP0165 IPDD_Miragene"
    builder, _calls, verifier = _builder(
        _projection(_entry(project_name=f"\u3000{label}\u00a0"))
    )

    draft = builder.build_draft(_request())

    assert verifier.calls == [(17, label)]
    assert draft.case_label == label
    assert draft.case_query == "26IP0165"


@pytest.mark.parametrize(
    ("request_overrides", "entry_overrides"),
    [
        ({"projection_instance_key": "missing"}, {}),
        ({}, {"projection_revision": "new-revision"}),
    ],
)
def test_projection_identity_or_revision_change_is_rejected(
    request_overrides,
    entry_overrides,
):
    builder, _calls, _verifier = _builder(_projection(_entry(**entry_overrides)))

    with pytest.raises(FDWorkEntryError) as raised:
        builder.build_draft(_request(**request_overrides))

    assert raised.value.code == "stale_selection"


def test_convenience_build_uses_identity_only_and_rebuilds_authoritatively():
    builder, calls, _verifier = _builder(_projection(_entry()))

    draft = builder.build(DATE, KEY, REVISION)

    assert calls == [DATE]
    assert draft.case_label == "MATTER-2026-001"
    assert draft.case_query == "MATTER-2026-001"


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"is_in_progress": True}, "in_progress_session"),
        ({"row_kind": "system_session"}, "system_project"),
        ({"is_report_uncategorized": True}, "uncategorized_project"),
        ({"project_name": "未归类"}, "uncategorized_project"),
        ({"project_is_system": True}, "system_project"),
        ({"project_is_special": True}, "system_project"),
        ({"is_report_project": False}, "system_project"),
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
    builder, _calls, _verifier = _builder(_projection(_entry(**overrides)))

    with pytest.raises(FDWorkEntryError) as raised:
        builder.build_draft(_request())

    assert raised.value.code == code


def test_adjusted_duration_wins_over_actual_duration():
    builder, _calls, _verifier = _builder(
        _projection(
            _entry(duration_seconds=3_600, adjusted_duration_seconds=5_040)
        )
    )
    assert builder.build_draft(_request()).duration_hours == "1.4"


def test_actual_duration_is_used_without_an_adjustment():
    builder, _calls, _verifier = _builder(
        _projection(_entry(duration_seconds=5_040, adjusted_duration_seconds=None))
    )
    assert builder.build_draft(_request()).duration_hours == "1.4"


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
def test_duration_conversion_matches_timeline_one_decimal_semantics(seconds, expected):
    assert format_duration_hours(seconds) == expected


def test_duration_that_rounds_to_zero_is_rejected_at_remote_boundary():
    builder, _calls, _verifier = _builder(_projection(_entry(duration_seconds=179)))
    with pytest.raises(FDWorkEntryError) as raised:
        builder.build_draft(_request())
    assert raised.value.code == "invalid_duration"


def test_narrative_only_strips_edge_whitespace_without_rewriting_body():
    builder, _calls, _verifier = _builder(
        _projection(_entry(session_note=" \nLine one.\n\n  Line two with  spaces.\t "))
    )
    assert (
        builder.build_draft(_request()).narrative
        == "Line one.\n\n  Line two with  spaces."
    )


def test_unbound_project_is_rejected_without_searching_remote_cases():
    builder, _calls, verifier = _builder(_projection(_entry()), bound=False)

    with pytest.raises(FDWorkEntryError) as raised:
        builder.build_draft(_request())

    assert raised.value.code == "project_not_fd_work_bound"
    assert verifier.calls == [(17, "MATTER-2026-001")]
