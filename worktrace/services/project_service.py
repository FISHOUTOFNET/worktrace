"""Project command facade with explicit classification-catalog ownership."""

from __future__ import annotations

from ..mutation_effects import classification_catalog_mutation
from ..service_facade import bind_core_facade
from . import project_service_core as _core

for _name in dir(_core):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_core, _name)

_create_project_impl = _core.create_project
_update_project_impl = _core.update_project
_set_project_enabled_impl = _core.set_project_enabled
_set_excluded_project_enabled_impl = _core.set_excluded_project_enabled
_archive_project_impl = _core.archive_project
_soft_delete_project_impl = _core.soft_delete_project

create_project = classification_catalog_mutation(_create_project_impl)
update_project = classification_catalog_mutation(_update_project_impl)
set_project_enabled = classification_catalog_mutation(_set_project_enabled_impl)
set_excluded_project_enabled = classification_catalog_mutation(
    _set_excluded_project_enabled_impl
)
archive_project = classification_catalog_mutation(_archive_project_impl)
soft_delete_project = classification_catalog_mutation(_soft_delete_project_impl)

_core.create_project = create_project
_core.update_project = update_project
_core.set_project_enabled = set_project_enabled
_core.set_excluded_project_enabled = set_excluded_project_enabled
_core.archive_project = archive_project
_core.soft_delete_project = soft_delete_project
bind_core_facade(__name__, _core)
