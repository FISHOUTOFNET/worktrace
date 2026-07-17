"""Folder-rule command facade with explicit catalog ownership."""

from __future__ import annotations

from ..mutation_effects import classification_catalog_mutation
from . import folder_rule_service_core as _core

for _name in dir(_core):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_core, _name)

create_or_update_folder_rule = classification_catalog_mutation(
    _core.create_or_update_folder_rule
)
update_folder_rule = classification_catalog_mutation(_core.update_folder_rule)
delete_folder_rule = classification_catalog_mutation(_core.delete_folder_rule)
set_folder_rule_enabled = classification_catalog_mutation(
    _core.set_folder_rule_enabled
)

_core.create_or_update_folder_rule = create_or_update_folder_rule
_core.update_folder_rule = update_folder_rule
_core.delete_folder_rule = delete_folder_rule
_core.set_folder_rule_enabled = set_folder_rule_enabled
