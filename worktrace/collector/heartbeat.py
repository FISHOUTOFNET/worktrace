from __future__ import annotations

import time

from ..db import active_database_epoch_key, now_str
from ..services import database_maintenance_service
from ..services.settings_service import set_settings

_HEARTBEAT_PERSIST_INTERVAL_SECONDS = 30.0
_LAST_PERSISTED_BY_DATABASE: dict[tuple[str, int], tuple[str, float]] = {}


def update_heartbeat(status: str = "running") -> None:
    """Persist runtime liveness only outside a maintenance lifecycle."""

    if database_maintenance_service.is_maintenance_in_progress():
        return
    database_epoch = active_database_epoch_key()
    now_monotonic = time.monotonic()
    previous = _LAST_PERSISTED_BY_DATABASE.get(database_epoch)
    if (
        previous is not None
        and previous[0] == status
        and now_monotonic - previous[1] < _HEARTBEAT_PERSIST_INTERVAL_SECONDS
    ):
        return
    set_settings(
        {
            "collector_status": status,
            "last_collector_heartbeat": now_str(),
        }
    )
    _LAST_PERSISTED_BY_DATABASE[database_epoch] = (status, now_monotonic)


__all__ = ["update_heartbeat"]
