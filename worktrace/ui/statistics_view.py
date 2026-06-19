from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from tkinter import messagebox
from typing import Any

import customtkinter as ctk

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
        self._summary_labels: dict[str, ctk.CTkLabel] = {}
        self._row_widgets: dict[str, dict[str, Any]] = {}
        self.empty_label = None
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
        design.button(controls, text="Markdown", variant="subtle", width=104, command=self.export_markdown).pack(side="left")

        self.body = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.body.grid(row=1, column=0, sticky="nsew", padx=24, pady=(0, 24))
        self.body.grid_columnconfigure(0, weight=1)

        self.summary_frame = ctk.CTkFrame(self.body, fg_color="transparent")
        self.summary_frame.grid(row=0, column=0, sticky="ew")
        for col in range(5):
            self.summary_frame.grid_columnconfigure(col, weight=1, uniform="summary")
        self._build_summary_cards()

        self.table = design.card(self.body)
        self.table.grid(row=1, column=0, sticky="ew", pady=(14, 0))
        self.table.grid_columnconfigure(0, weight=1)
        header_row = ctk.CTkFrame(self.table, fg_color="transparent")
        header_row.grid(row=0, column=0, sticky="ew", padx=18, pady=(16, 8))
        header_row.grid_columnconfigure(0, weight=1)
        design.label(header_row, text="项目统计", variant="section").grid(row=0, column=0, sticky="w")
        self.rows_frame = ctk.CTkFrame(self.table, fg_color="transparent")
        self.rows_frame.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 12))
        self.rows_frame.grid_columnconfigure(0, weight=1)

    def _build_summary_cards(self) -> None:
        for index, key in enumerate(["total", "effective", "idle", "excluded", "uncategorized"]):
            titles = {
                "total": "总时长",
                "effective": "有效",
                "idle": "空闲",
                "excluded": "排除",
                "uncategorized": "未归类",
            }
            card = design.card(self.summary_frame)
            card.grid(row=0, column=index, sticky="ew", padx=(0 if index == 0 else 10, 0))
            design.label(card, text=titles[key], variant="caption_strong").pack(anchor="w", padx=16, pady=(14, 2))
            value = design.label(card, text="00:00:00", variant="subtitle")
            value.pack(anchor="w", padx=16, pady=(0, 14))
            self._summary_labels[key] = value

    def refresh(self) -> None:
        if not self._validate_dates():
            return
        summary = statistics_service.get_summary(self.start_var.get(), self.end_var.get())
        values = {
            "total": summary["total_duration"],
            "effective": summary["effective_duration"],
            "idle": summary["idle_duration"],
            "excluded": summary["excluded_duration"],
            "uncategorized": summary["uncategorized_duration"],
        }
        for key, seconds in values.items():
            self._summary_labels[key].configure(text=format_duration(seconds))

        total = max(1, int(summary["effective_duration"] or summary["total_duration"] or 1))
        rows = statistics_service.get_project_stats(self.start_var.get(), self.end_var.get())
        self._sync_project_rows(rows, total)

    def _sync_project_rows(self, rows: list[dict], total: int) -> None:
        active_keys = {str(row["project"]) for row in rows}
        for key in list(self._row_widgets):
            if key not in active_keys:
                self._row_widgets[key]["frame"].destroy()
                del self._row_widgets[key]
        if not rows:
            self._show_empty()
            return
        self._hide_empty()
        for row_index, row in enumerate(rows):
            key = str(row["project"])
            widgets = self._row_widgets.get(key)
            if widgets is None:
                widgets = self._create_project_stat_row()
                self._row_widgets[key] = widgets
            widgets["frame"].grid(row=row_index, column=0, sticky="ew", padx=6, pady=5)
            self._update_project_stat_row(widgets, row, total)

    def _create_project_stat_row(self) -> dict[str, Any]:
        frame = ctk.CTkFrame(self.rows_frame, fg_color=design.CARD_SUBTLE_BG, corner_radius=design.RADIUS_MD)
        frame.grid_columnconfigure(1, weight=1)
        name = design.label(frame, text="", variant="strong", anchor="w")
        name.grid(row=0, column=0, sticky="w", padx=14, pady=(10, 2))
        count = design.label(frame, text="", variant="caption")
        count.grid(row=1, column=0, sticky="w", padx=14, pady=(0, 10))
        bar = ctk.CTkProgressBar(frame, height=8, progress_color=design.ACCENT)
        bar.grid(row=0, column=1, rowspan=2, sticky="ew", padx=14)
        duration = design.label(frame, text="", variant="strong", width=72)
        duration.grid(row=0, column=2, rowspan=2, sticky="e", padx=(0, 14))
        return {"frame": frame, "name": name, "count": count, "bar": bar, "duration": duration}

    def _update_project_stat_row(self, widgets: dict[str, Any], row: dict, total: int) -> None:
        duration = int(row["total_duration"] or 0)
        percent = min(1.0, max(0.0, duration / total))
        widgets["name"].configure(text=str(row["project"]))
        widgets["count"].configure(text=f"{row['record_count']} 条记录")
        widgets["bar"].set(percent)
        widgets["duration"].configure(text=format_duration(duration))

    def _show_empty(self) -> None:
        for widgets in self._row_widgets.values():
            widgets["frame"].grid_remove()
        if self.empty_label is None:
            self.empty_label = design.label(self.rows_frame, text="当前范围暂无记录", variant="caption")
        self.empty_label.grid(row=0, column=0, sticky="w", padx=6, pady=(0, 10))

    def _hide_empty(self) -> None:
        if self.empty_label is not None:
            self.empty_label.grid_remove()

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
