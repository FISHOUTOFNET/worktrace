"""Collector command channel extension for process-lifecycle terminalization."""
from __future__ import annotations

from typing import Any

from .collector import (
    CollectorCommandState,
    CollectorControl,
)


class RuntimeCollectorControl(CollectorControl):
    """CollectorControl that can close unfinished commands on runtime exit.

    AppRuntime decides *when* the Collector lifecycle has terminated. The command
    channel remains the sole owner that mutates command state and publishes the
    terminal diagnostic.
    """

    def terminalize_unfinished(self, diagnostic: str) -> tuple[str, ...]:
        terminalized: list[str] = []
        reason = str(diagnostic or "collector_terminated")
        with self._lock:
            for command in self._commands.values():
                if command.state is CollectorCommandState.PENDING:
                    command.state = CollectorCommandState.CANCELLED
                    command.result = self._terminal_result(
                        command,
                        ok=False,
                        error=reason,
                        terminal_diagnostic=reason,
                    )
                    terminalized.append(command.command_id)
                    command.done_event.set()
                elif command.state in {
                    CollectorCommandState.TAKEN,
                    CollectorCommandState.UNKNOWN,
                }:
                    command.state = CollectorCommandState.COMPLETED
                    command.result = self._terminal_result(
                        command,
                        ok=False,
                        error=reason,
                        terminal_diagnostic=reason,
                    )
                    terminalized.append(command.command_id)
                    command.done_event.set()
            self._pending_ids.clear()
            self._wake_event.set()
        return tuple(terminalized)

    def _terminal_result(
        self,
        command: Any,
        *,
        ok: bool,
        error: str,
        terminal_diagnostic: str,
    ) -> dict[str, Any]:
        return {
            "ok": bool(ok),
            "error": str(error),
            "command_id": command.command_id,
            "command_kind": command.kind.value,
            "command_state": command.state.value,
            "command_state_unknown": False,
            "terminal_state": self._hold_state.value,
            "terminal_diagnostic": str(terminal_diagnostic),
        }


__all__ = ["RuntimeCollectorControl"]
