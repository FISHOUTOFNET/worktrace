from __future__ import annotations

from ..db import now_str
from ..services.settings_service import set_setting


def update_heartbeat(status: str = "running") -> None:
    set_setting("collector_status", status)
    set_setting("last_collector_heartbeat", now_str())
