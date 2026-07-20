"""Test-only reset and inspection helpers for the process write gate."""

from __future__ import annotations

from worktrace.write_gate import DATABASE_WRITE_GATE, WriteGatePhase


def write_gate_state() -> tuple[WriteGatePhase, str | None]:
    return DATABASE_WRITE_GATE.phase(), DATABASE_WRITE_GATE.recovery_block_reason()


def reset_global_write_gate_for_test() -> None:
    gate = DATABASE_WRITE_GATE
    with gate._lock:  # noqa: SLF001 - test-only global isolation
        gate._phase = WriteGatePhase.OPEN  # noqa: SLF001
        gate._owner_thread_id = None  # noqa: SLF001
        gate._recovery_block_reason = None  # noqa: SLF001
        gate._generation += 1  # noqa: SLF001
        gate._thread_state.observed_generation = gate._generation  # noqa: SLF001
        gate._thread_state.recovery_write_depth = 0  # noqa: SLF001


__all__ = ["reset_global_write_gate_for_test", "write_gate_state"]
