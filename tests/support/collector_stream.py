from __future__ import annotations

from dataclasses import dataclass, field

from worktrace.collector.activity_session_recorder import ActivitySessionRecorder
from worktrace.collector.decision_trace import InMemoryDecisionTraceRecorder
from worktrace.collector.state_machine import CollectorStateMachine
from worktrace.platforms.base import ActiveWindow
from worktrace.services import activity_service, runtime_activity_state_service


@dataclass
class CollectorStream:
    date: str = "2026-06-18"
    trace: InMemoryDecisionTraceRecorder = field(
        default_factory=InMemoryDecisionTraceRecorder
    )

    def __post_init__(self) -> None:
        recorder = ActivitySessionRecorder(decision_trace_recorder=self.trace)
        self.machine = CollectorStateMachine(recorder=recorder)

    def start(self, name: str, *, at: int) -> "CollectorStream":
        return self.switch(name, at=at)

    def same(self, name: str, *, at: int) -> "CollectorStream":
        return self.switch(name, at=at)

    def switch(self, name: str, *, at: int) -> "CollectorStream":
        self.machine.transition_to(
            "recording",
            ActiveWindow(name, f"{name.lower()}.exe", name),
            at_time=self.time(at),
        )
        return self

    def pause(self, *, at: int) -> "CollectorStream":
        self.machine.pause(at_time=self.time(at))
        return self

    def resume(self, name: str, *, at: int) -> "CollectorStream":
        return self.switch(name, at=at)

    def stop(self, *, at: int) -> "CollectorStream":
        self.machine.transition_to("stopped", at_time=self.time(at))
        return self

    def shutdown(self, *, at: int) -> "CollectorStream":
        self.machine._stop_recording_at_boundary(self.time(at), "shutdown")
        return self

    def idle(self, *, at: int) -> "CollectorStream":
        self.machine.transition_to("idle", at_time=self.time(at))
        return self

    def error(self, *, at: int) -> "CollectorStream":
        self.machine.transition_to("error", at_time=self.time(at))
        return self

    def excluded(self, *, at: int) -> "CollectorStream":
        self.machine.transition_to("excluded", at_time=self.time(at))
        return self

    def time(self, seconds: int) -> str:
        hour = 9 + seconds // 3600
        minute = (seconds % 3600) // 60
        second = seconds % 60
        return f"{self.date} {hour:02d}:{minute:02d}:{second:02d}"

    def rows(self) -> list[dict]:
        return activity_service.get_activities_by_date(self.date)

    def snapshot(self) -> dict:
        return (
            runtime_activity_state_service.sample_runtime_activity_state().snapshot
            or {}
        )
