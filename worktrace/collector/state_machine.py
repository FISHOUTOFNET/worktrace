from __future__ import annotations

import logging
from dataclasses import dataclass

from ..constants import (
    SOURCE_AUTO,
    SOURCE_SYSTEM,
    STATUS_ERROR,
    STATUS_EXCLUDED,
    STATUS_IDLE,
    STATUS_NORMAL,
    STATUS_PAUSED,
)
from ..db import now_str
from ..platforms.base import ActiveWindow
from ..services import activity_service, privacy_service

STATE_TO_STATUS = {
    "recording": STATUS_NORMAL,
    "idle": STATUS_IDLE,
    "paused": STATUS_PAUSED,
    "excluded": STATUS_EXCLUDED,
    "error": STATUS_ERROR,
}


@dataclass
class CollectorStateMachine:
    state: str = "stopped"
    active_signature: tuple[str, str, str, str] | None = None

    def transition_to(
        self,
        state: str,
        active_window: ActiveWindow | None = None,
        at_time: str | None = None,
    ) -> None:
        if state == "stopped":
            activity_service.close_current_open_record(at_time)
            self.state = "stopped"
            self.active_signature = None
            return

        status = STATE_TO_STATUS[state]
        signature = self._signature(status, active_window)
        open_activity = activity_service.get_open_activity()
        if open_activity and self._open_matches(open_activity, signature):
            self.state = state
            self.active_signature = signature
            return

        transition_time = at_time or now_str()
        if open_activity:
            activity_service.close_activity(int(open_activity["id"]), transition_time)

        payload = self._payload_for(status, active_window)
        activity_id = activity_service.create_activity(
            start_time=transition_time,
            source=SOURCE_AUTO if status == STATUS_NORMAL else SOURCE_SYSTEM,
            **payload,
        )
        activity_service.finalize_created_activity(activity_id)
        self.state = state
        self.active_signature = signature
        if status == STATUS_EXCLUDED:
            logging.info("collector state transition status=excluded")
        else:
            logging.info("collector state transition state=%s", state)

    def _signature(
        self, status: str, active_window: ActiveWindow | None
    ) -> tuple[str, str, str, str]:
        if status == STATUS_EXCLUDED:
            payload = privacy_service.make_excluded_activity_payload()
            return (status, payload["app_name"], payload["process_name"], payload["window_title"])
        if status in {STATUS_IDLE, STATUS_PAUSED, STATUS_ERROR}:
            return (status, status, status, status)
        if active_window is None:
            return (status, "", "", "")
        return (status, active_window.app_name, active_window.process_name, active_window.window_title)

    def _open_matches(self, open_activity: dict, signature: tuple[str, str, str, str]) -> bool:
        return (
            open_activity["status"],
            open_activity["app_name"],
            open_activity["process_name"],
            open_activity["window_title"],
        ) == signature

    def _payload_for(self, status: str, active_window: ActiveWindow | None) -> dict:
        if status == STATUS_EXCLUDED:
            return privacy_service.make_excluded_activity_payload()
        if status == STATUS_IDLE:
            return {
                "app_name": "空闲",
                "process_name": "idle",
                "window_title": "用户空闲",
                "status": STATUS_IDLE,
                "is_billable": False,
            }
        if status == STATUS_PAUSED:
            return {
                "app_name": "已暂停",
                "process_name": "paused",
                "window_title": "采集已暂停",
                "status": STATUS_PAUSED,
                "is_billable": False,
            }
        if status == STATUS_ERROR:
            return {
                "app_name": "异常",
                "process_name": "error",
                "window_title": "采集异常",
                "status": STATUS_ERROR,
                "is_billable": False,
            }
        if active_window is None:
            raise ValueError("active_window is required for recording state")
        return {
            "app_name": active_window.app_name or "unknown",
            "process_name": active_window.process_name or "unknown",
            "window_title": active_window.window_title or "",
            "status": STATUS_NORMAL,
        }
