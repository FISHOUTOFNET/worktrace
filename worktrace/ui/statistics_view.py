from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from tkinter import messagebox
from typing import Any

import customtkinter as ctk

from ..formatters import format_duration, format_project_label
from ..services import export_service, statistics_service, timeline_service
from ..services.settings_service import get_setting
from . import design
from .date_range import DateRange, classify_range, current_week_range, previous_week_range, shift_range, today_range


class StatisticsView(ctk.CTkFrame):
    def __init__(self, master, start_var=None, end_var=None):
        super().__init__(master)
        today = timeline_service.get_default_report_date()
        self.start_var = start_var or ctk.StringVar(value=today)
        self.end_var = end_var or ctk.StringVar(value=today)
        self.range_var = ctk.StringVar(value="今日")
        self._default_report_date = today
        self._summary_labels: dict[str, ctk.CTkLabel] = {}
        self._row_widgets: dict[str, dict[str, Any]] = {}
        self._latest_project_rows: list[dict] = []
        self._range_refresh_after_id: str | None = None
        self._suppress_range_trace = False
        self.empty_label = None
        self._build()
        self._bind_range_traces()

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
        self.prev_range_button = design.button(controls, text="<", width=34, command=lambda: self._shift_visible_range(-1))
        self.prev_range_button.pack(side="left", padx=(0, 4))
        self.range_segment = design.segmented_button(
            controls,
            values=["上周", "本周", "今日"],
            variable=self.range_var,
            command=self._apply_quick_range,
            width=174,
        )
        self.range_segment.pack(side="left", padx=(0, 8))
        self.start_entry = design.entry(controls, textvariable=self.start_var, width=122)
        self.start_entry.pack(side="left")
        self.start_entry.bind("<Return>", lambda _event: self.refresh(), add="+")
        design.label(controls, text="-", variant="caption").pack(side="left", padx=6)
        self.end_entry = design.entry(controls, textvariable=self.end_var, width=122)
        self.end_entry.pack(side="left")
        self.end_entry.bind("<Return>", lambda _event: self.refresh(), add="+")
        self.next_range_button = design.button(controls, text=">", width=34, command=lambda: self._shift_visible_range(1))
        self.next_range_button.pack(side="left", padx=(8, 8))
        design.button(controls, text="Excel", variant="subtle", width=76, command=self.export_excel).pack(
            side="left"
        )

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
        for index, key in enumerate(["total", "effective", "uncategorized", "idle", "excluded"]):
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

    def _bind_range_traces(self) -> None:
        for variable in (self.start_var, self.end_var):
            variable.trace_add("write", lambda *_args: self._schedule_range_refresh())

    def refresh(self, ensure_context: bool = True) -> None:
        if not self._validate_dates():
            return
        self._sync_range_buttons()
        self._refresh_values(ensure_context=ensure_context)

    def refresh_current_activity(self) -> None:
        current_default = timeline_service.get_default_report_date()
        if (
            self.start_var.get() == self._default_report_date
            and self.end_var.get() == self._default_report_date
            and current_default != self._default_report_date
        ):
            self.start_var.set(current_default)
            self.end_var.set(current_default)
            self._default_report_date = current_default
        if not self._dates_are_valid():
            self._sync_range_buttons()
            return
        self._sync_range_buttons()
        self._refresh_values(ensure_context=False)

    def _apply_today_range(self) -> None:
        self._set_visible_range(today_range(timeline_service.get_default_report_date()))

    def _apply_current_week_range(self) -> None:
        self._set_visible_range(current_week_range(timeline_service.get_default_report_date()))

    def _apply_previous_week_range(self) -> None:
        self._set_visible_range(previous_week_range(timeline_service.get_default_report_date()))

    def _apply_quick_range(self, value: str) -> None:
        if value == "上周":
            self._apply_previous_week_range()
        elif value == "本周":
            self._apply_current_week_range()
        elif value == "今日":
            self._apply_today_range()

    def _shift_visible_range(self, direction: int) -> None:
        shifted = shift_range(self.start_var.get(), self.end_var.get(), direction)
        if shifted is None:
            return
        self._set_visible_range(shifted)

    def _set_visible_range(self, date_range: DateRange) -> None:
        self._suppress_range_trace = True
        try:
            self.start_var.set(date_range.start)
            self.end_var.set(date_range.end)
        finally:
            self._suppress_range_trace = False
        self.refresh()

    def _schedule_range_refresh(self) -> None:
        if self._suppress_range_trace:
            return
        if not hasattr(self, "after"):
            return
        if self._range_refresh_after_id is not None:
            try:
                self.after_cancel(self._range_refresh_after_id)
            except Exception:
                pass
        self._range_refresh_after_id = self.after(500, self._refresh_after_range_change)

    def _refresh_after_range_change(self) -> None:
        self._range_refresh_after_id = None
        self._sync_range_buttons()
        if self._dates_are_valid():
            self._refresh_values(ensure_context=True)

    def _sync_range_buttons(self) -> None:
        state = "normal" if classify_range(self.start_var.get(), self.end_var.get()) != "custom" else "disabled"
        for button_name in ("prev_range_button", "next_range_button"):
            button = getattr(self, button_name, None)
            if button is not None:
                button.configure(state=state)
        if hasattr(self, "range_var"):
            self.range_var.set(self._active_range_label())

    def _refresh_values(self, ensure_context: bool = True) -> None:
        summary = statistics_service.get_summary(
            self.start_var.get(),
            self.end_var.get(),
            ensure_context=ensure_context,
            include_live=True,
        )
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
        rows = statistics_service.get_project_stats(
            self.start_var.get(),
            self.end_var.get(),
            ensure_context=ensure_context,
            include_live=True,
        )
        self._sync_project_rows(rows, total)

    def _sync_project_rows(self, rows: list[dict], total: int) -> None:
        self._latest_project_rows = list(rows)
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
        frame.grid_columnconfigure(0, weight=0, minsize=230)
        frame.grid_columnconfigure(1, weight=1)
        frame.grid_columnconfigure(2, weight=0, minsize=94)
        name = design.label(frame, text="", variant="strong", anchor="w", width=220)
        name.grid(row=0, column=0, sticky="w", padx=14, pady=(10, 2))
        count = design.label(frame, text="", variant="caption", width=220, anchor="w")
        count.grid(row=1, column=0, sticky="w", padx=14, pady=(0, 10))
        bar = ctk.CTkProgressBar(frame, height=8, progress_color=design.ACCENT)
        bar.grid(row=0, column=1, rowspan=2, sticky="ew", padx=14)
        duration = design.label(frame, text="", variant="strong", width=90)
        duration.grid(row=0, column=2, rowspan=2, sticky="e", padx=(0, 14))
        return {"frame": frame, "name": name, "count": count, "bar": bar, "duration": duration}

    def _update_project_stat_row(self, widgets: dict[str, Any], row: dict, total: int) -> None:
        duration = int(row["total_duration"] or 0)
        percent = min(1.0, max(0.0, duration / total))
        widgets["name"].configure(text=format_project_label(row["project"], row.get("project_description")))
        widgets["count"].configure(text=f"{row['record_count']} 条项目记录")
        widgets["bar"].set(percent)
        widgets["duration"].configure(text=format_duration(duration))

    def copy_page_text(self) -> str:
        lines = [
            "统计与导出",
            f"日期范围：{self.start_var.get()} 至 {self.end_var.get()}",
            "",
            "汇总",
        ]
        for key, title in [("total", "总时长"), ("effective", "有效"), ("uncategorized", "未归类"), ("idle", "空闲"), ("excluded", "排除")]:
            label = self._summary_labels.get(key)
            if label is not None:
                lines.append(f"{title}：{label.cget('text')}")
        lines.extend(["", "项目统计"])
        for row in self._latest_project_rows:
            lines.append(
                f"{format_project_label(row['project'], row.get('project_description'))}｜{format_duration(row['total_duration'])}｜{row['record_count']} 条项目记录"
            )
        return "\n".join(lines)

    def _active_range_label(self) -> str:
        today = timeline_service.get_default_report_date()
        current = DateRange(self.start_var.get(), self.end_var.get(), classify_range(self.start_var.get(), self.end_var.get()))
        if current == previous_week_range(today):
            return "上周"
        if current == current_week_range(today):
            return "本周"
        if current == today_range(today):
            return "今日"
        return ""

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
        if not self._dates_are_valid(show_errors=True):
            return False
        return True

    def _dates_are_valid(self, show_errors: bool = False) -> bool:
        try:
            start = date.fromisoformat(self.start_var.get())
            end = date.fromisoformat(self.end_var.get())
        except ValueError:
            if show_errors:
                messagebox.showerror("日期格式错误", "日期格式必须为 YYYY-MM-DD")
            return False
        if start > end:
            if show_errors:
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
