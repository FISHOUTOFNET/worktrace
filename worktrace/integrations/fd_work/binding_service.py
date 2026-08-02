"""Application-facing owner of durable FD Work project binding truth."""

from __future__ import annotations

from typing import Any, Callable, Iterable, Mapping

from .binding_repository import (
    FDWorkBindingRepository,
    FDWorkBindingStoreError,
    FDWorkProjectBinding,
)
from .case_identity import case_label_hash, normalize_case_label
from .contracts import FDWorkEntryError
from .limits import FD_WORK_ADAPTER_CONTRACT_VERSION


class FDWorkBindingService:
    def __init__(
        self,
        repository: FDWorkBindingRepository,
        *,
        project_reader: Callable[[int], Mapping[str, Any] | None],
        project_list_reader: Callable[[], Iterable[Mapping[str, Any]]],
        adapter_contract_version: int = FD_WORK_ADAPTER_CONTRACT_VERSION,
    ) -> None:
        self.repository = repository
        self._project_reader = project_reader
        self._project_list_reader = project_list_reader
        self._adapter_contract_version = int(adapter_contract_version)
        self._invalidated_project_ids: set[int] = set()
        self._all_invalidated = False

    def bind_project(
        self,
        project_id: int,
        project_name: str,
        *,
        adapter_contract_version: int | None = None,
    ) -> None:
        project = self._project_reader(int(project_id))
        if project is None or int(project.get("id") or 0) != int(project_id):
            raise FDWorkEntryError("project_not_fd_work_bound")
        normalized = normalize_case_label(project_name)
        if not normalized or normalize_case_label(project.get("name")) != normalized:
            raise FDWorkEntryError("case_selection_mismatch")
        self._invalidated_project_ids.add(int(project_id))
        try:
            self.repository.clear_binding(int(project_id))
            self.repository.bind_project(
                int(project_id),
                self._created_at(project),
                case_label_hash(normalized),
                int(adapter_contract_version or self._adapter_contract_version),
            )
        except FDWorkBindingStoreError as exc:
            raise FDWorkEntryError(exc.code) from exc
        except Exception as exc:
            code = "binding_store_busy" if "busy" in str(exc).casefold() else "binding_store_unavailable"
            raise FDWorkEntryError(code) from exc
        self._invalidated_project_ids.discard(int(project_id))

    def clear_binding(self, project_id: int) -> None:
        self._invalidated_project_ids.add(int(project_id))
        try:
            self.repository.clear_binding(int(project_id))
        except FDWorkBindingStoreError as exc:
            raise FDWorkEntryError(exc.code) from exc

    def is_project_bound(
        self,
        project_id: int,
        project_name: str | None = None,
        project_created_at: str | None = None,
    ) -> bool:
        project_id = int(project_id)
        if self._all_invalidated or project_id in self._invalidated_project_ids:
            return False
        try:
            binding = self.repository.get_binding(project_id)
        except FDWorkBindingStoreError:
            return False
        if binding is None:
            return False
        if project_name is None:
            project = self._project_reader(project_id)
            if project is None:
                return False
            project_name = str(project.get("name") or "")
            project_created_at = self._created_at(project)
        return self._binding_matches(
            binding,
            project_name,
            project_created_at,
        )

    def require_project_binding(self, project_id: int, project_name: str) -> None:
        project = self._project_reader(int(project_id))
        if project is None or not self.is_project_bound(
            int(project_id),
            project_name,
            self._created_at(project),
        ):
            raise FDWorkEntryError("project_not_fd_work_bound")

    def list_bound_project_ids(self) -> set[int]:
        return self.reconcile_bindings()

    def reconcile_bindings(self) -> set[int]:
        if self._all_invalidated:
            return set()
        try:
            bindings = self.repository.list_bindings()
        except FDWorkBindingStoreError:
            return set()
        projects = {
            int(project.get("id") or 0): project
            for project in self._project_list_reader()
            if int(project.get("id") or 0) > 0
        }
        valid: set[int] = set()
        stale: set[int] = set()
        for binding in bindings:
            project = projects.get(binding.project_id)
            if (
                project is not None
                and binding.project_id not in self._invalidated_project_ids
                and self._binding_matches(
                    binding,
                    str(project.get("name") or ""),
                    self._created_at(project),
                )
            ):
                valid.add(binding.project_id)
            else:
                stale.add(binding.project_id)
        if stale:
            try:
                self.repository.clear_bindings(stale)
            except FDWorkBindingStoreError:
                valid.difference_update(stale)
        return valid

    def clear_all_bindings(self, *, delete_database: bool = False) -> None:
        self._all_invalidated = True
        self._invalidated_project_ids.clear()
        try:
            if delete_database:
                self.repository.delete_database()
            else:
                self.repository.clear_all()
        except FDWorkBindingStoreError as exc:
            raise FDWorkEntryError(exc.code) from exc
        self._all_invalidated = False

    def _binding_matches(
        self,
        binding: FDWorkProjectBinding,
        project_name: str,
        project_created_at: str | None,
    ) -> bool:
        if binding.adapter_contract_version != self._adapter_contract_version:
            return False
        if binding.bound_name_hash != case_label_hash(project_name):
            return False
        if binding.project_created_at is not None:
            return binding.project_created_at == project_created_at
        return True

    @staticmethod
    def _created_at(project: Mapping[str, Any]) -> str | None:
        value = project.get("created_at")
        return str(value) if value is not None else None


__all__ = ["FDWorkBindingService"]
