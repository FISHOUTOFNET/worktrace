"""Typed internal contracts for live display and collector payloads.

These types document plain ``dict`` payloads exchanged between collector,
Activity Display Model, ViewModel, and frontend rendering. They are internal
development contracts, not published APIs or runtime validators.
"""

from __future__ import annotations

from typing import Any, Literal, TypedDict

LiveState = Literal[
    "none",
    "persisted_open",
    "status_only",
    "suppressed",
]
CollectorSnapshotState = Literal["paused", "idle", "excluded", "error"]
DurationSemantic = Literal["current_live", "aggregate_live", "static_closed", "static_status"]
DisplaySessionKind = Literal[
    "none",
    "persisted_open",
    "status_only",
    "suppressed",
]
DisplayBasePolicy = Literal[
    "suppressed",
    "persisted_open",
]


class DisplayProjectContract(TypedDict, total=False):
    id: int | None
    name: str
    description: str
    source: str
    is_uncategorized: bool
    is_suggested_project: bool


class ActivitySnapshotContract(TypedDict, total=False):
    """Display-safe collector snapshot payload.

    Raw window titles, filesystem paths and URI hosts are deliberately absent.
    The snapshot carries one formal project block: ``display_project``.
    Candidate inference remains internal to the collector and never enters
    page DTOs, revisions, structural signatures, or frontend identity.
    """

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
    project_duration_live: bool
    current_duration_live: bool
    materialize_recent: bool
    materialize_timeline: bool
    materialize_details: bool
    status_only_reason: str
    base_policy_reason: str


class LiveClockContract(TypedDict, total=False):
    display_span_id: str
    stable_live_key: str
    stable_live_key_hash: str
    live_state: LiveState
    live_started_at_epoch_ms: int
    carry_seconds: int
    duration_semantic: DurationSemantic
    current_live_seconds_at_sample: int
    current_live_base_seconds: int
    aggregate_duration_seconds_at_sample: int
    aggregate_display_base_seconds: int
    display_base_seconds: int
    duration_seconds_at_sample: int
    active_elapsed_at_sample: int
    current_elapsed_at_sample: int
    is_live: bool
    is_project_duration_live: bool
    current_duration_live: bool
    project_duration_live: bool
    display_session_kind: DisplaySessionKind
    base_policy: DisplayBasePolicy
    status_only_reason: str
    base_policy_reason: str
    display_policy: DisplaySessionPolicyContract
    current_activity_display_span_id: str
    current_resource_identity_hash: str


class DisplaySpanContract(TypedDict, total=False):
    display_span_id: str
    activity_id: int
    anchor_activity_id: int
    source: str
    live_state: LiveState
    start_time: str
    end_time: str
    resource_identity_hash: str
    duration_semantic: DurationSemantic | str
    duration: str
    duration_seconds: int
    duration_seconds_at_sample: int
    current_live_seconds_at_sample: int
    current_live_base_seconds: int
    aggregate_duration_seconds_at_sample: int
    aggregate_display_base_seconds: int
    display_base_seconds: int
    live_clock: LiveClockContract
    project_id: int
    project_name: str
    project_description: str
    resource_name: str
    is_current: bool
    is_live: bool
    project_duration_live: bool
    current_duration_live: bool
    display_session_kind: DisplaySessionKind | str
    base_policy: DisplayBasePolicy | str
    status_only_reason: str
    base_policy_reason: str
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
    live_anchor_activity_id: int
    live_anchor_base_seconds: int
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
    project_id: int
    persisted_activity_id: int
    live_state: str
    is_in_progress: bool
    is_virtual_live: bool
    is_live: bool
    current_duration_live: bool
    project_duration_live: bool
    stable_live_key_hash: str
    live_started_at_epoch_ms: int
    carry_seconds: int
    resource_name: str
    app_name: str
    start_time: str
    end_time: str | None
    activity_id: int | None
    source: str
    display_span_id: str
    current_activity_display_span_id: str
    current_resource_identity_hash: str
    live_clock: LiveClockContract
    duration_semantic: DurationSemantic | str
    display_base_seconds: int
    live_base_seconds: int
    current_live_seconds_at_sample: int
    current_live_base_seconds: int
    duration_seconds_at_sample: int
    aggregate_duration_seconds_at_sample: int
    aggregate_display_base_seconds: int
    display_project: DisplayProjectContract | None
    is_uncategorized: bool
    is_classified: bool


class RecentActivityRowContract(TypedDict, total=False):
    project_name: str
    project_description: str
    project_id: int
    start_time: str
    end_time: str
    duration: str
    duration_seconds: int
    duration_semantic: DurationSemantic | str
    display_base_seconds: int
    display_span_id: str
    stable_live_key_hash: str
    live_state: str
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


class TimelineSessionRowContract(RecentActivityRowContract, total=False):
    projection_instance_key: str
    projection_revision: str
    adjusted_duration_seconds: int | None
    has_duration_override: bool
    status: str
    event_count: int
    session_note: str
    # Read-only scope for Timeline's right summary panel. This is distinct
    # from activity_ids, which remains the stable edit/override identity.
    summary_activity_ids: list[int]


class ActivityDetailRowContract(TypedDict, total=False):
    activity_id: int
    start_time: str
    end_time: str
    duration: str
    duration_seconds: int
    duration_semantic: DurationSemantic | str
    display_base_seconds: int
    display_span_id: str
    stable_live_key_hash: str
    live_state: str
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
    duration_semantic: DurationSemantic | str
    display_span_id: str
    stable_live_key_hash: str
    display_base_seconds: int
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
    live_clock: LiveClockContract
    display_span_id: str
    live_started_at_epoch_ms: int
    carry_seconds: int
    duration_seconds_at_sample: int
    stable_live_key: str
    stable_live_key_hash: str
    live_state: str
    is_live: bool
    is_project_duration_live: bool
    project_duration_live: bool
    current_duration_live: bool
    current_activity: CurrentActivityContract
    sample_id: str


class CollectorDecisionTraceContract(TypedDict, total=False):
    observed_at: str
    previous_signature_hash: str
    incoming_signature_hash: str
    same_signature: bool
    status: str
    end_reason: str
    hard_boundary_reason: str
    elapsed_seconds: int
    persisted_activity_id_before: int | None
    persisted_activity_id_after: int | None
    snapshot_action: str
    project_ownership_action: str
    extra: dict[str, Any]
