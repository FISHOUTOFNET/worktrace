"""Startup recovery facade with explicit report-mutation ownership."""

from __future__ import annotations

from ..mutation_effects import report_structure_mutation
from . import recovery_service_core as _core

for _name in dir(_core):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_core, _name)

mark_record_error = report_structure_mutation(_core.mark_record_error)
_core.mark_record_error = mark_record_error
