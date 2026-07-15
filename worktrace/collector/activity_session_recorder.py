from __future__ import annotations

from dataclasses import dataclass, field

from ..constants import (
    SOURCE_AUTO,
    SOURCE_SYSTEM,
    STATUS_ERROR,
    STATUS_EXCLUDED,
    STATUS_IDLE,
    STATUS_NORMAL,
    STATUS_PAUSED,
)
from ..services import activity_service, project_service
from ..services.activity_lifecycle_service import (
    close_activity as lifecycle_close_activity,
    persist_midnight_anchor,
    persist_open_activity,
)
from ..services.project_ownership_service import (
    ProjectOwnershipState,
    advance_ownership,
    begin_ownership_for_new_resource,
    candidate_project_for_activity,
    clear_ownership_state,
)
from ..services.runtime_activity_state_service import clear_runtime_activity_state
from .decision_trace import (
    CollectorDecisionTrace,
    DecisionTraceRecorder,
    NULL_DECISION_TRACE_RECORDER,
    signature_hash,
)
from .resource_identity_resolver import (
    DEFAULT_RESOURCE_IDENTITY_RESOLVER,
    ResourceIdentityResolver,
)
from .snapshot_publisher import SnapshotPublisher
from .transition_types import ActivityEndReason, ActivitySignature, seconds_between

SYSTEM_STATUSES = {STATUS_IDLE, STATUS_PAUSED, STATUS_EXCLUDED, STATUS_ERROR}
OPEN_ACTIVITY_CHECKPOINT_SECONDS = 30


@dataclass
class ActivitySessionRecorder:
    current_payload: dict | None = None
    current_signature: ActivitySignature | None = None
    current_start_time: str | None = None
    current_last_seen_time: str | None = None
    persisted_activity_id: int | None = None
    persisted_checkpoint_seconds: int = 0
    project_ownership_state: ProjectOwnershipState | None = field(default=None)
    resolver: ResourceIdentityResolver = field(default=DEFAULT_RESOURCE_IDENTITY_RESOLVER)
    snapshot_publisher: SnapshotPublisher = field(default_factory=SnapshotPublisher)
    decision_trace_recorder: DecisionTraceRecorder = field(
        default=NULL_DECISION_TRACE_RECORDER
    )

    def observe(
        self,
        payload: dict,
        signature: ActivitySignature,
        at_time: str,
        end_reason: ActivityEndReason = ActivityEndReason.RESOURCE_SWITCH,
    ) -> None:
        persisted_before = self.persisted_activity_id
        previous_signature = self.current_signature
        same_signature = self.current_signature == signature
        if self.current_payload is None:
            self._start(payload, signature, at_time)
            self._record_observe_trace(
                payload,
                previous_signature,
                signature,
                same_signature=False,
                at_time=at_time,
                end_reason=end_reason,
                persisted_before=persisted_before,
            )
            return

        if same_signature:
            self.current_payload = {
                **self.current_payload,
                **{k: v for k, v in payload.items() if v is not None},
            }
            self.current_last_seen_time = at_time
            self.project_ownership_state = advance_ownership(
                self.project_ownership_state,
                at_time,
            )
            self._ensure_persisted(at_time)
            self._checkpoint_persisted_progress(at_time)
            self._publish_snapshot(at_time)
            self._record_observe_trace(
                payload,
                previous_signature,
                signature,
                same_signature=True,
                at_time=at_time,
                end_reason=end_reason,
                persisted_before=persisted_before,
            )
            return

        self.finish_current_activity(at_time, end_reason)
        self._start(payload, signature, at_time)
        self._record_observe_trace(
            payload,
            previous_signature,
            signature,
            same_signature=False,
            at_time=at_time,
            end_reason=end_reason,
            persisted_before=persisted_before,
        )

    def finish_current_activity(
        self,
        at_time: str,
        reason: ActivityEndReason,
    ) -> None:
        if self.current_payload is None or self.current_start_time is None:
            self.clear_snapshot()
            return

        # Never persist a reversed wall-clock interval. A backward system clock
        # jump closes at the last safe wall time while keeping the monotonic/max
        # duration already stored on the row.
        end_time = max(str(at_time), str(self.current_start_time))
        elapsed = seconds_between(self.current_start_time, end_time)
        status = str(self.current_payload.get("status") or "")
        self._ensure_persisted(end_time)
        self.decision_trace_recorder.record(
            CollectorDecisionTrace(
                observed_at=end_time,
                previous_signature_hash=signature_hash(self.current_signature),
                status=status,
                end_reason=str(reason.value),
                elapsed_seconds=elapsed,
                persisted_activity_id_before=self.persisted_activity_id,
                persisted_activity_id_after=self.persisted_activity_id,
                snapshot_action="close_persisted",
            )
        )
        if self.persisted_activity_id is not None:
            lifecycle_close_activity(
                self.persisted_activity_id,
                end_time,
                duration_seconds=elapsed,
            )

        self.current_payload = None
        self.current_signature = None
        self.current_start_time = None
        self.current_last_seen_time = None
        self.persisted_activity_id = None
        self.persisted_checkpoint_seconds = 0
        self.clear_snapshot()

    def stop(
        self,
        at_time: str,
        reason: ActivityEndReason = ActivityEndReason.STOP_BOUNDARY,
    ) -> None:
        self.finish_current_activity(at_time, reason)
        self.project_ownership_state = clear_ownership_state()

    def split_at_midnight(self, at_time: str) -> bool:
        if self.current_payload is None or self.current_start_time is None:
            self.clear_short_buffers()
            self.clear_snapshot()
            return False
        payload = dict(self.current_payload)
        signature = self.current_signature or self.resolver.signature_for_payload(payload)
        project_id = self._current_concrete_project_id()
        self.stop(at_time, reason=ActivityEndReason.MIDNIGHT_BOUNDARY)
        self.clear_short_buffers()
        self._start(
            payload,
            signature,
            at_time,
            midnight_project_id=project_id,
        )
        return True

    def clear_short_buffers(self) -> None:
        """Compatibility no-op; short-activity buffering no longer exists."""

    def clear_snapshot(self) -> None:
        self.snapshot_publisher.clear("recorder_snapshot_clear")

    def clear_runtime_state(self, reason: str) -> None:
        """Forget every process-local identity without writing to the database."""
        self.current_payload = None
        self.current_signature = None
        self.current_start_time = None
        self.current_last_seen_time = None
        self.persisted_activity_id = None
        self.persisted_checkpoint_seconds = 0
        self.project_ownership_state = clear_ownership_state()
        self.clear_snapshot()
        clear_runtime_activity_state(reason)

    def ensure_persisted_for_clipboard(self, at_time: str) -> int | None:
        self._ensure_persisted(at_time)
        self._checkpoint_persisted_progress(at_time)
        self._publish_snapshot(at_time)
        return self.persisted_activity_id

    def _start(
        self,
        payload: dict,
        signature: ActivitySignature,
        at_time: str,
        *,
        midnight_project_id: int | None = None,
    ) -> None:
        self.current_payload = dict(payload)
        self.current_signature = signature
        self.current_start_time = at_time
        self.current_last_seen_time = at_time
        self.persisted_activity_id = None
        self.persisted_checkpoint_seconds = 0
        self._begin_project_ownership(payload, at_time)
        if payload.get("status") == STATUS_NORMAL and midnight_project_id is not None:
            self._persist_midnight_anchor(midnight_project_id, at_time)
        else:
            self._ensure_persisted(at_time)
        # The open row is created immediately, but its duration is a low-frequency
        # crash-recovery checkpoint rather than the live clock's source of truth.
        self._publish_snapshot(at_time)

    def _begin_project_ownership(self, payload: dict, at_time: str) -> None:
        status = str(payload.get("status") or STATUS_NORMAL)
        if status in SYSTEM_STATUSES:
            self.project_ownership_state = clear_ownership_state()
            return
        resource = payload.get("resource")
        candidate = candidate_project_for_activity(payload, resource)
        self.project_ownership_state = begin_ownership_for_new_resource(
            self.project_ownership_state,
            candidate,
            at_time,
        )

    def _ensure_persisted(self, at_time: str) -> None:
        if (
            self.current_payload is None
            or self.current_start_time is None
            or self.persisted_activity_id is not None
        ):
            return
        status = self.current_payload.get("status") or STATUS_NORMAL
        allowed_statuses = {
            STATUS_NORMAL,
            STATUS_IDLE,
            STATUS_PAUSED,
            STATUS_EXCLUDED,
            STATUS_ERROR,
        }
        if status not in allowed_statuses:
            return
        elapsed = seconds_between(self.current_start_time, at_time)
        source = SOURCE_AUTO if status == STATUS_NORMAL else SOURCE_SYSTEM
        activity_id = persist_open_activity(
            start_time=self.current_start_time,
            source=source,
            payload=self.current_payload,
        )
        persisted_before = self.persisted_activity_id
        self.persisted_activity_id = activity_id
        self.persisted_checkpoint_seconds = 0
        self.decision_trace_recorder.record(
            CollectorDecisionTrace(
                observed_at=at_time,
                status=str(status or ""),
                elapsed_seconds=elapsed,
                persisted_activity_id_before=persisted_before,
                persisted_activity_id_after=activity_id,
                snapshot_action="persisted_open",
            )
        )

    def _persist_midnight_anchor(self, project_id: int, at_time: str) -> None:
        if (
            self.current_payload is None
            or self.current_start_time is None
            or self.persisted_activity_id is not None
        ):
            return
        activity_id = persist_midnight_anchor(
            start_time=self.current_start_time,
            source=SOURCE_AUTO,
            payload=self.current_payload,
            project_id=project_id,
        )
        self.persisted_activity_id = activity_id
        self.persisted_checkpoint_seconds = 0
        self._publish_snapshot(at_time)

    def _current_concrete_project_id(self) -> int | None:
        if self.persisted_activity_id is None:
            return None
        activity = activity_service.get_activity(self.persisted_activity_id)
        if not activity:
            return None
        project_id = activity.get("project_id")
        return (
            int(project_id)
            if project_service.is_concrete_project_id(project_id)
            else None
        )

    def _checkpoint_persisted_progress(
        self,
        at_time: str,
        *,
        force: bool = False,
    ) -> None:
        if self.persisted_activity_id is None or self.current_start_time is None:
            return
        elapsed = seconds_between(self.current_start_time, at_time)
        if not force and (
            elapsed - int(self.persisted_checkpoint_seconds)
            < OPEN_ACTIVITY_CHECKPOINT_SECONDS
        ):
            return
        activity_service.set_activity_duration(
            self.persisted_activity_id,
            elapsed,
        )
        self.persisted_checkpoint_seconds = max(
            int(self.persisted_checkpoint_seconds),
            int(elapsed),
        )

    # Compatibility alias for focused tests and older callers. Production
    # observations use the throttled checkpoint method above.
    def _update_persisted_progress(self, at_time: str) -> None:
        self._checkpoint_persisted_progress(at_time)

    def _publish_snapshot(self, at_time: str) -> None:
        self.snapshot_publisher.publish(
            payload=self.current_payload,
            start_time=self.current_start_time,
            at_time=at_time,
            project_ownership_state=self.project_ownership_state,
            persisted_activity_id=self.persisted_activity_id,
            checkpoint_seconds=self.persisted_checkpoint_seconds,
        )
        self.decision_trace_recorder.record(
            CollectorDecisionTrace(
                observed_at=at_time,
                persisted_activity_id_after=self.persisted_activity_id,
                snapshot_action="publish" if self.current_payload else "clear",
            )
        )

    def _record_observe_trace(
        self,
        payload: dict,
        previous_signature: ActivitySignature | None,
        incoming_signature: ActivitySignature,
        *,
        same_signature: bool,
        at_time: str,
        end_reason: ActivityEndReason,
        persisted_before: int | None,
        project_ownership_action: str = "",
    ) -> None:
        self.decision_trace_recorder.record(
            CollectorDecisionTrace(
                observed_at=at_time,
                previous_signature_hash=signature_hash(previous_signature),
                incoming_signature_hash=signature_hash(incoming_signature),
                same_signature=same_signature,
                status=str(payload.get("status") or ""),
                end_reason=str(end_reason.value),
                persisted_activity_id_before=persisted_before,
                persisted_activity_id_after=self.persisted_activity_id,
                project_ownership_action=project_ownership_action,
            )
        )
