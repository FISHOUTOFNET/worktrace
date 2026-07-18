from __future__ import annotations

import runpy
from pathlib import Path

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

# The repository is the sole runtime DML owner. Schema migration and secure
# replacement are explicit lifecycle exceptions, not competing command owners.
_owners["activity_inference_job"] = {
    "worktrace/schema_migrations.py",
    "worktrace/schema_migrations_history.py",
    "worktrace/services/activity_inference_job_repository.py",
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
pytestmark = _STATE["pytestmark"]

for _name, _value in _STATE.items():
    if _name.startswith("test_"):
        globals()[_name] = _value
