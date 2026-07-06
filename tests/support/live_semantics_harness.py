from __future__ import annotations

import json
from dataclasses import dataclass

from worktrace.collector.state_machine import CollectorStateMachine
from worktrace.constants import STATUS_NORMAL
from worktrace.platforms.base import ActiveWindow
from worktrace.services import activity_service, settings_service, timeline_service
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
        raw = settings_service.get_setting("current_activity_snapshot", "") or ""
        if not raw:
            return {}
        value = json.loads(raw)
        return value if isinstance(value, dict) else {}

    def set_snapshot(self, snapshot: dict | None) -> None:
        settings_service.set_setting(
            "current_activity_snapshot",
            json.dumps(snapshot) if snapshot else "",
        )
        settings_service.clear_settings_cache()

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
        activity_id = activity_service.create_activity(
            name,
            f"{name.lower()}.exe",
            name,
            start_time=self.at(start),
        )
        activity_service.close_activity(activity_id, self.at(end), seconds)
        return int(activity_id)

    def create_open_activity(
        self,
        name: str,
        *,
        start: str,
        seconds: int,
    ) -> int:
        activity_id = activity_service.create_activity(
            name,
            f"{name.lower()}.exe",
            name,
            start_time=self.at(start),
        )
        activity_service.set_activity_duration(activity_id, seconds)
        return int(activity_id)

    def pages(self, *, details_ids: list[int] | None = None, date: str | None = None) -> dict:
        report_date = date or self.date
        return {
            "overview": self.bridge.get_overview(),
            "recent": self.bridge.get_recent_activities(),
            "timeline": self.bridge.get_timeline(report_date),
            "details": self.bridge.get_timeline_session_details(
                details_ids or [],
                report_date,
            ),
            "refresh": self.bridge.get_refresh_state(report_date),
        }

