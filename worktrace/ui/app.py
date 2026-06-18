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

        self.tabs = ctk.CTkTabview(self, command=self._on_tab_changed)
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
        self.after(500, self.refresh_current_tab)

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

    def refresh_current_tab(self) -> None:
        if self.tabs.get() == "时间线":
            if not self.timeline.is_user_interacting():
                self.timeline.refresh()
        refresh_ms = max(5, get_int_setting("ui_refresh_seconds", 5)) * 1000
        self.after(refresh_ms, self.refresh_current_tab)

    def _on_tab_changed(self) -> None:
        current = self.tabs.get()
        if current == "统计与导出":
            self.statistics.refresh()
        elif current == "设置与隐私":
            self.settings.refresh()
        elif current == "时间线":
            self.timeline.refresh()

    def on_close(self) -> None:
        self.stop_event.set()
        self.destroy()
