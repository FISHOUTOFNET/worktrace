"""Destructive database-maintenance command facade."""

from __future__ import annotations

from ..mutation_effects import database_replacement_mutation
from ..service_facade import bind_core_facade
from . import database_maintenance_service_core as _core

for _name in dir(_core):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_core, _name)

clear_all_live_data = database_replacement_mutation(_core.clear_all_live_data)
_core.clear_all_live_data = clear_all_live_data
bind_core_facade(__name__, _core)
