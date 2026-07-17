"""Clipboard fact command facade."""

from __future__ import annotations

from ..mutation_effects import report_structure_mutation
from ..service_facade import bind_core_facade
from . import clipboard_service_core as _core

for _name in dir(_core):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_core, _name)

record_clipboard_event = report_structure_mutation(_core.record_clipboard_event)
prune_old_events = report_structure_mutation(_core.prune_old_events)

_core.record_clipboard_event = record_clipboard_event
_core.prune_old_events = prune_old_events
bind_core_facade(__name__, _core)
