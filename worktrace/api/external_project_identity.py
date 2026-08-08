"""Narrow application port for optional external project identity."""

from __future__ import annotations

from typing import Any, Callable, Iterable, Mapping, Protocol


ProjectCreate = Callable[[str, str, str], dict[str, Any]]
ProjectUpdate = Callable[[int, str, str, str], dict[str, Any]]
ProjectReader = Callable[[int], Mapping[str, Any] | None]


class ProjectIdentityIntegrationCapability(Protocol):
    """Use-case boundary between Project Rules and an identity integration."""

    def list_project_identities(
        self, projects: Iterable[Mapping[str, Any]]
    ) -> list[dict[str, Any]]: ...

    def create_project(
        self,
        name: str,
        description: str,
        language: str,
        external_identity_proof: str | None,
    ) -> dict[str, Any]: ...

    def update_project(
        self,
        project_id: int,
        name: str,
        description: str,
        language: str,
        external_identity_proof: str | None,
    ) -> dict[str, Any]: ...

    def clear_project_identity(self, project_id: int) -> dict[str, Any]: ...

    def after_project_deleted(self, project_id: int) -> dict[str, Any]: ...


class LocalProjectIdentityCapability:
    """Explicit integration-off capability used by tests and local-only composition."""

    def __init__(
        self,
        *,
        create_project: ProjectCreate,
        update_project: ProjectUpdate,
    ) -> None:
        self._create_project = create_project
        self._update_project = update_project

    def list_project_identities(
        self, projects: Iterable[Mapping[str, Any]]
    ) -> list[dict[str, Any]]:
        return [dict(project) for project in projects]

    def create_project(
        self,
        name: str,
        description: str,
        language: str,
        external_identity_proof: str | None,
    ) -> dict[str, Any]:
        if external_identity_proof is not None:
            return {"ok": False, "error": "external_identity_unavailable"}
        result = self._create_project(name, description, language)
        if result.get("ok") is True:
            result["external_identity_binding"] = {"bound": False}
        return result

    def update_project(
        self,
        project_id: int,
        name: str,
        description: str,
        language: str,
        external_identity_proof: str | None,
    ) -> dict[str, Any]:
        if external_identity_proof is not None:
            return {"ok": False, "error": "external_identity_unavailable"}
        result = self._update_project(project_id, name, description, language)
        if result.get("ok") is True:
            result["external_identity_binding"] = {"bound": False}
        return result

    @staticmethod
    def clear_project_identity(project_id: int) -> dict[str, Any]:
        del project_id
        return {"ok": True, "external_identity_binding": {"bound": False}}

    @staticmethod
    def after_project_deleted(project_id: int) -> dict[str, Any]:
        del project_id
        return {"bound": False}


__all__ = [
    "LocalProjectIdentityCapability",
    "ProjectCreate",
    "ProjectIdentityIntegrationCapability",
    "ProjectReader",
    "ProjectUpdate",
]
