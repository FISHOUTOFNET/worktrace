"""Test-only reset and inspection helpers for the process write gate."""

from __future__ import annotations

from worktrace.write_gate import DATABASE_WRITE_GATE, WriteGatePhase


def write_gate_state() -> tuple[WriteGatePhase, str | None]:
    return DATABASE_WRITE_GATE.phase(), DATABASE_WRITE_GATE.recovery_block_reason()


def reset_global_write_gate_for_test() -> None:
    gate = DATABASE_WRITE_GATE
    with gate._lock:
        gate._phase = WriteGatePhase.OPEN
        gate._owner_thread_id = None
        gate._recovery_block_reason = None
        gate._generation += 1
        gate._thread_state.observed_generation = gate._generation
        gate._thread_state.recovery_write_depth = 0


__all__ = ["reset_global_write_gate_for_test", "write_gate_state"]
