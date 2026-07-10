from __future__ import annotations

import json

from ..constants import (
    STATUS_ERROR,
    STATUS_EXCLUDED,
    STATUS_IDLE,
    STATUS_NORMAL,
    STATUS_PAUSED,
    UNCATEGORIZED_PROJECT,
)
from ..contracts.live_display_contracts import ActivitySnapshotContract
from ..resources.types import DetectedResource
from ..services.project_ownership_service import (
    ProjectOwnershipState,
    serialize_project_ownership,
    uncategorized_label,
)
from ..services.runtime_activity_state_service import clear_runtime_activity_state
from ..services.settings_service import get_setting, set_setting
from .transition_types import seconds_between

SYSTEM_STATUSES = {STATUS_IDLE, STATUS_PAUSED, STATUS_EXCLUDED, STATUS_ERROR}


class SnapshotPublisher:
    """Sole current_activity_snapshot writer."""

    def publish(
        self,
        *,
        payload: dict | None,
        start_time: str | None,
        at_time: str,
        project_ownership_state: ProjectOwnershipState | None,
        persisted_activity_id: int | None,
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
        resource_path_hint: str | None = None
        resource_uri_host: str | None = None
        if isinstance(resource, DetectedResource):
            resource_display_name = resource.display_name
            resource_kind = resource.resource_kind
            resource_subtype = resource.resource_subtype
            resource_identity_key = resource.identity_key
            resource_path_hint = resource.path_hint
            resource_uri_host = resource.uri_host

        activity_display_name = resource_display_name
        if not activity_display_name:
            activity_display_name = (
                payload.get("app_name")
                or payload.get("process_name")
                or ""
            )
        status = payload.get("status") or STATUS_NORMAL

        ownership = project_ownership_state
        if status in SYSTEM_STATUSES or ownership is None or ownership.display_project is None:
            display_label = uncategorized_label()
            candidate_label = uncategorized_label()
            transition_dict = serialize_project_ownership(None)["project_transition"]
        else:
            display_label = ownership.display_project
            candidate_label = ownership.candidate_project or uncategorized_label()
            # Snapshots retain the transition shape only for old readers.
            # A pending confirmation window is no longer a runtime contract.
            transition_dict = {
                **ownership.project_transition.to_dict(),
                "pending": False,
                "started_at": "",
                "elapsed_seconds": 0,
                "threshold_seconds": 0,
                "from_project_id": None,
                "to_project_id": None,
            }

        display_project_dict = display_label.to_dict()
        candidate_project_dict = candidate_label.to_dict()
        project_transition_pending = False
        inferred_project_name = display_label.name or UNCATEGORIZED_PROJECT

        snapshot: ActivitySnapshotContract = {
            "app_name": payload.get("app_name") or "",
            "process_name": payload.get("process_name") or "",
            "window_title": payload.get("window_title") or "",
            "file_path_hint": payload.get("file_path_hint"),
            "activity_display_name": activity_display_name,
            "resource_kind": resource_kind,
            "resource_subtype": resource_subtype,
            "resource_display_name": resource_display_name,
            "resource_identity_key": resource_identity_key,
            "resource_path_hint": resource_path_hint,
            "resource_uri_host": resource_uri_host,
            "inferred_project_name": inferred_project_name,
            "status": status,
            "start_time": start_time,
            "elapsed_seconds": elapsed,
            # Raw rows are never extended by absorbed short activity. Keep
            # the contract field for readers that have not yet dropped it.
            "extra_seconds": 0,
            "persisted_activity_id": persisted_activity_id,
            "is_persisted": persisted_activity_id is not None,
            "display_project": display_project_dict,
            "candidate_project": candidate_project_dict,
            "project_transition": transition_dict,
            "project_transition_pending": project_transition_pending,
        }
        set_setting("current_activity_snapshot", json.dumps(snapshot, ensure_ascii=False))

    def clear(self, reason: str = "snapshot_clear") -> None:
        clear_runtime_activity_state(
            reason,
            clear_snapshot=True,
            clear_pending=False,
            clear_ownership=False,
        )

    def restore_raw(self, value: str) -> None:
        set_setting("current_activity_snapshot", value or "")

    def read_raw(self) -> str:
        return get_setting("current_activity_snapshot", "") or ""


DEFAULT_SNAPSHOT_PUBLISHER = SnapshotPublisher()
