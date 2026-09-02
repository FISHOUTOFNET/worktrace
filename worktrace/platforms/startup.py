"""Platform-neutral launch-at-login repair contracts."""
from __future__ import annotations

from enum import Enum
from typing import Protocol, runtime_checkable


class LaunchAtLoginRepairOutcome(str, Enum):
    UNSUPPORTED = "unsupported"
    DISABLED = "disabled"
    CANONICAL = "canonical"
    REPAIRED = "repaired"


class LaunchAtLoginRepairError(RuntimeError):
    """Classified repair failure safe for runtime retry policy."""

    def __init__(
        self,
        code: str,
        *,
        retryable: bool,
        native_codes: tuple[int, ...] = (),
        operation: str = "repair",
    ) -> None:
        normalized = str(code or "launch_at_login_repair_failed").strip()
        super().__init__(normalized)
        self.code = normalized
        self.retryable = bool(retryable)
        self.native_codes = tuple(int(value) for value in native_codes)
        self.operation = str(operation or "repair")


@runtime_checkable
class LaunchAtLoginRepairCapability(Protocol):
    def repair_once(self) -> LaunchAtLoginRepairOutcome: ...


__all__ = [
    "LaunchAtLoginRepairCapability",
    "LaunchAtLoginRepairError",
    "LaunchAtLoginRepairOutcome",
]
