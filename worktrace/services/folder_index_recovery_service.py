"""Interrupted folder-index recovery infrastructure facade."""

from __future__ import annotations

from ..db import infrastructure_write_scope
from . import folder_index_recovery_service_core as _core

for _name in dir(_core):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_core, _name)

_recover_impl = _core.recover_interrupted_indexes


def recover_interrupted_indexes() -> int:
    with infrastructure_write_scope():
        return _recover_impl()


_core.recover_interrupted_indexes = recover_interrupted_indexes
