import pytest

from worktrace.constants import STATUS_ERROR, STATUS_EXCLUDED, STATUS_IDLE, STATUS_NORMAL, STATUS_PAUSED
from worktrace.services import activity_status_policy as policy


def test_activity_status_contracts_are_centralized():
    assert policy.is_activity_fact_status(STATUS_NORMAL)
    assert policy.is_activity_fact_status(STATUS_EXCLUDED)
    assert policy.is_activity_fact_status(STATUS_IDLE)
    assert policy.is_activity_fact_status(STATUS_PAUSED)
    assert policy.is_activity_fact_status(STATUS_ERROR)

    assert policy.is_project_attributable_status(STATUS_NORMAL)
    assert not policy.is_project_attributable_status(STATUS_EXCLUDED)
    assert not policy.is_project_attributable_status(STATUS_IDLE)
    assert not policy.is_project_attributable_status(STATUS_PAUSED)
    assert not policy.is_project_attributable_status(STATUS_ERROR)

    for status in (STATUS_NORMAL, STATUS_EXCLUDED, STATUS_IDLE, STATUS_PAUSED, STATUS_ERROR):
        assert policy.is_status_reportable(status)
        assert policy.is_status_exportable(status)


def test_special_statuses_are_not_natural_hard_boundaries():
    assert not policy.does_status_require_boundary(STATUS_NORMAL, 3600)
    assert not policy.does_status_require_boundary(STATUS_EXCLUDED, 3600)
    assert not policy.does_status_require_boundary(STATUS_IDLE, 30)
    assert policy.does_status_require_boundary(STATUS_IDLE, 3600)
    assert policy.does_status_require_boundary(STATUS_PAUSED, 0)
    assert not policy.does_status_require_boundary(STATUS_ERROR, 30)
    assert policy.does_status_require_boundary(STATUS_ERROR, 3600)


@pytest.mark.parametrize("status", ["healthy", "degraded", "failing", "stopped"])
def test_collector_health_is_not_activity_status(status):
    assert not policy.is_collector_health_status(status)
    assert not policy.is_activity_fact_status(status)
