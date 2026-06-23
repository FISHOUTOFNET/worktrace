from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DetectedResource:
    resource_kind: str
    resource_subtype: str
    display_name: str
    identity_key: str
    is_anchor: bool
    confidence: int
    source: str
    app_name: str
    process_name: str
    window_title: str
    path_hint: str | None = None
    path_key: str | None = None
    uri_scheme: str | None = None
    uri_host: str | None = None
    uri_hint: str | None = None
    metadata_json: str | None = None
