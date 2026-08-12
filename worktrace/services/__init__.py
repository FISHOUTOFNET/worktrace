"""Service package exports with runtime-safe derived-state orchestration."""

# AppRuntime and other package-level consumers receive the guarded folder-index
# service. Direct imports of ``worktrace.services.folder_index_service`` remain
# available as the low-level durable scanner/index writer.
from . import folder_index_runtime_service as folder_index_service

__all__ = ["folder_index_service"]
