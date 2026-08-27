"""Collector command channel extension for process-lifecycle terminalization."""
from __future__ import annotations

from typing import Any

from .collector import (
    CollectorCommandKind,
    CollectorCommandState,
    CollectorControl,
    CollectorHoldState,
)

_MAX_RETAINED_TERMINAL_COMMANDS = 64
_TERMINAL_COMMAND_STATES = frozenset(
    {
        CollectorCommandState.COMPLETED,
        CollectorCommandState.CANCELLED,
    }
)


class RuntimeCollectorControl(CollectorControl):
    """Production command channel with lifecycle finalization and bounded history.

    AppRuntime decides *when* the Collector lifecycle has terminated. The command
    channel remains the sole owner that mutates command state and publishes the
    terminal diagnostic. Pending, taken and unknown commands are never evicted;
    only completed/cancelled diagnostic history is retained with a small bound.
    """

    def _request(
        self,
        kind: CollectorCommandKind,
        timeout_seconds: float,
    ) -> dict[str, Any]:
        result = super()._request(kind, timeout_seconds)
        with self._lock:
            self._mark_terminal_recent_locked(str(result.get("command_id") or ""))
            self._prune_terminal_commands_locked()
        return result

    def _complete(
        self,
        command_id: str,
        kind: CollectorCommandKind,
        result: dict[str, Any],
        *,
        terminal_state: CollectorHoldState,
    ) -> bool:
        completed = super()._complete(
            command_id,
            kind,
            result,
            terminal_state=terminal_state,
        )
        if completed:
            with self._lock:
                self._mark_terminal_recent_locked(command_id)
                self._prune_terminal_commands_locked()
        return completed

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
            for command_id in terminalized:
                self._mark_terminal_recent_locked(command_id)
            self._prune_terminal_commands_locked()
            self._wake_event.set()
        return tuple(terminalized)

    def _mark_terminal_recent_locked(self, command_id: str) -> None:
        command = self._commands.get(str(command_id or ""))
        if command is None or command.state not in _TERMINAL_COMMAND_STATES:
            return
        self._commands.pop(command.command_id, None)
        self._commands[command.command_id] = command

    def _prune_terminal_commands_locked(self) -> None:
        terminal_ids = [
            command_id
            for command_id, command in self._commands.items()
            if command.state in _TERMINAL_COMMAND_STATES
        ]
        excess = len(terminal_ids) - _MAX_RETAINED_TERMINAL_COMMANDS
        for command_id in terminal_ids[: max(0, excess)]:
            self._commands.pop(command_id, None)

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