from __future__ import annotations

import runpy
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.contract]

_STATE = runpy.run_path(
    str(Path(__file__).with_name("_architecture_owner_governance_base.py"))
)

_owners = _STATE["_GENERATION_DML_OWNERS"]
for _table_owners in _owners.values():
    # Published migration history is an explicit schema-lifecycle owner, never
    # a runtime command owner. It may contain old writes for any migrated table.
    _table_owners.add("worktrace/schema_migrations_history.py")
    if "worktrace/services/secure_backup_service.py" in _table_owners:
        _table_owners.add("worktrace/services/secure_backup_core.py")

# v10-to-v11 is the one published migration that removes the legacy assignment
# sentinel. Runtime assignment writes remain owned only by the command service.
_owners["activity_project_assignment"].add("worktrace/schema_migrations.py")

# The repository is the sole runtime DML owner. Schema migration, whole-database
# maintenance, and secure replacement are explicit lifecycle exceptions.
_owners["activity_inference_job"] = {
    "worktrace/schema_migrations.py",
    "worktrace/schema_migrations_history.py",
    "worktrace/services/activity_inference_job_repository.py",
    "worktrace/services/database_maintenance_service.py",
    "worktrace/services/secure_backup_core.py",
    "worktrace/services/secure_backup_service.py",
}

_original_dynamic_dml = _STATE["_dynamic_dml"]


def _dynamic_dml(path):
    statements = _original_dynamic_dml(path)
    relative = path.relative_to(_STATE["ROOT"]).as_posix()
    if relative != "worktrace/services/secure_backup_core.py":
        return statements
    replacement_tables = set(_owners) - {"history_mutation_job"}
    return [
        (line, operation, tables or replacement_tables)
        for line, operation, tables in statements
    ]


_STATE["_dynamic_dml"] = _dynamic_dml

for _name, _value in _STATE.items():
    if _name.startswith("test_"):
        globals()[_name] = _value


def _generation_owner_offenders() -> list[str | None]:
    offenders: list[str] = []
    covered: set[str] = set()
    for path in _STATE["_python_files"]():
        relative = path.relative_to(_STATE["ROOT"]).as_posix()
        for line, operation, table in _STATE["_literal_dml"](path):
            owners = _owners.get(table)
            if owners is None:
                continue
            covered.add(table)
            if relative not in owners:
                offenders.append(f"{relative}:{line}:{operation}:{table}")
        for line, operation, tables in _dynamic_dml(path):
            if not tables:
                offenders.append(f"{relative}:{line}:{operation}:dynamic")
                continue
            for table in tables:
                covered.add(table)
                if relative not in _owners[table]:
                    offenders.append(f"{relative}:{line}:{operation}:{table}")
    for table in sorted(set(_owners) - covered):
        offenders.append(f"missing:{table}")
    return sorted(set(offenders)) or [None]


_OWNER_OFFENDERS = _generation_owner_offenders()


@pytest.mark.parametrize(
    "offender",
    _OWNER_OFFENDERS,
    ids=lambda value: "clean" if value is None else str(value),
)
def test_generation_backed_dml_stays_with_canonical_command_owners(
    offender: str | None,
) -> None:
    assert offender is None, offender


def test_historical_migration_owner_is_lifecycle_scoped() -> None:
    assert all(
        "worktrace/schema_migrations_history.py" in owners
        for owners in _owners.values()
    )
    assert _owners["activity_inference_job"] >= {
        "worktrace/services/activity_inference_job_repository.py",
        "worktrace/services/database_maintenance_service.py",
        "worktrace/schema_migrations.py",
    }
