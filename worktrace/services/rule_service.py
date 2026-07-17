"""Keyword-rule command facade with explicit catalog ownership."""

from __future__ import annotations

from ..mutation_effects import classification_catalog_mutation
from ..service_facade import bind_core_facade
from . import rule_service_core as _core

for _name in dir(_core):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_core, _name)

create_rule = classification_catalog_mutation(_core.create_rule)
set_rule_enabled = classification_catalog_mutation(_core.set_rule_enabled)
update_rule = classification_catalog_mutation(_core.update_rule)
delete_rule = classification_catalog_mutation(_core.delete_rule)

_core.create_rule = create_rule
_core.set_rule_enabled = set_rule_enabled
_core.update_rule = update_rule
_core.delete_rule = delete_rule
bind_core_facade(__name__, _core)
