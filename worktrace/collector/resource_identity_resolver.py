from __future__ import annotations

import ntpath
from dataclasses import dataclass

from ..constants import (
    STATUS_ERROR,
    STATUS_EXCLUDED,
    STATUS_IDLE,
    STATUS_NORMAL,
    STATUS_PAUSED,
)
from ..path_utils import normalize_path_key
from ..platforms.base import ActiveWindow
from ..resources.resource_builders import make_system_resource, resource_signature
from ..resources.resource_identity import (
    infer_resource_for_activity,
    infer_resource_from_active_window,
)
from ..resources.types import DetectedResource
from ..services import privacy_service
from ..services.privacy_anonymization_service import update_path_or_anonymize
from .transition_types import ActivitySignature


@dataclass(frozen=True)
class ResourceMatch:
    matched: bool
    signature: ActivitySignature | None = None


class ResourceIdentityResolver:
    """Collector resource identity and late-path privacy boundary."""

    def payload_for(self, status: str, active_window: ActiveWindow | None) -> dict:
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

    def normalize_for_privacy(
        self,
        status: str,
        payload: dict,
        active_window: ActiveWindow | None,
    ) -> tuple[str, dict]:
        if status != STATUS_NORMAL or not self.payload_resource_is_excluded(payload):
            return status, payload
        return STATUS_EXCLUDED, self.payload_for(STATUS_EXCLUDED, active_window)

    def signature_for_payload(self, payload: dict) -> ActivitySignature:
        resource = payload.get("resource")
        return resource_signature(
            str(payload.get("status") or ""),
            resource if isinstance(resource, DetectedResource) else None,
            str(payload.get("app_name") or ""),
            str(payload.get("process_name") or ""),
            str(payload.get("window_title") or ""),
            payload.get("file_path_hint"),
        )

    def signature_for_activity(self, activity: dict) -> ActivitySignature:
        enriched = activity
        if "resource" not in enriched:
            enriched = dict(activity)
            enriched["resource"] = infer_resource_for_activity(enriched)
        return self.signature_for_payload(enriched)

    def current_matches(
        self,
        *,
        current: dict | None,
        current_signature: ActivitySignature | None,
        new_payload: dict,
        new_signature: ActivitySignature,
        persisted_activity_id: int | None,
    ) -> ResourceMatch:
        if current is None or current_signature is None:
            return ResourceMatch(False)

        if current_signature == new_signature:
            if self._supplement_path_if_needed(
                current,
                new_payload,
                persisted_activity_id,
            ):
                return ResourceMatch(False)
            return ResourceMatch(True, new_signature)

        if self.signatures_represent_same_resource(
            current_signature,
            new_signature,
            current,
            new_payload,
        ):
            if self._supplement_path_if_needed(
                current,
                new_payload,
                persisted_activity_id,
            ):
                return ResourceMatch(False)
            return ResourceMatch(True, new_signature)

        return ResourceMatch(False)

    def signatures_represent_same_resource(
        self,
        old_sig: ActivitySignature,
        new_sig: ActivitySignature,
        current: dict,
        payload: dict,
    ) -> bool:
        if old_sig[0] != new_sig[0]:
            return False

        old_resource = current.get("resource")
        new_resource = payload.get("resource")

        if isinstance(old_resource, DetectedResource) and isinstance(
            new_resource,
            DetectedResource,
        ):
            if old_resource.resource_kind != new_resource.resource_kind:
                return False
            if old_resource.resource_subtype != new_resource.resource_subtype:
                return False
            old_key = old_resource.identity_key
            new_key = new_resource.identity_key
            if old_key == new_key:
                return True
            return self.file_name_and_path_keys_match(old_key, new_key)

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

    def file_name_and_path_keys_match(self, old_key: str, new_key: str) -> bool:
        for prefix_a, prefix_b in (
            ("office_file_name:", "office_file:"),
            ("file_name:", "file_path:"),
        ):
            if old_key.startswith(prefix_a) and new_key.startswith(prefix_b):
                name_part = old_key[len(prefix_a) :]
                path_part = new_key[len(prefix_b) :]
                basename = ntpath.basename(path_part).lower().replace(" ", "-")
                if basename == name_part:
                    return True
            if old_key.startswith(prefix_b) and new_key.startswith(prefix_a):
                path_part = old_key[len(prefix_b) :]
                name_part = new_key[len(prefix_a) :]
                basename = ntpath.basename(path_part).lower().replace(" ", "-")
                if basename == name_part:
                    return True
        return False

    def payload_resource_is_excluded(self, payload: dict) -> bool:
        resource = payload.get("resource")
        if resource is None:
            return False
        try:
            return privacy_service.is_resource_excluded(resource)
        except Exception:
            # Privacy uncertainty is exclusion, never permission to persist.
            return True

    def _supplement_path_if_needed(
        self,
        current: dict,
        payload: dict,
        persisted_activity_id: int | None,
    ) -> bool:
        """Return True when late path discovery converted the row to excluded."""
        old_path = (current.get("file_path_hint") or "").strip()
        new_path = (payload.get("file_path_hint") or "").strip()
        new_resource = payload.get("resource")
        if not new_path and isinstance(new_resource, DetectedResource):
            new_path = str(new_resource.path_hint or "").strip()
        if old_path or not new_path:
            return False
        if persisted_activity_id is None:
            current["file_path_hint"] = new_path
            return False
        excluded = update_path_or_anonymize(persisted_activity_id, new_path)
        if not excluded:
            current["file_path_hint"] = new_path
        return excluded


DEFAULT_RESOURCE_IDENTITY_RESOLVER = ResourceIdentityResolver()
