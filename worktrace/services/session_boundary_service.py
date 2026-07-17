"""Session-boundary command facade."""

from __future__ import annotations

from ..mutation_effects import report_structure_mutation
from . import session_boundary_service_core as _core

for _name in dir(_core):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_core, _name)

record_boundary = report_structure_mutation(_core.record_boundary)
_core.record_boundary = record_boundary
