"""Persisted activity-resource command facade."""

from __future__ import annotations

import sqlite3

from ..mutation_effects import report_structure_mutation
from ..resources.types import DetectedResource
from . import resource_service_core as _core

for _name in dir(_core):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_core, _name)

_create_or_update_impl = _core.create_or_update_activity_resource


@report_structure_mutation
def _create_or_update_owned(
    activity_id: int,
    resource: DetectedResource,
) -> None:
    _create_or_update_impl(activity_id, resource, conn=None)


def create_or_update_activity_resource(
    activity_id: int,
    resource: DetectedResource,
    conn: sqlite3.Connection | None = None,
) -> None:
    if conn is not None:
        _create_or_update_impl(activity_id, resource, conn=conn)
        return
    _create_or_update_owned(activity_id, resource)
