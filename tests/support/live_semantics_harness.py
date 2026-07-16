from __future__ import annotations

from dataclasses import dataclass

from tests.support.activity_factory import create_open_activity
from worktrace.collector.state_machine import CollectorStateMachine
from worktrace.constants import STATUS_NORMAL
from worktrace.platforms.base import ActiveWindow
from worktrace.services import (
    activity_lifecycle_service,
    activity_service,
    runtime_activity_state_service,
    timeline_service,
)
from worktrace.webview_ui.bridge import WebViewBridge


@dataclass
class LiveSemanticsHarness:
    monkeypatch: object
    date: str = "2026-06-18"

    def __post_init__(self) -> None:
        self.machine = CollectorStateMachine()
        self.bridge = WebViewBridge()
        self.monkeypatch.setattr(
            timeline_service,
            "get_default_report_date",
            lambda: self.date,
        )

    def window(self, name: str) -> ActiveWindow:
        return ActiveWindow(name, f"{name.lower()}.exe", name)

    def record(self, name: str, at: str) -> None:
        self.machine.transition_to(
            "recording",
            self.window(name),
            at_time=self.at(at),
        )

    def pause(self, at: str) -> None:
        self.machine.pause(at_time=self.at(at))

    def stop(self, at: str) -> None:
        self.machine.transition_to("stopped", at_time=self.at(at))

    def status(self, state: str, at: str) -> None:
        self.machine.transition_to(state, at_time=self.at(at))

    def at(self, hhmmss: str) -> str:
        return f"{self.date} {hhmmss}"

    def rows(self) -> list[dict]:
        return activity_service.get_activities_by_date(self.date)

    def snapshot(self) -> dict:
        return (
            runtime_activity_state_service.sample_runtime_activity_state().snapshot
            or {}
        )

    def set_snapshot(self, snapshot: dict | None) -> None:
        if snapshot:
            runtime_activity_state_service.publish_runtime_activity_snapshot(
                snapshot,
                "live_semantics_harness",
            )
        else:
            runtime_activity_state_service.clear_runtime_activity_state(
                "live_semantics_harness",
            )

    def normal_snapshot(
        self,
        name: str,
        *,
        elapsed_seconds: int,
        start: str,
        is_persisted: bool = False,
        persisted_activity_id: int = 0,
        extra_seconds: int = 0,
    ) -> dict:
        return {
            "app_name": name,
            "process_name": f"{name.lower()}.exe",
            "activity_display_name": name,
            "resource_display_name": name,
            "resource_identity_key": f"app:{name}",
            "inferred_project_name": name,
            "start_time": self.at(start),
            "elapsed_seconds": elapsed_seconds,
            "extra_seconds": extra_seconds,
            "status": STATUS_NORMAL,
            "is_persisted": is_persisted,
            "persisted_activity_id": persisted_activity_id,
        }

    def create_closed_activity(
        self,
        name: str,
        *,
        start: str,
        end: str,
        seconds: int,
    ) -> int:
        activity_id = create_open_activity(
            app_name=name,
            process_name=f"{name.lower()}.exe",
            window_title=name,
            start_time=self.at(start),
        )
        activity_lifecycle_service.close_activity(
            activity_id,
            self.at(end),
            duration_seconds=seconds,
        )
        return int(activity_id)

    def create_open_activity(
        self,
        name: str,
        *,
        start: str,
        seconds: int,
    ) -> int:
        activity_id = create_open_activity(
            app_name=name,
            process_name=f"{name.lower()}.exe",
            window_title=name,
            start_time=self.at(start),
        )
        activity_lifecycle_service.checkpoint_activity(activity_id, seconds)
        return int(activity_id)

    def pages(self, *, details_ids: list[int] | None = None, date: str | None = None) -> dict:
        del details_ids
        report_date = date or self.date
        timeline = self.bridge.get_timeline(report_date)
        entries = timeline.get("entries") or []
        details = {"ok": True, "summary_rows": []}
        if entries:
            selected = entries[0]
            details = self.bridge.get_timeline_session_activity_summary(
                selected["projection_instance_key"],
                report_date,
                selected["projection_revision"],
            )
        return {
            "overview": self.bridge.get_overview(),
            "recent": self.bridge.get_recent_activities(),
            "timeline": timeline,
            "details": details,
            "refresh": self.bridge.get_refresh_state(report_date),
        }
