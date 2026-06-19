from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

import customtkinter as ctk
from tkinter import messagebox

from ..exports.markdown_exporter import format_duration
from ..services import export_service, statistics_service
from ..services.settings_service import get_setting


class StatisticsView(ctk.CTkFrame):
    def __init__(self, master):
        super().__init__(master)
        today = date.today().isoformat()
        self.start_var = ctk.StringVar(value=today)
        self.end_var = ctk.StringVar(value=today)
        self._build()

    def _build(self) -> None:
        top = ctk.CTkFrame(self)
        top.pack(fill="x", padx=12, pady=12)
        ctk.CTkLabel(top, text="开始").pack(side="left", padx=4)
        ctk.CTkEntry(top, textvariable=self.start_var, width=120).pack(side="left")
        ctk.CTkLabel(top, text="结束").pack(side="left", padx=(12, 4))
        ctk.CTkEntry(top, textvariable=self.end_var, width=120).pack(side="left")
        ctk.CTkButton(top, text="刷新", width=70, command=self.refresh).pack(side="left", padx=8)
        ctk.CTkButton(top, text="导出 Excel", command=self.export_excel).pack(side="left", padx=4)
        ctk.CTkButton(top, text="导出 Markdown", command=self.export_markdown).pack(side="left", padx=4)
        self.summary_label = ctk.CTkLabel(self, text="", justify="left")
        self.summary_label.pack(fill="x", padx=16, pady=8)
        self.table = ctk.CTkScrollableFrame(self)
        self.table.pack(fill="both", expand=True, padx=12, pady=12)

    def refresh(self) -> None:
        if not self._validate_dates():
            return
        summary = statistics_service.get_summary(self.start_var.get(), self.end_var.get())
        self.summary_label.configure(
            text=(
                f"总时长：{format_duration(summary['total_duration'])}    "
                f"有效：{format_duration(summary['effective_duration'])}    "
                f"空闲：{format_duration(summary['idle_duration'])}    "
                f"排除：{format_duration(summary['excluded_duration'])}    "
                f"未归类：{format_duration(summary['uncategorized_duration'])}"
            )
        )
        for child in self.table.winfo_children():
            child.destroy()
        headers = ["项目", "总时长", "计费", "非计费", "记录数"]
        for col, header in enumerate(headers):
            ctk.CTkLabel(self.table, text=header, font=ctk.CTkFont(weight="bold")).grid(
                row=0, column=col, padx=8, pady=4, sticky="w"
            )
        for row_index, row in enumerate(
            statistics_service.get_project_stats(self.start_var.get(), self.end_var.get()), start=1
        ):
            values = [
                row["project"],
                format_duration(row["total_duration"]),
                format_duration(row["billable_duration"]),
                format_duration(row["non_billable_duration"]),
                row["record_count"],
            ]
            for col, value in enumerate(values):
                ctk.CTkLabel(self.table, text=str(value)).grid(row=row_index, column=col, padx=8, pady=4)

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
