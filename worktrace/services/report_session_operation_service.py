"""Immutable report-operation command facade."""

from __future__ import annotations

from ..mutation_effects import report_structure_mutation
from . import report_session_operation_service_core as _core

for _name in dir(_core):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_core, _name)

edit_session = report_structure_mutation(_core.edit_session)
hide_session = report_structure_mutation(_core.hide_session)
merge_session = report_structure_mutation(_core.merge_session)
split_session = report_structure_mutation(_core.split_session)
copy_session = report_structure_mutation(_core.copy_session)
hide_session_activity = report_structure_mutation(_core.hide_session_activity)

_core.edit_session = edit_session
_core.hide_session = hide_session
_core.merge_session = merge_session
_core.split_session = split_session
_core.copy_session = copy_session
_core.hide_session_activity = hide_session_activity
