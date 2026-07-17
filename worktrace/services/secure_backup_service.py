"""Encrypted backup facade with explicit physical-replacement generations."""

from __future__ import annotations

from ..data_generation_repository import (
    ALL_DATA_GENERATION_NAMESPACES,
    DataGenerationRepository,
)
from ..db import get_connection, infrastructure_write_scope
from ..service_facade import bind_core_facade
from . import secure_backup_service_core as _core

for _name in dir(_core):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_core, _name)

_replace_import_impl = _core._replace_import


def _replace_import(data):
    with infrastructure_write_scope():
        imported = _replace_import_impl(data)
        with get_connection() as conn:
            DataGenerationRepository.bump(
                conn,
                ALL_DATA_GENERATION_NAMESPACES,
            )
    return imported


_core._replace_import = _replace_import
bind_core_facade(__name__, _core)
