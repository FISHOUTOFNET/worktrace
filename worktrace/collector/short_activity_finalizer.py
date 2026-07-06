from __future__ import annotations

from dataclasses import dataclass

from ..constants import STATUS_NORMAL
from ..contracts.live_display_contracts import ShortActivityAction
from ..services import activity_service, session_boundary_service
from ..services.activity_continuity_service import (
    can_absorb_short_pending,
    can_merge_finished_short_activity,
)
from ..services.runtime_activity_state_service import clear_runtime_activity_state
from .decision_trace import (
    CollectorDecisionTrace,
    DecisionTraceRecorder,
    NULL_DECISION_TRACE_RECORDER,
    signature_hash,
)
from .resource_identity_resolver import (
    DEFAULT_RESOURCE_IDENTITY_RESOLVER,
    ResourceIdentityResolver,
)
from .transition_types import ActivityEndReason, ActivitySignature


@dataclass(frozen=True)
class FinishedActivityCandidate:
    status: str
    signature: ActivitySignature | None
    start_time: str
    end_time: str
    seconds: int
    persisted_activity_id: int | None
    end_reason: ActivityEndReason
    payload: dict


@dataclass(frozen=True)
class ShortActivityDecision:
    action: ShortActivityAction
    target_activity_id: int | None
    absorbed_seconds: int
    reason: str


@dataclass(frozen=True)
class ResumeAnchorResult:
    decision: ShortActivityDecision
    target: dict | None = None


class ShortActivityFinalizer:
    """Sole owner for finished <30s normal merge/drop/resume policy."""

    def __init__(
        self,
        resolver: ResourceIdentityResolver = DEFAULT_RESOURCE_IDENTITY_RESOLVER,
        trace_recorder: DecisionTraceRecorder = NULL_DECISION_TRACE_RECORDER,
    ) -> None:
        self._resolver = resolver
        self.trace_recorder = trace_recorder
        self._resume_after_short_activity: dict | None = None

    def finalize(self, candidate: FinishedActivityCandidate) -> ShortActivityDecision:
        self.clear_pending_runtime_state()
        self._resume_after_short_activity = None

        if candidate.persisted_activity_id is not None:
            return self._record_finalize(
                candidate,
                ShortActivityDecision(
                action="close_persisted",
                target_activity_id=candidate.persisted_activity_id,
                absorbed_seconds=0,
                reason="persisted_current",
                ),
            )
        if candidate.seconds <= 0:
            return self._record_finalize(
                candidate,
                ShortActivityDecision(
                action="none",
                target_activity_id=None,
                absorbed_seconds=0,
                reason="zero_seconds",
                ),
            )
        if not can_merge_finished_short_activity(
            candidate.status,
            candidate.start_time,
            candidate.end_time,
        ):
            return self._record_finalize(
                candidate,
                ShortActivityDecision(
                action="drop",
                target_activity_id=None,
                absorbed_seconds=0,
                reason="not_mergeable_status_or_time",
                ),
            )

        target = activity_service.get_latest_closed_auto_normal_activity(
            after_time=session_boundary_service.latest_boundary_time()
        )
        if not target or not can_absorb_short_pending(target, candidate.start_time):
            return self._record_finalize(
                candidate,
                ShortActivityDecision(
                action="drop",
                target_activity_id=None,
                absorbed_seconds=0,
                reason="no_legal_anchor",
                ),
            )

        target_id = int(target["id"])
        activity_service.increment_activity_duration(target_id, candidate.seconds)
        target = dict(target)
        target["duration_seconds"] = int(target.get("duration_seconds") or 0) + candidate.seconds
        self._resume_after_short_activity = target
        return self._record_finalize(
            candidate,
            ShortActivityDecision(
            action="merge_to_anchor",
            target_activity_id=target_id,
            absorbed_seconds=candidate.seconds,
            reason="merged_to_latest_closed_anchor",
            ),
        )

    def resume_if_absorbed_activity_matches(
        self,
        *,
        payload: dict,
        signature: ActivitySignature,
    ) -> ResumeAnchorResult:
        target = self._resume_after_short_activity
        self._resume_after_short_activity = None
        if target and "resource" not in target:
            target = self._enrich_target_with_resource(target)
        if not target or self._resolver.signature_for_activity(target) != signature:
            return self._record_resume(
                ResumeAnchorResult(
                    ShortActivityDecision("none", None, 0, "no_resumable_anchor")
                ),
                signature,
            )
        start_time = str(target.get("start_time") or "")
        if not start_time:
            return self._record_resume(
                ResumeAnchorResult(
                    ShortActivityDecision("none", None, 0, "missing_anchor_start")
                ),
                signature,
            )
        target_id = int(target["id"])
        activity_service.reopen_activity(target_id)
        return self._record_resume(
            ResumeAnchorResult(
                ShortActivityDecision(
                action="resume_anchor",
                target_activity_id=target_id,
                absorbed_seconds=0,
                reason="incoming_resource_matches_absorbed_anchor",
                ),
                target=dict(target),
            ),
            signature,
        )

    def clear_pending_runtime_state(self) -> None:
        clear_runtime_activity_state(
            "short_activity_pending_clear",
            clear_snapshot=False,
            clear_pending=True,
            clear_ownership=False,
        )

    def clear(self) -> None:
        self._resume_after_short_activity = None
        self.clear_pending_runtime_state()

    def _enrich_target_with_resource(self, target: dict) -> dict:
        from ..resources.resource_identity import infer_resource_for_activity

        enriched = dict(target)
        enriched["resource"] = infer_resource_for_activity(enriched)
        return enriched

    def _record_finalize(
        self,
        candidate: FinishedActivityCandidate,
        decision: ShortActivityDecision,
    ) -> ShortActivityDecision:
        self.trace_recorder.record(
            CollectorDecisionTrace(
                observed_at=candidate.end_time,
                incoming_signature_hash=signature_hash(candidate.signature),
                status=candidate.status,
                end_reason=str(candidate.end_reason.value),
                elapsed_seconds=int(candidate.seconds),
                persisted_activity_id_before=candidate.persisted_activity_id,
                persisted_activity_id_after=candidate.persisted_activity_id,
                short_activity_action=decision.action,
                short_activity_reason=decision.reason,
                absorbed_seconds=decision.absorbed_seconds,
                target_activity_id=decision.target_activity_id,
            )
        )
        return decision

    def _record_resume(
        self,
        result: ResumeAnchorResult,
        signature: ActivitySignature,
    ) -> ResumeAnchorResult:
        self.trace_recorder.record(
            CollectorDecisionTrace(
                incoming_signature_hash=signature_hash(signature),
                short_activity_action=result.decision.action,
                short_activity_reason=result.decision.reason,
                absorbed_seconds=result.decision.absorbed_seconds,
                target_activity_id=result.decision.target_activity_id,
            )
        )
        return result


DEFAULT_SHORT_ACTIVITY_FINALIZER = ShortActivityFinalizer()
