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
from ..services import (
    activity_lifecycle_service,
    activity_maintenance_command_service,
    clipboard_fact_query_service,
    clipboard_service,
    privacy_service,
)
from ..services.activity_status_policy import does_status_require_boundary
from ..services.privacy_anonymization_service import anonymize_activity
from .activity_session_recorder import ActivitySessionRecorder, BoundaryClose
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

        requested_status = STATE_TO_STATUS[state]
        previous_status = ""
        if self.recorder.current_payload is not None:
            previous_status = str(
                self.recorder.current_payload.get("status") or ""
            )

        raw_payload = self.resolver.payload_for(requested_status, active_window)
        raw_signature = self.resolver.signature_for_payload(raw_payload)
        redact_current = self._should_redact_current_activity(
            requested_status,
            raw_payload,
            raw_signature,
        )
        status, payload = self.resolver.normalize_for_privacy(
            requested_status,
            raw_payload,
            active_window,
        )
        if redact_current and self.recorder.persisted_activity_id is not None:
            anonymize_activity(self.recorder.persisted_activity_id)
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
            self.active_signature = (
                self.recorder.current_signature or effective_signature
            )
            return

        boundary_required = does_status_require_boundary(status, 0)
        boundary_reason = _boundary_reason_for_status(status)
        end_reason = (
            _end_reason_for_boundary(boundary_reason)
            if boundary_required
            else ActivityEndReason.RESOURCE_SWITCH
        )
        if boundary_required and previous_status != status:
            prepared = self.recorder.stop_for_boundary(
                transition_time,
                end_reason,
            )
            self._commit_boundary(transition_time, boundary_reason, prepared)
        self.recorder.observe(
            payload,
            signature,
            transition_time,
            end_reason=end_reason,
        )
        self.state = state
        self.active_signature = signature
        if status == STATUS_EXCLUDED:
            logging.info("collector state transition status=excluded")
        else:
            logging.info("collector state transition state=%s", state)

    def _should_redact_current_activity(
        self,
        requested_status: str,
        raw_payload: dict,
        raw_signature: ActivitySignature,
    ) -> bool:
        current = self.recorder.current_payload
        current_signature = self.recorder.current_signature
        if (
            requested_status != STATUS_NORMAL
            or current is None
            or str(current.get("status") or "") != STATUS_NORMAL
            or current_signature is None
            or self.recorder.persisted_activity_id is None
        ):
            return False
        if not self.resolver.payload_resource_is_excluded(raw_payload):
            return False
        return self.resolver.signatures_represent_same_resource(
            current_signature,
            raw_signature,
            current,
            raw_payload,
        )

    def record_clipboard_event(
        self,
        event: ClipboardTextEvent,
        at_time: str | None = None,
    ) -> int | None:
        if not event.text:
            return None
        decision = privacy_service.evaluate_exclusion(event.source_window)
        if decision.excluded or decision.resolution_pending:
            return None
        copied_at = event.copied_at or at_time or now_str()
        activity_id = self._current_activity_id_for_clipboard_event(
            event,
            copied_at,
        )
        if activity_id is None:
            activity_id = clipboard_fact_query_service.find_activity_for_clipboard_event(
                event.source_window,
                copied_at,
            )
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
        self.state = "stopped"
        self.active_signature = None

    def reset_runtime_state(self, reason: str = "runtime_reset") -> None:
        """Forget process-local identity after the durable generation changed."""

        self.recorder.clear_runtime_state(reason)
        self.state = "stopped"
        self.active_signature = None

    def split_at_midnight(self, at_time: str) -> None:
        split = self.recorder.prepare_midnight_split(at_time)
        if split is None:
            self._commit_boundary(at_time, "midnight", None)
            return
        payload, signature, project_id, prepared = split
        self._commit_boundary(at_time, "midnight", prepared)
        self.recorder.resume_midnight_split(
            payload,
            signature,
            project_id,
            at_time,
        )
        self.active_signature = self.recorder.current_signature

    def pause(self, at_time: str | None = None) -> None:
        """Apply the durable user-pause boundary and user intent."""

        transition_time = at_time or now_str()
        if self.state != "paused" or self.recorder.current_payload is not None:
            prepared = self.recorder.stop_for_boundary(
                transition_time,
                ActivityEndReason.PAUSE_BOUNDARY,
            )
            activity_lifecycle_service.pause_collection(
                transition_time,
                reason="user_pause",
                current_activity_id=(
                    prepared.activity_id if prepared is not None else None
                ),
                current_duration_seconds=(
                    prepared.duration_seconds if prepared is not None else None
                ),
            )
            self.recorder.finalize_prepared_close(prepared)
            self.active_signature = None
        self.state = "paused"

    def quiesce_for_maintenance(self, at_time: str | None = None) -> None:
        """Seal active facts without a session boundary or durable pause mutation."""

        transition_time = at_time or now_str()
        prepared = self.recorder.stop_for_boundary(
            transition_time,
            ActivityEndReason.MAINTENANCE_SEGMENT,
        )
        activity_maintenance_command_service.seal_open_activity_for_maintenance(
            transition_time,
            current_activity_id=(
                prepared.activity_id if prepared is not None else None
            ),
            current_duration_seconds=(
                prepared.duration_seconds if prepared is not None else None
            ),
        )
        self.recorder.finalize_prepared_close(prepared)
        self.active_signature = None
        self.state = "maintenance"

    def stop(self, at_time: str | None = None, reason: str = "user_stop") -> None:
        transition_time = at_time or now_str()
        self._stop_recording_at_boundary(transition_time, reason)
        self.state = "stopped"
        self.active_signature = None

    def _stop_recording_at_boundary(self, at_time: str, reason: str) -> None:
        prepared = self.recorder.stop_for_boundary(
            at_time,
            _end_reason_for_boundary(reason),
        )
        self._commit_boundary(at_time, reason, prepared)

    def _commit_boundary(
        self,
        at_time: str,
        reason: str,
        prepared: BoundaryClose | None,
    ) -> None:
        activity_id: int | None = None
        duration_seconds: int | None = None
        if prepared is not None:
            activity_id = prepared.activity_id
            duration_seconds = prepared.duration_seconds
        activity_lifecycle_service.close_at_boundary(
            at_time,
            reason,
            current_activity_id=activity_id,
            current_duration_seconds=duration_seconds,
        )
        self.recorder.finalize_prepared_close(prepared)

    def _current_activity_id_for_clipboard_event(
        self,
        event: ClipboardTextEvent,
        copied_at: str,
    ) -> int | None:
        current = self.recorder.current_payload
        if current is None or current.get("status") != STATUS_NORMAL:
            return None
        payload = self.resolver.payload_for(STATUS_NORMAL, event.source_window)
        status, payload = self.resolver.normalize_for_privacy(
            STATUS_NORMAL,
            payload,
            event.source_window,
        )
        if status != STATUS_NORMAL:
            return None
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
    if reason == "user_pause":
        return ActivityEndReason.PAUSE_BOUNDARY
    if reason in {"user_stop", "fatal_collector_stop"}:
        return ActivityEndReason.STOP_BOUNDARY
    if reason == "shutdown":
        return ActivityEndReason.SHUTDOWN_BOUNDARY
    if reason == "sleep_resume":
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
