from __future__ import annotations

from datetime import date
import threading
from typing import Any, Callable

import customtkinter as ctk

from ..services.settings_service import get_bool_setting, get_int_setting, get_setting, set_setting
from . import design
from .first_run_dialog import FirstRunDialog


class WorkTraceApp(ctk.CTk):
    def __init__(self, start_collector_callback, stop_event: threading.Event):
        super().__init__()
        self.start_collector_callback = start_collector_callback
        self.stop_event = stop_event
        self.collector_started = False
        self.active_page = "overview"
        self.nav_buttons: dict[str, ctk.CTkButton] = {}
        self.pages: dict[str, Any] = {}
        self._page_factories: dict[str, Callable[[], Any]] = {}

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
        self.after(2000, self._refresh_current_activity_status)

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
        self.sidebar_record_button = design.button(
            status_card,
            text="开始记录",
            height=44,
            command=self.toggle_pause,
            fg_color=design.SUCCESS,
            hover_color=("#0f766e", "#10b981"),
            text_color="#ffffff",
        )
        self.sidebar_record_button.pack(fill="x", padx=12, pady=(0, 12))
        self.sidebar_pause_button = self.sidebar_record_button

        nav = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        nav.grid(row=2, column=0, sticky="new", padx=10)
        for key, label in [
            ("overview", "概览"),
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

        self._page_factories = {
            "overview": self._create_overview_page,
            "timeline": self._create_timeline_page,
            "statistics": self._create_statistics_page,
            "rules": self._create_rules_page,
            "settings": self._create_settings_page,
        }
        self._ensure_page("overview")
        self.show_page("overview")

    def _create_overview_page(self):
        from .overview_view import OverviewView

        page = OverviewView(
            self.content,
            open_timeline_callback=self.open_timeline,
            open_statistics_callback=lambda: self.show_page("statistics"),
        )
        self.overview = page
        return page

    def _create_timeline_page(self):
        from .timeline_view import TimelineView

        page = TimelineView(self.content)
        self.timeline = page
        return page

    def _create_statistics_page(self):
        from .statistics_view import StatisticsView

        page = StatisticsView(self.content)
        self.statistics = page
        return page

    def _create_rules_page(self):
        from .project_rules_view import ProjectRulesView

        page = ProjectRulesView(self.content)
        self.rules = page
        return page

    def _create_settings_page(self):
        from .settings_view import SettingsView

        page = SettingsView(self.content)
        self.settings = page
        return page

    def _ensure_page(self, key: str):
        page = self.pages.get(key)
        if page is not None:
            return page
        factory = getattr(self, "_page_factories", {}).get(key)
        if factory is None:
            return None
        page = factory()
        page.grid(row=0, column=0, sticky="nsew")
        self.pages[key] = page
        return page

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
        if key not in self.pages and key not in getattr(self, "_page_factories", {}):
            return
        page = self._ensure_page(key)
        if page is None:
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
        timeline = getattr(self, "timeline", None) or self._ensure_page("timeline")
        if timeline is None:
            return
        if hasattr(timeline, "open_context"):
            timeline.open_context(target, only_uncategorized=only_uncategorized, selected_session_id=session_id)
        else:
            timeline.date_var.set(target)
            timeline.only_uncategorized.set(only_uncategorized)
        self.show_page("timeline")

    def refresh_current_tab(self) -> None:
        page = self.pages.get(self.active_page)
        if self.active_page == "timeline" and page is not None:
            if not page.is_user_interacting():
                page.refresh()
        else:
            self._refresh_page(self.active_page)
        refresh_ms = max(5, get_int_setting("ui_refresh_seconds", 10)) * 1000
        self.after(refresh_ms, self.refresh_current_tab)

    def _refresh_page(self, key: str) -> None:
        page = self.pages.get(key)
        if page is not None and hasattr(page, "refresh"):
            page.refresh()

    def _refresh_current_activity_status(self) -> None:
        page = self.pages.get(self.active_page)
        if page is not None and hasattr(page, "refresh_current_activity"):
            page.refresh_current_activity()
        self.after(2000, self._refresh_current_activity_status)

    def _sync_nav_buttons(self) -> None:
        for key, button in self.nav_buttons.items():
            if key == self.active_page:
                button.configure(fg_color=design.ACCENT_SOFT, text_color=design.ACCENT, font=design.FONT_BODY_STRONG)
            else:
                button.configure(fg_color="transparent", text_color=design.TEXT, font=design.FONT_BODY)

    def _refresh_sidebar_status(self) -> None:
        self._sync_sidebar_status()
        self.after(1000, self._refresh_sidebar_status)

    def _sync_sidebar_status(self) -> None:
        status = self._status_text()
        raw_status = get_setting("collector_status", "stopped")
        paused = get_bool_setting("user_paused", False) or raw_status == "paused"
        self.sidebar_status_label.configure(text=status)
        if raw_status == "running" and not paused:
            self.sidebar_status_label.configure(text_color=design.SUCCESS)
            self.sidebar_record_button.configure(
                text="暂停记录",
                fg_color=design.DANGER,
                hover_color=design.DANGER_HOVER,
                text_color="#ffffff",
            )
            self.sidebar_status_hint.configure(text="正在记录当前活动")
        else:
            self.sidebar_status_label.configure(text_color=design.DANGER if paused else design.MUTED_TEXT)
            self.sidebar_record_button.configure(
                text="开始记录",
                fg_color=design.SUCCESS,
                hover_color=("#0f766e", "#10b981"),
                text_color="#ffffff",
            )
            self.sidebar_status_hint.configure(text="已暂停" if paused else "数据仅保存在本机")

    def _status_text(self) -> str:
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
        status = get_setting("collector_status", "stopped")
        paused = get_bool_setting("user_paused", False) or status == "paused"
        if paused or status != "running":
            set_setting("user_paused", "false")
            self._start_collector_once()
        else:
            set_setting("user_paused", "true")
        self._sync_sidebar_status()
        if self.active_page == "timeline":
            timeline = getattr(self, "timeline", None) or self.pages.get("timeline")
            if timeline is not None:
                timeline.refresh()

    def on_close(self) -> None:
        self.stop_event.set()
        self.destroy()
