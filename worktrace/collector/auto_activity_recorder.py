from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime

from ..constants import (
    SOURCE_AUTO,
    SOURCE_SYSTEM,
    STATUS_ERROR,
    STATUS_EXCLUDED,
    STATUS_IDLE,
    STATUS_NORMAL,
    STATUS_PAUSED,
    TIME_FORMAT,
    UNCATEGORIZED_PROJECT,
)
from ..resources.resource_builders import resource_signature
from ..resources.types import DetectedResource
from ..services import activity_service, project_service, session_boundary_service
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
    serialize_project_ownership,
    uncategorized_label,
)
from ..services.settings_service import get_setting, set_setting

SYSTEM_STATUSES = {STATUS_IDLE, STATUS_PAUSED, STATUS_EXCLUDED, STATUS_ERROR}


def _parse_time(value: str) -> datetime:
    return datetime.strptime(value, TIME_FORMAT)


def _seconds_between(start_time: str, end_time: str) -> int:
    return max(0, int((_parse_time(end_time) - _parse_time(start_time)).total_seconds()))


@dataclass
class AutoActivityRecorder:
    current_payload: dict | None = None
    current_signature: tuple[str, ...] | None = None
    current_start_time: str | None = None
    current_last_seen_time: str | None = None
    persisted_activity_id: int | None = None
    current_extra_seconds: int = 0
    resume_after_short_activity: dict | None = None
    project_ownership_state: ProjectOwnershipState | None = field(default=None)

    def observe(
        self,
        payload: dict,
        signature: tuple[str, ...],
        at_time: str,
    ) -> None:
        if self.current_payload is None:
            self._start(payload, signature, at_time)
            return

        if self.current_signature == signature:
            self.current_payload = {**self.current_payload, **{k: v for k, v in payload.items() if v is not None}}
            self.current_last_seen_time = at_time
            # Advance the project-ownership pending timer on an
            # unchanged resource signature. When the 30-second pending
            # window elapses the candidate is confirmed and becomes the
            # new display project.
            self.project_ownership_state = advance_ownership(
                self.project_ownership_state, at_time
            )
            self._ensure_persisted_if_ready(at_time)
            self._update_persisted_progress(at_time)
            self._write_snapshot(at_time)
            return

        self.finish_current(at_time)
        if self._resume_if_absorbed_activity_matches(payload, signature, at_time):
            return
        self._start(payload, signature, at_time)

    def finish_current(self, at_time: str, merge_transient: bool = True) -> None:
        if self.current_payload is None or self.current_start_time is None:
            self.clear_snapshot()
            return

        end_time = at_time
        elapsed = _seconds_between(self.current_start_time, end_time)
        status = self.current_payload.get("status")
        self._ensure_persisted_if_ready(end_time)
        if self.persisted_activity_id is not None:
            # Close via the ActivityLifecycle Command Facade so the
            # open → closed transition goes through the unified
            # close-finalize helper (project inference / automatic rules).
            lifecycle_close_activity(
                self.persisted_activity_id,
                end_time,
                duration_seconds=elapsed + self.current_extra_seconds,
            )
        elif merge_transient and elapsed > 0 and status in {STATUS_NORMAL, STATUS_IDLE}:
            self._merge_or_pend_short_seconds(elapsed)

        self.current_payload = None
        self.current_signature = None
        self.current_start_time = None
        self.current_last_seen_time = None
        self.persisted_activity_id = None
        self.current_extra_seconds = 0
        self.clear_snapshot()

    def stop(self, at_time: str, merge_transient: bool = True) -> None:
        self.finish_current(at_time, merge_transient=merge_transient)
        # Session boundary: clear the ownership state so the previous
        # session's display project is NOT inherited into a new session.
        self.project_ownership_state = clear_ownership_state()

    def split_at_midnight(self, at_time: str) -> bool:
        if self.current_payload is None or self.current_start_time is None:
            self.clear_short_buffers()
            self.clear_snapshot()
            return False
        payload = dict(self.current_payload)
        signature = self.current_signature or _activity_signature(payload)
        project_id = self._current_concrete_project_id()
        self.stop(at_time, merge_transient=False)
        self.clear_short_buffers()
        self._start(payload, signature, at_time)
        if payload.get("status") == STATUS_NORMAL and project_id is not None:
            self._persist_midnight_anchor(project_id, at_time)
        return True

    def clear_short_buffers(self) -> None:
        self.resume_after_short_activity = None
        self._set_pending_short_seconds(0)

    def clear_snapshot(self) -> None:
        set_setting("current_activity_snapshot", "")

    def _start(self, payload: dict, signature: tuple[str, ...], at_time: str) -> None:
        self.current_payload = dict(payload)
        self.current_signature = signature
        self.current_start_time = at_time
        self.current_last_seen_time = at_time
        self.persisted_activity_id = None
        self.current_extra_seconds = 0
        self.resume_after_short_activity = None
        self._begin_project_ownership(payload, at_time)
        self._ensure_persisted_if_ready(at_time)
        self._update_persisted_progress(at_time)
        self._write_snapshot(at_time)

    def _begin_project_ownership(self, payload: dict, at_time: str) -> None:
        """Initialize project ownership for a new resource signature.

        Resource identity is immediate — the snapshot will reflect the
        new resource right away. Project ownership is *delayed*: when
        the candidate project for the new resource differs from the
        last confirmed project, a 30-second pending window starts.
        During pending the display project continues to show the last
        confirmed project.

        System statuses (idle / paused / excluded / error) clear the
        ownership state so the previous session's project is not
        inherited across a system-status boundary.
        """
        status = str(payload.get("status") or STATUS_NORMAL)
        if status in SYSTEM_STATUSES:
            # Session boundary: clear ownership so the previous
            # session's display project is not inherited.
            self.project_ownership_state = clear_ownership_state()
            return
        resource = payload.get("resource")
        candidate = candidate_project_for_activity(payload, resource)
        self.project_ownership_state = begin_ownership_for_new_resource(
            self.project_ownership_state,
            candidate,
            at_time,
        )

    def ensure_persisted_for_clipboard(self, at_time: str) -> int | None:
        self._ensure_persisted_if_ready(at_time, force=True)
        self._update_persisted_progress(at_time)
        self._write_snapshot(at_time)
        return self.persisted_activity_id

    def _ensure_persisted_if_ready(self, at_time: str, force: bool = False) -> None:
        if self.current_payload is None or self.current_start_time is None or self.persisted_activity_id is not None:
            return
        status = self.current_payload.get("status")
        allowed_statuses = {STATUS_NORMAL} if force else {STATUS_NORMAL, STATUS_IDLE, STATUS_PAUSED, STATUS_EXCLUDED, STATUS_ERROR}
        if status not in allowed_statuses:
            return
        elapsed = _seconds_between(self.current_start_time, at_time)
        # The 30-second threshold and the STATUS_NORMAL clipboard gate are
        # enforced by the lifecycle facade. The recorder no longer performs
        # the threshold final check.
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
            pending = self._get_pending_short_seconds()
            if pending > 0:
                self.current_extra_seconds += pending
                self._set_pending_short_seconds(0)

    def _persist_midnight_anchor(self, project_id: int, at_time: str) -> None:
        if self.current_payload is None or self.current_start_time is None or self.persisted_activity_id is not None:
            return
        # Persist the midnight-anchor open activity via the lifecycle
        # facade so create + finalize + midnight_anchor assignment go
        # through a single command owner.
        activity_id = persist_midnight_anchor(
            start_time=self.current_start_time,
            source=SOURCE_AUTO,
            payload=self.current_payload,
            project_id=project_id,
        )
        self.persisted_activity_id = activity_id
        self.current_extra_seconds = 0
        self._update_persisted_progress(at_time)
        self._write_snapshot(at_time)

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
        elapsed = _seconds_between(self.current_start_time, at_time)
        activity_service.set_activity_duration(self.persisted_activity_id, elapsed + self.current_extra_seconds)

    def _merge_or_pend_short_seconds(self, seconds: int) -> None:
        if seconds <= 0:
            return
        target = activity_service.get_latest_closed_auto_normal_activity(
            after_time=session_boundary_service.latest_boundary_time()
        )
        if target:
            activity_service.increment_activity_duration(int(target["id"]), seconds)
            target["duration_seconds"] = int(target.get("duration_seconds") or 0) + seconds
            self.resume_after_short_activity = target
            return
        self.resume_after_short_activity = None
        self._set_pending_short_seconds(self._get_pending_short_seconds() + seconds)

    def _resume_if_absorbed_activity_matches(
        self,
        payload: dict,
        signature: tuple[str, ...],
        at_time: str,
    ) -> bool:
        target = self.resume_after_short_activity
        self.resume_after_short_activity = None
        # Reconstruct resource info into target for signature comparison
        if target and "resource" not in target:
            target = self._enrich_target_with_resource(target)
        if not target or _activity_signature(target) != signature:
            return False
        start_time = str(target.get("start_time") or "")
        if not start_time:
            return False
        activity_service.reopen_activity(int(target["id"]))
        self.current_payload = {**dict(payload)}
        self.current_signature = signature
        self.current_start_time = start_time
        self.current_last_seen_time = at_time
        self.persisted_activity_id = int(target["id"])
        stored_duration = int(target.get("duration_seconds") or 0)
        self.current_extra_seconds = max(0, stored_duration - _seconds_between(start_time, at_time))
        # Recompute project ownership for the resumed activity so the
        # display project reflects the resumed resource's candidate
        # (which should match the last confirmed project, producing no
        # pending).
        self._begin_project_ownership(payload, at_time)
        self._update_persisted_progress(at_time)
        self._write_snapshot(at_time)
        return True

    def _enrich_target_with_resource(self, target: dict) -> dict:
        from ..resources.resource_identity import infer_resource_for_activity
        enriched = dict(target)
        resource = infer_resource_for_activity(enriched)
        enriched["resource"] = resource
        return enriched

    def _get_pending_short_seconds(self) -> int:
        raw = get_setting("pending_short_seconds", "0") or "0"
        try:
            return max(0, int(raw))
        except ValueError:
            return 0

    def _set_pending_short_seconds(self, seconds: int) -> None:
        set_setting("pending_short_seconds", str(max(0, int(seconds))))

    def _write_snapshot(self, at_time: str) -> None:
        if self.current_payload is None or self.current_start_time is None:
            self.clear_snapshot()
            return
        elapsed = _seconds_between(self.current_start_time, at_time)
        resource = self.current_payload.get("resource")
        resource_display_name = ""
        resource_kind = ""
        resource_subtype = ""
        resource_identity_key = ""
        resource_path_hint: str | None = None
        resource_uri_host: str | None = None
        if resource is not None and isinstance(resource, DetectedResource):
            resource_display_name = resource.display_name
            resource_kind = resource.resource_kind
            resource_subtype = resource.resource_subtype
            resource_identity_key = resource.identity_key
            resource_path_hint = resource.path_hint
            resource_uri_host = resource.uri_host

        # activity_display_name prefers resource.display_name, then app/process.
        activity_display_name = resource_display_name
        if not activity_display_name:
            activity_display_name = (
                self.current_payload.get("app_name")
                or self.current_payload.get("process_name")
                or ""
            )
        status = self.current_payload.get("status") or STATUS_NORMAL

        ownership = self.project_ownership_state
        if status in SYSTEM_STATUSES or ownership is None or ownership.display_project is None:
            display_label = uncategorized_label()
            candidate_label = uncategorized_label()
            transition_dict = serialize_project_ownership(None)["project_transition"]
        else:
            display_label = ownership.display_project
            candidate_label = ownership.candidate_project or uncategorized_label()
            transition_dict = ownership.project_transition.to_dict()

        display_project_dict = display_label.to_dict()
        candidate_project_dict = candidate_label.to_dict()
        project_transition_pending = bool(transition_dict.get("pending"))

        # ``inferred_project_name`` mirrors the display project name;
        # consumed by statistics_service live projection and
        # refresh-revision.
        # than the candidate. New readers should use ``display_project``.
        inferred_project_name = display_label.name or UNCATEGORIZED_PROJECT

        payload = {
            "app_name": self.current_payload.get("app_name") or "",
            "process_name": self.current_payload.get("process_name") or "",
            "window_title": self.current_payload.get("window_title") or "",
            "file_path_hint": self.current_payload.get("file_path_hint"),
            "activity_display_name": activity_display_name,
            "resource_kind": resource_kind,
            "resource_subtype": resource_subtype,
            "resource_display_name": resource_display_name,
            "resource_identity_key": resource_identity_key,
            "resource_path_hint": resource_path_hint,
            "resource_uri_host": resource_uri_host,
            "inferred_project_name": inferred_project_name,
            "status": status,
            "start_time": self.current_start_time,
            "elapsed_seconds": elapsed,
            "extra_seconds": self.current_extra_seconds,
            "persisted_activity_id": self.persisted_activity_id,
            "is_persisted": self.persisted_activity_id is not None,
            "display_project": display_project_dict,
            "candidate_project": candidate_project_dict,
            "project_transition": transition_dict,
            "project_transition_pending": project_transition_pending,
        }
        set_setting("current_activity_snapshot", json.dumps(payload, ensure_ascii=False))


def _activity_signature(activity: dict) -> tuple[str, ...]:
    resource = activity.get("resource")
    return resource_signature(
        str(activity.get("status") or STATUS_NORMAL),
        resource if isinstance(resource, DetectedResource) else None,
        str(activity.get("app_name") or ""),
        str(activity.get("process_name") or ""),
        str(activity.get("window_title") or ""),
        activity.get("file_path_hint"),
    )
