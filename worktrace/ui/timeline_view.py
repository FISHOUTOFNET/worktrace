from __future__ import annotations

from datetime import date

import customtkinter as ctk

from ..exports.markdown_exporter import format_duration
from ..services import activity_service, project_service
from ..services.settings_service import get_bool_setting, get_setting, set_setting


class TimelineView(ctk.CTkFrame):
    def __init__(self, master):
        super().__init__(master)
        self.date_var = ctk.StringVar(value=date.today().isoformat())
        self.only_unconfirmed = ctk.BooleanVar(value=False)
        self.only_uncategorized = ctk.BooleanVar(value=False)
        self._project_by_name: dict[str, int] = {}
        self._build()

    def _build(self) -> None:
        top = ctk.CTkFrame(self)
        top.pack(fill="x", padx=12, pady=12)
        self.status_label = ctk.CTkLabel(top, text="采集器未运行")
        self.status_label.pack(side="left", padx=6)
        self.pause_button = ctk.CTkButton(top, text="暂停", width=90, command=self.toggle_pause)
        self.pause_button.pack(side="left", padx=6)
        ctk.CTkLabel(top, text="日期").pack(side="left", padx=(16, 4))
        ctk.CTkEntry(top, textvariable=self.date_var, width=120).pack(side="left")
        ctk.CTkButton(top, text="刷新", width=70, command=self.refresh).pack(side="left", padx=6)
        ctk.CTkCheckBox(top, text="仅未确认", variable=self.only_unconfirmed, command=self.refresh).pack(
            side="left", padx=6
        )
        ctk.CTkCheckBox(top, text="仅未归类", variable=self.only_uncategorized, command=self.refresh).pack(
            side="left", padx=6
        )

        self.scroll = ctk.CTkScrollableFrame(self)
        self.scroll.pack(fill="both", expand=True, padx=12, pady=(0, 12))

    def refresh(self) -> None:
        for child in self.scroll.winfo_children():
            child.destroy()
        status = get_setting("collector_status", "stopped")
        paused = get_bool_setting("user_paused", False)
        label = "记录中" if status == "running" else "采集器未运行"
        if paused or status == "paused":
            label = "已暂停"
        if status == "error":
            label = "状态异常"
        self.status_label.configure(text=label)
        self.pause_button.configure(text="继续" if paused else "暂停")

        projects = project_service.list_active_projects()
        self._project_by_name = {p["name"]: p["id"] for p in projects}
        project_names = list(self._project_by_name)
        headers = ["时间", "状态", "应用", "窗口", "时长", "项目", "计费", "确认", "备注", "操作"]
        for col, text in enumerate(headers):
            ctk.CTkLabel(self.scroll, text=text, font=ctk.CTkFont(weight="bold")).grid(
                row=0, column=col, padx=4, pady=4, sticky="w"
            )
        rows = activity_service.get_activities_by_date(self.date_var.get())
        if self.only_unconfirmed.get():
            rows = [row for row in rows if not row["is_confirmed"]]
        if self.only_uncategorized.get():
            rows = [row for row in rows if (row.get("project_name") or "未归类") == "未归类"]
        for index, row in enumerate(rows, start=1):
            self._draw_row(index, row, project_names)

    def _draw_row(self, index: int, row: dict, project_names: list[str]) -> None:
        time_range = f"{row['start_time'][11:16]}-{(row['end_time'] or '')[11:16]}"
        values = [
            time_range,
            row["status"],
            row["app_name"],
            row["window_title"],
            format_duration(row["duration_seconds"] or 0),
        ]
        for col, value in enumerate(values):
            ctk.CTkLabel(self.scroll, text=str(value), wraplength=180).grid(
                row=index, column=col, padx=4, pady=4, sticky="w"
            )

        current_project = row.get("project_name") or "未归类"
        project_var = ctk.StringVar(value=current_project)
        option = ctk.CTkOptionMenu(
            self.scroll,
            values=project_names,
            variable=project_var,
            width=130,
            command=lambda name, activity_id=row["id"]: self._set_project(activity_id, name),
        )
        option.grid(row=index, column=5, padx=4, pady=4, sticky="w")
        billable = ctk.BooleanVar(value=bool(row["is_billable"]))
        ctk.CTkCheckBox(
            self.scroll,
            text="",
            variable=billable,
            width=32,
            command=lambda activity_id=row["id"], var=billable: self._set_billable(activity_id, var.get()),
        ).grid(row=index, column=6, padx=4, pady=4)
        confirmed = ctk.BooleanVar(value=bool(row["is_confirmed"]))
        ctk.CTkCheckBox(
            self.scroll,
            text="",
            variable=confirmed,
            width=32,
            command=lambda activity_id=row["id"], var=confirmed: self._set_confirmed(activity_id, var.get()),
        ).grid(row=index, column=7, padx=4, pady=4)
        note = ctk.CTkEntry(self.scroll, width=180)
        note.insert(0, row.get("note") or "")
        note.grid(row=index, column=8, padx=4, pady=4)
        actions = ctk.CTkFrame(self.scroll, fg_color="transparent")
        actions.grid(row=index, column=9, padx=4, pady=4)
        ctk.CTkButton(
            actions,
            text="保存",
            width=54,
            command=lambda activity_id=row["id"], entry=note: self._save_note(activity_id, entry),
        ).pack(side="left", padx=(0, 4))
        ctk.CTkButton(
            actions,
            text="删除",
            width=54,
            fg_color="#a33",
            command=lambda activity_id=row["id"]: self._delete(activity_id),
        ).pack(side="left")

    def toggle_pause(self) -> None:
        set_setting("user_paused", "false" if get_bool_setting("user_paused", False) else "true")
        self.refresh()

    def _set_project(self, activity_id: int, name: str) -> None:
        activity_service.update_activity_project(activity_id, self._project_by_name[name], manual=True)
        self.refresh()

    def _set_billable(self, activity_id: int, value: bool) -> None:
        activity_service.set_activity_billable(activity_id, value)

    def _set_confirmed(self, activity_id: int, value: bool) -> None:
        activity_service.set_activity_confirmed(activity_id, value)

    def _save_note(self, activity_id: int, entry) -> None:
        activity_service.update_activity_note(activity_id, entry.get())
        self.refresh()

    def _delete(self, activity_id: int) -> None:
        activity_service.soft_delete_activity(activity_id)
        self.refresh()
