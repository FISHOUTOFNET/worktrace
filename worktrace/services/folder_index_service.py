"""Derived folder-index facade with explicit maintenance ownership."""

from __future__ import annotations

from functools import wraps

from ..db import infrastructure_write_scope
from ..mutation_effects import classification_index_mutation
from . import folder_index_service_core as _core

for _name in dir(_core):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_core, _name)


def _infrastructure_write(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        with infrastructure_write_scope():
            return function(*args, **kwargs)

    return wrapped


for _name in (
    "request_rebuild_for_rule",
    "delete_index_for_rule",
    "ensure_index_states_for_folder_rules",
    "mark_index_stale",
    "_begin_generation",
    "_fail_generation",
    "_abandon_generation",
    "_cleanup_old_generations",
    "_insert_entry_batch",
    "_validate_rule_index",
):
    _wrapped = _infrastructure_write(getattr(_core, _name))
    globals()[_name] = _wrapped
    setattr(_core, _name, _wrapped)

_activate_generation = classification_index_mutation(_core._activate_generation)
_core._activate_generation = _activate_generation
