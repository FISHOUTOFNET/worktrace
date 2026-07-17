"""Recoverable history-job command facade."""

from __future__ import annotations

from ..mutation_effects import (
    classification_catalog_mutation,
    report_structure_mutation,
)
from ..service_facade import bind_core_facade
from . import history_mutation_job_service_core as _core

for _name in dir(_core):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_core, _name)

submit_rule_job = classification_catalog_mutation(_core.submit_rule_job)
run_job_batch = report_structure_mutation(_core.run_job_batch)

_core.submit_rule_job = submit_rule_job
_core.run_job_batch = run_job_batch
bind_core_facade(__name__, _core)
