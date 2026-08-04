"""Application-facing owner of durable FD Work project binding truth."""

from __future__ import annotations

from datetime import datetime, timezone
import threading
import time
from typing import Any, Callable, Iterable, Mapping

from .binding_repository import (
    FDWorkBindingRepository,
    FDWorkBindingStoreError,
    FDWorkProjectBinding,
    PendingBindingOperation,
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
        self._reconciliation_lock = threading.Lock()
        self._reconciliation_thread: threading.Thread | None = None
        self._reconciliation_result: dict[str, object] | None = None
        self._reconciliation_cancel = threading.Event()

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
            self.repository.clear_project_state(int(project_id))
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

    def start_pending_reconciliation(self) -> bool:
        with self._reconciliation_lock:
            if (
                self._reconciliation_thread is not None
                and self._reconciliation_thread.is_alive()
            ):
                return False
            self._reconciliation_cancel.clear()
            self._reconciliation_result = None
            worker = threading.Thread(
                target=self._run_startup_reconciliation,
                name="fd-work-binding-reconciliation",
                daemon=True,
            )
            self._reconciliation_thread = worker
            worker.start()
        return True

    def wait_for_pending_reconciliation(self, *, timeout_seconds: float) -> bool:
        with self._reconciliation_lock:
            worker = self._reconciliation_thread
        if worker is None:
            return True
        worker.join(timeout=max(0.0, min(2.0, float(timeout_seconds))))
        return not worker.is_alive()

    def cancel_pending_reconciliation(self, *, timeout_seconds: float) -> bool:
        self._reconciliation_cancel.set()
        return self.wait_for_pending_reconciliation(timeout_seconds=timeout_seconds)

    def pending_reconciliation_result(self) -> dict[str, object] | None:
        with self._reconciliation_lock:
            return (
                dict(self._reconciliation_result)
                if self._reconciliation_result is not None
                else None
            )

    def _run_startup_reconciliation(self) -> None:
        try:
            result = self.reconcile_pending_operations(
                max_operations=32,
                timeout_seconds=0.25,
            )
        except Exception:
            result = {
                "completed": (),
                "discarded": (),
                "errors": {"reconciliation": "recovery_internal_error"},
                "limit_reached": True,
            }
        with self._reconciliation_lock:
            self._reconciliation_result = result

    def reconcile_pending_operations(
        self,
        *,
        max_operations: int = 32,
        timeout_seconds: float = 0.25,
    ) -> dict[str, object]:
        limit = max(1, min(128, int(max_operations)))
        deadline = time.monotonic() + max(0.01, min(2.0, float(timeout_seconds)))
        completed: list[str] = []
        discarded: list[str] = []
        errors: dict[str, str] = {}
        try:
            pending_operations = self.repository.list_pending_operations()
            if not pending_operations:
                return {
                    "completed": (),
                    "discarded": (),
                    "errors": {},
                    "limit_reached": False,
                }
            projects = [
                project
                for project in self._project_list_reader()
                if int(project.get("id") or 0) > 0
            ]
            if self._reconciliation_cancel.is_set():
                return {
                    "completed": (),
                    "discarded": (),
                    "errors": {},
                    "limit_reached": bool(pending_operations),
                }
        except FDWorkBindingStoreError as exc:
            return {
                "completed": (),
                "discarded": (),
                "errors": {"sidecar": exc.code},
                "limit_reached": False,
            }
        except Exception:
            return {
                "completed": (),
                "discarded": (),
                "errors": {"reconciliation": "recovery_project_read_failed"},
                "limit_reached": True,
            }
        processed = 0
        for pending in pending_operations:
            if (
                processed >= limit
                or time.monotonic() >= deadline
                or self._reconciliation_cancel.is_set()
            ):
                break
            processed += 1
            if pending.stage.startswith("recovery_"):
                errors[pending.operation_id] = pending.stage
                continue
            try:
                candidates, unproven = self._pending_candidates(pending, projects)
                if not candidates:
                    if unproven:
                        self.repository.set_pending_stage(
                            pending.operation_id,
                            "recovery_identity_unproven",
                        )
                        errors[pending.operation_id] = "recovery_identity_unproven"
                    else:
                        self.repository.delete_pending_operation(pending.operation_id)
                        discarded.append(pending.operation_id)
                    continue
                if len(candidates) != 1:
                    self.repository.set_pending_stage(
                        pending.operation_id,
                        "recovery_ambiguous",
                    )
                    errors[pending.operation_id] = "recovery_ambiguous"
                    continue
                project = candidates[0]
                project_id = int(project.get("id") or 0)
                project_name = str(project.get("name") or "")
                project_created_at = self._created_at(project)
                if (
                    case_label_hash(project_name) != pending.intended_name_hash
                    or pending.project_created_at is not None
                    and pending.project_created_at != project_created_at
                ):
                    self.repository.clear_binding(project_id)
                    self.repository.set_pending_stage(
                        pending.operation_id,
                        "recovery_identity_mismatch",
                    )
                    errors[pending.operation_id] = "recovery_identity_mismatch"
                    continue
                binding = self.repository.get_binding(project_id)
                if binding is not None and self._binding_matches(
                    binding,
                    project_name,
                    project_created_at,
                ):
                    self.repository.delete_pending_operation(pending.operation_id)
                    completed.append(pending.operation_id)
                    continue
                if binding is not None:
                    self.repository.clear_binding(project_id)
                if pending.project_id is None:
                    self.repository.record_pending_project(
                        pending.operation_id,
                        project_id,
                        project_created_at or "",
                        "project_created",
                    )
                self.repository.complete_pending_with_binding(
                    pending.operation_id,
                    project_id=project_id,
                    project_created_at=project_created_at,
                    bound_name_hash=pending.intended_name_hash,
                    adapter_contract_version=self._adapter_contract_version,
                )
                completed.append(pending.operation_id)
            except FDWorkBindingStoreError as exc:
                errors[pending.operation_id] = exc.code
        return {
            "completed": tuple(completed),
            "discarded": tuple(discarded),
            "errors": errors,
            "limit_reached": processed < len(pending_operations),
        }

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
        self.cancel_pending_reconciliation(timeout_seconds=0.25)
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
        if binding.bound_name_hash != case_label_hash(project_name):
            return False
        if binding.project_created_at is not None:
            return binding.project_created_at == project_created_at
        return True

    def _pending_candidates(
        self,
        pending: PendingBindingOperation,
        projects: Iterable[Mapping[str, Any]],
    ) -> tuple[list[Mapping[str, Any]], bool]:
        if pending.project_id is not None:
            matches = [
                project
                for project in projects
                if int(project.get("id") or 0) == pending.project_id
            ]
            return matches, False
        hash_matches = [
            project
            for project in projects
            if case_label_hash(str(project.get("name") or ""))
            == pending.intended_name_hash
        ]
        proven = [
            project
            for project in hash_matches
            if self._created_after(
                self._created_at(project),
                pending.started_at,
            )
        ]
        return proven, bool(hash_matches and not proven)

    @staticmethod
    def _created_after(project_created_at: str | None, started_at: str) -> bool:
        if not project_created_at:
            return False
        try:
            created = datetime.fromisoformat(project_created_at.replace("Z", "+00:00"))
            started = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        except ValueError:
            return False
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        return created.astimezone(timezone.utc) >= started.astimezone(timezone.utc)

    @staticmethod
    def _created_at(project: Mapping[str, Any]) -> str | None:
        value = project.get("created_at")
        return str(value) if value is not None else None


__all__ = ["FDWorkBindingService"]
