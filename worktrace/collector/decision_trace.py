from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from typing import Any, Protocol

from ..contracts.live_display_contracts import CollectorDecisionTraceContract
from .transition_types import ActivitySignature


@dataclass(frozen=True)
class CollectorDecisionTrace:
    observed_at: str = ""
    previous_signature_hash: str = ""
    incoming_signature_hash: str = ""
    same_signature: bool = False
    status: str = ""
    end_reason: str = ""
    hard_boundary_reason: str = ""
    elapsed_seconds: int = 0
    persisted_activity_id_before: int | None = None
    persisted_activity_id_after: int | None = None
    snapshot_action: str = ""
    project_ownership_action: str = ""
    extra: dict[str, Any] | None = None

    def to_dict(self) -> CollectorDecisionTraceContract:
        payload = asdict(self)
        payload["extra"] = dict(self.extra or {})
        return payload


class DecisionTraceRecorder(Protocol):
    def record(self, trace: CollectorDecisionTrace) -> None:
        ...


class NullDecisionTraceRecorder:
    def record(self, trace: CollectorDecisionTrace) -> None:
        return None


class InMemoryDecisionTraceRecorder:
    def __init__(self) -> None:
        self.traces: list[CollectorDecisionTrace] = []

    def record(self, trace: CollectorDecisionTrace) -> None:
        self.traces.append(trace)


def signature_hash(signature: ActivitySignature | None) -> str:
    if not signature:
        return ""
    joined = "|".join(str(part) for part in signature)
    return hashlib.sha1(joined.encode("utf-8")).hexdigest()[:12]


NULL_DECISION_TRACE_RECORDER = NullDecisionTraceRecorder()
