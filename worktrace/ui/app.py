from __future__ import annotations

import threading

import customtkinter as ctk

from ..services.settings_service import get_bool_setting, get_int_setting, set_setting
from .first_run_dialog import FirstRunDialog
from .settings_view import SettingsView
from .statistics_view import StatisticsView
from .timeline_view import TimelineView


class WorkTraceApp(ctk.CTk):
    def __init__(self, start_collector_callback, stop_event: threading.Event):
        super().__init__()
        self.start_collector_callback = start_collector_callback
        self.stop_event = stop_event
        self.collector_started = False
        self.title("WorkTrace v0.1 Lite")
        self.geometry("1200x760")
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        ctk.set_appearance_mode("System")

        self.tabs = ctk.CTkTabview(self)
        self.tabs.pack(fill="both", expand=True, padx=10, pady=10)
        timeline_tab = self.tabs.add("时间线")
        stats_tab = self.tabs.add("统计与导出")
        settings_tab = self.tabs.add("设置与隐私")
        self.timeline = TimelineView(timeline_tab)
        self.timeline.pack(fill="both", expand=True)
        self.statistics = StatisticsView(stats_tab)
        self.statistics.pack(fill="both", expand=True)
        self.settings = SettingsView(settings_tab)
        self.settings.pack(fill="both", expand=True)

        self.after(200, self._startup_privacy_gate)
        self.after(500, self.refresh_all)

    def _startup_privacy_gate(self) -> None:
        if get_bool_setting("first_run_notice_accepted", False):
            self._start_collector_once()
        else:
            FirstRunDialog(self, self._accept_notice)

    def _accept_notice(self) -> None:
        set_setting("first_run_notice_accepted", "true")
        self._start_collector_once()

    def _start_collector_once(self) -> None:
        if not self.collector_started:
            self.collector_started = True
            self.start_collector_callback()

    def refresh_all(self) -> None:
        self.timeline.refresh()
        self.statistics.refresh()
        self.settings.refresh()
        refresh_ms = max(1, get_int_setting("ui_refresh_seconds", 2)) * 1000
        self.after(refresh_ms, self.refresh_all)

    def on_close(self) -> None:
        self.stop_event.set()
        self.destroy()
