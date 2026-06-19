from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta
from pathlib import Path
from tkinter import messagebox
from typing import Callable

import customtkinter as ctk

from ..constants import TIME_FORMAT, UNCATEGORIZED_PROJECT
from ..exports.markdown_exporter import format_current_duration, format_duration
from ..services import export_service, statistics_service, timeline_service
from ..services.settings_service import get_setting
from . import design


class OverviewView(ctk.CTkFrame):
    def __init__(
        self,
        master,
        open_timeline_callback: Callable[[bool], None] | None = None,
        open_statistics_callback: Callable[[], None] | None = None,
    ):
        super().__init__(master, fg_color="transparent")
        self.open_timeline_callback = open_timeline_callback
        self.open_statistics_callback = open_statistics_callback
        self._current_activity_after_id: str | None = None
        self._build()
        self._schedule_current_activity_tick()

    def _build(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=24, pady=(22, 12))
        header.grid_columnconfigure(0, weight=1)
        design.label(header, text="今日概览", variant="title").grid(row=0, column=0, sticky="w")
        design.label(
            header,
            text="把今天的工作轨迹整理成可确认、可导出的工作记忆。",
            variant="caption",
        ).grid(row=1, column=0, sticky="w", pady=(4, 0))
        action_row = ctk.CTkFrame(header, fg_color="transparent")
        action_row.grid(row=0, column=1, rowspan=2, sticky="e")
        design.button(action_row, text="查看今日时间线", command=lambda: self._open_timeline(False)).pack(
            side="left", padx=(0, 8)
        )
        design.button(
            action_row,
            text="只看未归类",
            variant="subtle",
            command=lambda: self._open_timeline(True),
        ).pack(side="left", padx=(0, 8))
        design.button(action_row, text="导出本周草稿", variant="ghost", command=self.export_weekly_markdown).pack(
            side="left"
        )

        body = ctk.CTkScrollableFrame(self, fg_color="transparent")
        body.grid(row=1, column=0, sticky="nsew", padx=24, pady=(0, 24))
        body.grid_columnconfigure((0, 1, 2, 3), weight=1, uniform="kpi")
        body.grid_columnconfigure(0, weight=1)

        self.kpi_frame = ctk.CTkFrame(body, fg_color="transparent")
        self.kpi_frame.grid(row=0, column=0, columnspan=4, sticky="ew")
        for col in range(4):
            self.kpi_frame.grid_columnconfigure(col, weight=1, uniform="kpi")

        self.current_card = design.card(body)
        self.current_card.grid(row=1, column=0, columnspan=4, sticky="ew", pady=(14, 0))
        self.current_card.grid_columnconfigure(0, weight=1)
        design.label(self.current_card, text="当前活动", variant="section").grid(
            row=0, column=0, sticky="w", padx=18, pady=(16, 4)
        )
        self.current_activity_label = design.label(
            self.current_card,
            text="当前活动：无",
            variant="body",
            anchor="w",
            justify="left",
            wraplength=920,
        )
        self.current_activity_label.grid(row=1, column=0, sticky="ew", padx=18, pady=(0, 16))

        recent = design.card(body)
        recent.grid(row=2, column=0, columnspan=4, sticky="nsew", pady=(14, 0))
        recent.grid_columnconfigure(0, weight=1)
        recent_header = ctk.CTkFrame(recent, fg_color="transparent")
        recent_header.grid(row=0, column=0, sticky="ew", padx=18, pady=(16, 8))
        recent_header.grid_columnconfigure(0, weight=1)
        design.label(recent_header, text="最近会话", variant="section").grid(row=0, column=0, sticky="w")
        design.button(
            recent_header,
            text="统计与导出",
            variant="ghost",
            width=96,
            command=self._open_statistics,
        ).grid(row=0, column=1, sticky="e")
        self.recent_frame = ctk.CTkFrame(recent, fg_color="transparent")
        self.recent_frame.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 12))
        self.recent_frame.grid_columnconfigure(0, weight=1)

    def refresh(self) -> None:
        today = date.today().isoformat()
        summary = statistics_service.get_summary(today, today)
        kpis = [
            ("总时长", format_duration(summary["total_duration"]), "含有效、空闲和排除状态"),
            ("有效工作", format_duration(summary["effective_duration"]), "普通活动合计"),
            ("空闲", format_duration(summary["idle_duration"]), "离开或无操作时间"),
            ("未归类", format_duration(summary["uncategorized_duration"]), "需要整理的草稿"),
        ]
        _clear_children(self.kpi_frame)
        for index, (title, value, caption) in enumerate(kpis):
            card = design.card(self.kpi_frame)
            card.grid(row=0, column=index, sticky="ew", padx=(0 if index == 0 else 10, 0))
            design.label(card, text=title, variant="caption_strong").pack(anchor="w", padx=16, pady=(14, 2))
            design.label(card, text=value, variant="title").pack(anchor="w", padx=16)
            design.label(card, text=caption, variant="caption", wraplength=180, justify="left").pack(
                anchor="w", padx=16, pady=(2, 14)
            )
        self.current_activity_label.configure(text=current_activity_text())
        self._refresh_recent_sessions(today)

    def _refresh_recent_sessions(self, today: str) -> None:
        _clear_children(self.recent_frame)
        sessions = timeline_service.get_project_sessions_by_date(today, include_hidden=False)[:8]
        if not sessions:
            empty = design.section(self.recent_frame, fg_color=design.CARD_SUBTLE_BG)
            empty.grid(row=0, column=0, sticky="ew", padx=6, pady=6)
            design.label(empty, text="今天还没有可展示的工作会话。", variant="caption").pack(
                anchor="w", padx=14, pady=12
            )
            return
        for row_index, session in enumerate(sessions):
            row = ctk.CTkFrame(self.recent_frame, fg_color="transparent")
            row.grid(row=row_index, column=0, sticky="ew", padx=6, pady=3)
            row.grid_columnconfigure(1, weight=1)
            design.label(row, text=_session_time(session), variant="mono", width=92, anchor="w").grid(
                row=0, column=0, sticky="w", padx=(8, 12), pady=8
            )
            title = str(session.get("project_name") or UNCATEGORIZED_PROJECT)
            subtitle = str(session.get("status_summary") or "正常活动")
            design.label(row, text=title, variant="strong", anchor="w").grid(row=0, column=1, sticky="w")
            design.label(row, text=subtitle, variant="caption", anchor="w").grid(row=1, column=1, sticky="w")
            design.label(row, text=format_duration(session.get("duration_seconds") or 0), variant="strong").grid(
                row=0, column=2, rowspan=2, sticky="e", padx=(12, 8)
            )

    def _open_timeline(self, only_uncategorized: bool) -> None:
        if self.open_timeline_callback is not None:
            self.open_timeline_callback(only_uncategorized)

    def _open_statistics(self) -> None:
        if self.open_statistics_callback is not None:
            self.open_statistics_callback()

    def export_weekly_markdown(self) -> None:
        today = date.today()
        start = today - timedelta(days=today.weekday())
        export_dir = Path(get_setting("export_path", str(Path.home() / "Documents" / "WorkTrace Exports")))
        path = export_dir / f"worktrace_weekly_{start.isoformat()}_{today.isoformat()}.md"
        try:
            exported = export_service.export_markdown(start.isoformat(), today.isoformat(), str(path))
            messagebox.showinfo("导出完成", exported)
        except Exception as exc:
            logging.exception("weekly markdown export failed")
            messagebox.showerror("导出失败", str(exc))

    def _schedule_current_activity_tick(self) -> None:
        self.current_activity_label.configure(text=current_activity_text())
        self._current_activity_after_id = self.after(1000, self._schedule_current_activity_tick)

    def destroy(self) -> None:
        if self._current_activity_after_id is not None:
            try:
                self.after_cancel(self._current_activity_after_id)
            except Exception:
                pass
            self._current_activity_after_id = None
        super().destroy()


def current_activity_text() -> str:
    raw = get_setting("current_activity_snapshot", "") or ""
    if not raw:
        return "当前活动：无"
    try:
        snapshot = json.loads(raw)
    except json.JSONDecodeError:
        return "当前活动：无"
    name = snapshot.get("resource_display_name") or snapshot.get("app_name") or snapshot.get("process_name") or "未知"
    project = snapshot.get("inferred_project_name") or UNCATEGORIZED_PROJECT
    elapsed = format_current_duration(_current_elapsed_seconds(snapshot))
    state = "已进入历史" if snapshot.get("is_persisted") else "暂不入历史"
    if snapshot.get("status") == "idle":
        name = "空闲中"
    return f"当前活动：{name}｜{project}｜{elapsed}｜{state}"


def _current_elapsed_seconds(snapshot: dict) -> int:
    start_time = str(snapshot.get("start_time") or "").strip()
    if start_time:
        try:
            start = datetime.strptime(start_time, TIME_FORMAT)
            return max(0, int((datetime.now() - start).total_seconds()))
        except ValueError:
            pass
    try:
        return max(0, int(snapshot.get("elapsed_seconds") or 0))
    except (TypeError, ValueError):
        return 0


def _session_time(session: dict) -> str:
    start = session.get("start_time") or ""
    end = session.get("end_time") or ""
    return f"{start[11:16] if len(start) >= 16 else start}-{end[11:16] if len(end) >= 16 else ''}"


def _clear_children(widget) -> None:
    for child in widget.winfo_children():
        child.destroy()
