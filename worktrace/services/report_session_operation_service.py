"""Immutable report-operation command facade."""

from __future__ import annotations

from functools import wraps

from ..data_generation_repository import DataGenerationNamespace
from ..domain_unit_of_work import DomainUnitOfWork
from ..service_facade import bind_core_facade
from . import report_session_operation_service_core as _core

for _name in dir(_core):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_core, _name)


def _report_operation(function):
    """Persist receipts without invalidating structure for replay/no-op outcomes."""

    @wraps(function)
    def wrapped(*args, **kwargs):
        with DomainUnitOfWork(allow_no_effect=True) as unit_of_work:
            result = function(*args, **kwargs)
            if str(getattr(result, "outcome_type", "")) == "operation_committed":
                unit_of_work.add_effects(DataGenerationNamespace.REPORT_STRUCTURE)
            return result

    return wrapped


edit_session = _report_operation(_core.edit_session)
hide_session = _report_operation(_core.hide_session)
merge_session = _report_operation(_core.merge_session)
split_session = _report_operation(_core.split_session)
copy_session = _report_operation(_core.copy_session)
hide_session_activity = _report_operation(_core.hide_session_activity)

_core.edit_session = edit_session
_core.hide_session = hide_session
_core.merge_session = merge_session
_core.split_session = split_session
_core.copy_session = copy_session
_core.hide_session_activity = hide_session_activity
bind_core_facade(__name__, _core)
