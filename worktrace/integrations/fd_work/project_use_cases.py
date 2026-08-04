"""Atomic application workflows for FD Work-bound project identities."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Protocol
import secrets

from .binding_service import FDWorkBindingService
from .case_identity import case_label_hash, normalize_case_label
from .contracts import FDWorkEntryError
from .limits import FD_WORK_ADAPTER_CONTRACT_VERSION


ERROR_PERSISTENCE_UNCONFIRMED = "fd_work_persistence_unconfirmed"


class _SelectionClaim(Protocol):
    token: str
    label: str
    claim_id: str


class _SelectionService(Protocol):
    def claim_case_selection(
        self, selection_token: str | None, expected_label: str
    ) -> _SelectionClaim: ...

    def complete_case_selection_claim(self, claim: _SelectionClaim) -> None: ...

    def release_case_selection_claim(self, claim: _SelectionClaim) -> None: ...


class CreateFDWorkBoundProject:
    """Create a project and prove its durable FD Work binding before success."""

    def __init__(
        self,
        *,
        selection_service: _SelectionService,
        binding_service: FDWorkBindingService,
        create_project: Callable[[str, str, str], Mapping[str, Any]],
        project_reader: Callable[[int], Mapping[str, Any] | None],
        operation_id_factory: Callable[[], str] | None = None,
        clock: Callable[[], str] | None = None,
    ) -> None:
        self._selections = selection_service
        self._bindings = binding_service
        self._create_project = create_project
        self._project_reader = project_reader
        self._operation_id_factory = operation_id_factory or (
            lambda: secrets.token_urlsafe(24)
        )
        self._clock = clock or (
            lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
        )

    def execute(
        self,
        expected_label: str,
        description: str,
        language: str,
        selection_token: str | None,
    ) -> dict[str, Any]:
        claim = self._selections.claim_case_selection(
            selection_token, expected_label
        )
        operation_id = ""
        repository = self._bindings.repository
        pending_written = False
        project_written = False
        try:
            operation_id = str(self._operation_id_factory())
            repository.assert_writable()
            repository.begin_pending_operation(
                operation_id,
                "create",
                case_label_hash(claim.label),
                started_at=self._clock(),
            )
            pending_written = True
            created = dict(
                self._create_project(claim.label, description, language)
            )
            if created.get("ok") is not True:
                repository.delete_pending_operation(operation_id)
                pending_written = False
                self._selections.release_case_selection_claim(claim)
                return created
            project_written = True
            project_payload = created.get("project")
            project_id = (
                int(project_payload.get("id") or 0)
                if isinstance(project_payload, Mapping)
                else 0
            )
            project = self._read_project_identity(project_id, claim.label)
            project_created_at = self._created_at(project)
            repository.record_pending_project(
                operation_id,
                project_id,
                project_created_at,
                "project_created",
            )
            self._bindings.bind_project(
                project_id,
                claim.label,
                adapter_contract_version=FD_WORK_ADAPTER_CONTRACT_VERSION,
            )
            repository.set_pending_stage(operation_id, "binding_written")
            project = self._read_project_identity(project_id, claim.label)
            binding = repository.get_binding(project_id)
            name_hash = case_label_hash(claim.label)
            if (
                binding is None
                or binding.project_id != project_id
                or binding.project_created_at != self._created_at(project)
                or binding.bound_name_hash != name_hash
                or not self._bindings.is_project_bound(
                    project_id, claim.label, self._created_at(project)
                )
            ):
                raise FDWorkEntryError(ERROR_PERSISTENCE_UNCONFIRMED)
            repository.complete_pending_with_binding(
                operation_id,
                project_id=project_id,
                project_created_at=self._created_at(project),
                bound_name_hash=name_hash,
                adapter_contract_version=FD_WORK_ADAPTER_CONTRACT_VERSION,
            )
            pending_written = False
            self._selections.complete_case_selection_claim(claim)
            return {
                "ok": True,
                "project": self._public_project(project, project_payload),
                "fd_work_binding": {"bound": True, "verified": True},
            }
        except FDWorkEntryError as exc:
            if not project_written:
                self._release_unpersisted(claim, operation_id, pending_written)
            return {"ok": False, "error": self._public_error(exc.code)}
        except Exception:
            if not project_written:
                self._release_unpersisted(claim, operation_id, pending_written)
            return {"ok": False, "error": ERROR_PERSISTENCE_UNCONFIRMED}

    def _release_unpersisted(
        self, claim: _SelectionClaim, operation_id: str, pending_written: bool
    ) -> None:
        if pending_written:
            try:
                self._bindings.repository.delete_pending_operation(operation_id)
            except Exception:
                return
        self._selections.release_case_selection_claim(claim)

    def _read_project_identity(
        self, project_id: int, canonical_name: str
    ) -> Mapping[str, Any]:
        if project_id <= 0:
            raise FDWorkEntryError(ERROR_PERSISTENCE_UNCONFIRMED)
        project = self._project_reader(project_id)
        if (
            project is None
            or int(project.get("id") or 0) != project_id
            or normalize_case_label(project.get("name"))
            != normalize_case_label(canonical_name)
            or not self._created_at(project)
        ):
            raise FDWorkEntryError(ERROR_PERSISTENCE_UNCONFIRMED)
        return project

    @staticmethod
    def _created_at(project: Mapping[str, Any]) -> str:
        return str(project.get("created_at") or "")

    @staticmethod
    def _public_project(
        project: Mapping[str, Any], original: object
    ) -> dict[str, Any]:
        payload = dict(original) if isinstance(original, Mapping) else {}
        payload["id"] = int(project.get("id") or 0)
        payload["name"] = str(project.get("name") or "")
        for field in ("description", "language", "enabled", "archived"):
            if field in project and field not in payload:
                payload[field] = project[field]
        return payload

    @staticmethod
    def _public_error(code: str) -> str:
        if code in {
            "case_selection_required",
            "case_selection_expired",
            "case_selection_mismatch",
            "fd_work_busy",
        }:
            return code
        return ERROR_PERSISTENCE_UNCONFIRMED


class RebindFDWorkProject:
    """Rename and rebind a project, restoring its prior proven identity on failure."""

    def __init__(
        self,
        *,
        selection_service: _SelectionService,
        binding_service: FDWorkBindingService,
        update_project: Callable[[int, str, str, str], Mapping[str, Any]],
        project_reader: Callable[[int], Mapping[str, Any] | None],
        operation_id_factory: Callable[[], str] | None = None,
        clock: Callable[[], str] | None = None,
    ) -> None:
        self._selections = selection_service
        self._bindings = binding_service
        self._update_project = update_project
        self._project_reader = project_reader
        self._operation_id_factory = operation_id_factory or (
            lambda: secrets.token_urlsafe(24)
        )
        self._clock = clock or (
            lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
        )

    def execute(
        self,
        project_id: int,
        expected_label: str,
        description: str,
        language: str,
        selection_token: str | None,
    ) -> dict[str, Any]:
        claim = self._selections.claim_case_selection(
            selection_token, expected_label
        )
        operation_id = ""
        repository = self._bindings.repository
        try:
            operation_id = str(self._operation_id_factory())
            old_project = self._project_reader(int(project_id))
            if old_project is None or int(old_project.get("id") or 0) != int(project_id):
                raise FDWorkEntryError(ERROR_PERSISTENCE_UNCONFIRMED)
            old_project = dict(old_project)
            old_binding = repository.get_binding(int(project_id))
        except Exception:
            self._selections.release_case_selection_claim(claim)
            return {"ok": False, "error": ERROR_PERSISTENCE_UNCONFIRMED}
        pending_written = False
        project_written = False
        try:
            repository.assert_writable()
            repository.begin_pending_operation(
                operation_id,
                "rebind",
                case_label_hash(claim.label),
                previous_name_hash=case_label_hash(str(old_project.get("name") or "")),
                started_at=self._clock(),
            )
            pending_written = True
            updated = dict(
                self._update_project(
                    int(project_id), claim.label, description, language
                )
            )
            if updated.get("ok") is not True:
                repository.delete_pending_operation(operation_id)
                self._selections.release_case_selection_claim(claim)
                return updated
            project_written = True
            current = self._require_project_identity(
                int(project_id), claim.label, str(old_project.get("created_at") or "")
            )
            repository.record_pending_project(
                operation_id,
                int(project_id),
                str(current.get("created_at") or ""),
                "project_updated",
            )
            self._bindings.bind_project(
                int(project_id),
                claim.label,
                adapter_contract_version=FD_WORK_ADAPTER_CONTRACT_VERSION,
            )
            repository.set_pending_stage(operation_id, "binding_written")
            current = self._require_project_identity(
                int(project_id), claim.label, str(old_project.get("created_at") or "")
            )
            name_hash = case_label_hash(claim.label)
            binding = repository.get_binding(int(project_id))
            created_at = str(current.get("created_at") or "")
            if (
                binding is None
                or binding.project_created_at != created_at
                or binding.bound_name_hash != name_hash
                or not self._bindings.is_project_bound(
                    int(project_id), claim.label, created_at
                )
            ):
                raise FDWorkEntryError(ERROR_PERSISTENCE_UNCONFIRMED)
            repository.complete_pending_with_binding(
                operation_id,
                project_id=int(project_id),
                project_created_at=created_at,
                bound_name_hash=name_hash,
                adapter_contract_version=FD_WORK_ADAPTER_CONTRACT_VERSION,
            )
            pending_written = False
            self._selections.complete_case_selection_claim(claim)
            return {
                "ok": True,
                "project": CreateFDWorkBoundProject._public_project(current, updated.get("project")),
                "fd_work_binding": {"bound": True, "verified": True},
            }
        except Exception:
            if not project_written:
                if pending_written:
                    try:
                        repository.delete_pending_operation(operation_id)
                    except Exception:
                        return {"ok": False, "error": ERROR_PERSISTENCE_UNCONFIRMED}
                self._selections.release_case_selection_claim(claim)
                return {"ok": False, "error": ERROR_PERSISTENCE_UNCONFIRMED}
            restored = self._restore_previous_identity(
                operation_id, old_project, old_binding
            )
            if restored:
                self._selections.release_case_selection_claim(claim)
                return {"ok": False, "error": ERROR_PERSISTENCE_UNCONFIRMED}
            return {"ok": False, "error": "fd_work_inconsistent_state"}

    def _require_project_identity(
        self, project_id: int, name: str, created_at: str
    ) -> Mapping[str, Any]:
        project = self._project_reader(project_id)
        if (
            project is None
            or int(project.get("id") or 0) != project_id
            or normalize_case_label(project.get("name")) != normalize_case_label(name)
            or str(project.get("created_at") or "") != created_at
            or not created_at
        ):
            raise FDWorkEntryError(ERROR_PERSISTENCE_UNCONFIRMED)
        return project

    def _restore_previous_identity(
        self, operation_id: str, old_project: Mapping[str, Any], old_binding: Any
    ) -> bool:
        project_id = int(old_project.get("id") or 0)
        try:
            restored = self._update_project(
                project_id,
                str(old_project.get("name") or ""),
                str(old_project.get("description") or ""),
                str(old_project.get("language") or "中文"),
            )
            if restored.get("ok") is not True:
                return False
            current = self._require_project_identity(
                project_id,
                str(old_project.get("name") or ""),
                str(old_project.get("created_at") or ""),
            )
            if old_binding is None:
                self._bindings.repository.clear_binding(project_id)
            else:
                self._bindings.bind_project(
                    project_id,
                    str(old_project.get("name") or ""),
                    adapter_contract_version=old_binding.adapter_contract_version,
                )
            self._bindings.repository.delete_pending_operation(operation_id)
            restored_binding = self._bindings.repository.get_binding(project_id)
            if old_binding is None:
                return restored_binding is None
            return (
                restored_binding is not None
                and restored_binding.project_created_at == old_binding.project_created_at
                and restored_binding.bound_name_hash == old_binding.bound_name_hash
                and self._bindings.is_project_bound(
                    project_id,
                    str(old_project.get("name") or ""),
                    str(old_project.get("created_at") or ""),
                )
                and normalize_case_label(current.get("name"))
                == normalize_case_label(old_project.get("name"))
            )
        except Exception:
            return False


__all__ = [
    "CreateFDWorkBoundProject",
    "ERROR_PERSISTENCE_UNCONFIRMED",
    "RebindFDWorkProject",
]
