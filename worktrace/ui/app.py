from __future__ import annotations

from datetime import date
import threading

import customtkinter as ctk

from ..services.settings_service import get_bool_setting, get_int_setting, set_setting
from . import design
from .first_run_dialog import FirstRunDialog
from .overview_view import OverviewView
from .project_rules_view import ProjectRulesView
from .settings_view import SettingsView
from .statistics_view import StatisticsView
from .timeline_view import TimelineView


class WorkTraceApp(ctk.CTk):
    def __init__(self, start_collector_callback, stop_event: threading.Event):
        super().__init__()
        self.start_collector_callback = start_collector_callback
        self.stop_event = stop_event
        self.collector_started = False
        self.active_page = "overview"
        self.nav_buttons: dict[str, ctk.CTkButton] = {}

        self.title("有迹 WorkTrace")
        self.geometry("1240x780")
        self.minsize(1024, 720)
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        design.apply_app_theme()
        self.configure(fg_color=design.WINDOW_BG)

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self._build_shell()

        self.after(200, self._startup_privacy_gate)
        self.after(500, self.refresh_current_tab)
        self.after(1000, self._refresh_sidebar_status)

    def _build_shell(self) -> None:
        self.sidebar = ctk.CTkFrame(self, fg_color=design.SIDEBAR_BG, corner_radius=0, width=228)
        self.sidebar.grid(row=0, column=0, sticky="nsw")
        self.sidebar.grid_propagate(False)
        self.sidebar.grid_rowconfigure(2, weight=1)

        brand = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        brand.grid(row=0, column=0, sticky="ew", padx=18, pady=(22, 18))
        mark = ctk.CTkLabel(
            brand,
            text="有",
            width=40,
            height=40,
            corner_radius=12,
            fg_color=design.ACCENT,
            text_color="#ffffff",
            font=("Microsoft YaHei UI", 18, "bold"),
        )
        mark.pack(side="left", padx=(0, 10))
        title_box = ctk.CTkFrame(brand, fg_color="transparent")
        title_box.pack(side="left", fill="x", expand=True)
        design.label(title_box, text="有迹 WorkTrace", variant="section").pack(anchor="w")
        design.label(title_box, text="本地工作记忆", variant="caption").pack(anchor="w")

        status_card = design.card(self.sidebar, fg_color=design.CARD_SUBTLE_BG)
        status_card.grid(row=1, column=0, sticky="ew", padx=14, pady=(0, 14))
        self.sidebar_status_label = design.label(status_card, text="采集器未运行", variant="strong")
        self.sidebar_status_label.pack(anchor="w", padx=14, pady=(12, 2))
        self.sidebar_status_hint = design.label(status_card, text="数据仅保存在本机", variant="caption")
        self.sidebar_status_hint.pack(anchor="w", padx=14, pady=(0, 10))
        self.sidebar_pause_button = design.button(
            status_card,
            text="暂停记录",
            variant="subtle",
            command=self.toggle_pause,
        )
        self.sidebar_pause_button.pack(fill="x", padx=12, pady=(0, 12))

        nav = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        nav.grid(row=2, column=0, sticky="new", padx=10)
        for key, label in [
            ("overview", "今日概览"),
            ("timeline", "时间详情"),
            ("statistics", "统计与导出"),
            ("rules", "项目规则"),
            ("settings", "设置与隐私"),
        ]:
            button = design.button(
                nav,
                text=label,
                variant="ghost",
                anchor="w",
                height=38,
                command=lambda target=key: self.show_page(target),
            )
            button.pack(fill="x", pady=2)
            self.nav_buttons[key] = button

        footer = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        footer.grid(row=3, column=0, sticky="sew", padx=18, pady=18)
        design.label(footer, text="离线 · 无账号 · 无截图", variant="caption").pack(anchor="w")

        self.content = ctk.CTkFrame(self, fg_color="transparent")
        self.content.grid(row=0, column=1, sticky="nsew")
        self.content.grid_rowconfigure(0, weight=1)
        self.content.grid_columnconfigure(0, weight=1)

        self.overview = OverviewView(
            self.content,
            open_timeline_callback=self.open_timeline,
            open_statistics_callback=lambda: self.show_page("statistics"),
        )
        self.timeline = TimelineView(self.content)
        self.statistics = StatisticsView(self.content)
        self.rules = ProjectRulesView(self.content)
        self.settings = SettingsView(self.content)
        self.pages = {
            "overview": self.overview,
            "timeline": self.timeline,
            "statistics": self.statistics,
            "rules": self.rules,
            "settings": self.settings,
        }
        for page in self.pages.values():
            page.grid(row=0, column=0, sticky="nsew")
        self.show_page("overview")

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

    def show_page(self, key: str) -> None:
        if key not in self.pages:
            return
        self.pages[key].tkraise()
        self.active_page = key
        self._sync_nav_buttons()
        self._refresh_page(key)

    def open_timeline(
        self,
        only_uncategorized: bool = False,
        session_id: str | None = None,
        target_date: str | None = None,
    ) -> None:
        target = target_date or date.today().isoformat()
        if hasattr(self.timeline, "open_context"):
            self.timeline.open_context(target, only_uncategorized=only_uncategorized, selected_session_id=session_id)
        else:
            self.timeline.date_var.set(target)
            self.timeline.only_uncategorized.set(only_uncategorized)
        self.show_page("timeline")

    def refresh_current_tab(self) -> None:
        if self.active_page == "timeline":
            if not self.timeline.is_user_interacting():
                self.timeline.refresh()
        else:
            self._refresh_page(self.active_page)
        refresh_ms = max(5, get_int_setting("ui_refresh_seconds", 5)) * 1000
        self.after(refresh_ms, self.refresh_current_tab)

    def _refresh_page(self, key: str) -> None:
        page = self.pages.get(key)
        if page is not None and hasattr(page, "refresh"):
            page.refresh()

    def _sync_nav_buttons(self) -> None:
        for key, button in self.nav_buttons.items():
            if key == self.active_page:
                button.configure(fg_color=design.ACCENT_SOFT, text_color=design.ACCENT, font=design.FONT_BODY_STRONG)
            else:
                button.configure(fg_color="transparent", text_color=design.TEXT, font=design.FONT_BODY)

    def _refresh_sidebar_status(self) -> None:
        status = self._status_text()
        paused = get_bool_setting("user_paused", False)
        self.sidebar_status_label.configure(text=status)
        self.sidebar_pause_button.configure(text="继续记录" if paused else "暂停记录")
        self.after(1000, self._refresh_sidebar_status)

    def _status_text(self) -> str:
        from ..services.settings_service import get_setting

        status = get_setting("collector_status", "stopped")
        paused = get_bool_setting("user_paused", False)
        if paused or status == "paused":
            return "已暂停"
        if status == "running":
            return "记录中"
        if status == "error":
            return "状态异常"
        return "采集器未运行"

    def toggle_pause(self) -> None:
        set_setting("user_paused", "false" if get_bool_setting("user_paused", False) else "true")
        self._refresh_sidebar_status()
        if self.active_page == "timeline":
            self.timeline.refresh()

    def on_close(self) -> None:
        self.stop_event.set()
        self.destroy()
