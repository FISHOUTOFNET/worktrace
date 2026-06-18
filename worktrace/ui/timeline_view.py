from __future__ import annotations

from datetime import date
from typing import Any

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
        self._row_widgets: dict[int, dict[str, Any]] = {}
        self._header_created = False
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
        scroll_position = self._get_scroll_position()
        self._sync_status()
        self._ensure_header()

        date_text = self.date_var.get()
        if not self._valid_date(date_text):
            self.status_label.configure(text="日期格式错误，请使用 YYYY-MM-DD")
            self._restore_scroll_position(scroll_position)
            return

        projects = project_service.list_active_projects()
        self._project_by_name = {p["name"]: p["id"] for p in projects}
        project_names = list(self._project_by_name)
        rows = activity_service.get_activities_by_date(date_text)
        if self.only_unconfirmed.get():
            rows = [row for row in rows if not row["is_confirmed"]]
        if self.only_uncategorized.get():
            rows = [row for row in rows if (row.get("project_name") or "未归类") == "未归类"]

        current_ids = {int(row["id"]) for row in rows}
        for activity_id in list(self._row_widgets):
            if activity_id not in current_ids:
                self._destroy_row(activity_id)

        for index, row in enumerate(rows, start=1):
            activity_id = int(row["id"])
            if activity_id not in self._row_widgets:
                self._create_row(index, row, project_names)
            else:
                self._update_row(index, row, project_names)

        self._restore_scroll_position(scroll_position)

    def _valid_date(self, value: str) -> bool:
        try:
            date.fromisoformat(value)
        except ValueError:
            return False
        return True

    def _sync_status(self) -> None:
        status = get_setting("collector_status", "stopped")
        paused = get_bool_setting("user_paused", False)
        label = "记录中" if status == "running" else "采集器未运行"
        if paused or status == "paused":
            label = "已暂停"
        if status == "error":
            label = "状态异常"
        self.status_label.configure(text=label)
        self.pause_button.configure(text="继续" if paused else "暂停")

    def _ensure_header(self) -> None:
        if self._header_created:
            return
        headers = ["时间", "状态", "应用", "窗口", "时长", "项目", "计费", "确认", "备注", "操作"]
        for col, text in enumerate(headers):
            ctk.CTkLabel(self.scroll, text=text, font=ctk.CTkFont(weight="bold")).grid(
                row=0, column=col, padx=4, pady=4, sticky="w"
            )
        self._header_created = True

    def _row_values(self, row: dict) -> list[str]:
        time_range = f"{row['start_time'][11:16]}-{(row['end_time'] or '')[11:16]}"
        return [
            time_range,
            row["status"],
            row["app_name"],
            row["window_title"],
            format_duration(row["duration_seconds"] or 0),
        ]

    def _create_row(self, index: int, row: dict, project_names: list[str]) -> None:
        activity_id = int(row["id"])
        labels = []
        for col, value in enumerate(self._row_values(row)):
            label = ctk.CTkLabel(self.scroll, text=str(value), wraplength=180)
            label.grid(
                row=index, column=col, padx=4, pady=4, sticky="w"
            )
            labels.append(label)

        current_project = row.get("project_name") or "未归类"
        project_var = ctk.StringVar(value=current_project)
        option = ctk.CTkOptionMenu(
            self.scroll,
            values=project_names,
            variable=project_var,
            width=130,
            command=lambda name, activity_id=activity_id: self._set_project(activity_id, name),
        )
        option.grid(row=index, column=5, padx=4, pady=4, sticky="w")
        billable = ctk.BooleanVar(value=bool(row["is_billable"]))
        billable_box = ctk.CTkCheckBox(
            self.scroll,
            text="",
            variable=billable,
            width=32,
            command=lambda activity_id=activity_id, var=billable: self._set_billable(activity_id, var.get()),
        )
        billable_box.grid(row=index, column=6, padx=4, pady=4)
        confirmed = ctk.BooleanVar(value=bool(row["is_confirmed"]))
        confirmed_box = ctk.CTkCheckBox(
            self.scroll,
            text="",
            variable=confirmed,
            width=32,
            command=lambda activity_id=activity_id, var=confirmed: self._set_confirmed(activity_id, var.get()),
        )
        confirmed_box.grid(row=index, column=7, padx=4, pady=4)
        note = ctk.CTkEntry(self.scroll, width=180)
        note.insert(0, row.get("note") or "")
        note.grid(row=index, column=8, padx=4, pady=4)
        actions = ctk.CTkFrame(self.scroll, fg_color="transparent")
        actions.grid(row=index, column=9, padx=4, pady=4)
        ctk.CTkButton(
            actions,
            text="保存",
            width=54,
            command=lambda activity_id=activity_id, entry=note: self._save_note(activity_id, entry),
        ).pack(side="left", padx=(0, 4))
        ctk.CTkButton(
            actions,
            text="删除",
            width=54,
            fg_color="#a33",
            command=lambda activity_id=activity_id: self._delete(activity_id),
        ).pack(side="left")
        self._row_widgets[activity_id] = {
            "labels": labels,
            "project_var": project_var,
            "project_option": option,
            "billable_var": billable,
            "billable_box": billable_box,
            "confirmed_var": confirmed,
            "confirmed_box": confirmed_box,
            "note": note,
            "actions": actions,
        }

    def _update_row(self, index: int, row: dict, project_names: list[str]) -> None:
        activity_id = int(row["id"])
        widgets = self._row_widgets[activity_id]
        for col, label in enumerate(widgets["labels"]):
            label.grid(row=index, column=col, padx=4, pady=4, sticky="w")
        for label, value in zip(widgets["labels"], self._row_values(row), strict=True):
            label.configure(text=str(value))

        current_project = row.get("project_name") or "未归类"
        if current_project not in project_names:
            project_names = [current_project, *project_names]
        widgets["project_option"].configure(values=project_names)
        widgets["project_option"].grid(row=index, column=5, padx=4, pady=4, sticky="w")
        if widgets["project_var"].get() != current_project:
            widgets["project_var"].set(current_project)

        widgets["billable_box"].grid(row=index, column=6, padx=4, pady=4)
        if widgets["billable_var"].get() != bool(row["is_billable"]):
            widgets["billable_var"].set(bool(row["is_billable"]))

        widgets["confirmed_box"].grid(row=index, column=7, padx=4, pady=4)
        if widgets["confirmed_var"].get() != bool(row["is_confirmed"]):
            widgets["confirmed_var"].set(bool(row["is_confirmed"]))

        note = widgets["note"]
        note.grid(row=index, column=8, padx=4, pady=4)
        focused = self.focus_get()
        if focused not in (note, getattr(note, "_entry", None)):
            new_note = row.get("note") or ""
            if note.get() != new_note:
                note.delete(0, "end")
                note.insert(0, new_note)

        widgets["actions"].grid(row=index, column=9, padx=4, pady=4)

    def _destroy_row(self, activity_id: int) -> None:
        widgets = self._row_widgets.pop(activity_id)
        for widget in widgets["labels"]:
            widget.destroy()
        for key in ["project_option", "billable_box", "confirmed_box", "note", "actions"]:
            widgets[key].destroy()

    def _get_scroll_position(self) -> float:
        canvas = getattr(self.scroll, "_parent_canvas", None)
        if canvas is None:
            return 0.0
        return float(canvas.yview()[0])

    def _restore_scroll_position(self, position: float) -> None:
        canvas = getattr(self.scroll, "_parent_canvas", None)
        if canvas is not None:
            self.after_idle(lambda: canvas.yview_moveto(position))

    def toggle_pause(self) -> None:
        set_setting("user_paused", "false" if get_bool_setting("user_paused", False) else "true")
        self.refresh()

    def _set_project(self, activity_id: int, name: str) -> None:
        if name not in self._project_by_name:
            return
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
