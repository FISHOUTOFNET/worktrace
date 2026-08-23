"""Static post-commit lifecycle hooks for optional external state."""

from __future__ import annotations

from typing import Protocol


class ExternalStateLifecycleParticipant(Protocol):
    def after_local_data_cleared(self) -> None: ...

    def after_database_replaced(self) -> None: ...


class ApplicationDataLifecycle:
    """Invokes an explicit, fixed participant tuple after destructive commits."""

    def __init__(
        self, participants: tuple[ExternalStateLifecycleParticipant, ...]
    ) -> None:
        self._participants = participants

    def after_local_data_cleared(self) -> bool:
        succeeded = True
        for participant in self._participants:
            try:
                participant.after_local_data_cleared()
            except Exception:
                succeeded = False
        return succeeded

    def after_database_replaced(self) -> bool:
        succeeded = True
        for participant in self._participants:
            try:
                participant.after_database_replaced()
            except Exception:
                succeeded = False
        return succeeded


__all__ = ["ApplicationDataLifecycle", "ExternalStateLifecycleParticipant"]
