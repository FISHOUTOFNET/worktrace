"""Batch rule command facade."""

from __future__ import annotations

from ..mutation_effects import (
    classification_catalog_mutation,
    report_structure_mutation,
)
from ..service_facade import bind_core_facade
from . import rule_batch_service_core as _core

for _name in dir(_core):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_core, _name)

backfill_project_rules_batch = report_structure_mutation(
    _core.backfill_project_rules_batch
)
set_project_rules_batch_enabled = classification_catalog_mutation(
    _core.set_project_rules_batch_enabled
)

_core.backfill_project_rules_batch = backfill_project_rules_batch
_core.set_project_rules_batch_enabled = set_project_rules_batch_enabled
bind_core_facade(__name__, _core)
