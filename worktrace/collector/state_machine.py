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
from ..platforms.base import ActiveWindow, ClipboardTextEvent
from ..services import activity_lifecycle_service, clipboard_service, privacy_service, session_boundary_service
from ..services.activity_status_policy import does_status_require_boundary
from .activity_session_recorder import ActivitySessionRecorder
from .resource_identity_resolver import (
    DEFAULT_RESOURCE_IDENTITY_RESOLVER,
    ResourceIdentityResolver,
)
from .transition_types import ActivityEndReason, ActivitySignature

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
    active_signature: ActivitySignature | None = None
    recorder: ActivitySessionRecorder = field(default_factory=ActivitySessionRecorder)
    resolver: ResourceIdentityResolver = field(default=DEFAULT_RESOURCE_IDENTITY_RESOLVER)

    def transition_to(
        self,
        state: str,
        active_window: ActiveWindow | None = None,
        at_time: str | None = None,
    ) -> None:
        transition_time = at_time or now_str()
        if state == "stopped":
            self.stop(transition_time)
            return
        if state == "paused":
            self.pause(transition_time)
            return

        status = STATE_TO_STATUS[state]
        payload = self.resolver.payload_for(status, active_window)
        status, payload = self.resolver.normalize_for_privacy(status, payload, active_window)
        if status == STATUS_EXCLUDED:
            state = "excluded"
        signature = self.resolver.signature_for_payload(payload)

        match = self.resolver.current_matches(
            current=self.recorder.current_payload,
            current_signature=self.recorder.current_signature,
            new_payload=payload,
            new_signature=signature,
            persisted_activity_id=self.recorder.persisted_activity_id,
        )
        if match.matched:
            effective_signature = match.signature or signature
            self.recorder.current_signature = effective_signature
            self.recorder.observe(payload, effective_signature, transition_time)
            self.state = state
            self.active_signature = self.recorder.current_signature or effective_signature
            return

        previous_status = ""
        if self.recorder.current_payload is not None:
            previous_status = str(self.recorder.current_payload.get("status") or "")
        boundary_required = does_status_require_boundary(status, 0)
        boundary_reason = _boundary_reason_for_status(status)
        end_reason = (
            _end_reason_for_boundary(boundary_reason)
            if boundary_required
            else ActivityEndReason.RESOURCE_SWITCH
        )
        self.recorder.observe(payload, signature, transition_time, end_reason=end_reason)
        if boundary_required:
            self.recorder.clear_short_buffers()
            if previous_status != status:
                session_boundary_service.record_hard_boundary(
                    transition_time,
                    boundary_reason,
                )
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
        self._stop_recording_at_boundary(transition_time, "sleep_resume")
        activity_lifecycle_service.close_all_open_activities(transition_time)
        self.state = "stopped"
        self.active_signature = None

    def split_at_midnight(self, at_time: str) -> None:
        if self.recorder.split_at_midnight(at_time):
            session_boundary_service.record_hard_boundary(at_time, "midnight")
            self.active_signature = self.recorder.current_signature
        else:
            self.recorder.clear_short_buffers()
            session_boundary_service.record_hard_boundary(at_time, "midnight")

    def pause(self, at_time: str | None = None) -> None:
        transition_time = at_time or now_str()
        if self.state != "paused" or self.recorder.current_payload is not None:
            self._stop_recording_at_boundary(transition_time, "paused")
            activity_lifecycle_service.close_all_open_activities(transition_time)
            payload = self.resolver.payload_for(STATUS_PAUSED, None)
            signature = self.resolver.signature_for_payload(payload)
            self.recorder.observe(
                payload,
                signature,
                transition_time,
                end_reason=ActivityEndReason.PAUSE_BOUNDARY,
            )
            self.active_signature = signature
        self.state = "paused"

    def stop(self, at_time: str | None = None, reason: str = "user_stop") -> None:
        transition_time = at_time or now_str()
        self._stop_recording_at_boundary(transition_time, reason)
        activity_lifecycle_service.close_all_open_activities(transition_time)
        self.state = "stopped"
        self.active_signature = None

    def _stop_recording_at_boundary(self, at_time: str, reason: str) -> None:
        self.recorder.stop(at_time, reason=_end_reason_for_boundary(reason))
        self.recorder.clear_short_buffers()
        session_boundary_service.record_hard_boundary(at_time, reason)

    def _current_activity_id_for_clipboard_event(self, event: ClipboardTextEvent, copied_at: str) -> int | None:
        current = self.recorder.current_payload
        if current is None or current.get("status") != STATUS_NORMAL:
            return None
        payload = self.resolver.payload_for(STATUS_NORMAL, event.source_window)
        signature = self.resolver.signature_for_payload(payload)
        match = self.resolver.current_matches(
            current=current,
            current_signature=self.recorder.current_signature,
            new_payload=payload,
            new_signature=signature,
            persisted_activity_id=self.recorder.persisted_activity_id,
        )
        if not match.matched:
            return None
        return self.recorder.ensure_persisted_for_clipboard(copied_at)


def _end_reason_for_boundary(reason: str) -> ActivityEndReason:
    if reason in {"paused", "user_pause"}:
        return ActivityEndReason.PAUSE_BOUNDARY
    if reason in {"stopped", "user_stop"}:
        return ActivityEndReason.STOP_BOUNDARY
    if reason == "fatal_collector_stop":
        return ActivityEndReason.STOP_BOUNDARY
    if reason == "shutdown":
        return ActivityEndReason.SHUTDOWN_BOUNDARY
    if reason in {"time_jump", "sleep_resume"}:
        return ActivityEndReason.TIME_JUMP_BOUNDARY
    if reason == "midnight":
        return ActivityEndReason.MIDNIGHT_BOUNDARY
    if reason == "idle":
        return ActivityEndReason.IDLE_BOUNDARY
    if reason == "excluded":
        return ActivityEndReason.EXCLUDED_BOUNDARY
    if reason == "error":
        return ActivityEndReason.ERROR_BOUNDARY
    if reason == "privacy":
        return ActivityEndReason.PRIVACY_BOUNDARY
    if reason == "secure_import":
        return ActivityEndReason.SECURE_IMPORT_BOUNDARY
    if reason == "first_run_gate":
        return ActivityEndReason.FIRST_RUN_GATE_BOUNDARY
    return ActivityEndReason.STOP_BOUNDARY


def _boundary_reason_for_status(status: str) -> str:
    if status == STATUS_IDLE:
        return "idle"
    if status == STATUS_EXCLUDED:
        return "excluded"
    if status == STATUS_ERROR:
        return "error"
    if status == STATUS_PAUSED:
        return "user_pause"
    return status or "unknown"
