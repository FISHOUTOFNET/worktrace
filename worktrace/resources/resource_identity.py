from __future__ import annotations

from ..platforms.base import ActiveWindow
from .detectors import detect_resource
from .types import DetectedResource


def infer_resource_from_active_window(active_window: ActiveWindow) -> DetectedResource:
    return detect_resource(active_window)


def infer_resource_for_activity(activity: dict) -> DetectedResource:
    active_window = ActiveWindow(
        app_name=activity.get("app_name") or "",
        process_name=activity.get("process_name") or "",
        window_title=activity.get("window_title") or "",
        file_path_hint=activity.get("file_path_hint"),
    )
    return detect_resource(active_window)


def attach_resource_identity(row: dict) -> dict:
    item = dict(row)
    resource = infer_resource_for_activity(item)
    item["resource_kind"] = resource.resource_kind
    item["resource_subtype"] = resource.resource_subtype
    item["resource_display_name"] = resource.display_name
    item["resource_identity_key"] = resource.identity_key
    item["resource_is_anchor"] = resource.is_anchor
    item["resource_path_hint"] = resource.path_hint
    item["resource_uri_host"] = resource.uri_host
    item["activity_display_name"] = resource.display_name
    item["activity_identity_key"] = resource.identity_key
    return item
