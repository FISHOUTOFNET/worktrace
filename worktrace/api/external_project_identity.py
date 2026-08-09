"""Narrow application port for optional external project identity."""

from __future__ import annotations

from typing import Any, Callable, Iterable, Mapping, Protocol


ProjectCreate = Callable[[str, str, str], dict[str, Any]]
ProjectUpdate = Callable[[int, str, str, str], dict[str, Any]]
ProjectReader = Callable[[int], Mapping[str, Any] | None]


class ProjectIdentityIntegrationCapability(Protocol):
    """Use-case boundary between project consumers and an identity integration."""

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


class ExternalBoundProjectIdentityCapability(Protocol):
    """Narrow durable-binding operations used by the optional identity adapter."""

    def list_bound_project_ids(self) -> set[int]: ...

    def create_bound_project(
        self,
        name: str,
        description: str,
        language: str,
        selection_token: str | None,
    ) -> dict[str, Any]: ...

    def rebind_project(
        self,
        project_id: int,
        name: str,
        description: str,
        language: str,
        selection_token: str | None,
    ) -> dict[str, Any]: ...

    def clear_project_identity(self, project_id: int) -> dict[str, Any]: ...

    def after_project_deleted(self, project_id: int) -> dict[str, Any]: ...


class OptionalProjectIdentityCapability:
    """Keep local projects available while external identity remains opt-in."""

    def __init__(
        self,
        *,
        external: ExternalBoundProjectIdentityCapability,
        create_project: ProjectCreate,
        update_project: ProjectUpdate,
        project_reader: ProjectReader,
    ) -> None:
        self._external = external
        self._create_project = create_project
        self._update_project = update_project
        self._project_reader = project_reader

    def list_project_identities(
        self, projects: Iterable[Mapping[str, Any]]
    ) -> list[dict[str, Any]]:
        result = [dict(project) for project in projects]
        try:
            bound_ids = self._external.list_bound_project_ids()
        except Exception:
            bound_ids = set()
        for project in result:
            project["external_identity_bound"] = (
                int(project.get("id") or 0) in bound_ids
            )
        return result

    def create_project(
        self,
        name: str,
        description: str,
        language: str,
        external_identity_proof: str | None,
    ) -> dict[str, Any]:
        if external_identity_proof is not None:
            return self._external_result(
                self._external.create_bound_project(
                    name,
                    description,
                    language,
                    external_identity_proof,
                )
            )
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
            return self._external_result(
                self._external.rebind_project(
                    int(project_id),
                    name,
                    description,
                    language,
                    external_identity_proof,
                )
            )

        current = self._project_reader(int(project_id))
        was_bound = self._is_bound(int(project_id))
        old_name = str(current.get("name") or "").strip() if current else ""
        new_name = str(name or "").strip()
        name_changed = bool(current) and old_name != new_name

        result = self._update_project(
            int(project_id),
            name,
            description,
            language,
        )
        if result.get("ok") is not True:
            return result

        binding: dict[str, Any] = {"bound": bool(was_bound and not name_changed)}
        if was_bound and name_changed:
            try:
                cleared = self._external.clear_project_identity(int(project_id))
            except Exception:
                cleared = {"ok": False}
            if cleared.get("ok") is not True:
                binding["warning"] = (
                    "项目已改为本地项目；旧外部关联已失效，清理将在后续恢复"
                )
        result["external_identity_binding"] = binding
        return result

    def clear_project_identity(self, project_id: int) -> dict[str, Any]:
        return self._external.clear_project_identity(int(project_id))

    def after_project_deleted(self, project_id: int) -> dict[str, Any]:
        return self._external.after_project_deleted(int(project_id))

    def _is_bound(self, project_id: int) -> bool:
        if project_id <= 0:
            return False
        try:
            return project_id in self._external.list_bound_project_ids()
        except Exception:
            return False

    @staticmethod
    def _external_result(result: dict[str, Any]) -> dict[str, Any]:
        result = dict(result)
        binding = result.pop("fd_work_binding", None)
        if not isinstance(binding, dict):
            binding = result.get("external_identity_binding")
        if isinstance(binding, dict):
            result["external_identity_binding"] = dict(binding)
        return result


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
    "ExternalBoundProjectIdentityCapability",
    "LocalProjectIdentityCapability",
    "OptionalProjectIdentityCapability",
    "ProjectCreate",
    "ProjectIdentityIntegrationCapability",
    "ProjectReader",
    "ProjectUpdate",
]
