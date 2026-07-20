import pytest

pytestmark = [pytest.mark.db, pytest.mark.unit]

from worktrace.services import session_boundary_service
from worktrace.services.session_boundary_policy import (
    ALLOWED_HARD_BOUNDARY_REASONS,
    FORBIDDEN_TRANSIENT_REASONS,
    normalize_hard_boundary_reason,
    validate_hard_boundary_reason,
)


def test_allowed_hard_boundary_reasons_are_whitelisted(temp_db):
    for reason in ALLOWED_HARD_BOUNDARY_REASONS:
        session_boundary_service.record_boundary("2026-06-18 09:00:00", reason)


def test_retired_boundary_reason_aliases_are_rejected():
    for reason in ("paused", "stopped", "time_jump", "secure_import"):
        assert normalize_hard_boundary_reason(reason) == reason
        with pytest.raises(ValueError):
            validate_hard_boundary_reason(reason)


def test_transient_reasons_cannot_be_written_as_hard_boundaries(temp_db):
    for reason in FORBIDDEN_TRANSIENT_REASONS:
        with pytest.raises(ValueError):
            session_boundary_service.record_boundary("2026-06-18 09:00:00", reason)


def test_unknown_reason_is_rejected():
    with pytest.raises(ValueError):
        validate_hard_boundary_reason("idle_poll_failure")
