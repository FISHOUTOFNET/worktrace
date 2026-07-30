"""Typed current-only contracts for live display transport."""
from __future__ import annotations

from typing import Any, Literal, TypedDict

LiveState = Literal["none", "persisted_open", "suppressed"]
CollectorSnapshotState = Literal["paused", "idle", "excluded", "error"]
DurationSemantic = Literal["current_live", "aggregate_live", "static_closed"]
DisplaySessionKind = Literal["none", "persisted_open", "status_only", "suppressed"]
DisplayBasePolicy = Literal["suppressed", "persisted_open"]


class LiveClockV2(TypedDict):
    sampled_at_epoch_ms: int
    started_at_epoch_ms: int
    elapsed_seconds_at_sample: int
    aggregate_base_seconds: int
    duration_semantic: DurationSemantic
    is_live: bool
    live_state: LiveState
    display_span_id: str
    stable_live_key_hash: str


LiveClockContract = LiveClockV2


class DisplayProjectContract(TypedDict, total=False):
    id: int | None
    name: str
    description: str
    source: str
    is_uncategorized: bool
    is_suggested_project: bool


class ActivitySnapshotContract(TypedDict, total=False):
    app_name: str
    process_name: str
    activity_display_name: str
    resource_kind: str
    resource_subtype: str
    resource_display_name: str
    resource_identity_key: str
    status: str
    start_time: str
    elapsed_seconds: int
    persisted_activity_id: int | None
    is_persisted: bool
    display_project: DisplayProjectContract


class DisplaySessionPolicyContract(TypedDict, total=False):
    display_session_kind: DisplaySessionKind
    base_policy: DisplayBasePolicy
    aggregate_base_seconds: int
    current_base_seconds: int
    materialize_recent: bool
    materialize_timeline: bool
    materialize_details: bool
    status_only_reason: str
    base_policy_reason: str


class DisplaySpanContract(TypedDict, total=False):
    display_span_id: str
    activity_id: int
    anchor_activity_id: int
    source: str
    live_state: LiveState
    start_time: str
    end_time: str
    resource_identity_hash: str
    duration: str
    duration_seconds: int
    live_clock: LiveClockV2
    project_id: int
    project_name: str
    project_description: str
    resource_name: str
    is_current: bool
    is_virtual: bool
    is_persisted: bool
    is_visible_in_current: bool
    is_visible_in_recent: bool
    is_visible_in_timeline: bool
    is_visible_in_details: bool
    editable: bool
    exportable: bool
    edit_disabled: bool
    disable_reason: str
    display_project: DisplayProjectContract
    is_uncategorized: bool
    is_classified: bool


class CurrentActivityContract(TypedDict, total=False):
    active: bool
    display: str
    elapsed_seconds: int
    resource_elapsed_seconds: int
    status: str
    is_persisted: bool
    project_name: str
    project_description: str
    project_id: int
    persisted_activity_id: int
    resource_name: str
    app_name: str
    start_time: str
    end_time: str | None
    activity_id: int | None
    source: str
    display_project: DisplayProjectContract | None
    is_uncategorized: bool
    is_classified: bool
    live_clock: LiveClockV2


class RecentRecordRowContract(TypedDict, total=False):
    project_name: str
    project_description: str
    project_id: int
    start_time: str
    end_time: str
    duration: str
    duration_seconds: int
    live_clock: LiveClockV2
    activity_ids: list[int]
    first_activity_id: int | None
    activity_id: int
    open_activity_id: int
    source: str
    is_in_progress: bool
    is_live_projected: bool
    contributes_to_totals: bool
    is_uncategorized: bool
    is_classified: bool


class TimelineSessionRowContract(RecentRecordRowContract, total=False):
    projection_instance_key: str
    projection_revision: str
    adjusted_duration_seconds: int | None
    has_duration_override: bool
    status: str
    event_count: int
    session_note: str
    summary_activity_ids: list[int]


class ActivityDetailRowContract(TypedDict, total=False):
    activity_id: int
    start_time: str
    end_time: str
    duration: str
    duration_seconds: int
    live_clock: LiveClockV2
    app_name: str
    resource_type: str
    resource_name: str
    project_name: str
    project_description: str
    status: str
    source: str
    is_in_progress: bool
    is_live_projected: bool
    editable: bool
    exportable: bool


class ProjectActivitySummaryRowContract(TypedDict, total=False):
    row_kind: Literal["project_activity_summary"]
    summary_id: str
    activity_identity_key: str
    activity_name: str
    duration_seconds: int
    duration: str
    accounted_project_id: int
    accounted_project_name: str
    display_project_id: int
    display_project_name: str
    display_project_description: str
    activity_ids: list[int]
    is_in_progress: bool
    live_delta_eligible: bool
    live_clock: LiveClockV2
    edit_disabled: bool
    disable_reason: str


class RefreshStateContract(TypedDict, total=False):
    ok: bool
    collector_status: str
    collector_health_state: str
    collector_last_successful_observation_at: str
    collector_consecutive_failures: int
    paused: bool
    status_display: str
    current_activity_key: str
    current_activity_status: str
    is_persisted: bool
    persisted_activity_id: int
    live_revision: str
    page_revision: str
    today: str
    report_date: str
    latest_activity_id: int
    runtime: dict[str, Any]


class CollectorDecisionTraceContract(TypedDict, total=False):
    observed_at: str
    previous_signature_hash: str
    incoming_signature_hash: str
    same_signature: bool
    selected_transition: str
    selected_project_source: str
    decision_reason: str


__all__ = [
    "ActivityDetailRowContract",
    "ActivitySnapshotContract",
    "CollectorDecisionTraceContract",
    "CollectorSnapshotState",
    "CurrentActivityContract",
    "DisplayBasePolicy",
    "DisplayProjectContract",
    "DisplaySessionKind",
    "DisplaySessionPolicyContract",
    "DisplaySpanContract",
    "DurationSemantic",
    "LiveClockContract",
    "LiveClockV2",
    "LiveState",
    "ProjectActivitySummaryRowContract",
    "RecentRecordRowContract",
    "RefreshStateContract",
    "TimelineSessionRowContract",
]
