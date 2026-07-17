"""Activity query facade with explicit post-capture mutation ownership."""

from __future__ import annotations

from ..mutation_effects import report_structure_mutation
from ..service_facade import bind_core_facade
from . import activity_service_core as _core

for _name in dir(_core):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_core, _name)

_update_file_path_impl = _core.update_activity_file_path_hint
_removed_project_edit_impl = _core.update_project_editable_activities_project
_removed_note_edit_impl = _core.update_project_editable_activity_note

update_activity_file_path_hint = report_structure_mutation(_update_file_path_impl)


def update_project_editable_activities_project(
    activity_ids: list[int],
    project_id: int,
) -> None:
    """Preserve the explicit rejection contract for removed activity-level edits."""

    _removed_project_edit_impl(activity_ids, project_id)


def update_project_editable_activity_note(activity_id: int, note: str) -> None:
    """Preserve the explicit rejection contract for removed activity-level edits."""

    _removed_note_edit_impl(activity_id, note)


_core.update_activity_file_path_hint = update_activity_file_path_hint
_core.update_project_editable_activities_project = (
    update_project_editable_activities_project
)
_core.update_project_editable_activity_note = update_project_editable_activity_note
bind_core_facade(__name__, _core)
