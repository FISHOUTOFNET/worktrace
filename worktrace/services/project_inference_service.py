"""Project inference facade over persisted facts and an explicit report UoW."""

from __future__ import annotations

from ..constants import UNCATEGORIZED_PROJECT
from ..mutation_effects import report_structure_mutation
from . import project_inference_service_core as _core

for _name in dir(_core):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_core, _name)


def _require_uncategorized_project_id(conn) -> int:
    row = conn.execute(
        "SELECT id FROM project WHERE name = ?",
        (UNCATEGORIZED_PROJECT,),
    ).fetchone()
    if row is None:
        raise ValueError("database_schema_incompatible")
    return int(row["id"])


def _require_persisted_resource(conn, activity_id: int, activity: dict) -> dict:
    row = conn.execute(
        "SELECT * FROM activity_resource WHERE activity_id = ?",
        (int(activity_id),),
    ).fetchone()
    if row is None or not str(row["identity_key"] or "").strip():
        raise ValueError("data_repair_required")
    return dict(row)


_assign_project_for_activity_impl = _core.assign_project_for_activity
assign_project_for_activity = report_structure_mutation(
    _assign_project_for_activity_impl
)

_core.assign_project_for_activity = assign_project_for_activity
_core._get_uncategorized_project_id = _require_uncategorized_project_id
_core._resource_for_activity = _require_persisted_resource
