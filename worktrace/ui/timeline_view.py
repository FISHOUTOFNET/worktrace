from __future__ import annotations

from datetime import date
from tkinter import ttk
from typing import Any

import customtkinter as ctk

from ..constants import UNCATEGORIZED_PROJECT
from ..exports.markdown_exporter import format_duration
from ..services import activity_service, project_service
from ..services.settings_service import get_bool_setting, get_setting, set_setting


class TimelineView(ctk.CTkFrame):
    def __init__(self, master):
        super().__init__(master)
        self.date_var = ctk.StringVar(value=date.today().isoformat())
        self.only_unconfirmed = ctk.BooleanVar(value=False)
        self.only_uncategorized = ctk.BooleanVar(value=False)
        self.project_var = ctk.StringVar(value=UNCATEGORIZED_PROJECT)
        self.billable_var = ctk.BooleanVar(value=False)
        self.confirmed_var = ctk.BooleanVar(value=False)

        self._project_by_name: dict[str, int] = {}
        self._rows_by_id: dict[int, dict[str, Any]] = {}
        self._tree_values_by_id: dict[int, tuple[str, ...]] = {}
        self._selected_activity_id: int | None = None
        self._editor_dirty = False
        self._user_scrolling = False
        self._scroll_idle_after_id: str | None = None
        self._control_active = False
        self._control_idle_after_id: str | None = None
        self._loading_editor = False

        self._build()

    def _build(self) -> None:
        top = ctk.CTkFrame(self)
        top.pack(fill="x", padx=12, pady=12)
        self.status_label = ctk.CTkLabel(top, text="采集器未运行")
        self.status_label.pack(side="left", padx=6)
        self.pause_button = ctk.CTkButton(top, text="暂停", width=90, command=self.toggle_pause)
        self.pause_button.pack(side="left", padx=6)
        ctk.CTkLabel(top, text="日期").pack(side="left", padx=(16, 4))
        self.date_entry = ctk.CTkEntry(top, textvariable=self.date_var, width=120)
        self.date_entry.pack(side="left")
        ctk.CTkButton(top, text="刷新", width=70, command=self.refresh).pack(side="left", padx=6)
        ctk.CTkCheckBox(top, text="仅未确认", variable=self.only_unconfirmed, command=self.refresh).pack(
            side="left", padx=6
        )
        ctk.CTkCheckBox(top, text="仅未归类", variable=self.only_uncategorized, command=self.refresh).pack(
            side="left", padx=6
        )

        self._build_table()
        self._build_editor()
        self._clear_editor()

    def _build_table(self) -> None:
        table_frame = ctk.CTkFrame(self)
        table_frame.pack(fill="both", expand=True, padx=12, pady=(0, 8))
        table_frame.grid_rowconfigure(0, weight=1)
        table_frame.grid_columnconfigure(0, weight=1)

        style = ttk.Style(self)
        style.configure("WorkTrace.Treeview", rowheight=28)
        style.configure("WorkTrace.Treeview.Heading", font=("Microsoft YaHei UI", 10, "bold"))

        columns = ("time", "status", "app", "window", "duration", "project", "billable", "confirmed", "note")
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings", style="WorkTrace.Treeview")
        headings = {
            "time": "时间",
            "status": "状态",
            "app": "应用",
            "window": "窗口",
            "duration": "时长",
            "project": "项目",
            "billable": "计费",
            "confirmed": "确认",
            "note": "备注",
        }
        widths = {
            "time": 96,
            "status": 72,
            "app": 120,
            "window": 320,
            "duration": 90,
            "project": 120,
            "billable": 64,
            "confirmed": 64,
            "note": 220,
        }
        for column in columns:
            self.tree.heading(column, text=headings[column])
            self.tree.column(column, width=widths[column], minwidth=48, anchor="w", stretch=column in {"window", "note"})

        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self._on_scrollbar)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)
        self.tree.bind("<MouseWheel>", self._on_tree_mousewheel, add="+")
        self.tree.bind("<Button-4>", self._on_tree_mousewheel, add="+")
        self.tree.bind("<Button-5>", self._on_tree_mousewheel, add="+")
        scrollbar.bind("<ButtonPress-1>", self._on_scrollbar_activity, add="+")
        scrollbar.bind("<B1-Motion>", self._on_scrollbar_activity, add="+")
        scrollbar.bind("<ButtonRelease-1>", self._on_scrollbar_activity, add="+")

    def _build_editor(self) -> None:
        self.editor = ctk.CTkFrame(self)
        self.editor.pack(fill="x", padx=12, pady=(0, 12))
        self.editor.grid_columnconfigure(7, weight=1)

        self.editor_status_label = ctk.CTkLabel(self.editor, text="未选择记录")
        self.editor_status_label.grid(row=0, column=0, columnspan=8, sticky="w", padx=8, pady=(8, 4))

        ctk.CTkLabel(self.editor, text="项目").grid(row=1, column=0, sticky="w", padx=(8, 4), pady=4)
        self.project_menu = ctk.CTkOptionMenu(
            self.editor,
            values=[UNCATEGORIZED_PROJECT],
            variable=self.project_var,
            width=160,
            command=self._on_project_changed,
        )
        self.project_menu.grid(row=1, column=1, sticky="w", padx=(0, 12), pady=4)

        self.billable_box = ctk.CTkCheckBox(
            self.editor,
            text="计费",
            variable=self.billable_var,
            command=self._mark_editor_dirty,
            width=70,
        )
        self.billable_box.grid(row=1, column=2, sticky="w", padx=(0, 12), pady=4)
        self.confirmed_box = ctk.CTkCheckBox(
            self.editor,
            text="确认",
            variable=self.confirmed_var,
            command=self._mark_editor_dirty,
            width=70,
        )
        self.confirmed_box.grid(row=1, column=3, sticky="w", padx=(0, 12), pady=4)

        self.save_button = ctk.CTkButton(self.editor, text="保存", width=72, command=self._save_selected)
        self.save_button.grid(row=1, column=4, sticky="w", padx=(0, 8), pady=4)
        self.delete_button = ctk.CTkButton(
            self.editor,
            text="删除",
            width=72,
            fg_color="#a33",
            command=self._delete_selected,
        )
        self.delete_button.grid(row=1, column=5, sticky="w", padx=(0, 8), pady=4)

        ctk.CTkLabel(self.editor, text="备注").grid(row=2, column=0, sticky="nw", padx=(8, 4), pady=(6, 8))
        self.note_text = ctk.CTkTextbox(self.editor, height=76)
        self.note_text.grid(row=2, column=1, columnspan=7, sticky="ew", padx=(0, 8), pady=(6, 8))
        self.note_text.bind("<KeyRelease>", self._on_note_changed, add="+")
        self.note_text.bind("<<Paste>>", self._on_note_changed, add="+")

        self._editor_widgets = [
            self.project_menu,
            self.billable_box,
            self.confirmed_box,
            self.save_button,
            self.delete_button,
            self.note_text,
        ]
        for widget in self._editor_widgets:
            widget.bind("<ButtonPress-1>", self._on_editor_control_activity, add="+")
            widget.bind("<FocusIn>", self._on_editor_control_activity, add="+")

    def refresh(self) -> None:
        self._sync_status()
        date_text = self.date_var.get()
        if not self._valid_date(date_text):
            self.status_label.configure(text="日期格式错误，请使用 YYYY-MM-DD")
            return

        self._refresh_projects()
        rows = activity_service.get_activities_by_date(date_text)
        if self.only_unconfirmed.get():
            rows = [row for row in rows if not row["is_confirmed"]]
        if self.only_uncategorized.get():
            rows = [row for row in rows if (row.get("project_name") or UNCATEGORIZED_PROJECT) == UNCATEGORIZED_PROJECT]

        self._sync_tree_rows(rows)

    def is_user_interacting(self) -> bool:
        return (
            self._user_scrolling
            or self._control_active
            or self._editor_dirty
            or any(self._widget_has_focus(widget) for widget in self._editor_widgets)
        )

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

    def _refresh_projects(self) -> None:
        projects = project_service.list_active_projects()
        self._project_by_name = {p["name"]: int(p["id"]) for p in projects}
        names = list(self._project_by_name)
        if UNCATEGORIZED_PROJECT not in names:
            names.insert(0, UNCATEGORIZED_PROJECT)
        if self.project_var.get() and self.project_var.get() not in names:
            names.insert(0, self.project_var.get())
        self.project_menu.configure(values=names or [UNCATEGORIZED_PROJECT])

    def _tree_values(self, row: dict) -> tuple[str, ...]:
        start = row.get("start_time") or ""
        end = row.get("end_time") or ""
        start_text = start[11:16] if len(start) >= 16 else start
        end_text = end[11:16] if len(end) >= 16 else ""
        note = row.get("note") or ""
        note_summary = " ".join(str(note).split())
        if len(note_summary) > 40:
            note_summary = f"{note_summary[:40]}..."
        return (
            f"{start_text}-{end_text}",
            str(row.get("status") or ""),
            str(row.get("app_name") or ""),
            str(row.get("window_title") or ""),
            format_duration(row.get("duration_seconds") or 0),
            str(row.get("project_name") or UNCATEGORIZED_PROJECT),
            "是" if row.get("is_billable") else "否",
            "是" if row.get("is_confirmed") else "否",
            note_summary,
        )

    def _sync_tree_rows(self, rows: list[dict]) -> None:
        previous_selected_id = self._selected_activity_id
        previous_selected_row = self._rows_by_id.get(previous_selected_id) if previous_selected_id is not None else None
        old_children = list(self.tree.get_children())
        old_index = self._tree_index(previous_selected_id, old_children)
        yview = self.tree.yview()

        current_ids = [int(row["id"]) for row in rows]
        current_id_set = set(current_ids)
        self._rows_by_id = {int(row["id"]): row for row in rows}
        if self._editor_dirty and previous_selected_id is not None and previous_selected_row is not None:
            self._rows_by_id.setdefault(previous_selected_id, previous_selected_row)

        for iid in old_children:
            activity_id = int(iid)
            if activity_id not in current_id_set:
                self.tree.delete(iid)
                self._tree_values_by_id.pop(activity_id, None)

        for index, row in enumerate(rows):
            activity_id = int(row["id"])
            iid = str(activity_id)
            values = self._tree_values(row)
            if not self.tree.exists(iid):
                self.tree.insert("", index, iid=iid, values=values)
            else:
                if self._tree_values_by_id.get(activity_id) != values:
                    self.tree.item(iid, values=values)
                self.tree.move(iid, "", index)
            self._tree_values_by_id[activity_id] = values

        if previous_selected_id in current_id_set:
            self._select_tree_item(previous_selected_id, reveal=False)
            if not self._editor_dirty:
                self._load_editor(previous_selected_id)
        elif self._editor_dirty:
            self.tree.selection_remove(self.tree.selection())
            self.editor_status_label.configure(text="当前编辑未保存，刷新不会覆盖详情内容")
        else:
            self._selected_activity_id = None
            self.tree.selection_remove(self.tree.selection())
            if previous_selected_id is not None and rows:
                next_index = min(old_index if old_index is not None else 0, len(rows) - 1)
                next_id = int(rows[next_index]["id"])
                self._selected_activity_id = next_id
                self._select_tree_item(next_id, reveal=False)
                self._load_editor(next_id)
            else:
                self._clear_editor()

        self.after_idle(lambda position=yview[0]: self.tree.yview_moveto(position))

    def _tree_index(self, activity_id: int | None, children: list[str] | None = None) -> int | None:
        if activity_id is None:
            return None
        children = children if children is not None else list(self.tree.get_children())
        iid = str(activity_id)
        return children.index(iid) if iid in children else None

    def _on_tree_select(self, _event=None) -> None:
        selection = self.tree.selection()
        if not selection:
            if not self._editor_dirty:
                self._selected_activity_id = None
                self._clear_editor()
            return

        activity_id = int(selection[0])
        if (
            self._editor_dirty
            and self._selected_activity_id is not None
            and activity_id != self._selected_activity_id
        ):
            self._select_tree_item(self._selected_activity_id, reveal=False)
            self.editor_status_label.configure(text="当前修改未保存，请先保存后再切换记录")
            return

        if activity_id != self._selected_activity_id or not self._editor_dirty:
            self._selected_activity_id = activity_id
            self._load_editor(activity_id)

    def _select_tree_item(self, activity_id: int, reveal: bool) -> None:
        iid = str(activity_id)
        if not self.tree.exists(iid):
            return
        self.tree.selection_set(iid)
        self.tree.focus(iid)
        if reveal:
            self.tree.see(iid)

    def _load_editor(self, activity_id: int) -> None:
        if self._editor_dirty:
            return
        row = self._rows_by_id.get(activity_id)
        if row is None:
            self._clear_editor()
            return

        project_name = row.get("project_name") or UNCATEGORIZED_PROJECT
        names = list(self._project_by_name)
        if project_name not in names:
            names.insert(0, project_name)
            self.project_menu.configure(values=names)

        self._loading_editor = True
        self._set_editor_state("normal")
        self.project_var.set(project_name)
        self.billable_var.set(bool(row.get("is_billable")))
        self.confirmed_var.set(bool(row.get("is_confirmed")))
        self._set_note_text(row.get("note") or "")
        self._loading_editor = False
        self._editor_dirty = False
        self.editor_status_label.configure(
            text=f"正在编辑：{self._tree_values(row)[0]}｜{row.get('app_name') or ''}｜{project_name}"
        )

    def _clear_editor(self) -> None:
        self._loading_editor = True
        self.project_var.set(UNCATEGORIZED_PROJECT)
        self.billable_var.set(False)
        self.confirmed_var.set(False)
        self._set_note_text("")
        self._loading_editor = False
        self._editor_dirty = False
        self.editor_status_label.configure(text="未选择记录" if self.tree.get_children() else "暂无记录")
        self._set_editor_state("disabled")

    def _set_editor_state(self, state: str) -> None:
        for widget in self._editor_widgets:
            widget.configure(state=state)

    def _set_note_text(self, text: str) -> None:
        self.note_text.configure(state="normal")
        self.note_text.delete("1.0", "end")
        self.note_text.insert("1.0", text)

    def _get_note_text(self) -> str:
        return self.note_text.get("1.0", "end-1c")

    def _on_project_changed(self, _name: str) -> None:
        self._mark_editor_dirty()

    def _on_note_changed(self, _event=None) -> None:
        self._mark_editor_dirty()

    def _mark_editor_dirty(self, _event=None) -> None:
        if self._loading_editor or self._selected_activity_id is None:
            return
        self._editor_dirty = True
        self.editor_status_label.configure(text="当前修改未保存")

    def _save_selected(self) -> None:
        activity_id = self._selected_activity_id
        if activity_id is None:
            return
        row = self._rows_by_id.get(activity_id)
        if row is None:
            return

        project_name = self.project_var.get()
        project_id = self._project_by_name.get(project_name)
        if project_id is None:
            self.editor_status_label.configure(text="请选择有效项目")
            return

        if int(row.get("project_id") or 0) != project_id:
            activity_service.update_activity_project(activity_id, project_id, manual=True)

        billable = bool(self.billable_var.get())
        if bool(row.get("is_billable")) != billable:
            activity_service.set_activity_billable(activity_id, billable)

        note = self._get_note_text()
        if (row.get("note") or "") != note:
            activity_service.update_activity_note(activity_id, note)

        activity_service.set_activity_confirmed(activity_id, bool(self.confirmed_var.get()))
        self._editor_dirty = False
        self.refresh()
        if self.tree.exists(str(activity_id)):
            self._select_tree_item(activity_id, reveal=False)
            self._load_editor(activity_id)

    def _delete_selected(self) -> None:
        activity_id = self._selected_activity_id
        if activity_id is None:
            return

        old_children = list(self.tree.get_children())
        old_index = self._tree_index(activity_id, old_children)
        activity_service.soft_delete_activity(activity_id)
        self._editor_dirty = False
        self._selected_activity_id = None
        self.refresh()

        children = list(self.tree.get_children())
        if not children:
            self._clear_editor()
            return
        next_index = min(old_index if old_index is not None else 0, len(children) - 1)
        next_id = int(children[next_index])
        self._selected_activity_id = next_id
        self._select_tree_item(next_id, reveal=True)
        self._load_editor(next_id)

    def _on_tree_mousewheel(self, _event=None) -> None:
        self._mark_scrolling()

    def _on_scrollbar(self, *args) -> None:
        self._mark_scrolling()
        self.tree.yview(*args)

    def _on_scrollbar_activity(self, _event=None) -> None:
        self._mark_scrolling()

    def _mark_scrolling(self) -> None:
        self._user_scrolling = True
        if self._scroll_idle_after_id is not None:
            self.after_cancel(self._scroll_idle_after_id)
        self._scroll_idle_after_id = self.after(650, self._clear_scrolling)

    def _clear_scrolling(self) -> None:
        self._user_scrolling = False
        self._scroll_idle_after_id = None

    def _on_editor_control_activity(self, _event=None) -> None:
        self._control_active = True
        if self._control_idle_after_id is not None:
            self.after_cancel(self._control_idle_after_id)
        self._control_idle_after_id = self.after(800, self._clear_control_activity)

    def _clear_control_activity(self) -> None:
        self._control_active = False
        self._control_idle_after_id = None

    def _widget_has_focus(self, widget) -> bool:
        focused = self.focus_get()
        while focused is not None:
            if focused == widget:
                return True
            if focused in (
                getattr(widget, "_entry", None),
                getattr(widget, "_textbox", None),
                getattr(widget, "_canvas", None),
            ):
                return True
            focused = getattr(focused, "master", None)
        return False

    def toggle_pause(self) -> None:
        set_setting("user_paused", "false" if get_bool_setting("user_paused", False) else "true")
        self.refresh()
