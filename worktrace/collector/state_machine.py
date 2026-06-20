from __future__ import annotations

import logging
from dataclasses import dataclass, field

from ..constants import (
    STATUS_ERROR,
    STATUS_EXCLUDED,
    STATUS_IDLE,
    STATUS_NORMAL,
    STATUS_PAUSED,
)
from ..db import now_str
from ..path_utils import normalize_path_key
from ..platforms.base import ActiveWindow
from ..services import activity_service, privacy_service, session_boundary_service
from .auto_activity_recorder import AutoActivityRecorder

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
    active_signature: tuple[str, ...] | None = None
    recorder: AutoActivityRecorder = field(default_factory=AutoActivityRecorder)

    def transition_to(
        self,
        state: str,
        active_window: ActiveWindow | None = None,
        at_time: str | None = None,
    ) -> None:
        transition_time = at_time or now_str()
        if state == "stopped":
            self._stop_recording_at_boundary(transition_time, "stopped")
            activity_service.close_current_open_record(transition_time)
            self.state = "stopped"
            self.active_signature = None
            return
        if state == "paused":
            self.pause(transition_time)
            return

        status = STATE_TO_STATUS[state]
        payload = self._payload_for(status, active_window)
        signature = self._signature_for_payload(payload)
        if self._current_matches(payload, signature):
            self.recorder.observe(payload, self.recorder.current_signature or signature, transition_time)
            self.state = state
            self.active_signature = self.recorder.current_signature or signature
            return

        self.recorder.observe(payload, signature, transition_time)
        self.state = state
        self.active_signature = signature
        if status == STATUS_EXCLUDED:
            logging.info("collector state transition status=excluded")
        else:
            logging.info("collector state transition state=%s", state)

    def reset_for_time_jump(self, at_time: str | None = None) -> None:
        transition_time = at_time or now_str()
        self._stop_recording_at_boundary(transition_time, "time_jump")
        activity_service.close_current_open_record(transition_time)
        self.state = "stopped"
        self.active_signature = None

    def split_at_midnight(self, at_time: str) -> None:
        if self.recorder.split_at_midnight(at_time):
            session_boundary_service.record_boundary(at_time, "midnight")
            self.active_signature = self.recorder.current_signature
        else:
            self.recorder.clear_short_buffers()
            session_boundary_service.record_boundary(at_time, "midnight")

    def pause(self, at_time: str | None = None) -> None:
        transition_time = at_time or now_str()
        if self.state != "paused" or self.recorder.current_payload is not None:
            self._stop_recording_at_boundary(transition_time, "paused")
            activity_service.close_current_open_record(transition_time)
        self.state = "paused"
        self.active_signature = None

    def _stop_recording_at_boundary(self, at_time: str, reason: str) -> None:
        self.recorder.stop(at_time, merge_transient=False)
        self.recorder.clear_short_buffers()
        session_boundary_service.record_boundary(at_time, reason)

    def _signature_for_payload(self, payload: dict) -> tuple[str, ...]:
        return (
            str(payload.get("status") or ""),
            str(payload.get("app_name") or ""),
            str(payload.get("process_name") or ""),
            str(payload.get("window_title") or ""),
            normalize_path_key(str(payload.get("file_path_hint") or "")),
        )

    def _current_matches(
        self,
        payload: dict,
        signature: tuple[str, ...],
    ) -> bool:
        current = self.recorder.current_payload
        current_signature = self.recorder.current_signature
        if current is None or current_signature is None:
            return False
        base_matches = (
            current.get("status"),
            current.get("app_name"),
            current.get("process_name"),
            current.get("window_title"),
        ) == signature[:4]
        if not base_matches:
            return False

        old_path = (current.get("file_path_hint") or "").strip()
        new_path = (payload.get("file_path_hint") or "").strip()
        if not old_path and new_path:
            current["file_path_hint"] = new_path
            self.recorder.current_signature = signature
            if self.recorder.persisted_activity_id is not None:
                activity_service.update_activity_file_path_hint(self.recorder.persisted_activity_id, new_path)
            return True
        if old_path and new_path:
            return normalize_path_key(old_path) == normalize_path_key(new_path)
        return True

    def _payload_for(self, status: str, active_window: ActiveWindow | None) -> dict:
        if status == STATUS_EXCLUDED:
            return privacy_service.make_excluded_activity_payload()
        if status == STATUS_IDLE:
            return {
                "app_name": "空闲",
                "process_name": "idle",
                "window_title": "用户空闲",
                "status": STATUS_IDLE,
            }
        if status == STATUS_PAUSED:
            return {
                "app_name": "已暂停",
                "process_name": "paused",
                "window_title": "采集已暂停",
                "status": STATUS_PAUSED,
            }
        if status == STATUS_ERROR:
            return {
                "app_name": "异常",
                "process_name": "error",
                "window_title": "采集异常",
                "status": STATUS_ERROR,
            }
        if active_window is None:
            raise ValueError("active_window is required for recording state")
        return {
            "app_name": active_window.app_name or "unknown",
            "process_name": active_window.process_name or "unknown",
            "window_title": active_window.window_title or "",
            "file_path_hint": active_window.file_path_hint,
            "status": STATUS_NORMAL,
        }
