from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterator, TypeAlias

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
    checkpoint_activity as lifecycle_checkpoint_activity,
    close_activity as lifecycle_close_activity,
    persist_midnight_anchor,
    persist_open_activity,
)
from ..services.project_ownership_service import (
    ProjectOwnershipState,
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


@dataclass(frozen=True)
class PreparedActivityClose:
    """Immutable durable close command prepared from one recorder session."""

    session_serial: int
    activity_id: int | None
    end_time: str
    duration_seconds: int
    reason: ActivityEndReason
    status: str
    previous_signature_hash: str

    def __iter__(self) -> Iterator[int | str | None]:
        """Preserve tuple unpacking while callers migrate to named fields."""

        yield self.activity_id
        yield self.end_time
        yield self.duration_seconds


BoundaryClose: TypeAlias = PreparedActivityClose
MidnightSplit: TypeAlias = tuple[
    dict,
    ActivitySignature,
    int | None,
    PreparedActivityClose | None,
]


@dataclass
class ActivitySessionRecorder:
    current_payload: dict | None = None
    current_signature: ActivitySignature | None = None
    current_start_time: str | None = None
    current_last_seen_time: str | None = None
    persisted_activity_id: int | None = None
    persisted_checkpoint_seconds: int = 0
    checkpoint_on_next_observation: bool = False
    project_ownership_state: ProjectOwnershipState | None = field(default=None)
    resolver: ResourceIdentityResolver = field(default=DEFAULT_RESOURCE_IDENTITY_RESOLVER)
    snapshot_publisher: SnapshotPublisher = field(default_factory=SnapshotPublisher)
    decision_trace_recorder: DecisionTraceRecorder = field(
        default=NULL_DECISION_TRACE_RECORDER
    )
    _session_serial: int = field(default=0, init=False, repr=False)

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
                **{key: value for key, value in payload.items() if value is not None},
            }
            self.current_last_seen_time = at_time
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

    def prepare_current_activity_close(
        self,
        at_time: str,
        reason: ActivityEndReason,
    ) -> PreparedActivityClose | None:
        """Prepare durable close inputs without changing process-local state."""

        if self.current_payload is None or self.current_start_time is None:
            self.clear_snapshot()
            return None
        end_time = max(str(at_time), str(self.current_start_time))
        elapsed = seconds_between(self.current_start_time, end_time)
        self._ensure_persisted(end_time)
        return PreparedActivityClose(
            session_serial=self._session_serial,
            activity_id=self.persisted_activity_id,
            end_time=end_time,
            duration_seconds=elapsed,
            reason=reason,
            status=str(self.current_payload.get("status") or ""),
            previous_signature_hash=signature_hash(self.current_signature),
        )

    def finalize_prepared_close(
        self,
        prepared: PreparedActivityClose | None,
    ) -> bool:
        """Clear runtime state only after the corresponding command committed."""

        if prepared is None:
            return False
        if prepared.session_serial != self._session_serial:
            return False
        self.decision_trace_recorder.record(
            CollectorDecisionTrace(
                observed_at=prepared.end_time,
                previous_signature_hash=prepared.previous_signature_hash,
                status=prepared.status,
                end_reason=str(prepared.reason.value),
                elapsed_seconds=prepared.duration_seconds,
                persisted_activity_id_before=prepared.activity_id,
                persisted_activity_id_after=prepared.activity_id,
                snapshot_action="close_persisted",
            )
        )
        self.current_payload = None
        self.current_signature = None
        self.current_start_time = None
        self.current_last_seen_time = None
        self.persisted_activity_id = None
        self.persisted_checkpoint_seconds = 0
        self.checkpoint_on_next_observation = False
        self.project_ownership_state = clear_ownership_state()
        self._session_serial += 1
        self.clear_snapshot()
        return True

    def finish_current_activity(
        self,
        at_time: str,
        reason: ActivityEndReason,
    ) -> None:
        prepared = self.prepare_current_activity_close(at_time, reason)
        if prepared is None:
            return
        if prepared.activity_id is not None:
            lifecycle_close_activity(
                prepared.activity_id,
                prepared.end_time,
                duration_seconds=prepared.duration_seconds,
            )
        self.finalize_prepared_close(prepared)

    def stop(
        self,
        at_time: str,
        reason: ActivityEndReason = ActivityEndReason.STOP_BOUNDARY,
    ) -> None:
        self.finish_current_activity(at_time, reason)

    def stop_for_boundary(
        self,
        at_time: str,
        reason: ActivityEndReason,
    ) -> PreparedActivityClose | None:
        """Prepare a close command for the atomic lifecycle boundary owner."""

        return self.prepare_current_activity_close(at_time, reason)

    def prepare_midnight_split(self, at_time: str) -> MidnightSplit | None:
        if self.current_payload is None or self.current_start_time is None:
            self.clear_snapshot()
            return None
        payload = dict(self.current_payload)
        signature = self.current_signature or self.resolver.signature_for_payload(payload)
        project_id = self._current_concrete_project_id()
        prepared = self.stop_for_boundary(at_time, ActivityEndReason.MIDNIGHT_BOUNDARY)
        return payload, signature, project_id, prepared

    def resume_midnight_split(
        self,
        payload: dict,
        signature: ActivitySignature,
        project_id: int | None,
        at_time: str,
    ) -> None:
        self._start(
            payload,
            signature,
            at_time,
            midnight_project_id=project_id,
        )

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
        self.checkpoint_on_next_observation = False
        self.project_ownership_state = clear_ownership_state()
        self._session_serial += 1
        self.clear_snapshot()
        clear_runtime_activity_state(reason)

    def ensure_persisted_for_clipboard(self, at_time: str) -> int | None:
        self._ensure_persisted(at_time)
        self._checkpoint_persisted_progress(at_time, force=True)
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
        self._session_serial += 1
        self.current_payload = dict(payload)
        self.current_signature = signature
        self.current_start_time = at_time
        self.current_last_seen_time = at_time
        self.persisted_activity_id = None
        self.persisted_checkpoint_seconds = 0
        self.checkpoint_on_next_observation = False
        self._begin_project_ownership(payload)
        if payload.get("status") == STATUS_NORMAL and midnight_project_id is not None:
            self._persist_midnight_anchor(midnight_project_id, at_time)
        else:
            self._ensure_persisted(at_time)
        self._publish_snapshot(at_time)

    def _begin_project_ownership(self, payload: dict) -> None:
        status = str(payload.get("status") or STATUS_NORMAL)
        if status in SYSTEM_STATUSES:
            self.project_ownership_state = clear_ownership_state()
            return
        resource = payload.get("resource")
        candidate = candidate_project_for_activity(payload, resource)
        self.project_ownership_state = begin_ownership_for_new_resource(candidate)

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
        self.checkpoint_on_next_observation = True
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
        effective_force = bool(force or self.checkpoint_on_next_observation)
        if not effective_force and (
            elapsed - int(self.persisted_checkpoint_seconds)
            < OPEN_ACTIVITY_CHECKPOINT_SECONDS
        ):
            return
        lifecycle_checkpoint_activity(self.persisted_activity_id, elapsed)
        self.persisted_checkpoint_seconds = max(
            int(self.persisted_checkpoint_seconds),
            int(elapsed),
        )
        self.checkpoint_on_next_observation = False

    def _publish_snapshot(self, at_time: str) -> None:
        self.snapshot_publisher.publish(
            payload=self.current_payload,
            start_time=self.current_start_time,
            at_time=at_time,
            project_ownership_state=self.project_ownership_state,
            persisted_activity_id=self.persisted_activity_id,
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
