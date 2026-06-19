from __future__ import annotations

import json
from dataclasses import dataclass
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
from ..resource_patterns import infer_resource_identity
from ..services import activity_service
from ..services.settings_service import get_int_setting, get_setting, set_setting

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
            self._ensure_persisted_if_ready(at_time)
            self._update_persisted_progress(at_time)
            self._write_snapshot(at_time)
            return

        self.finish_current(at_time)
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
            activity_service.close_activity(self.persisted_activity_id, end_time)
            if self.current_extra_seconds:
                activity_service.increment_activity_duration(
                    self.persisted_activity_id,
                    self.current_extra_seconds,
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

    def clear_snapshot(self) -> None:
        set_setting("current_activity_snapshot", "")

    def _start(self, payload: dict, signature: tuple[str, str, str, str], at_time: str) -> None:
        self.current_payload = dict(payload)
        self.current_signature = signature
        self.current_start_time = at_time
        self.current_last_seen_time = at_time
        self.persisted_activity_id = None
        self.current_extra_seconds = 0
        self._ensure_persisted_if_ready(at_time)
        self._update_persisted_progress(at_time)
        self._write_snapshot(at_time)

    def _ensure_persisted_if_ready(self, at_time: str) -> None:
        if self.current_payload is None or self.current_start_time is None or self.persisted_activity_id is not None:
            return
        status = self.current_payload.get("status")
        if status not in {STATUS_NORMAL, STATUS_IDLE, STATUS_PAUSED, STATUS_EXCLUDED, STATUS_ERROR}:
            return
        elapsed = _seconds_between(self.current_start_time, at_time)
        if elapsed < self._threshold_for_status(str(status)):
            return

        source = SOURCE_AUTO if status == STATUS_NORMAL else SOURCE_SYSTEM
        activity_id = activity_service.create_activity(
            start_time=self.current_start_time,
            source=source,
            **self.current_payload,
        )
        activity_service.finalize_created_activity(activity_id)
        self.persisted_activity_id = activity_id

        if status == STATUS_NORMAL:
            pending = self._get_pending_short_seconds()
            if pending > 0:
                self.current_extra_seconds += pending
                self._set_pending_short_seconds(0)

    def _update_persisted_progress(self, at_time: str) -> None:
        if self.persisted_activity_id is None or self.current_start_time is None:
            return
        elapsed = _seconds_between(self.current_start_time, at_time)
        activity_service.set_activity_duration(self.persisted_activity_id, elapsed + self.current_extra_seconds)

    def _threshold_for_status(self, status: str) -> int:
        if status == STATUS_IDLE:
            return max(1, get_int_setting("min_idle_segment_seconds", 60))
        return max(1, get_int_setting("min_history_seconds", 60))

    def _merge_or_pend_short_seconds(self, seconds: int) -> None:
        if seconds <= 0:
            return
        target = activity_service.get_latest_closed_auto_normal_activity()
        if target:
            activity_service.increment_activity_duration(int(target["id"]), seconds)
            return
        self._set_pending_short_seconds(self._get_pending_short_seconds() + seconds)

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
        identity = infer_resource_identity(
            self.current_payload.get("app_name"),
            self.current_payload.get("process_name"),
            self.current_payload.get("window_title"),
            self.current_payload.get("file_path_hint"),
        )
        payload = {
            "app_name": self.current_payload.get("app_name") or "",
            "process_name": self.current_payload.get("process_name") or "",
            "window_title": self.current_payload.get("window_title") or "",
            "file_path_hint": self.current_payload.get("file_path_hint"),
            "resource_display_name": identity.display_name,
            "inferred_project_name": _snapshot_project_name(identity),
            "status": self.current_payload.get("status") or STATUS_NORMAL,
            "start_time": self.current_start_time,
            "elapsed_seconds": elapsed,
            "persisted_activity_id": self.persisted_activity_id,
            "is_persisted": self.persisted_activity_id is not None,
        }
        set_setting("current_activity_snapshot", json.dumps(payload, ensure_ascii=False))


def _snapshot_project_name(identity) -> str:
    if identity.resource_role != "anchor" or identity.resource_type != "file":
        return UNCATEGORIZED_PROJECT
    from ..services.project_inference_service import candidate_project_name_for_file_resource

    return candidate_project_name_for_file_resource(
        {
            "parent_dir": identity.parent_dir,
            "file_stem": identity.file_stem,
            "display_name": identity.display_name,
            "resource_role": identity.resource_role,
            "resource_type": identity.resource_type,
        }
    ) or UNCATEGORIZED_PROJECT
