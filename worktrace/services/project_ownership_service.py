"""Project ownership state machine — display-safe project label contract.

This service owns the **pure project-ownership state machine** and the
display-safe project label contract. It does NOT own DB open-row
lifecycle — that remains the sole responsibility of
``activity_lifecycle_service``.

The in-memory ownership state is held by ``AutoActivityRecorder`` (like
its other in-memory state: ``current_payload`` / ``current_signature``
/ ``current_start_time`` / ``persisted_activity_id`` /
``current_extra_seconds``). This service only provides the logic; the
recorder owns the state lifecycle.

Boundary rules
--------------
- This service lives in ``worktrace.services`` so it may import other
  services (``project_inference_service``, ``project_service``) and
  stdlib only. It MUST NOT be imported by ``worktrace.webview_ui.*``
  directly.
- It NEVER creates / closes / splits / reopens an ``activity_log`` row.
  DB open-row lifecycle is the exclusive responsibility of
  ``activity_lifecycle_service``.
- It NEVER auto-creates a suggested project.
- Candidate inference reuses ``project_inference_service`` — folder /
  keyword / suggested-project logic is never re-implemented here.
- It returns display-safe fields only (no raw ``window_title`` /
  ``file_path_hint`` / clipboard / note / SQL / traceback).

Ownership model
---------------
When a resource signature changes the recorder immediately switches the
current resource (resource identity is immediate). The *project
ownership*, however, enters a 30-second confirmation period:

- ``display_project`` continues to show the last confirmed project so
  the UI does not flap between projects on every window switch;
- ``candidate_project`` holds the newly-inferred project for the new
  resource;
- ``project_transition.pending`` is ``True`` until either 30 seconds
  elapse (candidate is confirmed) or a newer resource produces a
  candidate that matches the display project (pending is cancelled).

The 30-second project-ownership confirmation threshold
(``PROJECT_OWNERSHIP_CONFIRM_SECONDS``) is **orthogonal** to the
history-persistence threshold (``HISTORY_PERSIST_THRESHOLD_SECONDS``).
Both are 30 seconds today but are semantically independent. A clipboard
force-persist can turn a virtual activity into ``persisted_open`` before
the 30-second ownership threshold, but the live display still follows
``display_project`` until the pending window elapses or the activity ends.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any

from ..constants import (
    PROJECT_OWNERSHIP_CONFIRM_SECONDS,
    TIME_FORMAT,
    UNCATEGORIZED_PROJECT,
)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProjectLabel:
    """Display-safe project label.

    ``id`` is ``None`` for suggested-project names and uncategorized
    candidates (no concrete project row). ``source`` is one of:
    ``inherited`` / ``confirmed`` / ``manual`` / ``folder_rule`` /
    ``keyword_rule`` / ``suggested_project_name`` / ``uncategorized``.
    """

    name: str
    id: int | None = None
    description: str = ""
    source: str = "uncategorized"
    is_uncategorized: bool = False
    is_suggested_project: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "ProjectLabel | None":
        if not data or not isinstance(data, dict):
            return None
        return cls(
            name=str(data.get("name") or "").strip() or UNCATEGORIZED_PROJECT,
            id=int(data["id"]) if data.get("id") is not None else None,
            description=str(data.get("description") or ""),
            source=str(data.get("source") or "uncategorized"),
            is_uncategorized=bool(data.get("is_uncategorized", False)),
            is_suggested_project=bool(data.get("is_suggested_project", False)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "source": self.source,
            "is_uncategorized": self.is_uncategorized,
            "is_suggested_project": self.is_suggested_project,
        }


@dataclass(frozen=True)
class ProjectTransition:
    """Project ownership transition state.

    ``threshold_seconds`` gates the project-ownership confirmation window
    (``PROJECT_OWNERSHIP_CONFIRM_SECONDS``), NOT the history-persistence
    threshold (``HISTORY_PERSIST_THRESHOLD_SECONDS``). Both are 30 seconds
    today but are semantically independent — see
    ``worktrace.constants`` for details.
    """

    pending: bool = False
    started_at: str = ""
    elapsed_seconds: int = 0
    threshold_seconds: int = PROJECT_OWNERSHIP_CONFIRM_SECONDS
    from_project_id: int | None = None
    to_project_id: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "pending": self.pending,
            "started_at": self.started_at,
            "elapsed_seconds": self.elapsed_seconds,
            "threshold_seconds": self.threshold_seconds,
            "from_project_id": self.from_project_id,
            "to_project_id": self.to_project_id,
        }


@dataclass(frozen=True)
class ProjectOwnershipState:
    """Full ownership state held by ``AutoActivityRecorder``."""

    display_project: ProjectLabel | None = None
    candidate_project: ProjectLabel | None = None
    project_transition: ProjectTransition = field(default_factory=ProjectTransition)
    last_confirmed_project: ProjectLabel | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "display_project": self.display_project.to_dict() if self.display_project else None,
            "candidate_project": self.candidate_project.to_dict() if self.candidate_project else None,
            "project_transition": self.project_transition.to_dict(),
            "last_confirmed_project": (
                self.last_confirmed_project.to_dict() if self.last_confirmed_project else None
            ),
        }


# ---------------------------------------------------------------------------
# Label helpers
# ---------------------------------------------------------------------------


def uncategorized_label() -> ProjectLabel:
    """Return the canonical uncategorized project label."""
    return ProjectLabel(
        name=UNCATEGORIZED_PROJECT,
        id=None,
        description="",
        source="uncategorized",
        is_uncategorized=True,
        is_suggested_project=False,
    )


def labels_equal(a: ProjectLabel | None, b: ProjectLabel | None) -> bool:
    """Return ``True`` when two labels refer to the same project.

    Comparison is by concrete ``id`` when both have one, otherwise by
    casefolded ``name``. Two uncategorized labels are always equal.
    """
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    if a.id is not None and b.id is not None:
        return int(a.id) == int(b.id)
    return a.name.strip().casefold() == b.name.strip().casefold()


def candidate_project_for_activity(
    activity: dict | None,
    resource: Any = None,
) -> ProjectLabel:
    """Compute the candidate project label for a new resource.

    Reuses ``project_inference_service.candidate_project_label_for_activity``
    so folder / keyword / suggested-project inference has a single
    implementation. Returns the uncategorized label when inference
    yields nothing (e.g. system status or empty activity).
    """
    if activity is None:
        return uncategorized_label()
    status = str(activity.get("status") or "")
    if status and status not in {"normal"}:
        return uncategorized_label()
    from .project_inference_service import candidate_project_label_for_activity

    label_dict = candidate_project_label_for_activity(activity, _resource_dict(resource))
    return ProjectLabel.from_dict(label_dict) or uncategorized_label()


def _resource_dict(resource: Any) -> dict | None:
    """Coerce a ``DetectedResource`` or dict into a plain resource dict."""
    if resource is None:
        return None
    if isinstance(resource, dict):
        return resource
    # DetectedResource dataclass-like
    try:
        return {
            "resource_kind": resource.resource_kind,
            "resource_subtype": resource.resource_subtype,
            "display_name": resource.display_name,
            "identity_key": resource.identity_key,
            "is_anchor": int(resource.is_anchor),
            "app_name": resource.app_name,
            "process_name": resource.process_name,
            "window_title": resource.window_title,
            "path_hint": resource.path_hint,
            "uri_host": resource.uri_host,
        }
    except AttributeError:
        return None


# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------


def _parse_time(value: str) -> datetime:
    return datetime.strptime(value, TIME_FORMAT)


def _seconds_between(start_time: str, end_time: str) -> int:
    try:
        return max(0, int((_parse_time(end_time) - _parse_time(start_time)).total_seconds()))
    except (ValueError, TypeError):
        return 0


def begin_ownership_for_new_resource(
    state: ProjectOwnershipState | None,
    candidate: ProjectLabel,
    at_time: str,
    threshold_seconds: int = PROJECT_OWNERSHIP_CONFIRM_SECONDS,
) -> ProjectOwnershipState:
    """Begin ownership for a brand-new resource signature.

    Called by ``AutoActivityRecorder`` when the resource signature
    changes (immediate resource switch). The candidate is computed from
    the new resource; the display project inherits the last confirmed
    project when the candidate differs (entering a 30-second pending
    window), or matches the candidate immediately when they are equal.

    When there is no prior confirmed project (first normal activity of
    a session) the display project is set directly to the candidate —
    no pending window is needed.
    """
    last_confirmed = state.last_confirmed_project if state else None
    no_transition = ProjectTransition(
        pending=False,
        threshold_seconds=threshold_seconds,
    )
    if last_confirmed is None:
        return ProjectOwnershipState(
            display_project=candidate,
            candidate_project=candidate,
            project_transition=no_transition,
            last_confirmed_project=candidate,
        )
    if labels_equal(candidate, last_confirmed):
        return ProjectOwnershipState(
            display_project=last_confirmed,
            candidate_project=candidate,
            project_transition=no_transition,
            last_confirmed_project=last_confirmed,
        )
    transition = ProjectTransition(
        pending=True,
        started_at=at_time,
        elapsed_seconds=0,
        threshold_seconds=threshold_seconds,
        from_project_id=last_confirmed.id,
        to_project_id=candidate.id,
    )
    return ProjectOwnershipState(
        display_project=last_confirmed,
        candidate_project=candidate,
        project_transition=transition,
        last_confirmed_project=last_confirmed,
    )


def advance_ownership(
    state: ProjectOwnershipState | None,
    at_time: str,
) -> ProjectOwnershipState | None:
    """Advance the pending timer on an unchanged resource signature.

    Called by ``AutoActivityRecorder`` on every observe where the
    signature has NOT changed. When the pending window has elapsed
    (``>= threshold_seconds``), the candidate is confirmed and becomes
    the new display project. Otherwise the elapsed counter is updated
    and the display project stays as the inherited last-confirmed
    project.

    Returns ``state`` unchanged when there is no pending transition
    (including when ``state`` is ``None``).
    """
    if state is None:
        return None
    transition = state.project_transition
    if transition is None or not transition.pending:
        return state
    elapsed = _seconds_between(transition.started_at, at_time)
    if elapsed >= transition.threshold_seconds:
        candidate = state.candidate_project or uncategorized_label()
        return ProjectOwnershipState(
            display_project=candidate,
            candidate_project=candidate,
            project_transition=replace(transition, pending=False, elapsed_seconds=elapsed),
            last_confirmed_project=candidate,
        )
    return ProjectOwnershipState(
        display_project=state.display_project,
        candidate_project=state.candidate_project,
        project_transition=replace(transition, elapsed_seconds=elapsed),
        last_confirmed_project=state.last_confirmed_project,
    )


def clear_ownership_state() -> ProjectOwnershipState:
    """Return a fresh empty ownership state.

    Used at session boundaries (pause / stop / midnight split / recovery
    / time jump) so the previous session's display project is NOT
    inherited into the new session.
    """
    return ProjectOwnershipState()


def empty_state() -> ProjectOwnershipState:
    """Alias for :func:`clear_ownership_state`."""
    return ProjectOwnershipState()


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


def serialize_project_ownership(state: ProjectOwnershipState | None) -> dict[str, Any]:
    """Serialize the ownership state into a display-safe JSON dict.

    Returns a dict with ``display_project`` / ``candidate_project`` /
    ``project_transition`` keys (each ``None`` / empty when the state
    is empty). Safe to embed in the current-activity snapshot and
    surface to the frontend via the live projection.
    """
    if state is None:
        return {
            "display_project": None,
            "candidate_project": None,
            "project_transition": ProjectTransition().to_dict(),
        }
    return state.to_dict()


__all__ = [
    "ProjectLabel",
    "ProjectOwnershipState",
    "ProjectTransition",
    "advance_ownership",
    "begin_ownership_for_new_resource",
    "candidate_project_for_activity",
    "clear_ownership_state",
    "empty_state",
    "labels_equal",
    "serialize_project_ownership",
    "uncategorized_label",
]
