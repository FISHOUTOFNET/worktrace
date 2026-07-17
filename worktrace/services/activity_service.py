"""Activity query facade with explicit post-capture mutation ownership."""

from __future__ import annotations

from ..mutation_effects import report_structure_mutation
from . import activity_service_core as _core

for _name in dir(_core):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_core, _name)

update_activity_file_path_hint = report_structure_mutation(
    _core.update_activity_file_path_hint
)
_core.update_activity_file_path_hint = update_activity_file_path_hint
