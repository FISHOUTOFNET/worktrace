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
from ..platforms.base import ActiveWindow, ClipboardTextEvent
from ..resources.resource_builders import make_system_resource, resource_signature
from ..resources.resource_identity import infer_resource_from_active_window
from ..resources.types import DetectedResource
from ..services import activity_service, activity_lifecycle_service, clipboard_service, privacy_service, session_boundary_service
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
            activity_lifecycle_service.close_all_open_activities(transition_time)
            self.state = "stopped"
            self.active_signature = None
            return
        if state == "paused":
            self.pause(transition_time)
            return

        status = STATE_TO_STATUS[state]
        payload = self._payload_for(status, active_window)
        # Resource-aware exclusion: if a normal recording surfaces a resource
        # that should be excluded (e.g. browser uri_host or email subject hits
        # a 排除规则 rule), force the payload into the excluded state so
        # that no real resource metadata is persisted.
        if status == STATUS_NORMAL and self._payload_resource_is_excluded(payload):
            payload = self._payload_for(STATUS_EXCLUDED, active_window)
            status = STATUS_EXCLUDED
            state = "excluded"
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

    def record_clipboard_event(self, event: ClipboardTextEvent, at_time: str | None = None) -> int | None:
        if not event.text:
            return None
        if privacy_service.is_excluded(event.source_window):
            return None
        copied_at = event.copied_at or at_time or now_str()
        activity_id = self._current_activity_id_for_clipboard_event(event, copied_at)
        if activity_id is None:
            activity_id = clipboard_service.find_activity_for_clipboard_event(event.source_window, copied_at)
        if activity_id is None:
            return None
        return clipboard_service.record_clipboard_event(
            activity_id,
            event.text,
            event.source_window,
            copied_at=copied_at,
            sequence_number=event.sequence_number,
        )

    def reset_for_time_jump(self, at_time: str | None = None) -> None:
        transition_time = at_time or now_str()
        self._stop_recording_at_boundary(transition_time, "time_jump")
        activity_lifecycle_service.close_all_open_activities(transition_time)
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
            activity_lifecycle_service.close_all_open_activities(transition_time)
        self.state = "paused"
        self.active_signature = None

    def _stop_recording_at_boundary(self, at_time: str, reason: str) -> None:
        self.recorder.stop(at_time, merge_transient=False)
        self.recorder.clear_short_buffers()
        session_boundary_service.record_boundary(at_time, reason)

    def _current_activity_id_for_clipboard_event(self, event: ClipboardTextEvent, copied_at: str) -> int | None:
        current = self.recorder.current_payload
        if current is None or current.get("status") != STATUS_NORMAL:
            return None
        payload = self._payload_for(STATUS_NORMAL, event.source_window)
        signature = self._signature_for_payload(payload)
        if not self._current_matches(payload, signature):
            return None
        return self.recorder.ensure_persisted_for_clipboard(copied_at)

    def _signature_for_payload(self, payload: dict) -> tuple[str, ...]:
        resource = payload.get("resource")
        return resource_signature(
            str(payload.get("status") or ""),
            resource if isinstance(resource, DetectedResource) else None,
            str(payload.get("app_name") or ""),
            str(payload.get("process_name") or ""),
            str(payload.get("window_title") or ""),
            payload.get("file_path_hint"),
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

        if current_signature == signature:
            self._supplement_path_if_needed(current, payload)
            return True

        # Check if signatures differ only because path became available
        if self._signatures_represent_same_resource(current_signature, signature, current, payload):
            self._supplement_path_if_needed(current, payload)
            self.recorder.current_signature = signature
            return True

        return False

    def _supplement_path_if_needed(self, current: dict, payload: dict) -> None:
        old_path = (current.get("file_path_hint") or "").strip()
        new_path = (payload.get("file_path_hint") or "").strip()
        new_resource = payload.get("resource")

        if not old_path and new_path:
            current["file_path_hint"] = new_path
            if self.recorder.persisted_activity_id is not None:
                activity_service.update_activity_file_path_hint(self.recorder.persisted_activity_id, new_path)
        elif not old_path and new_resource and isinstance(new_resource, DetectedResource) and new_resource.path_hint:
            current["file_path_hint"] = new_resource.path_hint
            if self.recorder.persisted_activity_id is not None:
                activity_service.update_activity_file_path_hint(self.recorder.persisted_activity_id, new_resource.path_hint)

    def _signatures_represent_same_resource(
        self,
        old_sig: tuple[str, ...],
        new_sig: tuple[str, ...],
        current: dict,
        payload: dict,
    ) -> bool:
        # Must be same status
        if old_sig[0] != new_sig[0]:
            return False

        old_resource = current.get("resource")
        new_resource = payload.get("resource")

        # Both have DetectedResource
        if isinstance(old_resource, DetectedResource) and isinstance(new_resource, DetectedResource):
            # Same kind and subtype
            if old_resource.resource_kind != new_resource.resource_kind:
                return False
            if old_resource.resource_subtype != new_resource.resource_subtype:
                return False
            # Check if identity_keys refer to the same file
            # e.g., office_file_name:spec.docx vs office_file:d:\casea\spec.docx
            old_key = old_resource.identity_key
            new_key = new_resource.identity_key
            if old_key == new_key:
                return True
            # Check if one is a _name variant and the other is a _path variant of the same file
            if self._file_name_and_path_keys_match(old_key, new_key, old_resource, new_resource):
                return True
            # For generic apps, identity_key should be stable
            return False

        # One has resource, one doesn't - compare old-style fields
        if isinstance(old_resource, DetectedResource) and new_resource is None:
            return (
                current.get("status") == payload.get("status")
                and current.get("app_name") == payload.get("app_name")
                and current.get("process_name") == payload.get("process_name")
            )

        if old_resource is None and isinstance(new_resource, DetectedResource):
            return (
                current.get("status") == payload.get("status")
                and current.get("app_name") == payload.get("app_name")
                and current.get("process_name") == payload.get("process_name")
            )

        # Both without resource - old-style comparison
        base_matches = (
            current.get("status"),
            current.get("app_name"),
            current.get("process_name"),
            current.get("window_title"),
        ) == (
            payload.get("status"),
            payload.get("app_name"),
            payload.get("process_name"),
            payload.get("window_title"),
        )
        if not base_matches:
            return False

        old_path = (current.get("file_path_hint") or "").strip()
        new_path = (payload.get("file_path_hint") or "").strip()
        if not old_path and new_path:
            return True
        if old_path and new_path:
            return normalize_path_key(old_path) == normalize_path_key(new_path)
        return True

    def _file_name_and_path_keys_match(
        self,
        old_key: str,
        new_key: str,
        old_resource: DetectedResource,
        new_resource: DetectedResource,
    ) -> bool:
        # Check if old_key is a _name variant and new_key is a _path variant (or vice versa)
        # of the same underlying file
        import ntpath as _ntpath

        for prefix_a, prefix_b in [
            ("office_file_name:", "office_file:"),
            ("file_name:", "file_path:"),
        ]:
            if old_key.startswith(prefix_a) and new_key.startswith(prefix_b):
                name_part = old_key[len(prefix_a):]
                path_part = new_key[len(prefix_b):]
                # Check if the path ends with the name
                basename = _ntpath.basename(path_part).lower().replace(" ", "-")
                if basename == name_part:
                    return True
            if old_key.startswith(prefix_b) and new_key.startswith(prefix_a):
                path_part = old_key[len(prefix_b):]
                name_part = new_key[len(prefix_a):]
                basename = _ntpath.basename(path_part).lower().replace(" ", "-")
                if basename == name_part:
                    return True
        return False

    def _payload_resource_is_excluded(self, payload: dict) -> bool:
        resource = payload.get("resource")
        if resource is None:
            return False
        try:
            return privacy_service.is_resource_excluded(resource)
        except Exception:
            return False

    def _payload_for(self, status: str, active_window: ActiveWindow | None) -> dict:
        if status == STATUS_EXCLUDED:
            payload = privacy_service.make_excluded_activity_payload()
            payload["resource"] = make_system_resource(STATUS_EXCLUDED)
            return payload
        if status == STATUS_IDLE:
            return {
                "app_name": "空闲",
                "process_name": "idle",
                "window_title": "用户空闲",
                "status": STATUS_IDLE,
                "resource": make_system_resource(STATUS_IDLE),
            }
        if status == STATUS_PAUSED:
            return {
                "app_name": "已暂停",
                "process_name": "paused",
                "window_title": "采集已暂停",
                "status": STATUS_PAUSED,
                "resource": make_system_resource(STATUS_PAUSED),
            }
        if status == STATUS_ERROR:
            return {
                "app_name": "异常",
                "process_name": "error",
                "window_title": "采集异常",
                "status": STATUS_ERROR,
                "resource": make_system_resource(STATUS_ERROR),
            }
        if active_window is None:
            raise ValueError("active_window is required for recording state")
        resource = infer_resource_from_active_window(active_window)
        return {
            "app_name": active_window.app_name or "unknown",
            "process_name": active_window.process_name or "unknown",
            "window_title": active_window.window_title or "",
            "file_path_hint": active_window.file_path_hint,
            "status": STATUS_NORMAL,
            "resource": resource,
        }
