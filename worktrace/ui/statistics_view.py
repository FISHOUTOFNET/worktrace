from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

import customtkinter as ctk
from tkinter import messagebox

from ..exports.markdown_exporter import format_duration
from ..services import export_service, statistics_service
from ..services.settings_service import get_setting
from . import design


class StatisticsView(ctk.CTkFrame):
    def __init__(self, master):
        super().__init__(master)
        today = date.today().isoformat()
        self.start_var = ctk.StringVar(value=today)
        self.end_var = ctk.StringVar(value=today)
        self._build()

    def _build(self) -> None:
        self.configure(fg_color="transparent")
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=24, pady=(22, 12))
        header.grid_columnconfigure(0, weight=1)
        design.label(header, text="统计与导出", variant="title").grid(row=0, column=0, sticky="w")
        design.label(header, text="按日期范围检查项目投入，并导出可编辑的工时草稿。", variant="caption").grid(
            row=1, column=0, sticky="w", pady=(4, 0)
        )

        controls = ctk.CTkFrame(header, fg_color="transparent")
        controls.grid(row=0, column=1, rowspan=2, sticky="e")
        design.label(controls, text="开始", variant="caption").pack(side="left", padx=(0, 4))
        design.entry(controls, textvariable=self.start_var, width=122).pack(side="left")
        design.label(controls, text="结束", variant="caption").pack(side="left", padx=(12, 4))
        design.entry(controls, textvariable=self.end_var, width=122).pack(side="left")
        design.button(controls, text="刷新", width=70, command=self.refresh).pack(side="left", padx=8)
        design.button(controls, text="Excel", variant="subtle", width=76, command=self.export_excel).pack(
            side="left", padx=(0, 6)
        )
        design.button(controls, text="Markdown", variant="ghost", width=104, command=self.export_markdown).pack(side="left")

        self.body = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.body.grid(row=1, column=0, sticky="nsew", padx=24, pady=(0, 24))
        self.body.grid_columnconfigure(0, weight=1)

        self.summary_frame = ctk.CTkFrame(self.body, fg_color="transparent")
        self.summary_frame.grid(row=0, column=0, sticky="ew")
        for col in range(5):
            self.summary_frame.grid_columnconfigure(col, weight=1, uniform="summary")

        self.table = design.card(self.body)
        self.table.grid(row=1, column=0, sticky="ew", pady=(14, 0))
        self.table.grid_columnconfigure(0, weight=1)

    def refresh(self) -> None:
        if not self._validate_dates():
            return
        summary = statistics_service.get_summary(self.start_var.get(), self.end_var.get())
        _clear_children(self.summary_frame)
        items = [
            ("总时长", summary["total_duration"]),
            ("有效", summary["effective_duration"]),
            ("空闲", summary["idle_duration"]),
            ("排除", summary["excluded_duration"]),
            ("未归类", summary["uncategorized_duration"]),
        ]
        for index, (title, seconds) in enumerate(items):
            card = design.card(self.summary_frame)
            card.grid(row=0, column=index, sticky="ew", padx=(0 if index == 0 else 10, 0))
            design.label(card, text=title, variant="caption_strong").pack(anchor="w", padx=16, pady=(14, 2))
            design.label(card, text=format_duration(seconds), variant="subtitle").pack(anchor="w", padx=16, pady=(0, 14))

        _clear_children(self.table)
        header = ctk.CTkFrame(self.table, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=18, pady=(16, 8))
        header.grid_columnconfigure(0, weight=1)
        design.label(header, text="项目统计", variant="section").grid(row=0, column=0, sticky="w")
        total = max(1, int(summary["effective_duration"] or summary["total_duration"] or 1))
        rows = statistics_service.get_project_stats(self.start_var.get(), self.end_var.get())
        if not rows:
            design.label(self.table, text="当前范围暂无记录", variant="caption").grid(
                row=1, column=0, sticky="w", padx=18, pady=(0, 18)
            )
            return
        rows_frame = ctk.CTkFrame(self.table, fg_color="transparent")
        rows_frame.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 12))
        rows_frame.grid_columnconfigure(0, weight=1)
        for row_index, row in enumerate(rows):
            self._project_stat_row(rows_frame, row_index, row, total)

    def _project_stat_row(self, parent, row_index: int, row: dict, total: int) -> None:
        frame = ctk.CTkFrame(parent, fg_color=design.CARD_SUBTLE_BG, corner_radius=design.RADIUS_MD)
        frame.grid(row=row_index, column=0, sticky="ew", padx=6, pady=5)
        frame.grid_columnconfigure(1, weight=1)
        duration = int(row["total_duration"] or 0)
        percent = min(1.0, max(0.0, duration / total))
        design.label(frame, text=str(row["project"]), variant="strong", anchor="w").grid(
            row=0, column=0, sticky="w", padx=14, pady=(10, 2)
        )
        design.label(frame, text=f"{row['record_count']} 条记录", variant="caption").grid(
            row=1, column=0, sticky="w", padx=14, pady=(0, 10)
        )
        bar = ctk.CTkProgressBar(frame, height=8, progress_color=design.ACCENT)
        bar.grid(row=0, column=1, rowspan=2, sticky="ew", padx=14)
        bar.set(percent)
        design.label(frame, text=format_duration(duration), variant="strong", width=72).grid(
            row=0, column=2, rowspan=2, sticky="e", padx=(0, 14)
        )

    def _export_path(self, suffix: str) -> Path:
        export_dir = Path(get_setting("export_path", str(Path.home() / "Documents" / "WorkTrace Exports")))
        return export_dir / f"worktrace_{self.start_var.get()}_{self.end_var.get()}.{suffix}"

    def _validate_dates(self) -> bool:
        try:
            start = date.fromisoformat(self.start_var.get())
            end = date.fromisoformat(self.end_var.get())
        except ValueError:
            messagebox.showerror("日期格式错误", "日期格式必须为 YYYY-MM-DD")
            return False
        if start > end:
            messagebox.showerror("日期范围错误", "开始日期不能晚于结束日期")
            return False
        return True

    def export_excel(self) -> None:
        try:
            path = export_service.export_excel(self.start_var.get(), self.end_var.get(), str(self._export_path("xlsx")))
            messagebox.showinfo("导出完成", path)
            self.refresh()
        except Exception as exc:
            logging.exception("excel export failed")
            messagebox.showerror("导出失败", str(exc))

    def export_markdown(self) -> None:
        try:
            path = export_service.export_markdown(self.start_var.get(), self.end_var.get(), str(self._export_path("md")))
            messagebox.showinfo("导出完成", path)
            self.refresh()
        except Exception as exc:
            logging.exception("markdown export failed")
            messagebox.showerror("导出失败", str(exc))


def _clear_children(widget) -> None:
    for child in widget.winfo_children():
        child.destroy()
