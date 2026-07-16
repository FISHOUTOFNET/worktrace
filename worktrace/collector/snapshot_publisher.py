from __future__ import annotations

from ..constants import (
    STATUS_ERROR,
    STATUS_EXCLUDED,
    STATUS_IDLE,
    STATUS_NORMAL,
    STATUS_PAUSED,
)
from ..contracts.live_display_contracts import ActivitySnapshotContract
from ..resources.types import DetectedResource
from ..services.project_ownership_service import (
    ProjectOwnershipState,
    serialize_project_ownership,
    uncategorized_label,
)
from ..services.runtime_activity_state_service import (
    clear_runtime_activity_state,
    get_runtime_activity_snapshot,
    publish_runtime_activity_snapshot,
)
from .transition_types import seconds_between

SYSTEM_STATUSES = {STATUS_IDLE, STATUS_PAUSED, STATUS_EXCLUDED, STATUS_ERROR}


class SnapshotPublisher:
    """Sole publisher of the process-local, display-safe activity sample."""

    def publish(
        self,
        *,
        payload: dict | None,
        start_time: str | None,
        at_time: str,
        project_ownership_state: ProjectOwnershipState | None,
        persisted_activity_id: int | None,
        checkpoint_seconds: int = 0,
    ) -> None:
        if payload is None or start_time is None:
            self.clear()
            return

        elapsed = seconds_between(start_time, at_time)
        resource = payload.get("resource")
        resource_display_name = ""
        resource_kind = ""
        resource_subtype = ""
        resource_identity_key = ""
        if isinstance(resource, DetectedResource):
            resource_display_name = resource.display_name
            resource_kind = resource.resource_kind
            resource_subtype = resource.resource_subtype
            resource_identity_key = resource.identity_key

        activity_display_name = resource_display_name
        if not activity_display_name:
            activity_display_name = (
                payload.get("app_name")
                or payload.get("process_name")
                or ""
            )
        status = payload.get("status") or STATUS_NORMAL

        ownership = project_ownership_state
        if (
            status in SYSTEM_STATUSES
            or ownership is None
            or ownership.display_project is None
        ):
            display_label = uncategorized_label()
            candidate_label = uncategorized_label()
            transition_dict = serialize_project_ownership(None)["project_transition"]
        else:
            display_label = ownership.display_project
            candidate_label = ownership.candidate_project or uncategorized_label()
            # Compatibility shape only. There is no pending confirmation window.
            transition_dict = {
                **ownership.project_transition.to_dict(),
                "pending": False,
                "started_at": "",
                "elapsed_seconds": 0,
                "threshold_seconds": 0,
                "from_project_id": None,
                "to_project_id": None,
            }

        snapshot: ActivitySnapshotContract = {
            "app_name": payload.get("app_name") or "",
            "process_name": payload.get("process_name") or "",
            "activity_display_name": activity_display_name,
            "resource_kind": resource_kind,
            "resource_subtype": resource_subtype,
            "resource_display_name": resource_display_name,
            "resource_identity_key": resource_identity_key,
            # Temporary display-safe compatibility mirror. It contains only the
            # formal project label and is removed with the transition model.
            "inferred_project_name": display_label.name,
            "status": status,
            "start_time": start_time,
            "elapsed_seconds": elapsed,
            "checkpoint_seconds": max(0, int(checkpoint_seconds)),
            # Compatibility duration field remains zero until the transition
            # model is removed from all readers.
            "extra_seconds": 0,
            "persisted_activity_id": persisted_activity_id,
            "is_persisted": persisted_activity_id is not None,
            "display_project": display_label.to_dict(),
            "candidate_project": candidate_label.to_dict(),
            "project_transition": transition_dict,
            "project_transition_pending": False,
        }
        publish_runtime_activity_snapshot(snapshot, "collector_snapshot_publish")

    def clear(self, reason: str = "snapshot_clear") -> None:
        clear_runtime_activity_state(
            reason,
            clear_snapshot=True,
            clear_pending=False,
            clear_ownership=False,
        )

    def read(self) -> ActivitySnapshotContract | None:
        value = get_runtime_activity_snapshot()
        return value if isinstance(value, dict) else None


DEFAULT_SNAPSHOT_PUBLISHER = SnapshotPublisher()
