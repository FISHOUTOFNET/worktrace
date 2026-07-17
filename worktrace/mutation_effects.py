"""Named mutation decorators backed by the domain unit of work."""

from __future__ import annotations

from .data_generation_repository import DataGenerationNamespace
from .domain_unit_of_work import (
    DomainUnitOfWork,
    current_domain_unit_of_work,
    domain_mutation,
    transactional_write,
)

MutationEffect = DataGenerationNamespace

report_structure_mutation = domain_mutation(
    DataGenerationNamespace.REPORT_STRUCTURE,
)
classification_catalog_mutation = domain_mutation(
    DataGenerationNamespace.REPORT_STRUCTURE,
    DataGenerationNamespace.CLASSIFICATION_CATALOG,
    DataGenerationNamespace.PRIVACY_CATALOG,
)
classification_index_mutation = domain_mutation(
    DataGenerationNamespace.CLASSIFICATION_CATALOG,
    DataGenerationNamespace.PRIVACY_CATALOG,
)
settings_mutation = domain_mutation(
    DataGenerationNamespace.SETTINGS,
)
privacy_settings_mutation = domain_mutation(
    DataGenerationNamespace.SETTINGS,
    DataGenerationNamespace.PRIVACY_CATALOG,
)
privacy_catalog_mutation = domain_mutation(
    DataGenerationNamespace.PRIVACY_CATALOG,
)
database_replacement_mutation = domain_mutation(
    DataGenerationNamespace.REPORT_STRUCTURE,
    DataGenerationNamespace.CLASSIFICATION_CATALOG,
    DataGenerationNamespace.SETTINGS,
    DataGenerationNamespace.PRIVACY_CATALOG,
    DataGenerationNamespace.DATABASE_REPLACEMENT,
)


def add_mutation_effects(*effects: DataGenerationNamespace | str) -> None:
    unit_of_work = current_domain_unit_of_work()
    if unit_of_work is None:
        raise RuntimeError("domain_unit_of_work_not_active")
    unit_of_work.add_effects(*effects)


__all__ = [
    "DomainUnitOfWork",
    "MutationEffect",
    "add_mutation_effects",
    "classification_catalog_mutation",
    "classification_index_mutation",
    "current_domain_unit_of_work",
    "database_replacement_mutation",
    "domain_mutation",
    "privacy_catalog_mutation",
    "privacy_settings_mutation",
    "report_structure_mutation",
    "settings_mutation",
    "transactional_write",
]
