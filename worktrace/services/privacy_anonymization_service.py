"""Privacy anonymization command facade."""

from __future__ import annotations

from ..mutation_effects import report_structure_mutation
from . import privacy_anonymization_service_core as _core

for _name in dir(_core):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_core, _name)

update_path_or_anonymize = report_structure_mutation(
    _core.update_path_or_anonymize
)
anonymize_activity = report_structure_mutation(_core.anonymize_activity)

_core.update_path_or_anonymize = update_path_or_anonymize
_core.anonymize_activity = anonymize_activity
