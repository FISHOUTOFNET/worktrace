"""Service package compatibility exports."""

from . import folder_index_service as folder_index_service
from . import folder_index_runtime_service as _folder_index_runtime_service

for _name in (
    "ensure_index_states_for_folder_rules",
    "rebuild_folder_index",
    "run_folder_index_worker",
    "validate_ready_indexes",
):
    setattr(
        folder_index_service,
        _name,
        getattr(_folder_index_runtime_service, _name),
    )

__all__ = ["folder_index_service"]
