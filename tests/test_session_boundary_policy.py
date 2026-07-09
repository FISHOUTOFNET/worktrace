import pytest

from worktrace.services import session_boundary_service
from worktrace.services.session_boundary_policy import (
    ALLOWED_HARD_BOUNDARY_REASONS,
    FORBIDDEN_TRANSIENT_REASONS,
    normalize_hard_boundary_reason,
    validate_hard_boundary_reason,
)


def test_allowed_hard_boundary_reasons_are_whitelisted(temp_db):
    for reason in ALLOWED_HARD_BOUNDARY_REASONS:
        session_boundary_service.record_hard_boundary("2026-06-18 09:00:00", reason)


def test_legacy_boundary_reasons_are_normalized():
    assert normalize_hard_boundary_reason("paused") == "user_pause"
    assert normalize_hard_boundary_reason("stopped") == "user_stop"
    assert normalize_hard_boundary_reason("time_jump") == "sleep_resume"


def test_transient_reasons_cannot_be_written_as_hard_boundaries(temp_db):
    for reason in FORBIDDEN_TRANSIENT_REASONS:
        with pytest.raises(ValueError):
            session_boundary_service.record_hard_boundary("2026-06-18 09:00:00", reason)


def test_unknown_reason_is_rejected():
    with pytest.raises(ValueError):
        validate_hard_boundary_reason("idle_poll_failure")
