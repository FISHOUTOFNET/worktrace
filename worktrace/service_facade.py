"""Transparent module bridge for command facades backed by implementation cores."""

from __future__ import annotations

import sys
from types import ModuleType


class _CoreBackedFacadeModule(ModuleType):
    """Mirror runtime attribute replacement from a public facade to its core.

    Tests and integrations legitimately replace public dependencies with
    monkeypatches. A facade/core split must preserve that module contract;
    otherwise the core retains a stale reference and executes a different
    dependency graph from the public module.
    """

    def __setattr__(self, name: str, value) -> None:
        ModuleType.__setattr__(self, name, value)
        core = self.__dict__.get("_facade_core")
        if core is None or name in {"_facade_core", "_core"}:
            return
        if hasattr(core, name):
            setattr(core, name, value)


def bind_core_facade(module_name: str, core: ModuleType) -> None:
    module = sys.modules[module_name]
    if not isinstance(module, _CoreBackedFacadeModule):
        module.__class__ = _CoreBackedFacadeModule
    ModuleType.__setattr__(module, "_facade_core", core)


__all__ = ["bind_core_facade"]
