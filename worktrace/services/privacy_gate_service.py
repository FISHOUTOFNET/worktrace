"""Installation privacy-consent command facade."""

from __future__ import annotations

from ..mutation_effects import privacy_settings_mutation
from ..service_facade import bind_core_facade
from . import privacy_gate_service_core as _core

for _name in dir(_core):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_core, _name)

accept_privacy_notice = privacy_settings_mutation(_core.accept_privacy_notice)
_restore_impl = _core.restore_installation_privacy_state


@privacy_settings_mutation
def _restore_owned(state) -> None:
    _restore_impl(state, conn=None)


def restore_installation_privacy_state(state, *, conn=None) -> None:
    if conn is not None:
        _restore_impl(state, conn=conn)
        return
    _restore_owned(state)


_core.accept_privacy_notice = accept_privacy_notice
_core.restore_installation_privacy_state = restore_installation_privacy_state
bind_core_facade(__name__, _core)
