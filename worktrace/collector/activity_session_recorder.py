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
    force_persist_open_activity_for_clipboard,
    persist_midnight_anchor,
    persist_open_activity_if_ready,
)
from ..services.project_ownership_service import (
    ProjectOwnershipState,
    advance_ownership,
    begin_ownership_for_new_resource,
    candidate_project_for_activity,
    clear_ownership_state,
)
from ..services.runtime_activity_state_service import clear_runtime_activity_state
from .resource_identity_resolver import (
    DEFAULT_RESOURCE_IDENTITY_RESOLVER,
    ResourceIdentityResolver,
)
from .short_activity_finalizer import (
    FinishedActivityCandidate,
    ShortActivityFinalizer,
)
from .snapshot_publisher import SnapshotPublisher
from .transition_types import ActivityEndReason, ActivitySignature, seconds_between

SYSTEM_STATUSES = {STATUS_IDLE, STATUS_PAUSED, STATUS_EXCLUDED, STATUS_ERROR}


@dataclass
class ActivitySessionRecorder:
    current_payload: dict | None = None
    current_signature: ActivitySignature | None = None
    current_start_time: str | None = None
    current_last_seen_time: str | None = None
    persisted_activity_id: int | None = None
    current_extra_seconds: int = 0
    project_ownership_state: ProjectOwnershipState | None = field(default=None)
    resolver: ResourceIdentityResolver = field(default=DEFAULT_RESOURCE_IDENTITY_RESOLVER)
    short_finalizer: ShortActivityFinalizer = field(default_factory=ShortActivityFinalizer)
    snapshot_publisher: SnapshotPublisher = field(default_factory=SnapshotPublisher)

    def observe(
        self,
        payload: dict,
        signature: ActivitySignature,
        at_time: str,
        end_reason: ActivityEndReason = ActivityEndReason.RESOURCE_SWITCH,
    ) -> None:
        if self.current_payload is None:
            self._start(payload, signature, at_time)
            return

        if self.current_signature == signature:
            self.current_payload = {
                **self.current_payload,
                **{k: v for k, v in payload.items() if v is not None},
            }
            self.current_last_seen_time = at_time
            self.project_ownership_state = advance_ownership(
                self.project_ownership_state,
                at_time,
            )
            self._ensure_persisted_if_ready(at_time)
            self._update_persisted_progress(at_time)
            self._publish_snapshot(at_time)
            return

        self.finish_current_activity(at_time, end_reason)
        if self._resume_if_absorbed_activity_matches(payload, signature, at_time):
            return
        self._start(payload, signature, at_time)

    def finish_current_activity(
        self,
        at_time: str,
        reason: ActivityEndReason,
    ) -> None:
        if self.current_payload is None or self.current_start_time is None:
            self.clear_snapshot()
            return

        end_time = at_time
        elapsed = seconds_between(self.current_start_time, end_time)
        status = str(self.current_payload.get("status") or "")
        self._ensure_persisted_if_ready(end_time)
        candidate = FinishedActivityCandidate(
            status=status,
            signature=self.current_signature,
            start_time=self.current_start_time,
            end_time=end_time,
            seconds=elapsed,
            persisted_activity_id=self.persisted_activity_id,
            end_reason=reason,
            payload=dict(self.current_payload),
        )
        decision = self.short_finalizer.finalize(candidate)
        if decision.action == "close_persisted" and self.persisted_activity_id is not None:
            lifecycle_close_activity(
                self.persisted_activity_id,
                end_time,
                duration_seconds=elapsed + self.current_extra_seconds,
            )

        self.current_payload = None
        self.current_signature = None
        self.current_start_time = None
        self.current_last_seen_time = None
        self.persisted_activity_id = None
        self.current_extra_seconds = 0
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
        self._start(payload, signature, at_time)
        if payload.get("status") == STATUS_NORMAL and project_id is not None:
            self._persist_midnight_anchor(project_id, at_time)
        return True

    def clear_short_buffers(self) -> None:
        self.short_finalizer.clear()

    def clear_snapshot(self) -> None:
        self.snapshot_publisher.clear("recorder_snapshot_clear")

    def clear_runtime_state(self, reason: str) -> None:
        self.short_finalizer.clear()
        self.project_ownership_state = clear_ownership_state()
        clear_runtime_activity_state(reason)

    def ensure_persisted_for_clipboard(self, at_time: str) -> int | None:
        self._ensure_persisted_if_ready(at_time, force=True)
        self._update_persisted_progress(at_time)
        self._publish_snapshot(at_time)
        return self.persisted_activity_id

    def _start(self, payload: dict, signature: ActivitySignature, at_time: str) -> None:
        self.current_payload = dict(payload)
        self.current_signature = signature
        self.current_start_time = at_time
        self.current_last_seen_time = at_time
        self.persisted_activity_id = None
        self.current_extra_seconds = 0
        self.short_finalizer.clear()
        self._begin_project_ownership(payload, at_time)
        self._ensure_persisted_if_ready(at_time)
        self._update_persisted_progress(at_time)
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

    def _ensure_persisted_if_ready(self, at_time: str, force: bool = False) -> None:
        if (
            self.current_payload is None
            or self.current_start_time is None
            or self.persisted_activity_id is not None
        ):
            return
        status = self.current_payload.get("status")
        allowed_statuses = (
            {STATUS_NORMAL}
            if force
            else {STATUS_NORMAL, STATUS_IDLE, STATUS_PAUSED, STATUS_EXCLUDED, STATUS_ERROR}
        )
        if status not in allowed_statuses:
            return
        elapsed = seconds_between(self.current_start_time, at_time)
        source = SOURCE_AUTO if status == STATUS_NORMAL else SOURCE_SYSTEM
        if force:
            activity_id = force_persist_open_activity_for_clipboard(
                start_time=self.current_start_time,
                source=source,
                payload=self.current_payload,
            )
        else:
            activity_id = persist_open_activity_if_ready(
                start_time=self.current_start_time,
                source=source,
                payload=self.current_payload,
                elapsed_seconds=elapsed,
            )
        if activity_id is None:
            return
        self.persisted_activity_id = activity_id
        if status == STATUS_NORMAL:
            self.short_finalizer.clear_pending_runtime_state()

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
        self.current_extra_seconds = 0
        self._update_persisted_progress(at_time)
        self._publish_snapshot(at_time)

    def _current_concrete_project_id(self) -> int | None:
        if self.persisted_activity_id is None:
            return None
        activity = activity_service.get_activity(self.persisted_activity_id)
        if not activity:
            return None
        project_id = activity.get("project_id")
        return int(project_id) if project_service.is_concrete_project_id(project_id) else None

    def _update_persisted_progress(self, at_time: str) -> None:
        if self.persisted_activity_id is None or self.current_start_time is None:
            return
        elapsed = seconds_between(self.current_start_time, at_time)
        activity_service.set_activity_duration(
            self.persisted_activity_id,
            elapsed + self.current_extra_seconds,
        )

    def _resume_if_absorbed_activity_matches(
        self,
        payload: dict,
        signature: ActivitySignature,
        at_time: str,
    ) -> bool:
        result = self.short_finalizer.resume_if_absorbed_activity_matches(
            payload=payload,
            signature=signature,
        )
        target = result.target
        if result.decision.action != "resume_anchor" or not target:
            return False
        start_time = str(target.get("start_time") or "")
        if not start_time:
            return False
        self.current_payload = dict(payload)
        self.current_signature = signature
        self.current_start_time = start_time
        self.current_last_seen_time = at_time
        self.persisted_activity_id = int(target["id"])
        stored_duration = int(target.get("duration_seconds") or 0)
        self.current_extra_seconds = max(
            0,
            stored_duration - seconds_between(start_time, at_time),
        )
        self._begin_project_ownership(payload, at_time)
        self._update_persisted_progress(at_time)
        self._publish_snapshot(at_time)
        return True

    def _publish_snapshot(self, at_time: str) -> None:
        self.snapshot_publisher.publish(
            payload=self.current_payload,
            start_time=self.current_start_time,
            at_time=at_time,
            project_ownership_state=self.project_ownership_state,
            persisted_activity_id=self.persisted_activity_id,
            current_extra_seconds=self.current_extra_seconds,
        )
