"""Atomic application workflow for permanent user-project deletion."""
from __future__ import annotations

from ..data_generation_repository import DataGenerationNamespace
from ..domain_unit_of_work import DomainUnitOfWork
from . import (
    assignment_command_service,
    history_mutation_job_query_service,
    project_service,
    rule_catalog_command_service,
    rule_catalog_query_service,
)
from .project_command_policy import ProjectLifecycleError
from .system_project_service import require_uncategorized_project_id


def delete_project(project_id: int) -> dict[str, int]:
    """Delete one user project and all mutable ownership in one root transaction."""

    requested_id = int(project_id)
    with DomainUnitOfWork(
        (
            DataGenerationNamespace.CLASSIFICATION_CATALOG,
            DataGenerationNamespace.REPORT_STRUCTURE,
        )
    ) as uow:
        conn = uow.connection
        project_service.require_mutable_user_project(conn, requested_id)
        rule_refs = rule_catalog_query_service.list_project_rule_refs_in_transaction(
            conn,
            requested_id,
        )
        if history_mutation_job_query_service.has_active_jobs_for_rule_refs_in_transaction(
            conn,
            rule_refs,
        ):
            raise ProjectLifecycleError("project_busy")

        uncategorized_id = require_uncategorized_project_id(conn)
        released = assignment_command_service.release_project_assignments_in_transaction(
            uow,
            conn,
            project_id=requested_id,
            uncategorized_project_id=uncategorized_id,
        )

        deleted_rules = 0
        for rule_type, rule_id in rule_refs:
            if not rule_catalog_command_service.delete_rule_in_transaction(
                uow,
                conn,
                rule_type,
                rule_id,
            ):
                raise ProjectLifecycleError("operation_failed")
            deleted_rules += 1

        project_service.delete_project_identity_in_transaction(
            uow,
            conn,
            requested_id,
        )
        return {
            "project_id": requested_id,
            "released_assignment_count": int(released),
            "deleted_rule_count": deleted_rules,
        }


__all__ = ["delete_project"]
