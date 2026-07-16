"""Project ownership state — internal candidate and official display label."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..constants import UNCATEGORIZED_PROJECT
from .project_attribution_policy import is_official_project_source


@dataclass(frozen=True)
class ProjectLabel:
    """Display-safe project label.

    ``id`` is ``None`` for suggested-project names and uncategorized
    candidates. Only manual/folder/keyword sources are formal display projects.
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
class ProjectOwnershipState:
    """Internal ownership state held by ``ActivitySessionRecorder``.

    ``candidate_project`` remains internal inference state. Runtime snapshots and
    page DTOs expose only ``display_project``.
    """

    display_project: ProjectLabel | None = None
    candidate_project: ProjectLabel | None = None


def uncategorized_label() -> ProjectLabel:
    return ProjectLabel(
        name=UNCATEGORIZED_PROJECT,
        id=None,
        description="",
        source="uncategorized",
        is_uncategorized=True,
        is_suggested_project=False,
    )


def labels_equal(a: ProjectLabel | None, b: ProjectLabel | None) -> bool:
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
    if activity is None:
        return uncategorized_label()
    status = str(activity.get("status") or "")
    if status and status != "normal":
        return uncategorized_label()
    from .project_inference_service import candidate_project_label_for_activity

    label_dict = candidate_project_label_for_activity(activity, _resource_dict(resource))
    return ProjectLabel.from_dict(label_dict) or uncategorized_label()


def _resource_dict(resource: Any) -> dict | None:
    if resource is None:
        return None
    if isinstance(resource, dict):
        return resource
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


def _is_official_label(label: ProjectLabel | None) -> bool:
    return bool(label is not None and is_official_project_source(label.source))


def begin_ownership_for_new_resource(candidate: ProjectLabel) -> ProjectOwnershipState:
    """Assign the formal display project immediately for an official candidate."""

    if _is_official_label(candidate):
        return ProjectOwnershipState(
            display_project=candidate,
            candidate_project=candidate,
        )
    return ProjectOwnershipState(
        display_project=uncategorized_label(),
        candidate_project=candidate,
    )


def clear_ownership_state() -> ProjectOwnershipState:
    return ProjectOwnershipState()


__all__ = [
    "ProjectLabel",
    "ProjectOwnershipState",
    "begin_ownership_for_new_resource",
    "candidate_project_for_activity",
    "clear_ownership_state",
    "labels_equal",
    "uncategorized_label",
]
