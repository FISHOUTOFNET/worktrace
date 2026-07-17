"""Infrastructure facade for versioned activity-resource fact repair."""

from __future__ import annotations

from ..db import infrastructure_write_scope
from ..service_facade import bind_core_facade
from . import activity_fact_repair_service_core as _core

for _name in dir(_core):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_core, _name)

_repair_impl = _core.repair_missing_activity_resources


def repair_missing_activity_resources(batch_size: int = _core.DEFAULT_BATCH_SIZE) -> int:
    with infrastructure_write_scope():
        return _repair_impl(batch_size=batch_size)


_core.repair_missing_activity_resources = repair_missing_activity_resources
bind_core_facade(__name__, _core)
