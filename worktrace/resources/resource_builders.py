"""Shared builders and helpers for activity resources.

This module is the single source of truth for:
- constructing system-level ``DetectedResource`` instances (idle / paused /
  excluded / error);
- computing a stable resource signature tuple used by the collector to decide
  whether two observations refer to the same underlying resource;
- parsing ``metadata_json`` strings safely.
"""
from __future__ import annotations

import json

from ..constants import (
    EXCLUDED_APP_NAME,
    EXCLUDED_PROCESS_NAME,
    EXCLUDED_WINDOW_TITLE,
    STATUS_ERROR,
    STATUS_EXCLUDED,
    STATUS_IDLE,
    STATUS_PAUSED,
)
from ..path_utils import normalize_path_key
from .types import DetectedResource


def make_system_resource(
    status: str,
    app_name: str | None = None,
    process_name: str | None = None,
    window_title: str | None = None,
) -> DetectedResource:
    """Build a ``DetectedResource`` for a system-level status.

    ``status`` must be one of :data:`STATUS_IDLE`, :data:`STATUS_PAUSED`,
    :data:`STATUS_EXCLUDED` or :data:`STATUS_ERROR`.

    For idle / paused / error the optional ``app_name`` / ``process_name`` /
    ``window_title`` arguments are passed through; when omitted, sensible
    defaults matching the collector payload are used.

    For excluded the resource is always anonymous — it uses the
    ``EXCLUDED_*`` constants and never carries ``path_hint``, ``uri_host`` or
    ``metadata_json``, regardless of the arguments passed in.
    """
    if status == STATUS_IDLE:
        return DetectedResource(
            resource_kind="system",
            resource_subtype="idle",
            display_name="空闲",
            identity_key="system:idle",
            is_anchor=False,
            confidence=100,
            source="auto_idle",
            app_name=app_name if app_name is not None else "空闲",
            process_name=process_name if process_name is not None else "idle",
            window_title=window_title if window_title is not None else "用户空闲",
        )
    if status == STATUS_PAUSED:
        return DetectedResource(
            resource_kind="system",
            resource_subtype="paused",
            display_name="已暂停",
            identity_key="system:paused",
            is_anchor=False,
            confidence=100,
            source="auto_paused",
            app_name=app_name if app_name is not None else "已暂停",
            process_name=process_name if process_name is not None else "paused",
            window_title=window_title if window_title is not None else "采集已暂停",
        )
    if status == STATUS_EXCLUDED:
        return DetectedResource(
            resource_kind="system",
            resource_subtype="excluded",
            display_name=EXCLUDED_APP_NAME,
            identity_key="system:excluded",
            is_anchor=False,
            confidence=100,
            source="auto_excluded",
            app_name=EXCLUDED_APP_NAME,
            process_name=EXCLUDED_PROCESS_NAME,
            window_title=EXCLUDED_WINDOW_TITLE,
            path_hint=None,
            uri_scheme=None,
            uri_host=None,
            uri_hint=None,
            metadata_json=None,
        )
    if status == STATUS_ERROR:
        return DetectedResource(
            resource_kind="system",
            resource_subtype="error",
            display_name="异常",
            identity_key="system:error",
            is_anchor=False,
            confidence=100,
            source="auto_error",
            app_name=app_name if app_name is not None else "异常",
            process_name=process_name if process_name is not None else "error",
            window_title=window_title if window_title is not None else "采集异常",
        )
    raise ValueError(f"unsupported system status: {status!r}")


def resource_signature(
    status: str,
    resource: DetectedResource | None,
    app_name: str = "",
    process_name: str = "",
    window_title: str = "",
    file_path_hint: str | None = None,
) -> tuple[str, ...]:
    """Compute a stable signature tuple for an activity observation.

    When a ``DetectedResource`` is available the signature is derived from the
    resource's kind / subtype / identity_key and a normalised path-or-host
    component.  Otherwise the signature falls back to the raw activity fields.
    """
    if resource is not None:
        path_or_host = ""
        if resource.path_hint:
            path_or_host = normalize_path_key(resource.path_hint)
        elif resource.uri_host:
            path_or_host = resource.uri_host.lower().strip()
        else:
            path_or_host = resource.display_name
        return (
            str(status or ""),
            resource.resource_kind,
            resource.resource_subtype,
            resource.identity_key,
            path_or_host,
        )
    return (
        str(status or ""),
        str(app_name or ""),
        str(process_name or ""),
        str(window_title or ""),
        normalize_path_key(str(file_path_hint or "")),
    )


def parse_metadata_json(value: str | None) -> dict | None:
    """Parse a ``metadata_json`` string into a dict, or ``None`` if invalid."""
    if not value:
        return None
    try:
        result = json.loads(value)
        return result if isinstance(result, dict) else None
    except (json.JSONDecodeError, TypeError):
        return None
